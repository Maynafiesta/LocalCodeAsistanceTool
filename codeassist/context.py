"""CPU-only lexical retrieval. An index is a shared, explicitly selected project snapshot."""

import argparse
import fnmatch
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path

EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".inl",
    ".tpp",
    ".md",
    ".rst",
    ".txt",
    ".cmake",
    ".pro",
    ".pri",
}
EXCLUDED_DIRS = {
    "build",
    "dist",
    "vendor",
    "third_party",
    "node_modules",
    "data",
    "artifacts",
    "clients",
    "generated",
    "external",
}
EXCLUDED_FILES = (
    "moc_*",
    "ui_*",
    "qrc_*",
    "*secret*",
    "*credential*",
    "*token*",
    "*password*",
    "CMakeCache.txt",
)
STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "what",
    "how",
    "can",
    "explain",
    "please",
    "project",
    "code",
    "bir",
    "ve",
    "ile",
    "bu",
    "için",
    "nedir",
    "nasıl",
    "neden",
    "projede",
    "kod",
    "açıkla",
}


def patterns(root: Path):
    path = root / ".codeassistignore"
    if not path.is_file() or path.is_symlink():
        return []
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def index_project(root: Path, destination: Path):
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Project root must be a directory")
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    ignore = patterns(root)
    fd, temporary = tempfile.mkstemp(prefix="context-", suffix=".sqlite", dir=destination.parent)
    os.close(fd)
    files = chunks = skipped = 0
    try:
        with sqlite3.connect(temporary) as db:
            db.execute(
                "CREATE VIRTUAL TABLE chunks USING fts5(path, start UNINDEXED, "
                "end UNINDEXED, content, tokenize='unicode61 tokenchars _')"
            )
            db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT)")
            # Prune directories before traversal. Never follow symlinks or hidden trees.
            for directory, directories, filenames in os.walk(root, followlinks=False):
                parent = Path(directory)
                directories[:] = sorted(
                    d
                    for d in directories
                    if not d.startswith(".")
                    and d not in EXCLUDED_DIRS
                    and not d.startswith("build-")
                    and not d.startswith("cmake-build-")
                    and not (parent / d).is_symlink()
                    and not any(
                        fnmatch.fnmatch((parent / d).relative_to(root).as_posix() + "/", p)
                        for p in ignore
                    )
                )
                for name in sorted(filenames):
                    path = parent / name
                    relative = path.relative_to(root).as_posix()
                    if (
                        path.is_symlink()
                        or name.startswith(".")
                        or path.suffix.lower() not in EXTENSIONS
                        or any(fnmatch.fnmatch(name.lower(), p.lower()) for p in EXCLUDED_FILES)
                        or any(fnmatch.fnmatch(relative, p) for p in ignore)
                    ):
                        continue
                    try:
                        if path.stat().st_size > 512_000:
                            skipped += 1
                            continue
                        content = path.read_text(encoding="utf-8")
                        if "\0" in content:
                            skipped += 1
                            continue
                    except (UnicodeError, OSError):
                        skipped += 1
                        continue
                    lines = content.splitlines()
                    files += 1
                    for offset in range(0, len(lines), 60):
                        piece = "\n".join(lines[offset : offset + 80])
                        if not piece.strip():
                            continue
                        db.execute(
                            "INSERT INTO chunks VALUES (?, ?, ?, ?)",
                            (relative, offset + 1, min(offset + 80, len(lines)), piece),
                        )
                        chunks += 1
            db.execute("INSERT INTO metadata VALUES ('root', ?)", (str(root),))
            db.execute("INSERT INTO metadata VALUES ('files', ?)", (str(files),))
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"files": files, "chunks": chunks, "skipped": skipped}


def search(index: str | Path, query: str, limit: int = 4, char_budget: int = 6000):
    path = Path(index).resolve()
    if not path.is_file():
        return []
    # Quote every token: user input cannot introduce FTS operators or SQL.
    terms = list(
        dict.fromkeys(
            t.lower()
            for t in re.findall(r"\w+", query[-4000:])
            if len(t) > 2 and t.lower() not in STOP_WORDS
        )
    )[-32:]
    if not terms:
        return []
    expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute(
            "SELECT path, start, end, content FROM chunks WHERE chunks MATCH ? "
            "ORDER BY bm25(chunks, 2.0, 0.0, 0.0, 1.0) LIMIT ?",
            (expression, limit * 3),
        ).fetchall()
    results = []
    for name, start, end, content in rows:
        if any(r["path"] == name and start <= r["end"] and end >= r["start"] for r in results):
            continue
        # Preserve accurate line ranges when truncating a long chunk.
        kept = []
        for line in content.splitlines():
            if sum(len(x) + 1 for x in kept) + len(line) + 1 > char_budget:
                break
            kept.append(line)
        if not kept:
            continue
        piece = "\n".join(kept)
        results.append(
            {"path": name, "start": start, "end": start + len(kept) - 1, "content": piece}
        )
        char_budget -= len(piece) + 1
        if len(results) == limit or char_budget < 100:
            break
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    index = sub.add_parser("build")
    index.add_argument("root", type=Path)
    index.add_argument("--output", type=Path, default=Path("data/context.sqlite"))
    lookup = sub.add_parser("search")
    lookup.add_argument("query")
    lookup.add_argument("--index", type=Path, default=Path("data/context.sqlite"))
    args = parser.parse_args()
    if args.command == "build":
        print(json.dumps(index_project(args.root, args.output), ensure_ascii=False))
    else:
        print(json.dumps(search(args.index, args.query), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
