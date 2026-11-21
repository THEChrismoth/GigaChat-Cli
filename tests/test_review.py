from gigachat_cli.core.review import ReviewWorkspace


def test_review_ignores_artifacts_and_reads_requested_range(tmp_path):
    (tmp_path / "main.py").write_text("# padding\n" * 1600 + "return_value = 42\n", encoding="utf-8")
    for directory in ("build", ".git", "node_modules"):
        path = tmp_path / directory
        path.mkdir()
        (path / "generated.py").write_text("return_value = 0", encoding="utf-8")
    (tmp_path / ".env").write_text("return_value = secret", encoding="utf-8")
    (tmp_path / "secret.pem").write_text("return_value = key", encoding="utf-8")

    workspace = ReviewWorkspace(str(tmp_path))

    assert workspace.call("list_files", {})["files"] == ["main.py"]
    assert workspace.call("search_code", {"query": "return_value"})["matches"] == [
        {"path": "main.py", "line": 1601, "text": "return_value = 42"},
    ]
    assert workspace.call("read_file", {"path": "main.py", "start_line": 1601})["lines"] == [
        {"line": 1601, "text": "return_value = 42"},
    ]
    for path in ("../main.py", str(tmp_path / "main.py"), ".env", "build/generated.py", "secret.pem"):
        assert "error" in workspace.call("read_file", {"path": path})


def test_review_rechecks_path_before_reading(tmp_path):
    source = tmp_path / "main.py"
    source.write_text("print(1)", encoding="utf-8")
    workspace = ReviewWorkspace(str(tmp_path))
    source.unlink()
    source.mkdir()

    assert "error" in workspace.call("read_file", {"path": "main.py"})
