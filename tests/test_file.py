import os

import pytest

from gigachat_cli.utils.command import CommandUtils
from gigachat_cli.utils.file import FileUtils, split_path_argument
from gigachat_cli.widgets.file_list import FileList


class FakeInput:
    """Заглушка поля ввода"""

    def __init__(self):
        self.value = ""
        self.cursor_position = 0

    def focus(self):
        pass


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "module.py").write_text("", encoding="utf-8")
    (tmp_path / "setup.py").write_text("", encoding="utf-8")
    (tmp_path / "Scripts").mkdir()
    return tmp_path


@pytest.fixture
def file_utils(tree):
    commands = CommandUtils()
    commands.current_directory = tree
    return FileUtils(commands)


def complete(file_utils, text):
    """Автодополнение первым вариантом, как при нажатии Enter в списке файлов"""
    files, command, current_path = file_utils.get_files_for_completion(text)
    file_list = FileList()
    file_list.update_files(files, command, current_path)
    field = FakeInput()
    file_list.apply_selection(field)
    return files, field.value


windows_only = pytest.mark.skipif(os.name != "nt", reason="Обратный слеш разделяет путь только на Windows")


@pytest.mark.parametrize(
    ("argument", "expected"),
    [
        ("", ("", "")),
        ("mai", ("", "mai")),
        ("src/ma", ("src/", "ma")),
        ("/usr/lo", ("/usr/", "lo")),
    ],
)
def test_split_path_argument(argument, expected):
    assert split_path_argument(argument) == expected


@pytest.mark.parametrize(
    ("argument", "expected"),
    [
        ("src\\ma", ("src\\", "ma")),
        ("C:\\Users\\", ("C:\\Users\\", "")),
        ("a/b\\c", ("a/b\\", "c")),
    ],
)
def test_split_path_argument_windows(argument, expected):
    assert split_path_argument(argument, separators=("/", "\\")) == expected


@pytest.mark.parametrize(
    ("argument", "expected"),
    [
        ("src\\ma", ("", "src\\ma")),
        ("a/b\\c", ("a/", "b\\c")),
    ],
)
def test_split_path_argument_posix(argument, expected):
    # В POSIX обратный слеш - часть имени файла
    assert split_path_argument(argument, separators=("/",)) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("!ls ", True),
        ("!ls sr", True),
        ("!ls", False),
        ("!git status", False),
        ("ls src", False),
        ("/model", False),
    ],
)
def test_should_show_files(file_utils, text, expected):
    assert file_utils.should_show_files(text) is expected


def test_directories_listed_first(file_utils):
    files, _, _ = file_utils.get_files_for_completion("!ls ")
    assert files == ["Scripts", "src", "setup.py"]


@pytest.mark.parametrize(
    ("text", "files", "result"),
    [
        ("!ls ", ["Scripts", "src", "setup.py"], "!ls Scripts"),
        ("!ls se", ["setup.py"], "!ls setup.py"),
        ("!cat src/m", ["main.py", "module.py"], "!cat src/main.py"),
        pytest.param("!cat src\\mo", ["module.py"], "!cat src\\module.py", marks=windows_only),
        ("!cp setup.py ", ["Scripts", "src", "setup.py"], "!cp setup.py Scripts"),
        ("!cp  setup.py  sr", ["src"], "!cp  setup.py  src"),
    ],
)
def test_completion(file_utils, text, files, result):
    assert complete(file_utils, text) == (files, result)


@pytest.mark.skipif(os.name == "nt", reason="На Windows обратный слеш недопустим в имени файла")
def test_completion_backslash_in_file_name_posix(file_utils, tree):
    (tree / "odd\\name.txt").write_text("", encoding="utf-8")

    assert complete(file_utils, "!cat odd\\n") == (["odd\\name.txt"], "!cat odd\\name.txt")


def test_completion_absolute_path(file_utils, tree):
    files, value = complete(file_utils, f"!cat {tree / 'src'}/ma")

    assert files == ["main.py"]
    assert value == f"!cat {tree / 'src'}/main.py"


def test_completion_home_path(file_utils, tree, monkeypatch):
    monkeypatch.setenv("HOME", str(tree))
    monkeypatch.setenv("USERPROFILE", str(tree))

    files, value = complete(file_utils, "!ls ~/sr")

    assert files == ["src"]
    assert value == "!ls ~/src"


def test_completion_missing_directory(file_utils):
    assert file_utils.get_files_for_completion("!ls missing/")[0] == []


def test_completion_without_argument(file_utils):
    assert file_utils.get_files_for_completion("!ls")[0] == []


def test_file_list_navigation(tree):
    file_list = FileList()
    file_list.visible_count = 2
    file_list.update_files(["a", "b", "c"], "!ls ", str(tree))

    file_list.select_next()
    file_list.select_next()
    assert file_list.get_selected_file() == "c"
    assert file_list.visible_start == 1

    file_list.select_next()
    assert file_list.get_selected_file() == "a"
    assert file_list.visible_start == 0

    file_list.select_previous()
    assert file_list.get_selected_file() == "c"
    assert file_list.visible_start == 1
