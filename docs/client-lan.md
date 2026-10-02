# LAN client setup

The server exposes the gateway on port 8080; Ollama has no published host port.
Use your server's actual LAN address. `192.0.2.10` below is a documentation-only example.

## Generate per-user settings

```bash
.venv/bin/codeassist-client user1 user2 --server http://192.0.2.10:8080 --output clients/lan
```

Merge the generated user map from `clients/lan/server.env` into the private `.env`.
Preserve existing users. Set `BIND_ADDRESS` to the server's LAN address, then recreate
the gateway with both Compose files:

```bash
docker compose -f compose.yaml -f compose.offline.yaml up -d --no-build --pull never --wait gateway
```

Give each user only their own generated configuration. Client settings contain a private
access key and must not be committed or shared as a common installation package.

## Install on a Linux client

Install VS Code and an appropriate Continue VSIX. For the tested Linux x64 profile,
place these files together in a private transfer directory:

- The user's `config.yaml`.
- `scripts/check-client.py` and `scripts/client_config.py`.
- `scripts/install-ubuntu-client.sh`.
- `continue-2.0.0-linux-x64.vsix` obtained from its publisher.

Run the installer from that directory. It checks the LAN/API, installs the extension,
backs up the previous Continue YAML, and installs the private configuration.

Alternatively, install the extension and copy the generated configuration manually.
Disable **Allow Anonymous Telemetry** in Continue User Settings, select the local chat
and autocomplete models, then run **Developer: Reload Window**.

## Check connectivity and models

```bash
curl --noproxy '*' --connect-timeout 5 http://192.0.2.10:8080/health/live
python3 check-client.py --config ~/.continue/config.yaml
```

The Python check uses only the standard library and tests liveness, authentication,
model readiness, completion, and chat. Configuration inspection without printing the
access key is available through `--inspect`.

A VM using NAT can initiate connections to the LAN server; VM port forwarding is not
needed for this direction. If access fails, compare host and VM connectivity, routing,
VPN settings, and Wi-Fi client isolation. A successful server-local check does not prove
that a remote client can reach it.

For Windows, `Test-NetConnection <server-address> -Port 8080` helps distinguish network
failure from model/configuration errors. HTTP 401 indicates authentication failure;
503 from readiness indicates missing/unavailable models.

## Editor acceptance

Check streaming chat and inline completion separately. A CLI completion result does
not prove that VS Code displays suggestions. Use the [FIM guide](fim.md) for editor
settings and the [monitor guide](monitor.md) to inspect server-side request handling.

Source indexing is optional. To use the default database, build the selected snapshot,
set `CONTEXT_INDEX_PATH=/context/context.sqlite`, and recreate the gateway. This does
not automatically add central source retrieval to FIM.
