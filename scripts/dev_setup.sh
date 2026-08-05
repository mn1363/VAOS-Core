#!/usr/bin/env bash
# Create a virtual environment and install VAOS in editable mode with
# development dependencies.
set -euo pipefail

python3.13 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"

echo "Environment ready. Activate it with: source .venv/bin/activate"
