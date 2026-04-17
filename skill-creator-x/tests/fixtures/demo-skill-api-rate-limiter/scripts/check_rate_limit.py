"""Check API rate limit status.

Usage:
    python scripts/check_rate_limit.py --url <api-endpoint> [--max-retries 3]
"""

from __future__ import annotations

import argparse
import sys


def check(url: str, max_retries: int = 3) -> bool:
    """Check if the given URL is currently rate-limited.

    Returns True if the endpoint is accessible (not rate-limited),
    False if rate-limited or unreachable.
    """
    for attempt in range(max_retries):
        try:
            import urllib.request

            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.getcode()
                if status == 429:
                    continue
                return True
        except Exception:
            continue
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check API rate limit status")
    parser.add_argument("--url", required=True, help="API endpoint URL")
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args()

    ok = check(args.url, args.max_retries)
    if ok:
        print(f"OK: {args.url} is accessible")
    else:
        print(f"RATE-LIMITED: {args.url} returned 429 or is unreachable")
    sys.exit(0 if ok else 1)
