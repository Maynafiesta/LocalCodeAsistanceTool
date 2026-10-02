import argparse
import json
import os
import re
import secrets
from pathlib import Path


def private_write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents replacing existing credentials or following a symlink.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(content)


def main():
    parser = argparse.ArgumentParser(
        description="Generate private Continue configs and server keys"
    )
    parser.add_argument("users", nargs="+", help="User IDs: letters, numbers, underscore, hyphen")
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    parser.add_argument("--output", type=Path, default=Path("clients"))
    args = parser.parse_args()
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", user) for user in args.users):
        parser.error("Invalid user ID")
    if len(set(args.users)) != len(args.users):
        parser.error("Duplicate user IDs")
    if not args.server.startswith(("http://", "https://")):
        parser.error("Server must be an HTTP(S) URL")
    targets = [args.output / "server.env"] + [args.output / u / "config.yaml" for u in args.users]
    if any(p.exists() or p.is_symlink() for p in targets):
        parser.error("Output exists; use a new --output directory to preserve existing credentials")
    template = (Path(__file__).parent / "continue.yaml.template").read_text()
    tokens = {u: secrets.token_urlsafe(32) for u in args.users}
    private_write(args.output / "server.env", "CODEASSIST_TOKENS='" + json.dumps(tokens) + "'\n")
    for user, token in tokens.items():
        rendered = template.replace("SERVER_URL_JSON", json.dumps(args.server.rstrip("/")))
        rendered = rendered.replace("AUTH_HEADER_JSON", json.dumps("Bearer " + token))
        private_write(args.output / user / "config.yaml", rendered)
    print(f"Created {len(tokens)} client configs and {args.output / 'server.env'} (private files).")


if __name__ == "__main__":
    main()
