#!/usr/bin/env bash
# Run the VAOS CLI, forwarding any arguments through.
set -euo pipefail

python -m cli.main "$@"
