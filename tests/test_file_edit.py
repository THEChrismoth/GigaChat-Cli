import codecs
import stat

import pytest

from gigachat_cli.core.file_edit import FileEditError, MAX_EDIT_BYTES, prepare_file_edit, read_snapshot


@pytest.mark.parametrize("original", [None, b"print('original')\n"])
async def test_python_proposal_rejects_code_that_cannot_compile(tmp_path, original):
    target = tmp_path / "example.py"
    if original is not None:
        target.write_bytes(original)
    with pytest.raises(FileEditError, match="Ошибка синтаксиса Python в строке 1"):
        await prepare_file_edit(read_snapshot(tmp_path, target.name), "return 1\n")


async def test_python_edit_preserves_the_style_of_an_existing_file(tmp_path):
    target = tmp_path / "example.py"
    target.write_bytes(b"print(\r\n    'original'\r\n)\r\n")
    replacement = "print(\n    'new'\n)\n"

    edit = await prepare_file_edit(read_snapshot(tmp_path, target.name), replacement)

    assert edit.after == replacement.replace("\n", "\r\n").encode()


def test_edit_preview_apply_and_undo_preserve_bytes(tmp_path):
    target = tmp_path / "пример.py"
    original = codecs.BOM_UTF8 + "а\r\nб\r\n".encode()
    target.write_bytes(original)
    target.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    original_mode = stat.S_IMODE(target.stat().st_mode)
    change = read_snapshot(tmp_path, target.name).propose("а\nв\n")

    assert target.read_bytes() == original
    assert "-б" in change.diff() and "+в" in change.diff()
    undo = change.apply()
    assert target.read_bytes() == codecs.BOM_UTF8 + "а\r\nв\r\n".encode()
    assert stat.S_IMODE(target.stat().st_mode) == original_mode
    undo.apply()
    assert target.read_bytes() == original


def test_create_empty_file_and_undo(tmp_path):
    target = tmp_path / "new.txt"
    change = read_snapshot(tmp_path, target.name).propose("")
    assert "/dev/null" in change.diff()
    assert not target.exists()
    undo = change.apply()
    assert target.read_bytes() == b""
    assert "/dev/null" in undo.diff()
    undo.apply()
    assert not target.exists()


@pytest.mark.parametrize("operation", ["edit", "create", "undo"])
def test_external_changes_are_preserved(tmp_path, operation):
    target = tmp_path / "notes.txt"
    if operation != "create":
        target.write_bytes(b"original")
    change = read_snapshot(tmp_path, target.name).propose("proposed")
    if operation == "undo":
        change = change.apply()
    target.write_bytes(b"external")
    with pytest.raises(FileEditError, match="Файл изменился"):
        change.apply()
    assert target.read_bytes() == b"external"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("path", ["../outside", ".git/config", ".env.local", "missing/file", "file:stream", "."])
def test_invalid_targets_are_rejected(tmp_path, path):
    with pytest.raises(FileEditError):
        read_snapshot(tmp_path, path)


def test_parent_link_added_after_preview_does_not_redirect_write(tmp_path):
    project = tmp_path / "project"
    parent = project / "sub"
    parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    change = read_snapshot(project, "sub/new.txt").propose("new")
    parent.rmdir()
    try:
        parent.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Символьные ссылки недоступны: {error}")
    with pytest.raises(FileEditError, match="Ссылки"):
        change.apply()
    assert not (outside / "new.txt").exists()


@pytest.mark.parametrize("data", [b"\0binary", b"\xff", b"x" * (MAX_EDIT_BYTES + 1)])
def test_binary_and_large_files_are_rejected(tmp_path, data):
    (tmp_path / "notes.txt").write_bytes(data)
    with pytest.raises(FileEditError):
        read_snapshot(tmp_path, "notes.txt")


def test_preview_shows_final_newline_change(tmp_path):
    (tmp_path / "notes.txt").write_bytes(b"hello")
    change = read_snapshot(tmp_path, "notes.txt").propose("hello\n")
    assert "-hello\n\\ Нет перевода строки" in change.diff()
    assert "+hello\n" in change.diff()
