from __future__ import annotations

import json
import msvcrt
import os
import queue
import sqlite3
import sys
import threading
import traceback
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any


APP_TITLE = "云启数据采集机器人"
APP_LOCK_FILE: Any | None = None


def find_project_root() -> Path:
    env_root = os.getenv("TEMU_WORKBENCH_PROJECT_ROOT", "").strip()
    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root).expanduser())

    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        candidates.extend([executable_dir, executable_dir.parent])
    else:
        candidates.append(Path(__file__).resolve().parents[2])

    candidates.extend([Path.cwd(), Path(r"D:\learning\temu_listing_workbench")])
    for candidate in candidates:
        root = candidate.resolve()
        if (root / "backend" / "app").exists():
            return root
    return Path.cwd().resolve()


PROJECT_ROOT = find_project_root()
BACKEND_DIR = PROJECT_ROOT / "backend"
os.environ.setdefault("TEMU_WORKBENCH_PROJECT_ROOT", str(PROJECT_ROOT))
os.environ.setdefault("TEMU_WORKBENCH_BACKEND_DIR", str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR))


DEFAULT_START_URL = "https://www.yunqishuju.com/temu/semiy2/"
DYNAMIC_FILTER_DIR = BACKEND_DIR / "runtime" / "yunqi_dynamic_filters"


@dataclass(frozen=True)
class CategoryOption:
    label: str
    kind: str
    config_path: Path | None = None
    category_key: str | None = None
    category_path: tuple[str, ...] = ()
    path_text: str = ""


PRIORITY_CATEGORY_CONFIGS = {
    "户外睡袋": BACKEND_DIR / "config" / "yunqi_filters_sleeping_bag.json",
    "泳池用品": BACKEND_DIR / "config" / "yunqi_filters_pool.json",
    "麻将/桌游棋牌": BACKEND_DIR / "config" / "yunqi_filters_mahjong.json",
}

STEP_DEFINITIONS = [
    ("打开浏览器", "open_browser", "rpa"),
    ("选择站点", "site", "rpa"),
    ("选择分类", "category", "rpa"),
    ("上架时间3月内", "listing_date", "rpa"),
    ("点击搜索", "search", "rpa"),
    ("导出Excel", "export", "rpa"),
    ("导入数据库", "import_latest", "import"),
    ("轮询导出全部类目", "batch_export_all", "batch_export"),
]


def acquire_single_instance_lock() -> bool:
    global APP_LOCK_FILE
    lock_dir = BACKEND_DIR / "runtime"
    try:
        lock_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    lock_path = lock_dir / "yunqi_robot_gui.lock"
    try:
        lock_file = lock_path.open("a+", encoding="utf-8")
    except OSError:
        return False
    try:
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock_file.close()
        return False
    try:
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(str(os.getpid()))
        lock_file.flush()
    except OSError:
        pass
    APP_LOCK_FILE = lock_file
    return True


def load_category_options() -> tuple[dict[str, CategoryOption], str]:
    options: dict[str, CategoryOption] = {}
    for label, config_path in PRIORITY_CATEGORY_CONFIGS.items():
        options[label] = CategoryOption(label=label, kind="config", config_path=config_path, path_text=label)

    database_options, message = load_database_category_options()
    for option in database_options:
        display = unique_category_label(options, option.label)
        options[display] = CategoryOption(
            label=display,
            kind=option.kind,
            config_path=option.config_path,
            category_key=option.category_key,
            category_path=option.category_path,
            path_text=option.path_text,
        )
    return options, message


def load_database_category_options() -> tuple[list[CategoryOption], str]:
    try:
        from app.core.config import DATABASE_PATH

        database_path = Path(DATABASE_PATH)
        if not database_path.exists():
            return [], f"数据库类目未加载：找不到数据库 {database_path}"

        with sqlite3.connect(database_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT id, category_key, label, label_en, label_cn, path_text, path_json, has_children
                    FROM yunqi_categories
                    WHERE source_type = 'yunqi' AND is_active = 1
                    ORDER BY level ASC, path_text ASC
                    """
                ).fetchall()
            ]
    except Exception as exc:  # noqa: BLE001
        return [], f"数据库类目未加载：{exc}"

    leaf_rows = [row for row in rows if not bool(row.get("has_children"))]
    selected_rows = leaf_rows or rows
    options: list[CategoryOption] = []
    for row in selected_rows:
        label_text = str(row.get("label") or "").strip()
        path_text = str(row.get("path_text") or "").strip()
        if label_text == "全分类" or path_text == "全分类":
            continue
        try:
            raw_path = json.loads(str(row.get("path_json") or "[]"))
        except json.JSONDecodeError:
            raw_path = []
        category_path = tuple(str(item).strip() for item in raw_path if str(item).strip())
        if not category_path:
            continue
        path_text = path_text or " > ".join(category_path)
        label = f"[数据库] {path_text}"
        options.append(
            CategoryOption(
                label=label,
                kind="database",
                category_key=str(row.get("category_key") or row.get("id") or ""),
                category_path=category_path,
                path_text=path_text,
            )
        )

    return options, f"已从数据库加载 {len(options)} 个云启末级类目。"


def unique_category_label(options: dict[str, CategoryOption], label: str) -> str:
    if label not in options:
        return label
    index = 2
    while f"{label} #{index}" in options:
        index += 1
    return f"{label} #{index}"


def normalize_search_text(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def match_category_options(options: dict[str, CategoryOption], query: str, *, limit: int = 100) -> list[str]:
    text = normalize_search_text(query)
    labels = list(options.keys())
    if not text:
        return labels[:limit]

    matches: list[str] = []
    for label, option in options.items():
        haystack = normalize_search_text(f"{label} {option.path_text} {' '.join(option.category_path)}")
        if text in haystack:
            matches.append(label)
            if len(matches) >= limit:
                break
    return matches


def resolve_category_option(options: dict[str, CategoryOption], value: str) -> tuple[str, CategoryOption]:
    label = str(value or "").strip()
    if label in options:
        return label, options[label]

    normalized = normalize_search_text(label)
    exact_matches = [
        (candidate_label, option)
        for candidate_label, option in options.items()
        if normalized
        and (
            normalize_search_text(candidate_label) == normalized
            or normalize_search_text(option.path_text) == normalized
            or normalize_search_text(option.category_path[-1] if option.category_path else "") == normalized
        )
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]

    contains_matches = [(candidate_label, options[candidate_label]) for candidate_label in match_category_options(options, label)]
    if len(contains_matches) == 1:
        return contains_matches[0]
    if not contains_matches:
        raise RuntimeError(f"找不到类目：{label}")

    suggestions = "\n".join(f"- {candidate_label}" for candidate_label, _ in contains_matches[:10])
    raise RuntimeError(f"匹配到多个类目，请从下拉候选里选一个：\n{suggestions}")


def database_category_options(options: dict[str, CategoryOption]) -> list[tuple[str, CategoryOption]]:
    return [(label, option) for label, option in options.items() if option.kind == "database" and option.category_path]


def category_level_values(options: dict[str, CategoryOption], prefix: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for _label, option in database_category_options(options):
        path = option.category_path
        if len(path) <= len(prefix):
            continue
        if prefix and tuple(path[: len(prefix)]) != prefix:
            continue
        value = path[len(prefix)]
        if value not in seen:
            seen.add(value)
            values.append(value)
    return values


def find_category_option_by_path(
    options: dict[str, CategoryOption],
    path: tuple[str, ...],
) -> tuple[str, CategoryOption] | None:
    for label, option in database_category_options(options):
        if option.category_path == path:
            return label, option
    return None


def find_category_options_by_prefix(
    options: dict[str, CategoryOption],
    prefix: tuple[str, ...],
) -> list[tuple[str, CategoryOption]]:
    return [
        (label, option)
        for label, option in database_category_options(options)
        if option.category_path[: len(prefix)] == prefix
    ]


def default_category_path(options: dict[str, CategoryOption]) -> tuple[str, ...]:
    preferred = ("Sports & Outdoors(运动与户外)", "Camping & Hiking(野营登山)")
    if find_category_option_by_path(options, preferred):
        return preferred

    database_options = database_category_options(options)
    if database_options:
        return database_options[0][1].category_path
    return ()


def resolve_category_config(option: CategoryOption) -> Path:
    if option.kind == "config":
        if not option.config_path:
            raise RuntimeError(f"类目缺少配置文件：{option.label}")
        return option.config_path
    if option.kind == "database":
        return write_dynamic_filter_config(option)
    raise RuntimeError(f"未知类目类型：{option.kind}")


def write_dynamic_filter_config(option: CategoryOption) -> Path:
    if not option.category_path:
        raise RuntimeError(f"数据库类目缺少路径：{option.label}")

    from app.modules.yunqi.filter_configs import write_yunqi_category_filter_config

    return write_yunqi_category_filter_config(
        category_key=option.category_key,
        category_path=option.category_path,
        path_text=option.path_text,
        output_dir=DYNAMIC_FILTER_DIR,
        start_url=DEFAULT_START_URL,
    )


class YunqiRobotGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("760x560")
        self.minsize(700, 500)
        self.log_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.action_buttons: list[ttk.Button] = []
        self.last_export_path: Path | None = None
        self.category_options, self.category_load_message = load_category_options()
        self.category_level_vars = [tk.StringVar(), tk.StringVar(), tk.StringVar()]
        self.category_level_boxes: list[ttk.Combobox] = []

        self.set_category_path(default_category_path(self.category_options))
        self.status_var = tk.StringVar(value="就绪")

        self.build_ui()
        self.after(150, self.drain_log_queue)

    def build_ui(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(root, text=APP_TITLE, font=("Microsoft YaHei UI", 16, "bold"))
        title.pack(anchor=tk.W)

        settings = ttk.LabelFrame(root, text="采集设置", padding=12)
        settings.pack(fill=tk.X, pady=(16, 12))
        settings.columnconfigure(1, weight=1)

        for row, (label, variable) in enumerate(
            zip(("一级类目", "二级类目", "三级类目"), self.category_level_vars)
        ):
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky=tk.W, padx=(0, 10), pady=4)
            category_box = ttk.Combobox(
                settings,
                textvariable=variable,
                values=[],
                state="readonly",
                width=72,
            )
            category_box.grid(row=row, column=1, sticky=tk.EW, pady=4)
            category_box.bind(
                "<<ComboboxSelected>>",
                lambda _event, level=row: self.on_category_level_selected(level),
            )
            self.category_level_boxes.append(category_box)
        self.refresh_category_level_boxes()

        ttk.Label(
            settings,
            text="按层级选择数据库类目；机器人会按这些层级在云启页面逐级点击。",
            foreground="#555555",
        ).grid(row=3, column=1, sticky=tk.W, pady=(0, 4))

        ttk.Label(settings, text="项目目录").grid(row=4, column=0, sticky=tk.W, padx=(0, 10), pady=4)
        ttk.Label(settings, text=str(PROJECT_ROOT), foreground="#555555").grid(row=4, column=1, sticky=tk.W, pady=4)

        step_frame = ttk.LabelFrame(root, text="分步执行", padding=12)
        step_frame.pack(fill=tk.X, pady=(0, 12))
        step_frame.columnconfigure((0, 1, 2, 3), weight=1)

        for index, (label, step, action_kind) in enumerate(STEP_DEFINITIONS):
            if action_kind == "batch_export":
                command = lambda l=label: self.start_batch_export(l)
            else:
                command = lambda s=step, k=action_kind, l=label: self.start_step(s, k, l)
            button = ttk.Button(
                step_frame,
                text=label,
                command=command,
            )
            button.grid(row=index // 4, column=index % 4, sticky=tk.EW, padx=4, pady=4)
            self.action_buttons.append(button)

        ttk.Label(
            step_frame,
            text="建议顺序：打开浏览器 → 选择站点 → 选择分类 → 上架时间3月内 → 点击搜索 → 导出Excel → 导入数据库；批量轮询会自动跑全部末级类目。",
            foreground="#555555",
        ).grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=(8, 0))

        status_frame = ttk.Frame(root)
        status_frame.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(status_frame, text="状态：").pack(side=tk.LEFT)
        ttk.Label(status_frame, textvariable=self.status_var, foreground="#1f6feb").pack(side=tk.LEFT)

        log_frame = ttk.LabelFrame(root, text="运行日志", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_frame, height=14, wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self.write_log(self.category_load_message)
        self.write_log("选择类目后，可以按步骤逐个执行。机器人 Chrome 会保持打开，后续步骤会复用同一个页面。")

    def set_category_path(self, path: tuple[str, ...]) -> None:
        for index, variable in enumerate(self.category_level_vars):
            variable.set(path[index] if index < len(path) else "")

    def selected_category_path(self) -> tuple[str, ...]:
        return tuple(variable.get().strip() for variable in self.category_level_vars if variable.get().strip())

    def refresh_category_level_boxes(self) -> None:
        prefix: tuple[str, ...] = ()
        for index, (variable, category_box) in enumerate(zip(self.category_level_vars, self.category_level_boxes)):
            if index > 0 and len(prefix) < index:
                variable.set("")
                category_box.configure(values=[], state="disabled")
                continue

            values = category_level_values(self.category_options, prefix)
            current = variable.get().strip()
            if current and current not in values:
                current = ""
                variable.set("")

            if values:
                category_box.configure(values=values, state="readonly")
            else:
                category_box.configure(values=[], state="disabled")

            if current:
                prefix = (*prefix, current)

    def on_category_level_selected(self, level: int) -> None:
        for index in range(level + 1, len(self.category_level_vars)):
            self.category_level_vars[index].set("")
        self.refresh_category_level_boxes()

    def resolve_selected_category_option(self) -> tuple[str, CategoryOption]:
        path = self.selected_category_path()
        if not path:
            raise RuntimeError("请先选择一级类目和二级类目。")

        exact = find_category_option_by_path(self.category_options, path)
        if exact:
            return exact

        candidates = find_category_options_by_prefix(self.category_options, path)
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise RuntimeError(f"找不到数据库类目路径：{' > '.join(path)}")

        next_values = category_level_values(self.category_options, path)
        if next_values:
            suggestions = "\n".join(f"- {value}" for value in next_values[:10])
            raise RuntimeError(f"请继续选择下一级类目：\n{suggestions}")

        suggestions = "\n".join(f"- {label}" for label, _ in candidates[:10])
        raise RuntimeError(f"匹配到多个类目，请选到末级类目：\n{suggestions}")

    def start_step(self, run_step: str, action_kind: str, label: str) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_TITLE, "机器人正在运行，请等当前步骤结束。")
            return

        try:
            category_label, category_option = self.resolve_selected_category_option()
        except RuntimeError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        config_path = resolve_category_config(category_option)
        if action_kind == "rpa" and not config_path.exists():
            messagebox.showerror(APP_TITLE, f"找不到配置文件：\n{config_path}")
            return

        self.set_buttons_enabled(False)
        self.status_var.set(f"运行中：{label}")
        self.write_log(f"开始步骤：{label}")
        self.write_log(f"类目：{category_label}")
        if category_option.path_text and category_option.path_text != category_label:
            self.write_log(f"类目路径：{category_option.path_text}")
        self.write_log(f"配置：{config_path}")

        self.worker = threading.Thread(
            target=self.run_step,
            args=(config_path, run_step, action_kind, label),
            daemon=True,
        )
        self.worker.start()

    def start_batch_export(self, label: str) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_TITLE, "机器人正在运行，请等当前步骤结束。")
            return

        if not messagebox.askyesno(
            APP_TITLE,
            "将轮询导出数据库中所有云启末级类目，过程可能耗时很久。\n\n"
            "默认只导出 Excel/CSV，不自动导入数据库。是否开始？",
        ):
            return

        self.set_buttons_enabled(False)
        self.status_var.set(f"运行中：{label}")
        self.write_log(f"开始步骤：{label}")
        self.write_log("范围：yunqi_categories 表中所有 active 末级类目")
        self.worker = threading.Thread(
            target=self.run_batch_export,
            args=(label,),
            daemon=True,
        )
        self.worker.start()

    def run_step(self, config_path: Path, run_step: str, action_kind: str, label: str) -> None:
        try:
            from app.core.config import DATABASE_PATH
            from app.core.database import init_db

            result: dict[str, Any] = {
                "step_label": label,
                "database_imported": False,
                "browser_kept_open": True,
                "database_path": str(DATABASE_PATH),
            }

            if action_kind == "import":
                from app.modules.yunqi.collector import collect_yunqi_excel_file

                import_path = self.last_export_path or find_latest_export_file()
                if not import_path:
                    raise RuntimeError("没有找到可导入的云启 Excel。请先点击“导出Excel”。")

                init_db()
                self.post_log(f"导入文件：{import_path}")
                import_result = collect_yunqi_excel_file(import_path, rebuild_keywords=True)
                result.update(import_result)
                result["database_imported"] = True
            else:
                from app.modules.yunqi.rpa_exporter import export_yunqi_excel_via_rpa

                self.post_log("连接云启机器人 Chrome（CDP 常驻模式）。")
                export_result = export_yunqi_excel_via_rpa(
                    filter_config_path=config_path,
                    headless=False,
                    background_headed=True,
                    keep_open_on_error=True,
                    keep_browser_open=True,
                    use_cdp=True,
                    run_step=run_step,
                )
                result["rpa"] = export_result
                download_path = export_result.get("download_path")
                if download_path:
                    self.last_export_path = Path(download_path)
                    result["last_export_path"] = str(self.last_export_path)

            self.post_log(json.dumps(result, ensure_ascii=False, indent=2))
            self.log_queue.put(("done", label))
        except Exception as exc:  # noqa: BLE001
            self.post_log(traceback.format_exc())
            self.log_queue.put(("error", str(exc)))

    def run_batch_export(self, label: str) -> None:
        try:
            from app.core.config import DATABASE_PATH
            from app.modules.yunqi.batch_exporter import export_yunqi_all_categories

            self.post_log("连接云启机器人 Chrome（CDP 常驻模式），开始轮询全部类目。")
            result = export_yunqi_all_categories(
                headless=False,
                background_headed=True,
                keep_open_on_error=True,
                keep_browser_open=True,
                use_cdp=True,
                import_after_export=False,
                log=self.post_log,
            )
            result["database_path"] = str(DATABASE_PATH)
            latest_success = next(
                (
                    item
                    for item in reversed(result.get("downloads", []))
                    if item.get("status") in {"exported", "imported"} and item.get("download_path")
                ),
                None,
            )
            if latest_success:
                self.last_export_path = Path(latest_success["download_path"])
            self.post_log(json.dumps(result, ensure_ascii=False, indent=2))
            self.log_queue.put(("done", label))
        except Exception as exc:  # noqa: BLE001
            self.post_log(traceback.format_exc())
            self.log_queue.put(("error", str(exc)))

    def post_log(self, message: str) -> None:
        self.log_queue.put(("log", message))

    def drain_log_queue(self) -> None:
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "log":
                    self.write_log(str(payload))
                elif kind == "done":
                    self.status_var.set(f"完成：{payload}")
                    self.enable_buttons()
                elif kind == "error":
                    self.status_var.set("失败")
                    self.enable_buttons()
                    messagebox.showerror(APP_TITLE, str(payload))
        except queue.Empty:
            pass
        self.after(150, self.drain_log_queue)

    def enable_buttons(self) -> None:
        self.set_buttons_enabled(True)

    def set_buttons_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for button in self.action_buttons:
            button.configure(state=state)

    def write_log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message.rstrip() + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)


def main() -> None:
    if not acquire_single_instance_lock():
        messagebox.showerror(APP_TITLE, "云启数据采集机器人已经打开，请先使用当前窗口。")
        return
    app = YunqiRobotGui()
    app.mainloop()


def find_latest_export_file() -> Path | None:
    try:
        from app.core.config import STORAGE_DIR
    except Exception:
        storage_dir = PROJECT_ROOT / "storage"
    else:
        storage_dir = STORAGE_DIR

    export_dir = storage_dir / "yunqi_exports"
    if not export_dir.exists():
        return None
    candidates = [
        path
        for path in export_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".xlsx", ".xls", ".csv"}
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


if __name__ == "__main__":
    main()
