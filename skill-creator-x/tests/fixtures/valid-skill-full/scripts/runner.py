#!/usr/bin/env python3
"""Minimal runnable stub used by valid-skill-full fixture (SC-001)."""

import sys


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: runner.py <csv>")
        return 2
    print(f"would summarize {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
