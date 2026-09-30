#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

uv_win="${UV_WIN:-/mnt/c/Users/katao/.local/bin/uv.exe}"
python_version="$(tr -d '[:space:]' < .python-version)"

if [[ ! -x "${uv_win}" ]]; then
  echo "setup-windows-venv: Windows uv was not found: ${uv_win}" >&2
  echo "Set UV_WIN to the host uv.exe path if it is installed elsewhere." >&2
  exit 1
fi

"${uv_win}" venv .venv-win --python "${python_version}"
UV_PROJECT_ENVIRONMENT=.venv-win "${uv_win}" sync "$@"
