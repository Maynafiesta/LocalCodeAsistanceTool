#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
command -v python3 >/dev/null || { printf 'Python 3 is required.\n' >&2; exit 1; }
command -v code >/dev/null || { printf 'Install VSCode inside the Ubuntu VM first.\n' >&2; exit 1; }
if [[ "$(uname -m)" != x86_64 ]]; then
  printf 'This package contains the Linux x64 VSIX; a matching architecture is required.\n' >&2
  exit 1
fi
test -f config.yaml
test -f continue-2.0.0-linux-x64.vsix
# Verify server access before changing the editor configuration.
python3 check-client.py --config config.yaml
code --install-extension "$PWD/continue-2.0.0-linux-x64.vsix"
continue_config_dir="${HOME}/.continue"
mkdir -p "$continue_config_dir"
if [[ -e "$continue_config_dir/config.yaml" || -L "$continue_config_dir/config.yaml" ]]; then
  config_backup="$(mktemp "$continue_config_dir/config.yaml.backup.XXXXXX")"
  cp -L "$continue_config_dir/config.yaml" "$config_backup"
  chmod 600 "$config_backup"
  printf 'Existing config backed up: %s\n' "$config_backup"
fi
config_staging="$(mktemp "$continue_config_dir/config.yaml.new.XXXXXX")"
cp config.yaml "$config_staging"
chmod 600 "$config_staging"
mv "$config_staging" "$continue_config_dir/config.yaml"
printf '\nContinue is configured. In VSCode run Developer: Reload Window.\n'
printf 'Disable Allow Anonymous Telemetry in Continue User Settings.\n'
printf 'Select Local C++14 Chat and Local FIM Completion, then test Chat and Tab autocomplete.\n'
