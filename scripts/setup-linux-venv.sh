#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

python_version="$(tr -d '[:space:]' < .python-version)"

if ! command -v uv >/dev/null 2>&1; then
  echo "setup-linux-venv: uv is not available in this Linux container" >&2
  exit 1
fi

# sync creates a missing environment and preserves an existing one on retries.
UV_PROJECT_ENVIRONMENT=.venv-linux uv sync --python "${python_version}" "$@"
