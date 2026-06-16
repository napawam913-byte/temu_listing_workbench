from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.modules.visual_generation.worker import run_visual_queue_drain  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Temu workbench visual generation queue worker.")
    parser.add_argument("--sleep", type=float, default=2.0, help="Sleep seconds between empty drain passes.")
    parser.add_argument("--max-jobs", type=int, default=None, help="Max jobs to drain in one pass.")
    parser.add_argument("--once", action="store_true", help="Drain once and exit.")
    args = parser.parse_args()

    while True:
        result = run_visual_queue_drain(max_jobs=args.max_jobs)
        if args.once:
            print(result)
            return 0 if result.get("failed", 0) == 0 else 1
        if result.get("processed", 0) == 0:
            time.sleep(max(0.1, float(args.sleep or 0.1)))


if __name__ == "__main__":
    raise SystemExit(main())
