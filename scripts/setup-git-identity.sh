#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
identity_file="${project_root}/.windows-bridge/git-identity.config"

# Change only identity; preserve Dev Containers' credential helper and other settings.
# Repository-local user.* settings keep their normal precedence over global settings.
if [[ -r "$identity_file" ]]; then
  for key in user.name user.email; do
    if value="$(git config --file "$identity_file" --get "$key")"; then
      if [[ -n "$value" ]]; then
        git config --global "$key" "$value"
      fi
    else
      status=$?
      if [[ "$status" -ne 1 ]]; then
        echo "Cannot read host Git identity: $key" >&2
        exit "$status"
      fi
    fi
  done
fi

# Keep the base image's existing .env fallback for fields absent on the host.
cd "$project_root"
setup-git-identity

for key in user.name user.email; do
  if ! git config --get "$key" >/dev/null; then
    echo "Git $key is unset. Configure Git in the host WSL distro and reopen in Dev Containers." >&2
  fi
done
