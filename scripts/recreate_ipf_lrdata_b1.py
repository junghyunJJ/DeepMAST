#!/usr/bin/env python
"""Recreate final_ipf/lrdata_V19S23-092-B1.h5ad from n_ipf.h5ad."""

from __future__ import annotations

import argparse
from importlib import import_module
import sys
from pathlib import Path


DEFAULT_OUTPUT_DIR = Path("final_ipf")
DEFAULT_SAMPLE = "V19S23-092-B1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sp-enrich-root", type=Path, required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--sample", default=DEFAULT_SAMPLE)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_path = args.input or args.sp_enrich_root / "data/n_ipf.h5ad"
    target = args.output_dir / f"lrdata_{args.sample}.h5ad"

    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")
    if not args.sp_enrich_root.exists():
        raise SystemExit(f"sp_enrich_mcp not found: {args.sp_enrich_root}")
    if target.exists() and not args.force:
        raise SystemExit(f"Refusing to overwrite {target}; pass --force to rebuild it.")

    sys.path.insert(0, str(args.sp_enrich_root))
    run_lianap = import_module("mcp_servers.runplot_LIANAp_NMF").run_lianap

    run_lianap(
        filename=str(input_path),
        organism="human",
        platform="auto",
        sample_key="sample",
        interest_sample=args.sample,
        n_rings=2,
        distance_percentile=99.0,
        n_perms=100,
        max_iter_nmf=20,
        save_path=str(args.output_dir),
    )

    if not target.exists():
        raise SystemExit(f"Expected output was not created: {target}")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
