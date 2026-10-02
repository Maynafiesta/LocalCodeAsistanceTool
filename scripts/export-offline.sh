#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
bundle_path="${1:-artifacts/offline-bundle}"
if [[ -e "$bundle_path" ]]; then
  printf 'Destination already exists: %s\n' "$bundle_path" >&2
  exit 1
fi
test -d data/ollama/models
test -f artifacts/continue-2.0.0-linux-x64.vsix
mkdir -p "$bundle_path"
chmod 700 "$bundle_path"
# Models alone: exclude Ollama keys, prompts, local indexes and user credentials.
# Ollama writes some model metadata as root:600. Archive inside its own container.
docker compose exec -T ollama tar -cf - -C /root/.ollama models > "$bundle_path/models.tar"
docker image save --output "$bundle_path/images.tar" \
  ollama/ollama:0.35.0 codeassist-gateway:0.1.0
cp artifacts/continue-2.0.0-linux-x64.vsix "$bundle_path/"
tar -cf "$bundle_path/source.tar" \
  --exclude='__pycache__' --exclude='*.pyc' \
  codeassist scripts examples docs tests pyproject.toml requirements.lock \
  Dockerfile compose.yaml compose.offline.yaml .env.example .gitignore .dockerignore README.md
(cd "$bundle_path" && sha256sum models.tar images.tar source.tar *.vsix > SHA256SUMS)
printf 'Bundle prepared: %s. See docs/offline.md for deployment.\n' "$bundle_path"
