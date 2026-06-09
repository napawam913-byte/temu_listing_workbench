from __future__ import annotations

import csv
import json
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app.core.config import BACKEND_DIR, STORAGE_DIR, ensure_runtime_dirs
from app.modules.yunqi.export_files import rename_export_for_filter_config


DEFAULT_PROFILE_DIR = BACKEND_DIR / "runtime" / "yunqi_robot_browser_profile"
DEFAULT_DOWNLOAD_DIR = STORAGE_DIR / "yunqi_exports"
DEFAULT_CATEGORY_DIR = STORAGE_DIR / "yunqi_categories"
DEFAULT_PLAYWRIGHT_BROWSERS_DIR = Path.home() / "AppData" / "Local" / "ms-playwright"
RPA_RUN_STEPS = {"full", "open_browser", "crawl_categories", "site", "category", "listing_date", "search", "export"}
YUNQI_EXPORT_RECORD_TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?")
YUNQI_EXPORT_RECORD_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


class YunqiRpaError(Exception):
    pass


@dataclass(frozen=True)
class YunqiRpaConfig:
    start_url: str
    user_data_dir: Path = DEFAULT_PROFILE_DIR
    download_dir: Path = DEFAULT_DOWNLOAD_DIR
    headless: bool = False
    background_headed: bool = False
    slow_mo_ms: int = 0
    viewport_width: int = 1920
    viewport_height: int = 1080
    window_width: int = 1600
    window_height: int = 900
    cdp_port: int = 9233
    navigation_timeout_ms: int = 60000
    download_timeout_ms: int = 300000
    export_button_names: tuple[str, ...] = ("export", "download", "Export", "Download", "\u5bfc\u51fa", "\u4e0b\u8f7d")
    search_button_names: tuple[str, ...] = ("search", "query", "Search", "Query", "\u641c\u7d22", "\u67e5\u8be2")

    @classmethod
    def from_env(
        cls,
        *,
        start_url: str | None = None,
        headless: bool | None = None,
        background_headed: bool | None = None,
    ) -> "YunqiRpaConfig":
        resolved_start_url = (
            (start_url or "").strip()
            or os.getenv("YUNQI_START_URL", "").strip()
            or os.getenv("YUNQI_BASE_URL", "").strip()
        )
        if not resolved_start_url:
            raise YunqiRpaError("YUNQI_START_URL or YUNQI_BASE_URL is required for RPA collection.")

        configured_headless = os.getenv("YUNQI_RPA_HEADLESS", "").strip().lower() in {"1", "true", "yes", "on"}
        configured_background = os.getenv("YUNQI_RPA_BACKGROUND_HEADED", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        return cls(
            start_url=resolved_start_url,
            user_data_dir=Path(os.getenv("YUNQI_RPA_PROFILE_DIR", str(DEFAULT_PROFILE_DIR))).expanduser(),
            download_dir=Path(os.getenv("YUNQI_RPA_DOWNLOAD_DIR", str(DEFAULT_DOWNLOAD_DIR))).expanduser(),
            headless=configured_headless if headless is None else headless,
            background_headed=configured_background if background_headed is None else background_headed,
            slow_mo_ms=to_int(os.getenv("YUNQI_RPA_SLOW_MO_MS")) or 0,
            viewport_width=to_int(os.getenv("YUNQI_RPA_VIEWPORT_WIDTH")) or 1920,
            viewport_height=to_int(os.getenv("YUNQI_RPA_VIEWPORT_HEIGHT")) or 1080,
            window_width=to_int(os.getenv("YUNQI_RPA_WINDOW_WIDTH")) or 1600,
            window_height=to_int(os.getenv("YUNQI_RPA_WINDOW_HEIGHT")) or 900,
            cdp_port=to_int(os.getenv("YUNQI_RPA_CDP_PORT")) or 9233,
            navigation_timeout_ms=to_int(os.getenv("YUNQI_RPA_NAVIGATION_TIMEOUT_MS")) or 60000,
            download_timeout_ms=to_int(os.getenv("YUNQI_RPA_DOWNLOAD_TIMEOUT_MS")) or 300000,
        )


@dataclass(frozen=True)
class ResponseDownload:
    content: bytes
    suggested_filename: str
    url: str

    def save_as(self, path: str) -> None:
        Path(path).write_bytes(self.content)


def export_yunqi_excel_via_rpa(
    *,
    filter_config_path: str | Path | None = None,
    headless: bool | None = None,
    background_headed: bool | None = None,
    login_only: bool = False,
    search_only: bool = False,
    keep_open_on_error: bool = False,
    keep_browser_open: bool = False,
    use_cdp: bool = False,
    run_step: str | None = None,
) -> dict[str, Any]:
    filter_config = load_filter_config(filter_config_path)
    resolved_step = normalize_run_step(run_step)
    config = YunqiRpaConfig.from_env(
        start_url=str(filter_config.get("start_url") or "").strip(),
        headless=headless,
        background_headed=background_headed,
    )
    if config.headless and config.background_headed:
        config = replace_dataclass(config, background_headed=False)

    config.user_data_dir.mkdir(parents=True, exist_ok=True)
    config.download_dir.mkdir(parents=True, exist_ok=True)
    (config.download_dir / "errors").mkdir(parents=True, exist_ok=True)
    DEFAULT_CATEGORY_DIR.mkdir(parents=True, exist_ok=True)
    ensure_runtime_dirs()
    ensure_playwright_browser_path()

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise YunqiRpaError(
            "Playwright is not installed. Run `pip install -r backend/requirements.txt` "
            "and then `python -m playwright install chromium`."
        ) from exc

    with sync_playwright() as playwright:
        launch_options: dict[str, Any] = {
            "user_data_dir": str(config.user_data_dir),
            "headless": config.headless,
            "accept_downloads": True,
            "downloads_path": str(config.download_dir),
            "slow_mo": config.slow_mo_ms,
        }
        launch_args = [
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-features=CalculateNativeWinOcclusion",
        ]
        if config.headless:
            launch_options["viewport"] = {"width": config.viewport_width, "height": config.viewport_height}
        elif config.background_headed:
            launch_options["viewport"] = {"width": config.window_width, "height": config.window_height}
            launch_args.extend(
                [
                    f"--window-size={config.window_width},{config.window_height}",
                ]
            )
        else:
            launch_args.append("--start-maximized")
            launch_options["no_viewport"] = True
        launch_options["args"] = launch_args

        browser = None
        try:
            if use_cdp:
                browser = connect_or_launch_cdp_browser(playwright, config, launch_args)
                context = select_live_browser_context(browser)
            else:
                write_chrome_download_preferences(config.user_data_dir, config.download_dir)
                context = playwright.chromium.launch_persistent_context(**launch_options)
        except Exception as exc:  # noqa: BLE001
            root_cause = f"{type(exc).__name__}: {exc}"
            raise YunqiRpaError(
                "Could not start the Yunqi robot browser. "
                "If another robot browser is already open, close that browser or stop the older process first. "
                f"Profile: {config.user_data_dir}. Root cause: {root_cause}"
            ) from exc
        page = select_live_page(context)
        page.set_default_timeout(config.navigation_timeout_ms)
        configure_browser_download_directory(page, config.download_dir)

        try:
            ensure_yunqi_page(page, config, force=resolved_step in {"full", "open_browser"})
            if login_only:
                if config.headless:
                    raise YunqiRpaError("--login requires a headed browser. Use --headed or omit --headless.")
                input("Log in to the Yunqi robot browser, then press Enter here to save the session...")
                return {
                    "status": "login_saved",
                    "start_url": config.start_url,
                    "browser_mode": describe_browser_mode(config),
                    "profile_dir": str(config.user_data_dir),
                    "viewport": read_viewport_info(page),
                }

            if config.background_headed:
                wait_for_page_inputs(page)
                center_browser_window(page, config.window_width, config.window_height)
                minimize_browser_window(page)

            action_plan = build_filter_action_plan(filter_config)

            if resolved_step == "open_browser":
                return build_rpa_result("browser_opened", config, page, run_step=resolved_step)

            if resolved_step == "crawl_categories":
                perform_actions(page, action_plan["setup"])
                crawl_result = crawl_categories_from_filter_config(page, config, filter_config)
                return {
                    **build_rpa_result("categories_crawled", config, page, run_step=resolved_step),
                    **crawl_result,
                }

            if resolved_step == "site":
                perform_actions(page, action_plan["setup"])
                perform_actions(page, action_plan["site"])
                return build_rpa_result("site_selected", config, page, run_step=resolved_step)

            if resolved_step == "category":
                perform_actions(page, action_plan["setup"])
                perform_actions(page, action_plan["category"])
                return build_rpa_result("category_selected", config, page, run_step=resolved_step)

            if resolved_step == "listing_date":
                perform_actions(page, action_plan["setup"])
                perform_actions(page, action_plan["listing_date"])
                return build_rpa_result("listing_date_filled", config, page, run_step=resolved_step)

            if resolved_step == "search":
                perform_search(page, filter_config, config)
                return build_rpa_result("searched", config, page, run_step=resolved_step)

            if resolved_step == "full":
                perform_actions(page, action_plan["setup"])
                perform_actions(page, action_plan["site"])
                perform_actions(page, action_plan["category"])
                perform_actions(page, action_plan["listing_date"])
                perform_actions(page, filter_config.get("before_search_actions", []))
                perform_search(page, filter_config, config)
                if search_only or filter_config.get("search_only"):
                    return build_rpa_result("searched", config, page, run_step="search_only")

            perform_actions(page, filter_config.get("before_export_actions", []))
            export_mode = str(filter_config.get("export_mode") or "modal").strip().lower()
            if export_mode in {"direct", "direct_download", "legacy"}:
                with page.expect_download(timeout=config.download_timeout_ms) as download_info:
                    if filter_config.get("export_action"):
                        perform_action(page, filter_config["export_action"])
                    else:
                        click_first_named_button(page, config.export_button_names, optional=False)
                download = download_info.value
            else:
                download = export_yunqi_download_via_modal(page, config=config, filter_config=filter_config)
            saved_path = save_download(download, config.download_dir)
            original_download_path = saved_path
            saved_path = rename_export_for_filter_config(saved_path, filter_config)
            result = {
                "status": "exported",
                "start_url": config.start_url,
                "run_step": resolved_step,
                "browser_mode": describe_browser_mode(config),
                "profile_dir": str(config.user_data_dir),
                "viewport": read_viewport_info(page),
                "download_path": str(saved_path),
                "suggested_filename": download.suggested_filename,
            }
            if str(original_download_path) != str(saved_path):
                result["original_download_path"] = str(original_download_path)
            return result
        except PlaywrightTimeoutError as exc:
            screenshot_path = save_error_screenshot(page, config.download_dir)
            wait_for_user_on_error(keep_open_on_error=keep_open_on_error, config=config)
            raise YunqiRpaError(f"Yunqi RPA timed out: {exc}. Screenshot: {screenshot_path}") from exc
        except Exception as exc:
            screenshot_path = save_error_screenshot(page, config.download_dir)
            wait_for_user_on_error(keep_open_on_error=keep_open_on_error, config=config)
            if isinstance(exc, YunqiRpaError):
                raise YunqiRpaError(f"{exc}. Screenshot: {screenshot_path}") from exc
            raise YunqiRpaError(f"Yunqi RPA failed: {exc}. Screenshot: {screenshot_path}") from exc
        finally:
            if use_cdp:
                if not keep_browser_open and browser is not None:
                    browser.close()
            elif keep_browser_open and not config.headless:
                wait_until_browser_window_closed(context)
            else:
                context.close()


def load_filter_config(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    config_path = Path(path)
    if not config_path.exists():
        raise YunqiRpaError(f"Filter config does not exist: {config_path}")
    with config_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise YunqiRpaError("Filter config must be a JSON object.")
    return payload


def normalize_run_step(run_step: str | None) -> str:
    if not run_step:
        return "full"
    normalized = str(run_step).strip().lower().replace("-", "_")
    aliases = {
        "open": "open_browser",
        "browser": "open_browser",
        "crawl_category": "crawl_categories",
        "categories": "crawl_categories",
        "category_tree": "crawl_categories",
        "country": "site",
        "select_country": "site",
        "station": "site",
        "select_site": "site",
        "select_category": "category",
        "date": "listing_date",
        "publish_date": "listing_date",
        "listing_time": "listing_date",
        "click_search": "search",
        "download": "export",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in RPA_RUN_STEPS:
        raise YunqiRpaError(f"Unsupported RPA run step: {run_step}. Allowed: {', '.join(sorted(RPA_RUN_STEPS))}")
    return normalized


def ensure_yunqi_page(page: Any, config: YunqiRpaConfig, *, force: bool) -> None:
    current_url = str(getattr(page, "url", "") or "")
    if not force and is_same_site(current_url, config.start_url):
        return
    page.goto(config.start_url, wait_until="domcontentloaded")


def is_same_site(current_url: str, start_url: str) -> bool:
    if current_url in {"", "about:blank"}:
        return False
    current = urlparse(current_url)
    target = urlparse(start_url)
    return bool(current.netloc and target.netloc and current.netloc == target.netloc)


def build_filter_action_plan(filter_config: dict[str, Any]) -> dict[str, list[Any]]:
    plan = {
        "setup": list(filter_config.get("setup_actions") or []),
        "site": list(filter_config.get("site_actions") or filter_config.get("country_actions") or []),
        "category": list(filter_config.get("category_actions") or []),
        "listing_date": list(filter_config.get("listing_date_actions") or filter_config.get("date_actions") or []),
    }
    if not plan["site"]:
        plan["site"] = [
            {
                "type": "select_labeled_option",
                "label": os.getenv("YUNQI_SITE_LABEL", "国家"),
                "text": os.getenv("YUNQI_SITE_NAME", "美国站"),
            }
        ]

    legacy_actions = list(filter_config.get("actions") or [])
    if not legacy_actions:
        return plan

    has_explicit_step_actions = bool(plan["category"] or plan["listing_date"])
    if has_explicit_step_actions:
        plan["setup"].extend(
            action for action in legacy_actions if str(action.get("type") or "").strip().lower() == "assert_min_viewport"
        )
        return plan

    for action in legacy_actions:
        if not isinstance(action, dict):
            plan["setup"].append(action)
            continue
        action_type = str(action.get("type") or "").strip().lower()
        if action_type == "cascader_path":
            plan["category"].append(action)
        elif action_type == "date_range":
            plan["listing_date"].append(action)
        else:
            plan["setup"].append(action)
    return plan


def perform_search(page: Any, filter_config: dict[str, Any], config: YunqiRpaConfig) -> None:
    if filter_config.get("search_action"):
        perform_action(page, filter_config["search_action"])
    elif filter_config.get("auto_search", True):
        click_first_named_button(page, config.search_button_names, optional=True)
    perform_actions(page, filter_config.get("after_search_actions", []))


def build_rpa_result(status: str, config: YunqiRpaConfig, page: Any, *, run_step: str) -> dict[str, Any]:
    return {
        "status": status,
        "run_step": run_step,
        "start_url": config.start_url,
        "browser_mode": describe_browser_mode(config),
        "profile_dir": str(config.user_data_dir),
        "download_dir": str(config.download_dir),
        "viewport": read_viewport_info(page),
    }


def crawl_categories_from_filter_config(
    page: Any,
    config: YunqiRpaConfig,
    filter_config: dict[str, Any],
) -> dict[str, Any]:
    crawl_config = filter_config.get("category_crawl") if isinstance(filter_config.get("category_crawl"), dict) else {}
    placeholder = str(
        crawl_config.get("placeholder")
        or find_cascader_placeholder(filter_config)
        or os.getenv("YUNQI_CATEGORY_CRAWL_PLACEHOLDER")
        or "分类筛选"
    )
    max_depth = (
        to_int(crawl_config.get("max_depth"))
        or to_int(os.getenv("YUNQI_CATEGORY_CRAWL_MAX_DEPTH"))
        or 3
    )
    wait_ms = to_int(crawl_config.get("wait_ms")) or to_int(os.getenv("YUNQI_CATEGORY_CRAWL_WAIT_MS")) or 250
    timeout_ms = (
        to_int(crawl_config.get("timeout_ms")) or to_int(os.getenv("YUNQI_CATEGORY_CRAWL_TIMEOUT_MS")) or 20000
    )

    tree = crawl_category_tree(
        page,
        placeholder=placeholder,
        max_depth=max_depth,
        wait_ms=wait_ms,
        timeout_ms=timeout_ms,
    )
    node_count = count_category_nodes(tree)
    saved_path, latest_path, flat_saved_path, flat_latest_path = save_category_tree(
        tree,
        config=config,
        placeholder=placeholder,
        max_depth=max_depth,
        node_count=node_count,
    )
    database_result = import_category_tree_into_database(latest_path)
    return {
        "category_count": node_count,
        "category_tree_depth": max_depth,
        "category_output_path": str(saved_path),
        "category_latest_path": str(latest_path),
        "category_flat_output_path": str(flat_saved_path),
        "category_flat_latest_path": str(flat_latest_path),
        "category_database": database_result,
    }


def find_cascader_placeholder(filter_config: dict[str, Any]) -> str:
    for action in filter_config.get("actions") or []:
        if isinstance(action, dict) and str(action.get("type") or "").strip().lower() == "cascader_path":
            placeholder = str(action.get("placeholder") or "").strip()
            if placeholder:
                return placeholder
    for action in filter_config.get("category_actions") or []:
        if isinstance(action, dict) and str(action.get("type") or "").strip().lower() == "cascader_path":
            placeholder = str(action.get("placeholder") or "").strip()
            if placeholder:
                return placeholder
    return ""


def import_category_tree_into_database(path: Path) -> dict[str, Any]:
    try:
        from app.modules.yunqi.category_catalog import import_yunqi_categories_from_json

        return import_yunqi_categories_from_json(path)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "error": str(exc),
        }


def ensure_playwright_browser_path() -> None:
    if os.getenv("PLAYWRIGHT_BROWSERS_PATH", "").strip():
        return
    if DEFAULT_PLAYWRIGHT_BROWSERS_DIR.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(DEFAULT_PLAYWRIGHT_BROWSERS_DIR)


def connect_or_launch_cdp_browser(playwright: Any, config: YunqiRpaConfig, launch_args: list[str]) -> Any:
    endpoint = f"http://127.0.0.1:{config.cdp_port}"
    if not is_port_open("127.0.0.1", config.cdp_port):
        launch_cdp_chrome(config, launch_args)
        wait_for_cdp_port(config.cdp_port, timeout_seconds=20)
    return playwright.chromium.connect_over_cdp(endpoint)


def select_live_browser_context(browser: Any) -> Any:
    for context in browser.contexts:
        try:
            if any(not page.is_closed() for page in context.pages):
                return context
        except Exception:  # noqa: BLE001
            continue
    if browser.contexts:
        return browser.contexts[0]
    return browser.new_context(accept_downloads=True)


def select_live_page(context: Any) -> Any:
    for page in context.pages:
        try:
            if not page.is_closed():
                return page
        except Exception:  # noqa: BLE001
            continue
    return context.new_page()


def configure_browser_download_directory(page: Any, download_dir: Path) -> None:
    download_dir.mkdir(parents=True, exist_ok=True)
    try:
        session = page.context.new_cdp_session(page)
        session.send(
            "Browser.setDownloadBehavior",
            {
                "behavior": "allow",
                "downloadPath": str(download_dir),
                "eventsEnabled": True,
            },
        )
    except Exception:
        try:
            session = page.context.new_cdp_session(page)
            session.send(
                "Page.setDownloadBehavior",
                {
                    "behavior": "allow",
                    "downloadPath": str(download_dir),
                },
            )
        except Exception:
            pass


def write_chrome_download_preferences(user_data_dir: Path, download_dir: Path) -> None:
    download_dir.mkdir(parents=True, exist_ok=True)
    for profile_dir in (user_data_dir / "Default", user_data_dir):
        profile_dir.mkdir(parents=True, exist_ok=True)
        preferences_path = profile_dir / "Preferences"
        preferences: dict[str, Any] = {}
        if preferences_path.exists():
            try:
                with preferences_path.open("r", encoding="utf-8") as file:
                    payload = json.load(file)
                if isinstance(payload, dict):
                    preferences = payload
            except Exception:
                preferences = {}

        download_preferences = preferences.setdefault("download", {})
        if isinstance(download_preferences, dict):
            download_preferences["default_directory"] = str(download_dir)
            download_preferences["directory_upgrade"] = True
            download_preferences["prompt_for_download"] = False
        preferences.setdefault("savefile", {})["default_directory"] = str(download_dir)
        preferences_path.write_text(json.dumps(preferences, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def launch_cdp_chrome(config: YunqiRpaConfig, launch_args: list[str]) -> subprocess.Popen[Any]:
    executable = find_chrome_executable()
    config.user_data_dir.mkdir(parents=True, exist_ok=True)
    write_chrome_download_preferences(config.user_data_dir, config.download_dir)
    args = [
        str(executable),
        f"--remote-debugging-port={config.cdp_port}",
        f"--user-data-dir={config.user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-popup-blocking",
        "--disable-prompt-on-repost",
        f"--window-size={config.window_width},{config.window_height}",
        *launch_args,
        "about:blank",
    ]
    return subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )


def find_chrome_executable() -> Path:
    configured = os.getenv("YUNQI_RPA_CHROME_PATH", "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(sorted(DEFAULT_PLAYWRIGHT_BROWSERS_DIR.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True))
    candidates.extend(
        [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise YunqiRpaError(
        "Could not find a Chromium/Chrome executable. "
        "Set YUNQI_RPA_CHROME_PATH or run `python -m playwright install chromium`."
    )


def is_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def wait_for_cdp_port(port: int, *, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if is_port_open("127.0.0.1", port):
            return
        time.sleep(0.2)
    raise YunqiRpaError(f"Timed out waiting for Yunqi robot Chrome CDP port: {port}")


def perform_actions(page: Any, actions: Any) -> None:
    if not actions:
        return
    if not isinstance(actions, list):
        raise YunqiRpaError("RPA actions must be a list.")
    for action in actions:
        perform_action(page, action)


def perform_action(page: Any, action: Any) -> None:
    if not isinstance(action, dict):
        raise YunqiRpaError("Each RPA action must be a JSON object.")

    action_type = str(action.get("type") or "click").strip().lower()
    if action_type == "goto":
        page.goto(required_value(action, "url"), wait_until=action.get("wait_until") or "domcontentloaded")
        return
    if action_type in {"wait", "sleep"}:
        page.wait_for_timeout(to_int(action.get("milliseconds")) or to_int(action.get("ms")) or 1000)
        return
    if action_type == "wait_for_selector":
        page.locator(required_value(action, "selector")).first.wait_for()
        return
    if action_type == "assert_min_viewport":
        assert_min_viewport(page, to_int(required_value(action, "width")))
        return
    if action_type == "cascader_path":
        select_cascader_path(
            page,
            action.get("path"),
            placeholder=str(action.get("placeholder") or ""),
            wait_ms=to_int(action.get("wait_ms")) or 500,
            timeout_ms=to_int(action.get("timeout_ms")) or 20000,
        )
        return
    if action_type == "date_range":
        fill_labeled_date_range(
            page,
            label=required_value(action, "label"),
            start=resolve_date_value(action.get("start"), action.get("days_back")),
            end=resolve_date_value(action.get("end") or "today", None),
        )
        return
    if action_type == "select_labeled_option":
        select_labeled_option(
            page,
            label=required_value(action, "label"),
            text=required_value(action, "text"),
            exact=bool(action.get("exact", False)),
            wait_ms=to_int(action.get("wait_ms")) or 500,
        )
        return
    if action_type == "dom_click_text":
        click_text_via_dom(
            page,
            text=required_value(action, "text"),
            selector=str(action.get("selector") or "button"),
            exact=bool(action.get("exact", True)),
        )
        return

    locator = resolve_locator(page, action)
    if action_type == "fill":
        locator.first.fill(str(action.get("value", "")))
    elif action_type == "click":
        locator.first.click()
    elif action_type == "select":
        locator.first.select_option(str(action.get("value", "")))
    elif action_type == "check":
        locator.first.check()
    elif action_type == "press":
        locator.first.press(required_value(action, "key"))
    else:
        raise YunqiRpaError(f"Unsupported RPA action type: {action_type}")


def resolve_locator(page: Any, action: dict[str, Any]) -> Any:
    if action.get("selector"):
        return page.locator(str(action["selector"]))
    if action.get("role"):
        name = action.get("name")
        if name:
            return page.get_by_role(str(action["role"]), name=re.compile(str(name), re.I))
        return page.get_by_role(str(action["role"]))
    if action.get("label"):
        return page.get_by_label(str(action["label"]))
    if action.get("placeholder"):
        return page.get_by_placeholder(str(action["placeholder"]))
    if action.get("text"):
        return page.get_by_text(str(action["text"]), exact=bool(action.get("exact", False)))
    raise YunqiRpaError(f"RPA action needs selector, role, label, placeholder, or text: {action}")


def assert_min_viewport(page: Any, width: int) -> None:
    viewport = read_viewport_info(page)
    actual_width = to_int(viewport.get("innerWidth"))
    if not actual_width or actual_width >= width:
        return

    try_expand_viewport(page, width=width)
    viewport = read_viewport_info(page)
    actual_width = to_int(viewport.get("innerWidth"))
    if not actual_width or actual_width >= width:
        return

    minimum_workable_width = to_int(os.getenv("YUNQI_RPA_MIN_WORKABLE_WIDTH")) or 1180
    if actual_width >= minimum_workable_width:
        return

    raise YunqiRpaError(
        "Robot browser viewport is too narrow after resize attempt: "
        f"{actual_width}px < {width}px. Minimum workable width is {minimum_workable_width}px."
    )


def try_expand_viewport(page: Any, *, width: int) -> None:
    viewport = read_viewport_info(page)
    current_height = to_int(viewport.get("innerHeight")) or 800
    target_height = max(current_height, 800)
    try:
        page.set_viewport_size({"width": width, "height": target_height})
        page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001
        pass
    try:
        center_browser_window(page, width + 120, target_height + 120)
        page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001
        pass


def crawl_category_tree(
    page: Any,
    *,
    placeholder: str,
    max_depth: int,
    wait_ms: int,
    timeout_ms: int,
) -> list[dict[str, Any]]:
    if max_depth <= 0:
        raise YunqiRpaError("Category crawl max_depth must be greater than 0.")

    open_cascader(page, placeholder=placeholder, wait_ms=wait_ms, timeout_ms=timeout_ms)
    return crawl_category_level(page, level=0, parent_path=[], max_depth=max_depth, wait_ms=wait_ms)


def crawl_category_level(
    page: Any,
    *,
    level: int,
    parent_path: list[str],
    max_depth: int,
    wait_ms: int,
) -> list[dict[str, Any]]:
    nodes = read_category_level_nodes(page, level)
    tree: list[dict[str, Any]] = []
    for index, node in enumerate(nodes):
        label = str(node.get("label") or "").strip()
        if not label:
            continue

        path = [*parent_path, label]
        item: dict[str, Any] = {
            "label": label,
            "level": level + 1,
            "index": index,
            "node_id": node.get("node_id") or "",
            "aria_owns": node.get("aria_owns") or "",
            "aria_haspopup": bool(node.get("aria_haspopup")),
            "path": path,
            "path_text": " > ".join(path),
            "has_children": bool(node.get("has_children")),
            "disabled": bool(node.get("disabled")),
            "selected": bool(node.get("selected")),
            "checked": bool(node.get("checked")),
            "class_name": node.get("class_name") or "",
            "raw_text": node.get("raw_text") or label,
        }
        split_label = split_category_label(label)
        if split_label:
            item.update(split_label)

        if item["has_children"] and not item["disabled"] and level + 1 < max_depth:
            expand_category_node(page, level=level, index=index)
            page.wait_for_timeout(wait_ms)
            children = crawl_category_level(
                page,
                level=level + 1,
                parent_path=path,
                max_depth=max_depth,
                wait_ms=wait_ms,
            )
            item["children"] = children
        else:
            item["children"] = []
        tree.append(item)
    return tree


def open_cascader(page: Any, *, placeholder: str, wait_ms: int, timeout_ms: int) -> dict[str, Any]:
    open_result: dict[str, Any] = {}
    deadline = datetime.now() + timedelta(milliseconds=timeout_ms)
    while datetime.now() < deadline:
        locator_result = click_cascader_trigger_via_locator(page, placeholder=placeholder, timeout_ms=timeout_ms)
        if locator_result.get("ok"):
            page.wait_for_timeout(wait_ms)
            if read_category_level_nodes(page, 0):
                return locator_result

        open_result = evaluate_dom_action(
            page,
            """
            ({ placeholder }) => {
                const normalize = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
                const isVisible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                const inputs = Array.from(document.querySelectorAll('input'));
                const matchingInputs = inputs.filter((el) => !placeholder || el.placeholder.includes(placeholder));
                const visibleInputs = matchingInputs.filter(isVisible);
                const input = visibleInputs.find((el) => el.closest('.el-cascader') && el.classList.contains('el-input__inner'))
                    || visibleInputs.find((el) => el.closest('.el-cascader'))
                    || visibleInputs[0]
                    || matchingInputs.find((el) => el.closest('.el-cascader') && el.classList.contains('el-input__inner'))
                    || matchingInputs.find((el) => el.closest('.el-cascader'))
                    || matchingInputs[0];
                if (!input) {
                    return {
                        ok: false,
                        reason: 'cascader input not found',
                        url: window.location.href,
                        title: document.title,
                        inputCount: inputs.length,
                        inputs: inputs.slice(0, 20).map((el) => ({
                            placeholder: el.placeholder,
                            value: el.value,
                            className: el.className,
                            ariaLabel: el.getAttribute('aria-label'),
                            formItem: normalize(el.closest('.el-form-item')?.innerText || '')
                        }))
                    };
                }
                const root = input.closest('.el-cascader') || input.parentElement || input;
                input.scrollIntoView({ block: 'center', inline: 'center' });
                for (const eventName of ['mouseenter', 'mouseover', 'mousemove', 'mousedown', 'mouseup', 'click']) {
                    root.dispatchEvent(new MouseEvent(eventName, { bubbles: true, cancelable: true, view: window }));
                    input.dispatchEvent(new MouseEvent(eventName, { bubbles: true, cancelable: true, view: window }));
                }
                input.focus();
                input.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, key: 'ArrowDown' }));
                input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, cancelable: true, key: 'ArrowDown' }));
                return {
                    ok: true,
                    placeholder: input.placeholder,
                    className: input.className,
                    visible: isVisible(input),
                    rootClassName: root.className,
                };
            }
            """,
            {"placeholder": placeholder},
        )
        if open_result.get("ok"):
            page.wait_for_timeout(wait_ms)
            if read_category_level_nodes(page, 0):
                return open_result
        page.wait_for_timeout(500)
    raise YunqiRpaError(f"Could not open category cascader: {open_result}")


def click_cascader_trigger_via_locator(page: Any, *, placeholder: str, timeout_ms: int) -> dict[str, Any]:
    try:
        candidates = page.locator("div.el-cascader input.el-input__inner")
        count = min(candidates.count(), 10)
        selected_index = 0
        for index in range(count):
            candidate = candidates.nth(index)
            candidate_placeholder = str(candidate.get_attribute("placeholder") or "")
            candidate_class = str(candidate.get_attribute("class") or "")
            if "el-cascader__search-input" in candidate_class:
                continue
            if placeholder and placeholder not in candidate_placeholder:
                continue
            selected_index = index
            break
        target = candidates.nth(selected_index)
        target.click(force=True, timeout=min(timeout_ms, 5000))
        return {
            "ok": True,
            "method": "locator",
            "placeholder": str(target.get_attribute("placeholder") or ""),
            "className": str(target.get_attribute("class") or ""),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "method": "locator", "reason": f"{type(exc).__name__}: {exc}"}


def read_category_level_nodes(page: Any, level: int) -> list[dict[str, Any]]:
    result = evaluate_dom_action(
        page,
        """
        ({ level }) => {
            const normalize = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
            const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
            };
            const menus = Array.from(document.querySelectorAll('.el-cascader-menu'))
                .filter(isVisible)
                .sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
            const menu = menus[level];
            if (!menu) {
                return { ok: true, nodes: [], menuCount: menus.length };
            }
            const nodes = Array.from(menu.querySelectorAll('li.el-cascader-node[role="menuitem"], .el-cascader-node, li[role="menuitem"]'))
                .filter((node) => normalize(node.innerText || node.textContent));
            return {
                ok: true,
                menuCount: menus.length,
                nodes: nodes.map((node, index) => {
                    const labelNode = node.querySelector('.el-cascader-node__label') || node;
                    const rawText = normalize(node.innerText || node.textContent);
                    const label = normalize(labelNode.innerText || labelNode.textContent || rawText);
                    const ariaHaspopup = node.getAttribute('aria-haspopup') === 'true';
                    const ariaOwns = node.getAttribute('aria-owns') || '';
                    const hasArrow = Boolean(
                        node.querySelector('.el-icon-arrow-right, .el-cascader-node__postfix, [class*="arrow"]')
                    );
                    const disabled = node.classList.contains('is-disabled')
                        || node.getAttribute('aria-disabled') === 'true';
                    const checkbox = node.querySelector('.el-checkbox__original, input[type="checkbox"]');
                    return {
                        index,
                        node_id: node.id || '',
                        label,
                        raw_text: rawText,
                        aria_haspopup: ariaHaspopup,
                        aria_owns: ariaOwns,
                        has_children: (ariaHaspopup || Boolean(ariaOwns) || hasArrow) && !disabled,
                        disabled,
                        selected: node.classList.contains('in-active-path')
                            || node.classList.contains('is-active')
                            || node.getAttribute('aria-expanded') === 'true',
                        checked: Boolean(checkbox && checkbox.checked),
                        class_name: node.className,
                    };
                }),
            };
        }
        """,
        {"level": level},
    )
    if not result.get("ok"):
        raise YunqiRpaError(f"Could not read category level {level}: {result}")
    nodes = result.get("nodes") or []
    return nodes if isinstance(nodes, list) else []


def expand_category_node(page: Any, *, level: int, index: int) -> None:
    result = evaluate_dom_action(
        page,
        """
        ({ level, index }) => {
            const normalize = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
            const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
            };
            const menus = Array.from(document.querySelectorAll('.el-cascader-menu'))
                .filter(isVisible)
                .sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
            const menu = menus[level];
            if (!menu) return { ok: false, reason: 'menu level not found', level, menuCount: menus.length };
            const nodes = Array.from(menu.querySelectorAll('li.el-cascader-node[role="menuitem"], .el-cascader-node, li[role="menuitem"]'))
                .filter((node) => normalize(node.innerText || node.textContent));
            const node = nodes[index];
            if (!node) return { ok: false, reason: 'node index not found', level, index, nodeCount: nodes.length };

            node.scrollIntoView({ block: 'nearest', inline: 'nearest' });
            const target = node.querySelector('.el-cascader-node__postfix')
                || node.querySelector('.el-cascader-node__label')
                || node.querySelector('span')
                || node;
            for (const eventName of ['mouseenter', 'mouseover', 'mousemove', 'mousedown', 'mouseup', 'click']) {
                target.dispatchEvent(new MouseEvent(eventName, { bubbles: true, cancelable: true, view: window }));
                node.dispatchEvent(new MouseEvent(eventName, { bubbles: true, cancelable: true, view: window }));
            }
            return {
                ok: true,
                level,
                index,
                nodeId: node.id || '',
                ariaOwns: node.getAttribute('aria-owns') || '',
                ariaHaspopup: node.getAttribute('aria-haspopup') || '',
                text: normalize(node.innerText || node.textContent),
                className: node.className,
            };
        }
        """,
        {"level": level, "index": index},
    )
    if not result.get("ok"):
        raise YunqiRpaError(f"Could not expand category node: {result}")


def split_category_label(label: str) -> dict[str, str]:
    match = re.match(r"^(?P<en>.+?)\((?P<cn>[^()]*)\)$", label.strip())
    if not match:
        return {}
    return {
        "label_en": match.group("en").strip(),
        "label_cn": match.group("cn").strip(),
    }


def count_category_nodes(nodes: list[dict[str, Any]]) -> int:
    total = 0
    stack = list(nodes)
    while stack:
        node = stack.pop()
        total += 1
        children = node.get("children") or []
        if isinstance(children, list):
            stack.extend(child for child in children if isinstance(child, dict))
    return total


def save_category_tree(
    tree: list[dict[str, Any]],
    *,
    config: YunqiRpaConfig,
    placeholder: str,
    max_depth: int,
    node_count: int,
) -> tuple[Path, Path, Path, Path]:
    DEFAULT_CATEGORY_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().isoformat(timespec="seconds")
    flat_rows = flatten_category_tree(tree)
    payload = {
        "source": "yunqi",
        "generated_at": generated_at,
        "start_url": config.start_url,
        "placeholder": placeholder,
        "max_depth": max_depth,
        "category_count": node_count,
        "flat_count": len(flat_rows),
        "tree": tree,
    }
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved_path = DEFAULT_CATEGORY_DIR / f"yunqi_categories_{timestamp}.json"
    latest_path = DEFAULT_CATEGORY_DIR / "yunqi_categories_latest.json"
    flat_saved_path = DEFAULT_CATEGORY_DIR / f"yunqi_categories_flat_{timestamp}.csv"
    flat_latest_path = DEFAULT_CATEGORY_DIR / "yunqi_categories_flat_latest.csv"
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    saved_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")
    write_category_flat_csv(flat_saved_path, flat_rows)
    write_category_flat_csv(flat_latest_path, flat_rows)
    return saved_path, latest_path, flat_saved_path, flat_latest_path


def flatten_category_tree(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def visit(node: dict[str, Any], parent_path: str) -> None:
        row = {
            "level": node.get("level"),
            "label": node.get("label") or "",
            "label_en": node.get("label_en") or "",
            "label_cn": node.get("label_cn") or "",
            "path_text": node.get("path_text") or "",
            "parent_path_text": parent_path,
            "node_id": node.get("node_id") or "",
            "aria_haspopup": node.get("aria_haspopup"),
            "aria_owns": node.get("aria_owns") or "",
            "has_children": node.get("has_children"),
            "selected": node.get("selected"),
            "checked": node.get("checked"),
            "disabled": node.get("disabled"),
            "class_name": node.get("class_name") or "",
        }
        rows.append(row)
        for child in node.get("children") or []:
            if isinstance(child, dict):
                visit(child, str(node.get("path_text") or ""))

    for item in nodes:
        if isinstance(item, dict):
            visit(item, "")
    return rows


def write_category_flat_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "level",
        "label",
        "label_en",
        "label_cn",
        "path_text",
        "parent_path_text",
        "node_id",
        "aria_haspopup",
        "aria_owns",
        "has_children",
        "selected",
        "checked",
        "disabled",
        "class_name",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def select_cascader_path(page: Any, path: Any, *, placeholder: str, wait_ms: int, timeout_ms: int) -> None:
    if not isinstance(path, list) or not path:
        raise YunqiRpaError("cascader_path action requires a non-empty `path` list.")

    open_cascader(page, placeholder=placeholder, wait_ms=wait_ms, timeout_ms=timeout_ms)

    for item in path:
        target = str(item)
        click_result = click_cascader_item_via_locator(page, target, timeout_ms=timeout_ms)
        if not click_result.get("ok"):
            click_result = click_cascader_item_via_dom(page, target)
        if not click_result.get("ok"):
            raise YunqiRpaError(f"Could not select category path item `{target}`: {click_result}")
        page.wait_for_timeout(wait_ms)

    selection_state = read_cascader_selection_state(page, [str(item) for item in path])
    if not selection_state.get("ok"):
        raise YunqiRpaError(f"Category path was clicked but not selected: {selection_state}")
    close_cascader_dropdown(page, wait_ms=wait_ms)


def close_cascader_dropdown(page: Any, *, wait_ms: int) -> None:
    for _ in range(2):
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(max(100, wait_ms))
        except Exception:  # noqa: BLE001
            break
    try:
        page.evaluate("() => document.activeElement && document.activeElement.blur && document.activeElement.blur()")
    except Exception:  # noqa: BLE001
        pass


def cascader_text_candidates(label: str) -> list[str]:
    value = " ".join(str(label or "").split())
    candidates = [value] if value else []
    split_label = split_category_label(value)
    for key in ("label_en", "label_cn"):
        candidate = split_label.get(key)
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    if "(" in value:
        prefix = value.split("(", 1)[0].strip()
        if prefix and prefix not in candidates:
            candidates.append(prefix)
    return candidates


def click_cascader_item_via_locator(page: Any, target: str, *, timeout_ms: int) -> dict[str, Any]:
    errors: list[str] = []
    for candidate in cascader_text_candidates(target):
        try:
            locator = page.locator(".el-cascader-node:visible").filter(has_text=candidate).first
            locator.hover(timeout=min(timeout_ms, 5000))
            locator.click(force=True, timeout=min(timeout_ms, 5000))
            return {"ok": True, "method": "locator", "candidate": candidate}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{candidate}: {type(exc).__name__}: {exc}")
    return {"ok": False, "method": "locator", "target": target, "errors": errors}


def click_cascader_item_via_dom(page: Any, target: str) -> dict[str, Any]:
    return evaluate_dom_action(
        page,
        """
        ({ targets }) => {
            const normalize = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
            const targetTexts = targets.map(normalize).filter(Boolean);
            const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
            };
            const candidates = Array.from(document.querySelectorAll('.el-cascader-node, [role="menuitem"], li'));
            const visibleCandidates = candidates.filter(isVisible);
            const pools = [visibleCandidates, candidates];
            let node = null;
            for (const targetText of targetTexts) {
                for (const pool of pools) {
                    node = pool.find((el) => normalize(el.innerText || el.textContent) === targetText)
                        || pool.find((el) => normalize(el.innerText || el.textContent).includes(targetText));
                    if (node) break;
                }
                if (node) break;
            }
            if (!node) {
                return { ok: false, reason: 'category node not found', targets: targetTexts };
            }
            const target = node.querySelector('.el-cascader-node__label') || node;
            for (const eventName of ['mouseenter', 'mouseover', 'mousemove', 'mousedown', 'mouseup', 'click']) {
                target.dispatchEvent(new MouseEvent(eventName, { bubbles: true, cancelable: true, view: window }));
                node.dispatchEvent(new MouseEvent(eventName, { bubbles: true, cancelable: true, view: window }));
            }
            return { ok: true, method: 'dom', text: normalize(node.innerText || node.textContent), className: node.className };
        }
        """,
        {"targets": cascader_text_candidates(target)},
    )


def read_cascader_selection_state(page: Any, path: list[str]) -> dict[str, Any]:
    return evaluate_dom_action(
        page,
        """
        ({ path, candidateGroups }) => {
            const normalize = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
            const finalCandidates = candidateGroups[candidateGroups.length - 1] || [];
            const matches = (text, candidates) => candidates.some((candidate) => {
                const value = normalize(candidate);
                return value && (text === value || text.includes(value));
            });
            const tags = Array.from(document.querySelectorAll('.el-cascader__tags .el-tag, .el-cascader__tags span'))
                .map((node) => normalize(node.innerText || node.textContent))
                .filter(Boolean);
            const nodes = Array.from(document.querySelectorAll('.el-cascader-node, [role="menuitem"], li'))
                .map((node) => ({
                    text: normalize(node.innerText || node.textContent),
                    className: String(node.className || ''),
                }))
                .filter((node) => matches(node.text, finalCandidates));
            const activeNode = nodes.find((node) => (
                node.className.includes('is-active')
                || node.className.includes('in-checked-path')
                || node.className.includes('is-checked')
            ));
            const tagMatch = tags.find((tag) => matches(tag, finalCandidates));
            return {
                ok: Boolean(tagMatch || activeNode),
                path,
                finalCandidates,
                tags,
                matchingNodes: nodes,
            };
        }
        """,
        {"path": path, "candidateGroups": [cascader_text_candidates(item) for item in path]},
    )


def fill_labeled_date_range(page: Any, *, label: str, start: str, end: str) -> None:
    result = evaluate_dom_action(
        page,
        """
        ({ label, start, end }) => {
            const normalize = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
            const setNativeValue = (input, value) => {
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                setter.call(input, value);
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 'Enter' }));
                input.blur();
            };
            const labels = Array.from(document.querySelectorAll('label, .el-form-item__label'));
            const labelNode = labels.find((node) => normalize(node.innerText || node.textContent).includes(label));
            if (!labelNode) return { ok: false, reason: 'label not found', label };
            const item = labelNode.closest('.el-form-item') || labelNode.parentElement;
            if (!item) return { ok: false, reason: 'date form item not found', label };
            const inputs = Array.from(item.querySelectorAll('input'));
            const startInput = inputs.find((input) => input.placeholder.includes('开始')) || inputs[0];
            const endInput = inputs.find((input) => input.placeholder.includes('结束')) || inputs[1];
            if (!startInput || !endInput) {
                return { ok: false, reason: 'date inputs not found', label, inputCount: inputs.length };
            }
            setNativeValue(startInput, start);
            setNativeValue(endInput, end);
            document.body.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
            return {
                ok: true,
                label,
                startValue: startInput.value,
                endValue: endInput.value,
                placeholders: [startInput.placeholder, endInput.placeholder],
            };
        }
        """,
        {"label": label, "start": start, "end": end},
    )
    if not result.get("ok"):
        raise YunqiRpaError(f"Could not fill `{label}` date range: {result}")


def select_labeled_option(page: Any, *, label: str, text: str, exact: bool, wait_ms: int) -> None:
    current_result = evaluate_dom_action(
        page,
        """
        ({ label, text, exact }) => {
            const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
            const labels = Array.from(document.querySelectorAll('label, .el-form-item__label'));
            const labelNode = labels.find((node) => normalize(node.innerText || node.textContent).includes(label));
            const item = labelNode && (labelNode.closest('.el-form-item') || labelNode.parentElement);
            const input = item && (
                item.querySelector('input.el-input__inner')
                || item.querySelector('input')
            );
            const value = normalize(input ? input.value : '');
            const target = normalize(text);
            return {
                ok: !!labelNode && !!item && !!input,
                label,
                value,
                expected: target,
                alreadySelected: exact ? value === target : value.includes(target),
            };
        }
        """,
        {"label": label, "text": text, "exact": exact},
    )
    if current_result.get("alreadySelected"):
        return
    close_cascader_dropdown(page, wait_ms=wait_ms)

    direct_result = evaluate_dom_action(
        page,
        """
        ({ text, exact }) => {
            const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
            const target = normalize(text);
            const matchingDropdowns = Array.from(document.querySelectorAll('.el-select-dropdown')).filter((dropdown) => {
                const dropdownText = normalize(dropdown.innerText || dropdown.textContent);
                return dropdownText.includes(target);
            });
            if (matchingDropdowns.length !== 1) {
                return {
                    ok: false,
                    reason: matchingDropdowns.length ? 'ambiguous hidden option' : 'hidden option not found',
                    text: target,
                    dropdownCount: matchingDropdowns.length,
                };
            }
            for (const dropdown of matchingDropdowns) {
                const dropdownText = normalize(dropdown.innerText || dropdown.textContent);
                const candidates = Array.from(
                    dropdown.querySelectorAll('.el-select-dropdown__item, li[role="option"], [role="option"], li')
                );
                const node = candidates.find((el) => {
                    const current = normalize(el.innerText || el.textContent || el.value);
                    return exact ? current === target : current.includes(target);
                });
                if (!node) continue;
                for (const eventName of ['mouseenter', 'mouseover', 'mousedown', 'mouseup', 'click']) {
                    node.dispatchEvent(new MouseEvent(eventName, { bubbles: true, cancelable: true, view: window }));
                }
                return {
                    ok: true,
                    strategy: 'hidden_dropdown_option',
                    text: normalize(node.innerText || node.textContent || node.value),
                    dropdownText,
                    className: node.className,
                };
            }
            return { ok: false, reason: 'hidden option not found', text: target };
        }
        """,
        {"text": text, "exact": exact},
    )
    if direct_result.get("ok"):
        page.wait_for_timeout(300)
        if verify_labeled_option(page, label=label, text=text, exact=exact):
            return

    open_result = evaluate_dom_action(
        page,
        """
        ({ label }) => {
            const normalize = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
            const labels = Array.from(document.querySelectorAll('label, .el-form-item__label'));
            const labelNode = labels.find((node) => normalize(node.innerText || node.textContent).includes(label));
            if (!labelNode) return { ok: false, reason: 'label not found', label };
            const item = labelNode.closest('.el-form-item') || labelNode.parentElement;
            if (!item) return { ok: false, reason: 'form item not found', label };

            const root = item.querySelector('.el-select')
                || item.querySelector('.el-input')
                || item.querySelector('[role="combobox"]')
                || item;
            const input = root.querySelector('input') || root;
            for (const eventName of ['mouseenter', 'mouseover', 'mousedown', 'mouseup', 'click']) {
                root.dispatchEvent(new MouseEvent(eventName, { bubbles: true, cancelable: true, view: window }));
                input.dispatchEvent(new MouseEvent(eventName, { bubbles: true, cancelable: true, view: window }));
            }
            if (input.focus) input.focus();
            input.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, key: 'ArrowDown' }));
            return {
                ok: true,
                label,
                formItemText: normalize(item.innerText || item.textContent),
                inputValue: input.value || '',
            };
        }
        """,
        {"label": label},
    )
    if not open_result.get("ok"):
        raise YunqiRpaError(f"Could not open `{label}` selector: {open_result}")

    page.wait_for_timeout(wait_ms)
    locator_error = ""
    try:
        option_pattern = re.compile(rf"^\s*{re.escape(text)}\s*$") if exact else re.compile(re.escape(text))
        page.locator(".el-select-dropdown:visible .el-select-dropdown__item").filter(
            has_text=option_pattern
        ).first.click(timeout=5000)
        page.wait_for_timeout(300)
        if verify_labeled_option(page, label=label, text=text, exact=exact):
            return
        locator_error = str(read_labeled_option_value(page, label=label, text=text, exact=exact))
    except Exception as exc:  # noqa: BLE001
        locator_error = f"{type(exc).__name__}: {exc}"

    select_result = evaluate_dom_action(
        page,
        """
        ({ text, exact }) => {
            const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
            const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
            };
            const target = normalize(text);
            const dropdowns = Array.from(document.querySelectorAll('.el-select-dropdown')).filter(isVisible);
            const pools = dropdowns.length ? dropdowns : [document];
            const candidates = [];
            let node = null;
            let dropdownText = '';
            for (const pool of pools) {
                const poolCandidates = Array.from(
                    pool.querySelectorAll('.el-select-dropdown__item, li[role="option"], [role="option"]')
                );
                for (const el of poolCandidates) {
                    const current = normalize(el.innerText || el.textContent || el.value);
                    if (current) candidates.push(current);
                    if (!node && (exact ? current === target : current.includes(target))) {
                        node = el;
                        dropdownText = normalize(pool.innerText || pool.textContent);
                    }
                }
                if (node) break;
            }
            if (!node) {
                return {
                    ok: false,
                    reason: 'option not found',
                    text: target,
                    dropdownCount: dropdowns.length,
                    candidates: candidates.slice(0, 30)
                };
            }
            for (const eventName of ['mouseenter', 'mouseover', 'mousedown', 'mouseup', 'click']) {
                node.dispatchEvent(new MouseEvent(eventName, { bubbles: true, cancelable: true, view: window }));
            }
            node.click();
            return {
                ok: true,
                text: normalize(node.innerText || node.textContent || node.value),
                className: node.className,
                dropdownText,
            };
        }
        """,
        {"text": text, "exact": exact},
    )
    if not select_result.get("ok"):
        select_result["locator_error"] = locator_error
        raise YunqiRpaError(f"Could not select `{text}` for `{label}`: {select_result}")

    page.wait_for_timeout(300)
    if not verify_labeled_option(page, label=label, text=text, exact=exact):
        verify_result = read_labeled_option_value(page, label=label, text=text, exact=exact)
        raise YunqiRpaError(f"`{label}` did not keep selected value `{text}`: {verify_result}")


def verify_labeled_option(page: Any, *, label: str, text: str, exact: bool) -> bool:
    return bool(read_labeled_option_value(page, label=label, text=text, exact=exact).get("ok"))


def read_labeled_option_value(page: Any, *, label: str, text: str, exact: bool) -> dict[str, Any]:
    return evaluate_dom_action(
        page,
        """
        ({ label, text, exact }) => {
            const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
            const labels = Array.from(document.querySelectorAll('label, .el-form-item__label'));
            const labelNode = labels.find((node) => normalize(node.innerText || node.textContent).includes(label));
            const item = labelNode && (labelNode.closest('.el-form-item') || labelNode.parentElement);
            const input = item && (
                item.querySelector('input.el-input__inner')
                || item.querySelector('input')
            );
            const value = normalize(input ? input.value : '');
            const target = normalize(text);
            return {
                ok: exact ? value === target : value.includes(target),
                label,
                value,
                expected: target,
            };
        }
        """,
        {"label": label, "text": text, "exact": exact},
    )


def click_text_via_dom(page: Any, *, text: str, selector: str, exact: bool) -> None:
    result = evaluate_dom_action(
        page,
        """
        ({ selector, text, exact }) => {
            const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
            const target = normalize(text);
            const nodes = Array.from(document.querySelectorAll(selector));
            const node = nodes.find((el) => {
                const current = normalize(el.innerText || el.textContent || el.value);
                return exact ? current === target : current.includes(target);
            });
            if (!node) {
                return {
                    ok: false,
                    reason: 'click text target not found',
                    selector,
                    text: target,
                    candidates: nodes.slice(0, 20).map((el) => normalize(el.innerText || el.textContent || el.value))
                };
            }
            for (const eventName of ['mouseenter', 'mouseover', 'mousedown', 'mouseup', 'click']) {
                node.dispatchEvent(new MouseEvent(eventName, { bubbles: true, cancelable: true, view: window }));
            }
            return { ok: true, text: normalize(node.innerText || node.textContent || node.value), className: node.className };
        }
        """,
        {"selector": selector, "text": text, "exact": exact},
    )
    if not result.get("ok"):
        raise YunqiRpaError(f"Could not click text via DOM: {result}")


def parse_yunqi_export_record_time(value: Any) -> datetime | None:
    match = YUNQI_EXPORT_RECORD_TIME_RE.search(str(value or ""))
    if not match:
        return None
    text = match.group(0)
    for time_format in YUNQI_EXPORT_RECORD_TIME_FORMATS:
        try:
            return datetime.strptime(text, time_format)
        except ValueError:
            continue
    return None


def select_yunqi_export_download_record(
    records: list[dict[str, Any]],
    *,
    previous_records: set[str],
    requested_at: datetime,
    timestamp_tolerance_seconds: int = 5,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    min_record_time = requested_at - timedelta(seconds=max(timestamp_tolerance_seconds, 0))
    candidates: list[tuple[datetime, int, dict[str, Any]]] = []
    rejected: list[dict[str, Any]] = []

    for index, record in enumerate(records):
        if not record.get("has_download"):
            continue

        fingerprint = str(record.get("fingerprint") or record.get("text") or "").strip()
        time_text = str(record.get("time_text") or "").strip()
        record_time = parse_yunqi_export_record_time(time_text or fingerprint)
        summary = {
            "index": record.get("index", index),
            "fingerprint": fingerprint,
            "time_text": time_text,
        }

        if fingerprint in previous_records:
            rejected.append({**summary, "reason": "already_existed_before_export"})
            continue
        if record_time is None:
            rejected.append({**summary, "reason": "missing_or_unparseable_timestamp"})
            continue
        if record_time < min_record_time:
            rejected.append(
                {
                    **summary,
                    "reason": "timestamp_before_current_export",
                    "record_time": record_time.isoformat(sep=" "),
                    "min_record_time": min_record_time.isoformat(sep=" "),
                }
            )
            continue

        selected = dict(record)
        selected["record_time"] = record_time.isoformat(sep=" ")
        selected["min_record_time"] = min_record_time.isoformat(sep=" ")
        candidates.append((record_time, int(record.get("index", index) or 0), selected))

    if not candidates:
        return None, rejected

    candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    return candidates[0][2], rejected


def export_yunqi_download_via_modal(page: Any, *, config: YunqiRpaConfig, filter_config: dict[str, Any]) -> Any:
    modal_config = filter_config.get("export_modal") if isinstance(filter_config.get("export_modal"), dict) else {}
    modal_timeout_ms = to_int(modal_config.get("timeout_ms")) or 300000
    confirm_timeout_ms = to_int(modal_config.get("confirm_timeout_ms")) or 15000
    download_response_timeout_ms = to_int(modal_config.get("download_response_timeout_ms")) or 60000
    raw_timestamp_tolerance_seconds = modal_config.get("timestamp_tolerance_seconds")
    timestamp_tolerance_seconds = (
        to_int(raw_timestamp_tolerance_seconds)
        if raw_timestamp_tolerance_seconds is not None
        else 5
    )
    start_text = str(modal_config.get("start_text") or "立即导出")
    download_text = str(modal_config.get("download_text") or "下载")

    state = read_yunqi_export_modal_state(page)
    if not state.get("visible"):
        if filter_config.get("export_action"):
            perform_action(page, filter_config["export_action"])
        else:
            click_first_named_button(page, config.export_button_names, optional=False)
        state = wait_for_yunqi_export_modal(page, timeout_ms=30000)

    previous_records = set(str(record.get("fingerprint") or "") for record in state.get("records") or [])
    export_requested_at = datetime.now()
    click_yunqi_export_dialog_text(page, start_text, timeout_ms=30000)
    confirm_yunqi_export_if_prompted(page, timeout_ms=confirm_timeout_ms)
    ready_state = wait_for_new_yunqi_export_download_record(
        page,
        previous_records=previous_records,
        requested_at=export_requested_at,
        timeout_ms=modal_timeout_ms,
        timestamp_tolerance_seconds=timestamp_tolerance_seconds or 0,
        reopen_button_names=config.export_button_names,
    )
    confirm_yunqi_export_if_prompted(page, timeout_ms=3000)
    return click_yunqi_export_download_and_capture(
        page,
        download_text=download_text,
        timeout_ms=min(download_response_timeout_ms, config.download_timeout_ms),
        selected_record=ready_state.get("selected_download_record") or {},
    )


def wait_for_yunqi_export_modal(page: Any, *, timeout_ms: int) -> dict[str, Any]:
    deadline = datetime.now() + timedelta(milliseconds=timeout_ms)
    latest_state: dict[str, Any] = {}
    while datetime.now() < deadline:
        latest_state = read_yunqi_export_modal_state(page)
        if latest_state.get("visible"):
            return latest_state
        page.wait_for_timeout(500)
    raise YunqiRpaError(f"Could not open Yunqi export dialog: {latest_state}")


def wait_for_new_yunqi_export_download_record(
    page: Any,
    *,
    previous_records: set[str],
    requested_at: datetime,
    timeout_ms: int,
    timestamp_tolerance_seconds: int,
    reopen_button_names: tuple[str, ...],
) -> dict[str, Any]:
    deadline = datetime.now() + timedelta(milliseconds=timeout_ms)
    latest_state: dict[str, Any] = {}
    while datetime.now() < deadline:
        confirm_yunqi_export_if_prompted(page, timeout_ms=1000)
        latest_state = read_yunqi_export_modal_state(page)
        if not latest_state.get("visible"):
            click_first_named_button(page, reopen_button_names, optional=True)
            page.wait_for_timeout(1000)
            latest_state = read_yunqi_export_modal_state(page)
            if not latest_state.get("visible"):
                page.wait_for_timeout(1000)
                continue
        records = latest_state.get("records") or []
        ready_record, rejected_records = select_yunqi_export_download_record(
            records,
            previous_records=previous_records,
            requested_at=requested_at,
            timestamp_tolerance_seconds=timestamp_tolerance_seconds,
        )
        latest_state["export_requested_at"] = requested_at.isoformat(sep=" ")
        latest_state["timestamp_tolerance_seconds"] = timestamp_tolerance_seconds
        latest_state["rejected_download_records"] = rejected_records[-10:]
        if ready_record:
            latest_state["selected_download_record"] = ready_record
            return latest_state
        page.wait_for_timeout(1000)
    raise YunqiRpaError(
        "Yunqi export did not produce a downloadable record with a timestamp matching this export request: "
        f"{latest_state}"
    )


def read_yunqi_export_modal_state(page: Any) -> dict[str, Any]:
    return evaluate_dom_action(
        page,
        """
        () => {
            const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
            const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
            };
            const dialogs = Array.from(document.querySelectorAll('.el-dialog, [role="dialog"], .el-message-box'))
                .filter(isVisible)
                .map((dialog) => ({
                    node: dialog,
                    text: normalize(dialog.innerText || dialog.textContent),
                }));
            const dialog = dialogs.find((item) => item.text.includes('数据导出'))?.node;
            if (!dialog) {
                return {
                    ok: true,
                    visible: false,
                    visibleDialogs: dialogs.map((item) => item.text.slice(0, 120)),
                };
            }
            const rows = Array.from(dialog.querySelectorAll('tbody tr, .el-table__body tr, table tr'))
                .map((row, index) => {
                    const text = normalize(row.innerText || row.textContent);
                    const cells = Array.from(row.querySelectorAll('td, .cell'))
                        .map((cell) => normalize(cell.innerText || cell.textContent))
                        .filter(Boolean);
                    const timeText = cells.find((cellText) => /\\d{4}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2}/.test(cellText))
                        || (text.match(/\\d{4}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2}(?::\\d{2})?/) || [''])[0];
                    const hasDownload = Array.from(row.querySelectorAll('a, button, span, div')).some(
                        (node) => normalize(node.innerText || node.textContent || node.value) === '下载'
                    );
                    return {
                        index,
                        text,
                        time_text: timeText,
                        fingerprint: text,
                        has_download: hasDownload,
                    };
                })
                .filter((row) => row.text && row.text !== '时间 操作' && row.text !== '暂无数据');
            const buttons = Array.from(dialog.querySelectorAll('button, a, span'))
                .map((node) => ({
                    text: normalize(node.innerText || node.textContent || node.value),
                    className: String(node.className || ''),
                    disabled: Boolean(node.disabled) || node.classList.contains('is-disabled'),
                }))
                .filter((item) => item.text);
            return {
                ok: true,
                visible: true,
                title: normalize(dialog.querySelector('.el-dialog__title')?.innerText || ''),
                records: rows,
                buttons,
            };
        }
        """,
        {},
    )


def click_yunqi_export_dialog_text(
    page: Any,
    text: str,
    *,
    timeout_ms: int,
    prefer_download_row: bool = False,
) -> None:
    try:
        dialog = page.locator(".el-dialog:visible, [role='dialog']:visible").filter(has_text="数据导出").first
        if prefer_download_row:
            raise RuntimeError("download rows need exact DOM matching")
        for selector in ("button", "a", "span", "div"):
            locator = dialog.locator(selector).filter(has_text=text).first
            locator.click(force=True, timeout=min(timeout_ms, 5000))
            return
    except Exception:
        pass

    result = evaluate_dom_action(
        page,
        """
        ({ text, preferDownloadRow }) => {
            const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
            const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
            };
            const targetText = normalize(text);
            const dialogs = Array.from(document.querySelectorAll('.el-dialog, [role="dialog"], .el-message-box'))
                .filter(isVisible);
            const dialog = dialogs.find((node) => normalize(node.innerText || node.textContent).includes('数据导出'));
            if (!dialog) {
                return { ok: false, reason: 'export dialog not found', text: targetText };
            }
            let nodes = [];
            if (preferDownloadRow) {
                const rows = Array.from(dialog.querySelectorAll('tbody tr, .el-table__body tr, table tr'))
                    .filter((row) => Array.from(row.querySelectorAll('button, a')).some(
                        (node) => normalize(node.innerText || node.textContent || node.value) === targetText
                    ));
                nodes = rows.flatMap((row) => Array.from(row.querySelectorAll('button, a')));
            } else {
                nodes = Array.from(dialog.querySelectorAll('button, a, span, div'));
            }
            const node = nodes.find((item) => normalize(item.innerText || item.textContent || item.value) === targetText)
                || nodes.find((item) => normalize(item.innerText || item.textContent || item.value).includes(targetText));
            if (!node) {
                return {
                    ok: false,
                    reason: 'dialog text target not found',
                    text: targetText,
                    candidates: nodes.slice(0, 30).map((item) => normalize(item.innerText || item.textContent || item.value)),
                };
            }
            node.scrollIntoView({ block: 'center', inline: 'center' });
            for (const eventName of ['mouseenter', 'mouseover', 'mousemove', 'mousedown', 'mouseup', 'click']) {
                node.dispatchEvent(new MouseEvent(eventName, { bubbles: true, cancelable: true, view: window }));
            }
            return { ok: true, text: normalize(node.innerText || node.textContent || node.value), className: node.className };
        }
        """,
        {"text": text, "preferDownloadRow": prefer_download_row},
    )
    if not result.get("ok"):
        raise YunqiRpaError(f"Could not click Yunqi export dialog text `{text}`: {result}")


def click_yunqi_export_record_download(
    page: Any,
    *,
    download_text: str,
    selected_record: dict[str, Any] | None,
    timeout_ms: int,
) -> None:
    record = selected_record or {}
    fingerprint = str(record.get("fingerprint") or record.get("text") or "").strip()
    time_text = str(record.get("time_text") or "").strip()
    if not fingerprint and not time_text:
        raise YunqiRpaError("Refusing to download Yunqi export without a selected timestamped download record.")
    if not parse_yunqi_export_record_time(time_text or fingerprint):
        raise YunqiRpaError(f"Refusing to download Yunqi export with an invalid timestamped record: {record}")

    result = evaluate_dom_action(
        page,
        """
        ({ downloadText, fingerprint, timeText }) => {
            const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
            const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
            };
            const targetDownloadText = normalize(downloadText);
            const targetFingerprint = normalize(fingerprint);
            const targetTimeText = normalize(timeText);
            const dialogs = Array.from(document.querySelectorAll('.el-dialog, [role="dialog"], .el-message-box'))
                .filter(isVisible);
            const dialog = dialogs.find((node) => normalize(node.innerText || node.textContent).includes('鏁版嵁瀵煎嚭'));
            if (false && !dialog) {
                return { ok: false, reason: 'export dialog not found', targetFingerprint, targetTimeText };
            }
            const rows = Array.from(document.querySelectorAll('tbody tr, .el-table__body tr, table tr, .el-table__row'))
                .filter(isVisible)
                .map((row, index) => ({
                    node: row,
                    index,
                    text: normalize(row.innerText || row.textContent),
                }))
                .filter((row) => row.text);
            const row = rows.find((item) => targetFingerprint && item.text === targetFingerprint)
                || rows.find((item) => targetFingerprint && item.text.includes(targetFingerprint))
                || rows.find((item) => targetTimeText && item.text.includes(targetTimeText));
            if (!row) {
                return {
                    ok: false,
                    reason: 'selected download record row not found',
                    targetFingerprint,
                    targetTimeText,
                    candidates: rows.slice(0, 20).map((item) => item.text),
                };
            }
            const findByText = (nodes) => nodes.find((item) => {
                const current = normalize(item.innerText || item.textContent || item.value);
                return current === targetDownloadText;
            }) || nodes.find((item) => {
                const current = normalize(item.innerText || item.textContent || item.value);
                return current.includes(targetDownloadText);
            });
            const clickableNodes = Array.from(row.node.querySelectorAll('button, a, [role="button"], .el-button'))
                .filter(isVisible);
            const fallbackNodes = Array.from(row.node.querySelectorAll('span, div')).filter(isVisible);
            const node = findByText(clickableNodes) || findByText(fallbackNodes);
            if (!node) {
                return {
                    ok: false,
                    reason: 'download target not found in selected row',
                    rowText: row.text,
                    targetDownloadText,
                    candidates: [...clickableNodes, ...fallbackNodes]
                        .slice(0, 20)
                        .map((item) => normalize(item.innerText || item.textContent || item.value)),
                };
            }
            node.scrollIntoView({ block: 'center', inline: 'center' });
            if (node.focus) node.focus();
            for (const eventName of ['mouseenter', 'mouseover', 'mousemove', 'mousedown', 'mouseup', 'click']) {
                node.dispatchEvent(new MouseEvent(eventName, { bubbles: true, cancelable: true, view: window }));
            }
            if (node.click) node.click();
            return {
                ok: true,
                rowText: row.text,
                targetFingerprint,
                targetTimeText,
                clickedTag: node.tagName,
                clickedClassName: String(node.className || ''),
                clickedText: normalize(node.innerText || node.textContent || node.value),
            };
        }
        """,
        {"downloadText": download_text, "fingerprint": fingerprint, "timeText": time_text},
    )
    if not result.get("ok"):
        raise YunqiRpaError(f"Could not click selected Yunqi export download record: {result}")


def click_yunqi_export_download_and_capture(
    page: Any,
    *,
    download_text: str,
    timeout_ms: int,
    selected_record: dict[str, Any] | None = None,
) -> Any:
    response_error: Exception | None = None
    try:
        with page.expect_response(
            lambda response: "/api/proxytemu/export/download/" in response.url,
            timeout=timeout_ms,
        ) as response_info:
            click_yunqi_export_record_download(
                page,
                download_text=download_text,
                selected_record=selected_record,
                timeout_ms=30000,
            )
        response = response_info.value
        return response_to_download(page, response)
    except Exception as exc:  # noqa: BLE001
        response_error = exc

    try:
        with page.expect_download(timeout=timeout_ms) as download_info:
            click_yunqi_export_record_download(
                page,
                download_text=download_text,
                selected_record=selected_record,
                timeout_ms=30000,
            )
        return download_info.value
    except Exception as exc:  # noqa: BLE001
        raise YunqiRpaError(
            "Could not capture Yunqi export download. "
            f"Response capture failed: {response_error}. Native download failed: {exc}"
        ) from exc


def suggest_filename_from_response(response: Any) -> str:
    headers = getattr(response, "headers", {}) or {}
    content_disposition = str(headers.get("content-disposition") or headers.get("Content-Disposition") or "")
    filename = ""
    match = re.search(r"filename\\*=UTF-8''([^;]+)", content_disposition, flags=re.I)
    if match:
        filename = unquote(match.group(1).strip().strip('"'))
    if not filename:
        match = re.search(r'filename="?([^";]+)"?', content_disposition, flags=re.I)
        if match:
            filename = unquote(match.group(1).strip())
    if not filename:
        path_name = Path(urlparse(str(getattr(response, "url", "") or "")).path).name
        filename = path_name or "yunqi_export"

    suffix = Path(filename).suffix.lower()
    content_type = str(headers.get("content-type") or headers.get("Content-Type") or "").lower()
    if not suffix:
        if "spreadsheet" in content_type or "excel" in content_type:
            filename = f"{filename}.xlsx"
        else:
            filename = f"{filename}.csv"
    return filename


def response_to_download(page: Any, response: Any) -> ResponseDownload:
    content = response.body()
    if not content:
        raise YunqiRpaError(f"Yunqi download response was empty: {response.url}")

    headers = getattr(response, "headers", {}) or {}
    content_type = str(headers.get("content-type") or headers.get("Content-Type") or "").lower()
    if "application/json" in content_type:
        try:
            payload = json.loads(content.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise YunqiRpaError(f"Yunqi download JSON could not be parsed: {response.url}") from exc
        file_url = str(payload.get("data") or payload.get("url") or "").strip() if isinstance(payload, dict) else ""
        if not file_url:
            raise YunqiRpaError(f"Yunqi download JSON did not include a file URL: {payload}")
        file_response = page.context.request.get(file_url, timeout=60000)
        if file_response.status >= 400:
            raise YunqiRpaError(f"Yunqi export file download failed: {file_response.status} {file_url}")
        file_content = file_response.body()
        if not file_content:
            raise YunqiRpaError(f"Yunqi export file response was empty: {file_url}")
        return ResponseDownload(
            content=file_content,
            suggested_filename=suggest_filename_from_url_or_response(file_url, file_response),
            url=file_url,
        )

    return ResponseDownload(
        content=content,
        suggested_filename=suggest_filename_from_response(response),
        url=response.url,
    )


def suggest_filename_from_url_or_response(url: str, response: Any) -> str:
    filename = suggest_filename_from_response(response)
    if filename and filename != "yunqi_export.csv":
        return filename
    parsed_name = Path(urlparse(url).path).name
    return parsed_name or filename or "yunqi_export.csv"


def confirm_yunqi_export_if_prompted(page: Any, *, timeout_ms: int) -> bool:
    deadline = datetime.now() + timedelta(milliseconds=timeout_ms)
    latest_result: dict[str, Any] = {}
    while datetime.now() < deadline:
        latest_result = evaluate_dom_action(
            page,
            """
            () => {
                const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
                const isDisplayed = (el) => {
                    let node = el;
                    while (node && node.nodeType === 1) {
                        const style = window.getComputedStyle(node);
                        if (style.display === 'none' || style.visibility === 'hidden') {
                            return false;
                        }
                        node = node.parentElement;
                    }
                    return true;
                };
                const exportConfirmText = '\\u662f\\u5426\\u786e\\u5b9a\\u5bfc\\u51fa';
                const exportQueuedText = '\\u5df2\\u751f\\u6210\\u5bfc\\u51fa\\u4efb\\u52a1';
                const exportText = '\\u5bfc\\u51fa';
                const okText = '\\u786e\\u5b9a';
                const boxes = Array.from(document.querySelectorAll('.el-message-box__wrapper, .el-message-box'))
                    .filter(isDisplayed);
                const box = boxes.find((node) => {
                    const text = normalize(node.innerText || node.textContent);
                    return text.includes(exportConfirmText)
                        || text.includes(exportQueuedText)
                        || (text.includes(exportText) && text.includes(okText));
                });
                if (!box) {
                    return { ok: false, reason: 'export confirm prompt not found' };
                }
                const buttons = Array.from(box.querySelectorAll('button'));
                const confirmButton = buttons.find((button) => {
                    const text = normalize(button.innerText || button.textContent || button.value);
                    return text === okText && String(button.className || '').includes('el-button--primary');
                })
                    || buttons.find((button) => normalize(button.innerText || button.textContent || button.value) === okText)
                    || buttons.find((button) => String(button.className || '').includes('el-button--primary'));
                if (!confirmButton) {
                    return {
                        ok: false,
                        reason: 'export confirm button not found',
                        boxText: normalize(box.innerText || box.textContent),
                        buttons: buttons.map((button) => normalize(button.innerText || button.textContent || button.value)),
                    };
                }
                for (const eventName of ['mouseenter', 'mouseover', 'mousemove', 'mousedown', 'mouseup', 'click']) {
                    confirmButton.dispatchEvent(new MouseEvent(eventName, { bubbles: true, cancelable: true, view: window }));
                }
                confirmButton.click();
                return {
                    ok: true,
                    clicked: normalize(confirmButton.innerText || confirmButton.textContent || confirmButton.value),
                    boxText: normalize(box.innerText || box.textContent),
                };
            }
            """,
            {},
        )
        if latest_result.get("ok"):
            page.wait_for_timeout(500)
            return True
        page.wait_for_timeout(500)
    return False


def evaluate_dom_action(page: Any, function_body: str, arg: dict[str, Any]) -> dict[str, Any]:
    try:
        result = page.evaluate(function_body, arg)
    except Exception as exc:  # noqa: BLE001
        raise YunqiRpaError(f"DOM action failed: {exc}") from exc
    return result if isinstance(result, dict) else {"ok": bool(result), "value": result}


def click_first_named_button(page: Any, names: tuple[str, ...], *, optional: bool) -> bool:
    for name in names:
        try:
            page.locator("button:visible").filter(has_text=re.compile(re.escape(name), re.I)).first.click(timeout=5000)
            return True
        except Exception:  # noqa: BLE001 - try the next visible button.
            pass
    for name in names:
        try:
            page.get_by_role("button", name=re.compile(re.escape(name), re.I)).first.click(timeout=5000)
            return True
        except Exception:  # noqa: BLE001 - try the next selector strategy.
            pass
    for name in names:
        try:
            page.get_by_text(name, exact=False).first.click(timeout=5000)
            return True
        except Exception:  # noqa: BLE001 - try the next visible text.
            pass
    if optional:
        return False
    raise YunqiRpaError(f"Could not find a Yunqi export button. Tried: {', '.join(names)}")


def save_download(download: Any, download_dir: Path) -> Path:
    suggested = Path(download.suggested_filename or "yunqi_export.xlsx").name
    if isinstance(download, ResponseDownload):
        suggested = normalize_download_filename_for_content(suggested, download.content)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]+", "_", suggested).strip("_") or "yunqi_export.xlsx"
    target = download_dir / f"{timestamp}_{safe_name}"
    download.save_as(str(target))
    return repair_download_extension_for_content(target)


def normalize_download_filename_for_content(filename: str, content: bytes) -> str:
    safe_filename = Path(filename or "yunqi_export.xlsx").name
    suffix = Path(safe_filename).suffix.lower()
    inferred_suffix = infer_download_suffix_from_content(content)
    if inferred_suffix and suffix != inferred_suffix:
        if suffix in {"", ".csv", ".txt", ".download"}:
            return str(Path(safe_filename).with_suffix(inferred_suffix))
    return safe_filename


def repair_download_extension_for_content(path: Path) -> Path:
    try:
        with path.open("rb") as file:
            magic = file.read(8)
    except OSError:
        return path

    inferred_suffix = infer_download_suffix_from_content(magic)
    if not inferred_suffix or path.suffix.lower() == inferred_suffix:
        return path
    if path.suffix.lower() not in {"", ".csv", ".txt", ".download"}:
        return path

    target = path.with_suffix(inferred_suffix)
    counter = 2
    while target.exists():
        target = path.with_name(f"{path.stem}_{counter}{inferred_suffix}")
        counter += 1
    path.rename(target)
    if path.exists() and path.is_file():
        path.unlink()
    return target


def infer_download_suffix_from_content(content: bytes) -> str | None:
    if content.startswith(b"PK\x03\x04"):
        return ".xlsx"
    if content.startswith(b"\xd0\xcf\x11\xe0"):
        return ".xls"
    return None


def save_error_screenshot(page: Any, download_dir: Path) -> str:
    path = download_dir / "errors" / f"yunqi_rpa_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        return str(path)
    except Exception:  # noqa: BLE001
        return "screenshot-unavailable"


def wait_for_user_on_error(*, keep_open_on_error: bool, config: YunqiRpaConfig) -> None:
    if not keep_open_on_error or config.headless:
        return
    stdin = getattr(sys, "stdin", None)
    if not stdin or not getattr(stdin, "isatty", lambda: False)():
        return
    try:
        input("RPA failed. Inspect the robot browser, then press Enter to close it...")
    except (EOFError, RuntimeError, OSError):
        return


def read_viewport_info(page: Any) -> dict[str, Any]:
    try:
        payload = page.evaluate(
            """() => ({
                innerWidth: window.innerWidth,
                innerHeight: window.innerHeight,
                outerWidth: window.outerWidth,
                outerHeight: window.outerHeight,
                devicePixelRatio: window.devicePixelRatio
            })"""
        )
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def wait_for_page_inputs(page: Any) -> None:
    try:
        page.wait_for_function("() => document.querySelectorAll('input').length > 0", timeout=30000)
    except Exception as exc:  # noqa: BLE001
        raise YunqiRpaError("Yunqi page did not expose any input controls after loading.") from exc


def center_browser_window(page: Any, width: int, height: int) -> None:
    try:
        screen = page.evaluate(
            """() => ({
                availWidth: window.screen.availWidth,
                availHeight: window.screen.availHeight
            })"""
        )
        avail_width = to_int(screen.get("availWidth") if isinstance(screen, dict) else None)
        avail_height = to_int(screen.get("availHeight") if isinstance(screen, dict) else None)
        window_width = min(width, max(avail_width - 40, 800)) if avail_width else width
        window_height = min(height, max(avail_height - 40, 600)) if avail_height else height
        left = max((avail_width - window_width) // 2, 0) if avail_width else 0
        top = max((avail_height - window_height) // 2, 0) if avail_height else 0

        session = page.context.new_cdp_session(page)
        window = session.send("Browser.getWindowForTarget")
        session.send(
            "Browser.setWindowBounds",
            {
                "windowId": window["windowId"],
                "bounds": {
                    "windowState": "normal",
                    "left": left,
                    "top": top,
                    "width": window_width,
                    "height": window_height,
                },
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise YunqiRpaError(f"Could not center the robot browser window: {exc}") from exc


def minimize_browser_window(page: Any) -> None:
    try:
        session = page.context.new_cdp_session(page)
        window = session.send("Browser.getWindowForTarget")
        session.send(
            "Browser.setWindowBounds",
            {
                "windowId": window["windowId"],
                "bounds": {"windowState": "minimized"},
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise YunqiRpaError(f"Could not minimize the robot browser window: {exc}") from exc


def wait_until_browser_window_closed(context: Any) -> None:
    while True:
        try:
            pages = [page for page in context.pages if not page.is_closed()]
        except Exception:
            return
        if not pages:
            return
        time.sleep(1)


def describe_browser_mode(config: YunqiRpaConfig) -> str:
    if config.headless:
        return "headless"
    if config.background_headed:
        return "background_headed"
    return "headed"


def resolve_date_value(value: Any, days_back: Any) -> str:
    today = datetime.now().date()
    offset = to_int(days_back)
    if offset:
        return (today - timedelta(days=offset)).isoformat()
    if value is None or str(value).strip() == "":
        return today.isoformat()

    text = str(value).strip().lower()
    if text == "today":
        return today.isoformat()
    if text == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    return str(value).strip()


def required_value(action: dict[str, Any], key: str) -> str:
    value = action.get(key)
    if value is None or str(value).strip() == "":
        raise YunqiRpaError(f"RPA action is missing `{key}`: {action}")
    return str(value)


def to_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def replace_dataclass(config: YunqiRpaConfig, **changes: Any) -> YunqiRpaConfig:
    data = {
        "start_url": config.start_url,
        "user_data_dir": config.user_data_dir,
        "download_dir": config.download_dir,
        "headless": config.headless,
        "background_headed": config.background_headed,
        "slow_mo_ms": config.slow_mo_ms,
        "viewport_width": config.viewport_width,
        "viewport_height": config.viewport_height,
        "window_width": config.window_width,
        "window_height": config.window_height,
        "cdp_port": config.cdp_port,
        "navigation_timeout_ms": config.navigation_timeout_ms,
        "download_timeout_ms": config.download_timeout_ms,
        "export_button_names": config.export_button_names,
        "search_button_names": config.search_button_names,
    }
    data.update(changes)
    return YunqiRpaConfig(**data)
