#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
if [[ ! -f .env ]]; then
  .venv/bin/codeassist-client developer --output clients --server http://127.0.0.1:8080
  cp clients/server.env .env
  chmod 600 .env
  printf '\nLOCAL_UID=%s\nLOCAL_GID=%s\n' "$(id -u)" "$(id -g)" >> .env
fi
mkdir -p data/context artifacts
docker compose up -d ollama
docker compose exec -T ollama ollama pull qwen2.5-coder:1.5b-base
docker compose exec -T ollama ollama pull qwen2.5-coder:7b-instruct-q4_K_M
docker compose up -d --build --wait gateway
printf 'Gateway: http://127.0.0.1:8080; client configuration: clients/developer/config.yaml\n'
