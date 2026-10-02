"""Read the block-style YAML used by Continue without third-party dependencies.

Preserve the original text when patching. Flow mappings, anchors and environment
references are intentionally not resolved; report unsupported values explicitly.
"""

import json
import re
from urllib.parse import urlsplit


def scalar(value):
    value = value.strip()
    if value.startswith('"'):
        result, end = json.JSONDecoder().raw_decode(value)
        if not isinstance(result, str) or value[end:].strip().split("#", 1)[0].strip():
            raise ValueError("Unsupported YAML scalar")
        return result
    if value.startswith("'"):
        match = re.fullmatch(r"'((?:[^']|'')*)'\s*(?:#.*)?", value)
        if not match:
            raise ValueError("Unsupported YAML scalar")
        return match[1].replace("''", "'")
    value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
    if not value or value[0] in "[{&*!|>" or "${{" in value:
        raise ValueError("Expected a literal YAML scalar")
    return value


def model_blocks(content):
    """Return (start, end, property indentation) for models list entries."""
    roots = list(re.finditer(r"^([ ]*)models:[ \t]*(?:#.*)?$", content, re.MULTILINE))
    if len(roots) != 1:
        return []
    root = roots[0]
    root_indent = len(root[1])
    lines = list(re.finditer(r"^[^\n]*(?:\n|$)", content[root.end():], re.MULTILINE))
    entries = []
    item_indent = None
    end = len(content)
    for line in lines:
        text = line.group().rstrip("\r\n")
        if not text.strip() or text.lstrip().startswith("#"):
            continue
        indent = len(text) - len(text.lstrip(" "))
        entry = re.match(r"^([ ]*)-([ ]+)[A-Za-z][A-Za-z0-9_]*:", text)
        offset = root.end() + line.start()
        if entry and indent >= root_indent and (item_indent is None or indent == item_indent):
            item_indent = indent
            entries.append((offset, " " * (indent + 1 + len(entry[2]))))
        elif indent <= root_indent:
            end = offset
            break
    return [
        (start, entries[index + 1][0] if index + 1 < len(entries) else end, indentation)
        for index, (start, indentation) in enumerate(entries)
    ]


def field(stanza, indentation, key):
    # A model's first key can be on the list-item line.
    first = re.match(r"^[ ]*-[ ]+" + re.escape(key) + r":[ \t]*(.*)$", stanza.splitlines()[0])
    matches = re.findall(
        r"^" + re.escape(indentation + key) + r":[ \t]*(.*)$", stanza, re.MULTILINE
    )
    if first:
        matches.insert(0, first[1])
    if len(matches) > 1:
        raise ValueError("Duplicate model field: " + key)
    return scalar(matches[0]) if matches else None


def credentials(content):
    for start, end, indentation in model_blocks(content):
        stanza = content[start:end]
        base = field(stanza, indentation, "apiBase")
        headers = re.findall(r"^[ ]+Authorization:[ \t]*(.*)$", stanza, re.MULTILINE)
        if base and headers:
            parsed = urlsplit(base)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("apiBase must be an HTTP(S) address")
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("apiBase must not contain credentials, query or fragment")
            authorization = scalar(headers[0])
            if not authorization.startswith("Bearer ") or "${{" in authorization:
                raise ValueError("Authorization must contain a literal Bearer token")
            return base.rstrip("/"), authorization
    raise ValueError(
        "No model with apiBase and Authorization found in this file. "
        "Pass the config opened by Continue, or the original codeassist-laptop/config.yaml."
    )


def inspect(content):
    result = []
    for start, end, indentation in model_blocks(content):
        stanza = content[start:end]
        result.append({
            "name": field(stanza, indentation, "name"),
            "model": field(stanza, indentation, "model"),
            "has_apiBase": field(stanza, indentation, "apiBase") is not None,
            "has_Authorization": bool(re.search(r"^[ ]+Authorization:", stanza, re.MULTILINE)),
        })
    return result
