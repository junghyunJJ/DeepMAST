#!/bin/sh
set -eu
cd "$(dirname "$0")/../../.."
.venv/bin/python benchmarks/guardrail/scripts/reproduce_figure.py
