from pathlib import Path

from codeassist.context import index_project, search


def test_index_ignores_secrets_generated_hidden_symlinks_and_custom_patterns(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    for relative in (
        "build/x.cpp",
        ".git/x.cpp",
        "vendor/x.cpp",
        "private/x.cpp",
        "moc_device.cpp",
        "credentials.txt",
        "device.cpp",
    ):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("void SerialDevice::readFrame() {}\n")
    outside = tmp_path / "outside.cpp"
    outside.write_text("EXTERNAL_DATA")
    (project / "linked.cpp").symlink_to(outside)
    (project / "linked_dir").symlink_to(tmp_path, target_is_directory=True)
    (project / ".codeassistignore").write_text("private/*\n")
    index = tmp_path / "context.sqlite"
    assert index_project(project, index)["files"] == 1
    hits = search(index, "SerialDevice readFrame")
    assert [h["path"] for h in hits] == ["device.cpp"]
    assert search(index, "EXTERNAL_DATA") == []
    assert search(index, '" OR *) NEAR(') == []


def test_atomic_rebuild_removes_deleted_files_and_bounds_results(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    file = project / "ethernet.cpp"
    file.write_text("\n".join(f"int ethernet_{i} = 0;" for i in range(180)))
    index = tmp_path / "index.sqlite"
    index_project(project, index)
    hits = search(index, "ethernet_0", char_budget=100)
    assert sum(len(h["content"]) for h in hits) <= 100
    assert hits[0]["end"] == hits[0]["start"] + len(hits[0]["content"].splitlines()) - 1
    file.unlink()
    index_project(project, index)
    assert search(index, "ethernet_0") == []


def test_missing_index_and_empty_query(tmp_path):
    assert search(Path(tmp_path) / "missing.sqlite", "Qt") == []
