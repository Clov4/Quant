"""Thin wrapper around ``csequant.pipeline.build_cache``.

    python -m scripts.build_cache
    python -m scripts.build_cache --tickers IAM ATW BCP --start 2023-06-01

Equivalent to ``python -m csequant build-cache``; kept for convenience.
"""
from __future__ import annotations

import argparse

from csequant.config import load_config
from csequant.logging_conf import setup_logging
from csequant.pipeline import build_cache


def main() -> None:
    cfg = load_config()
    setup_logging(cfg.get("logging.level", "INFO"), cfg.path("logging.file"))
    ap = argparse.ArgumentParser(description="Build the CSE data cache")
    ap.add_argument("--tickers", nargs="*")
    ap.add_argument("--start")
    ap.add_argument("--end")
    args = ap.parse_args()
    cov = build_cache(cfg, args.tickers, args.start, args.end)
    print("\n=== Coverage ===")
    print(cov.to_string(index=False) if not cov.empty else "(no data)")


if __name__ == "__main__":
    main()
