# Offline deployment

Runtime inference uses VS Code → LAN gateway → local Ollama. Initial dependencies,
images, models, and extension packages must be prepared before losing internet access.
No package/model download is part of an inference request.

## Prepare a bundle

On an internet-connected preparation machine, install the target-compatible NVIDIA
driver, Docker/Compose, and NVIDIA Container Toolkit. Run preparation and obtain the
matching Continue VSIX from its publisher, then export:

```bash
bash scripts/prepare.sh
bash scripts/export-offline.sh artifacts/offline-bundle
```

The exporter includes model files, two local Docker images, application source, and the
Linux x64 Continue VSIX. It excludes generated client credentials, model-service keys,
source indexes, and request captures. Model and extension packages retain their own
redistribution requirements. Verify publisher checksums as well as bundle integrity.

Host OS packages, drivers, Docker, and the container toolkit are not included. Prepare
those separately for the target platform. Desktop x86-64 images are not ARM64/Jetson
images; an ARM64 export requires compatible images and a matching JetPack setup.
Re-export after application/image changes; source changes alone do not update an old image.

## Install on the target

In the bundle directory:

```bash
sha256sum -c SHA256SUMS
docker image load --input images.tar
mkdir codeassist
tar -xf source.tar -C codeassist
mkdir -p codeassist/data/ollama codeassist/data/context
tar -xf models.tar -C codeassist/data/ollama
cd codeassist
```

Generate private configuration using the prepared image, avoiding Python downloads:

```bash
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD:/workspace" -w /workspace codeassist-gateway:0.1.0 \
  codeassist-client developer user1 --server http://192.0.2.10:8080 --output clients
cp clients/server.env .env
chmod 600 .env
```

Replace `192.0.2.10` with the target LAN address. Set `BIND_ADDRESS`, `LOCAL_UID`, and
`LOCAL_GID` in the private `.env` as appropriate. Start without building or pulling:

```bash
docker compose -f compose.yaml -f compose.offline.yaml up -d --no-build --pull never
```

Ollama is attached only to the internal inference network. The gateway also uses a normal
bridge network so its LAN port can be published. This overlay does not impose a general
internet firewall on the host, gateway, or editor; enforce that through the network policy.

Distribute each user's private configuration and a matching VSIX. Disable Continue
anonymous telemetry and editor updates. Use local models/configuration; do not add external
model providers, crawlers, or remote tools to an offline profile.

## Acceptance

With internet unavailable and LAN intact, verify cold start, both models, remote chat,
inline completion, optional source indexing/search, and restart persistence. Check model
readiness failures and mixed-load latency. Refer to [validation scope](validation.md).

References: [Continue offline](https://docs.continue.dev/guides/running-continue-without-internet),
[Ollama local-only settings](https://docs.ollama.com/faq).
