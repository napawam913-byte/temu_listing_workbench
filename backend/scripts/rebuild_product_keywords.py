from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import init_db  # noqa: E402
from app.modules.recommendation.keyword_index import rebuild_all_product_keyword_index  # noqa: E402


def main() -> None:
    init_db()
    result = rebuild_all_product_keyword_index()
    print(
        f"Indexed {result['product_count']} products, "
        f"{result['keyword_count']} product keyword rows."
    )


if __name__ == "__main__":
    main()
