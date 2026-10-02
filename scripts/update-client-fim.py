"""Update generated Continue FIM budgets without changing credentials or chat settings.

Runs with Ubuntu 22's Python 3.10 standard library; no package downloads are needed.
"""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path

from client_config import field, model_blocks


def patched_config(content, profile):
    selected = []
    for start, end, indentation in model_blocks(content):
        if field(content[start:end], indentation, "model") == profile["model"]:
            selected.append((start, end, indentation))
    if len(selected) != 1:
        raise ValueError(
            "Expected exactly one configured FIM model. "
            "Run check-client.py --inspect --config <path> to check this file without revealing keys"
        )
    start, end, indentation = selected[0]
    stanza = content[start:end]
    if not stanza.endswith("\n"):
        stanza += "\n"
    for section in ("defaultCompletionOptions", "autocompleteOptions"):
        prefix = re.escape(indentation)
        pattern = re.compile(
            rf"(?ms)(^{prefix}{section}:[ \t]*(?:#[^\n]*)?\n)"
            rf"(.*?)(?=^[ ]{{0,{len(indentation)}}}\S|\Z)"
        )
        match = pattern.search(stanza)
        if not match and re.search(rf"^{prefix}{section}:", stanza, re.MULTILINE):
            raise ValueError(f"{section} must use a block-style YAML mapping")
        body = match[2] if match else ""
        child_indents = re.findall(r"^([ ]+)\w+:", body, re.MULTILINE)
        child_indent = min(child_indents, key=len) if child_indents else indentation + "  "
        for key, value in profile[section].items():
            if type(value) not in (int, bool):
                raise ValueError("FIM profile values must be integers or booleans")
            line = f"{child_indent}{key}: {json.dumps(value)}"
            existing = re.compile(rf"^{re.escape(child_indent)}{key}:.*$", re.MULTILINE)
            body = existing.sub(line, body) if existing.search(body) else body + line + "\n"
        replacement = (match[1] if match else f"{indentation}{section}:\n") + body
        if match:
            stanza = stanza[: match.start()] + replacement + stanza[match.end() :]
        else:
            stanza += replacement
    return content[:start] + stanza + content[end:]


def update(path, profile):
    if path.is_symlink():
        raise ValueError("Config is a symlink; pass the actual target with --config")
    original = path.read_text(encoding="utf-8")
    result = patched_config(original, profile)
    if result == original:
        return None
    backup_fd, backup = tempfile.mkstemp(prefix=path.name + ".backup.", dir=path.parent)
    with os.fdopen(backup_fd, "w", encoding="utf-8") as handle:
        handle.write(original)
    staging_fd, staging = tempfile.mkstemp(prefix=path.name + ".new.", dir=path.parent)
    try:
        with os.fdopen(staging_fd, "w", encoding="utf-8") as handle:
            handle.write(result)
        os.chmod(staging, 0o600)
        os.replace(staging, path)
    finally:
        Path(staging).unlink(missing_ok=True)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path.home() / ".continue/config.yaml")
    parser.add_argument(
        "--profile", type=Path, default=Path(__file__).with_name("fim-profile.json")
    )
    args = parser.parse_args()
    try:
        profile = json.loads(args.profile.read_text())
        backup = update(args.config, profile)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"FIM update failed: {error}\n")
    print(
        f"FIM: contextLength={profile['defaultCompletionOptions']['contextLength']}, "
        f"maxPromptTokens={profile['autocompleteOptions']['maxPromptTokens']}, "
        f"maxTokens={profile['defaultCompletionOptions']['maxTokens']}."
    )
    print("Credentials, server address and chat configuration preserved.")
    if backup:
        print(f"Private config backup: {backup}")
    print("In VSCode: Developer: Reload Window; select Local FIM Completion.")
    print("Set continue.enableTabAutocomplete and editor.inlineSuggest.enabled to true.")


if __name__ == "__main__":
    main()
