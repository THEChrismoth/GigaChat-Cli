import shlex

import pytest

from gigachat_cli.utils.command import quote_command_argument, split_command_arguments
from gigachat_cli.utils.file import complete_path_argument


def values(text, posix):
    return [argument.value for argument in split_command_arguments(text, posix)]


# --- Разбор аргументов ---

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", []),
        ("   ", []),
        ("!ls", ["!ls"]),
        ("!ls ", ["!ls", ""]),
        ("!ls  -la   src", ["!ls", "-la", "src"]),
        ("!cat My\\ Docs/a.txt", ["!cat", "My Docs/a.txt"]),
        ("!cat 'My Docs'/a.txt", ["!cat", "My Docs/a.txt"]),
        ('!cat "My Docs"/a.txt', ["!cat", "My Docs/a.txt"]),
        ('!cat "a \\"b\\" \\\\c \\d"', ["!cat", 'a "b" \\c \\d']),
        ("!cat 'a\\b'", ["!cat", "a\\b"]),
        ("!cat My\\ ", ["!cat", "My "]),
        ("!cat odd\\\\n", ["!cat", "odd\\n"]),
        ("!cat odd\\n", ["!cat", "oddn"]),
        # Незавершенный ввод не приводит к ошибке
        ("!cat 'My Do", ["!cat", "My Do"]),
        ('!cat "My Do', ["!cat", "My Do"]),
        ("!cat My\\", ["!cat", "My"]),
        ("!cat 'My Docs ", ["!cat", "My Docs "]),
    ],
)
def test_split_posix(text, expected):
    assert values(text, posix=True) == expected


@pytest.mark.parametrize(
    "text",
    ["!ls -la src", "!cat My\\ Docs/a.txt", "!cat 'My Docs'/a.txt", '!cat "a \\"b\\" \\\\c"', "!cat ''"],
)
def test_split_posix_matches_shlex(text):
    # На завершенных командах разбор совпадает с shlex, которым команды выполняются
    assert values(text, posix=True) == shlex.split(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("!dir ", ["!dir", ""]),
        ('!type "C:\\Program Files\\a.txt"', ["!type", "C:\\Program Files\\a.txt"]),
        ('!type "My Docs"\\a.txt', ["!type", "My Docs\\a.txt"]),
        ("!type src\\main.py", ["!type", "src\\main.py"]),
        ("!type 'a b'", ["!type", "'a", "b'"]),
        ('!dir "C:\\Program Fi', ["!dir", "C:\\Program Fi"]),
    ],
)
def test_split_windows(text, expected):
    assert values(text, posix=False) == expected


def test_argument_start_and_quote():
    arguments = split_command_arguments("!cat  'My Do", posix=True)

    assert arguments[1].start == 6
    assert arguments[1].quote == "'"
    assert split_command_arguments("!cat src", posix=True)[1].quote is None


# --- Экранирование ---

@pytest.mark.parametrize(
    ("value", "quote", "expected"),
    [
        ("main.py", None, "main.py"),
        ("My Docs", None, "My\\ Docs"),
        ("a&b(1)$x", None, "a\\&b\\(1\\)\\$x"),
        ("~/My Docs", None, "~/My\\ Docs"),
        ("My Docs", "'", "'My Docs'"),
        ("it's", "'", "'it'\\''s'"),
        ('My "Docs" $x', '"', '"My \\"Docs\\" \\$x"'),
    ],
)
def test_quote_posix(value, quote, expected):
    assert quote_command_argument(value, quote, posix=True) == expected


@pytest.mark.parametrize(
    ("value", "quote", "expected"),
    [
        ("main.py", None, "main.py"),
        ("src\\main.py", None, "src\\main.py"),
        ("My Docs", None, '"My Docs"'),
        ("a&b", None, '"a&b"'),
        ("main.py", '"', '"main.py"'),
        ("~/src", None, "~/src"),
    ],
)
def test_quote_windows(value, quote, expected):
    assert quote_command_argument(value, quote, posix=False) == expected


@pytest.mark.parametrize("posix", [True, False])
@pytest.mark.parametrize("quote", [None, "'", '"'])
@pytest.mark.parametrize("value", ["plain", "My Docs", "a&b (1)", "it's", "~/dir name/file.txt"])
def test_quote_round_trip(posix, quote, value):
    if not posix and quote == "'":
        pytest.skip("В cmd.exe одинарные кавычки не используются")

    quoted = quote_command_argument(value, quote, posix)

    assert values(f"!cat {quoted}", posix) == ["!cat", value]


# --- Подстановка выбранного файла ---

@pytest.mark.parametrize(
    ("text", "name", "expected"),
    [
        ("!ls ", "My Docs", "!ls My\\ Docs"),
        ("!ls My", "My Docs", "!ls My\\ Docs"),
        ("!ls My\\ Do", "My Docs", "!ls My\\ Docs"),
        ("!ls 'My Do", "My Docs", "!ls 'My Docs'"),
        ('!ls "My Do', "My Docs", '!ls "My Docs"'),
        ("!cat My\\ Docs/", "a b.txt", "!cat My\\ Docs/a\\ b.txt"),
        ("!cat 'My Docs'/a", "a b.txt", "!cat 'My Docs/a b.txt'"),
        ("!cp a.txt  sr", "src", "!cp a.txt  src"),
        # Обратный слеш в имени файла: вводится удвоенным и так же подставляется
        ("!cat odd\\\\n", "odd\\name.txt", "!cat odd\\\\name.txt"),
    ],
)
def test_complete_posix(text, name, expected):
    assert complete_path_argument(text, name, posix=True) == expected


@pytest.mark.parametrize(
    ("text", "name", "expected"),
    [
        ("!dir ", "My Docs", '!dir "My Docs"'),
        ("!dir My", "My Docs", '!dir "My Docs"'),
        ('!dir "My Do', "My Docs", '!dir "My Docs"'),
        ('!type "My Docs"\\a', "a b.txt", '!type "My Docs\\a b.txt"'),
        ("!type src\\mo", "module.py", "!type src\\module.py"),
        ('!dir "C:\\Program Fi', "Program Files", '!dir "C:\\Program Files"'),
    ],
)
def test_complete_windows(text, name, expected):
    assert complete_path_argument(text, name, posix=False) == expected


@pytest.mark.parametrize("posix", [True, False])
def test_complete_without_argument(posix):
    assert complete_path_argument("!ls", "src", posix) == "!ls src"
