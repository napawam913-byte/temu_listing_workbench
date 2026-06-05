from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build/update the local Yunqi category database.")
    parser.add_argument(
        "--category-json",
        default=os.getenv("YUNQI_CATEGORY_JSON"),
        help="Yunqi category tree JSON. Defaults to storage/yunqi_categories/yunqi_categories_latest.json.",
    )
    parser.add_argument(
        "--database-path",
        default=os.getenv("TEMU_WORKBENCH_DATABASE_PATH") or os.getenv("DATABASE_PATH"),
        help="Override the SQLite database path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.database_path:
        os.environ["TEMU_WORKBENCH_DATABASE_PATH"] = str(Path(args.database_path).expanduser())

    from app.core.config import DATABASE_PATH
    from app.modules.yunqi.category_catalog import import_yunqi_categories_from_json

    result = import_yunqi_categories_from_json(args.category_json)
    result["database_path"] = str(DATABASE_PATH)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
