#!/usr/bin/env python3
"""Run the unittest suite and reject silently skipped tests in CI."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    suite = unittest.defaultTestLoader.discover("tests")
    result = unittest.TextTestRunner(verbosity=2).run(suite)

    if result.skipped:
        print("\nUnexpected skipped tests:", file=sys.stderr)
        for test, reason in result.skipped:
            print(f"- {test}: {reason}", file=sys.stderr)

    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
