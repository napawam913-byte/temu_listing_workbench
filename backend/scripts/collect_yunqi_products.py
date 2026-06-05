from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Yunqi products and upsert them into the local SQLite DB.")
    parser.add_argument(
        "--replay-json",
        default=os.getenv("YUNQI_REPLAY_JSON"),
        help="Read Yunqi collection results from a local JSON file.",
    )
    parser.add_argument(
        "--excel-file",
        default=os.getenv("YUNQI_EXCEL_FILE"),
        help="Import a Yunqi exported Excel/CSV file with idempotent upsert.",
    )
    parser.add_argument("--rpa", action="store_true", help="Use the dedicated Playwright robot browser to export Excel.")
    parser.add_argument("--login", action="store_true", help="Open the dedicated robot browser for manual Yunqi login.")
    parser.add_argument(
        "--all-categories",
        action="store_true",
        help="Poll/export all active leaf categories from the local Yunqi category database.",
    )
    parser.add_argument(
        "--filter-config",
        default=os.getenv("YUNQI_FILTER_CONFIG"),
        help="JSON file describing Yunqi filter and export actions for RPA.",
    )
    browser_mode = parser.add_mutually_exclusive_group()
    browser_mode.add_argument("--headless", dest="browser_mode", action="store_const", const="headless", default=None)
    browser_mode.add_argument("--headed", dest="browser_mode", action="store_const", const="headed")
    browser_mode.add_argument(
        "--background-headed",
        dest="browser_mode",
        action="store_const",
        const="background_headed",
        help="Run a visible robot browser in the background/taskbar with a fixed viewport.",
    )
    parser.add_argument(
        "--search-only",
        action="store_true",
        help="Run Yunqi filters and search only; do not export or import.",
    )
    parser.add_argument(
        "--step",
        default=None,
        help=(
            "Run one RPA step: open_browser, site, crawl_categories, category, listing_date, search, export, or full. "
            "Aliases like open/date/download are also accepted."
        ),
    )
    parser.add_argument(
        "--category-max-depth",
        type=int,
        default=None,
        help="Maximum Yunqi category tree depth to crawl when --step crawl_categories is used.",
    )
    parser.add_argument(
        "--category-prefix",
        default=os.getenv("YUNQI_BATCH_CATEGORY_PREFIX"),
        help="Only batch-export categories whose path contains this text.",
    )
    parser.add_argument(
        "--category-limit",
        type=int,
        default=None,
        help="Export at most N categories in --all-categories mode. Useful for dry runs.",
    )
    parser.add_argument(
        "--batch-delay",
        type=float,
        default=float(os.getenv("YUNQI_BATCH_DELAY_SECONDS", "1")),
        help="Seconds to wait between category exports in --all-categories mode.",
    )
    parser.add_argument(
        "--batch-import",
        action="store_true",
        help="After each category export, import the downloaded Excel/CSV into products.",
    )
    parser.add_argument(
        "--batch-stop-on-error",
        action="store_true",
        help="Stop the category polling run on the first failed category.",
    )
    parser.add_argument(
        "--batch-max-consecutive-errors",
        type=int,
        default=3,
        help="Stop --all-categories after this many consecutive category failures.",
    )
    parser.add_argument(
        "--keep-open-on-error",
        action="store_true",
        help="Keep the robot browser open after an RPA failure for inspection.",
    )
    parser.add_argument(
        "--keep-browser-open",
        action="store_true",
        help="Leave the Yunqi robot browser open after this run.",
    )
    parser.add_argument(
        "--cdp",
        action="store_true",
        help="Use a persistent CDP-controlled Chrome instead of a one-shot Playwright context.",
    )
    parser.add_argument(
        "--database-path",
        default=os.getenv("TEMU_WORKBENCH_DATABASE_PATH") or os.getenv("DATABASE_PATH"),
        help="Override the SQLite DB path for this run.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Import at most N records from this run.")
    parser.add_argument("--fetch-details", action="store_true", help="Fetch product detail after list collection.")
    parser.add_argument("--skip-keywords", action="store_true", help="Skip rebuilding keyword index for imported rows.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.database_path:
        os.environ["TEMU_WORKBENCH_DATABASE_PATH"] = str(Path(args.database_path).expanduser())
    if args.category_max_depth:
        os.environ["YUNQI_CATEGORY_CRAWL_MAX_DEPTH"] = str(args.category_max_depth)

    from app.core.config import DATABASE_PATH  # noqa: E402
    from app.core.database import init_db  # noqa: E402
    from app.modules.yunqi.collector import (  # noqa: E402
        YunqiCollectorError,
        collect_yunqi_excel_file,
        collect_yunqi_products,
    )
    from app.modules.yunqi.batch_exporter import export_yunqi_all_categories  # noqa: E402
    from app.modules.yunqi.rpa_exporter import YunqiRpaError, export_yunqi_excel_via_rpa  # noqa: E402

    headless = None
    background_headed = False
    if args.browser_mode == "headless":
        headless = True
    elif args.browser_mode == "headed":
        headless = False
    elif args.browser_mode == "background_headed":
        headless = False
        background_headed = True

    try:
        if args.login and not args.rpa:
            raise YunqiCollectorError("--login must be used with --rpa.")
        if args.search_only and not args.rpa:
            raise YunqiCollectorError("--search-only must be used with --rpa.")
        if args.step and not args.rpa:
            raise YunqiCollectorError("--step must be used with --rpa.")
        if args.all_categories and not args.rpa:
            raise YunqiCollectorError("--all-categories must be used with --rpa.")

        if args.rpa and args.all_categories:
            result = export_yunqi_all_categories(
                headless=headless,
                background_headed=True if args.browser_mode is None else background_headed,
                keep_open_on_error=args.keep_open_on_error,
                keep_browser_open=True,
                use_cdp=True,
                category_prefix=args.category_prefix,
                category_limit=args.category_limit,
                delay_seconds=args.batch_delay,
                import_after_export=args.batch_import,
                import_limit=args.limit,
                rebuild_keywords=not args.skip_keywords,
                stop_on_error=args.batch_stop_on_error,
                max_consecutive_errors=args.batch_max_consecutive_errors,
                log=lambda message: print(message, file=sys.stderr),
            )
        elif args.rpa and args.login:
            result = export_yunqi_excel_via_rpa(
                filter_config_path=args.filter_config,
                headless=headless,
                background_headed=background_headed,
                login_only=True,
                search_only=args.search_only,
                keep_open_on_error=args.keep_open_on_error,
                keep_browser_open=args.keep_browser_open,
                use_cdp=args.cdp,
                run_step=args.step,
            )
        else:
            step_name = str(args.step or "").strip().lower().replace("-", "_")
            no_import_steps = {
                "open",
                "browser",
                "open_browser",
                "country",
                "select_country",
                "site",
                "station",
                "select_site",
                "crawl_category",
                "crawl_categories",
                "categories",
                "category_tree",
                "select_category",
                "category",
                "date",
                "publish_date",
                "listing_date",
                "listing_time",
                "click_search",
                "search",
            }
            if args.rpa and (args.search_only or step_name in no_import_steps):
                result = export_yunqi_excel_via_rpa(
                    filter_config_path=args.filter_config,
                    headless=headless,
                    background_headed=background_headed,
                    search_only=True,
                    keep_open_on_error=args.keep_open_on_error,
                    keep_browser_open=args.keep_browser_open,
                    use_cdp=args.cdp,
                    run_step=args.step,
                )
                result["database_imported"] = False
                result["keywords_rebuilt"] = False
                result["database_path"] = str(DATABASE_PATH)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0

            init_db()
            if args.rpa:
                export_result = export_yunqi_excel_via_rpa(
                    filter_config_path=args.filter_config,
                    headless=headless,
                    background_headed=background_headed,
                    search_only=args.search_only,
                    keep_open_on_error=args.keep_open_on_error,
                    keep_browser_open=args.keep_browser_open,
                    use_cdp=args.cdp,
                    run_step=args.step,
                )
                import_result = collect_yunqi_excel_file(
                    export_result["download_path"],
                    limit=args.limit,
                    rebuild_keywords=not args.skip_keywords,
                )
                result = {**import_result, "rpa": export_result}
            elif args.excel_file:
                result = collect_yunqi_excel_file(
                    args.excel_file,
                    limit=args.limit,
                    rebuild_keywords=not args.skip_keywords,
                )
            else:
                result = collect_yunqi_products(
                    replay_json_path=args.replay_json,
                    fetch_details=args.fetch_details,
                    limit=args.limit,
                    rebuild_keywords=not args.skip_keywords,
                )
    except (YunqiCollectorError, YunqiRpaError) as exc:
        print(f"Yunqi collection failed: {exc}", file=sys.stderr)
        return 1

    result["database_path"] = str(DATABASE_PATH)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
