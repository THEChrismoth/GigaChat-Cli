import asyncio
import os
import time
from pathlib import Path

import pytest

from conftest import python_command
from gigachat_cli.utils.command import CommandUtils


@pytest.fixture
def commands(tmp_path):
    utils = CommandUtils(command_timeout=5)
    utils.current_directory = tmp_path
    return utils


async def test_command_output(commands):
    success, output, return_code = await commands.execute_system_command(python_command("print(12345)"))

    assert success
    assert return_code == 0
    assert "12345" in output


async def test_command_runs_in_current_directory(commands, tmp_path):
    success, output, _ = await commands.execute_system_command(python_command("import os; print(os.getcwd())"))

    assert success
    assert Path(output.strip()).resolve() == tmp_path.resolve()


async def test_command_exit_code_and_stderr(commands):
    code = "import sys; sys.stderr.write('bad'); sys.exit(3)"
    success, output, return_code = await commands.execute_system_command(python_command(code))

    assert not success
    assert return_code == 3
    assert "bad" in output


async def test_unknown_command(commands):
    success, output, return_code = await commands.execute_system_command("definitely-not-a-command-42")

    assert not success
    assert return_code != 0
    if os.name != "nt":
        assert "не найдена" in output


async def test_empty_command(commands):
    assert await commands.execute_system_command("   ") == (False, "Пустая команда", 1)


@pytest.mark.skipif(os.name == "nt", reason="На Windows команда выполняется через cmd.exe без shlex")
async def test_unbalanced_quotes(commands):
    success, output, _ = await commands.execute_system_command('echo "unclosed')

    assert not success
    assert "Не удалось разобрать команду" in output


async def test_stdin_is_closed(commands):
    # Интерактивная команда не должна ждать ввода с клавиатуры
    started = time.monotonic()
    success, output, _ = await commands.execute_system_command(python_command("input()"))

    assert not success
    assert "EOFError" in output
    assert time.monotonic() - started < 5


async def test_subprocess_stdin_is_devnull(commands, monkeypatch):
    # Под pytest stdin и так пустой, поэтому проверяем параметры запуска процесса
    calls = []

    def spy(original):
        async def wrapper(*args, **kwargs):
            calls.append(kwargs)
            return await original(*args, **kwargs)
        return wrapper

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy(asyncio.create_subprocess_exec))
    monkeypatch.setattr(asyncio, "create_subprocess_shell", spy(asyncio.create_subprocess_shell))

    await commands.execute_system_command(python_command("pass"))

    assert calls[0]["stdin"] == asyncio.subprocess.DEVNULL


async def test_command_timeout(tmp_path):
    commands = CommandUtils(command_timeout=1)
    commands.current_directory = tmp_path

    started = time.monotonic()
    success, output, _ = await commands.execute_system_command(python_command("import time; time.sleep(30)"))

    assert not success
    assert "Превышено время выполнения" in output
    assert time.monotonic() - started < 10


async def test_command_cancellation_kills_process(commands, tmp_path):
    marker = tmp_path / "finished.txt"
    code = f"import time; time.sleep(3); open({str(marker)!r}, 'w').close()"

    task = asyncio.create_task(commands.execute_system_command(python_command(code)))
    await asyncio.sleep(1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(3)
    assert not marker.exists()


# --- cd ---

async def test_cd_relative(commands, tmp_path):
    (tmp_path / "sub").mkdir()

    success, _, _ = await commands.execute_system_command("cd sub")

    assert success
    assert commands.get_current_directory() == (tmp_path / "sub").resolve()


async def test_cd_parent(commands, tmp_path):
    (tmp_path / "sub").mkdir()
    commands.current_directory = tmp_path / "sub"

    await commands.execute_system_command("cd ..")

    assert commands.get_current_directory() == tmp_path.resolve()


async def test_cd_absolute_path_with_spaces(commands, tmp_path):
    target = tmp_path / "dir with spaces"
    target.mkdir()

    success, _, _ = await commands.execute_system_command(f'cd "{target}"')

    assert success
    assert commands.get_current_directory() == target.resolve()


@pytest.mark.parametrize("command", ["cd ~", "cd"])
async def test_cd_home(commands, command):
    success, _, _ = await commands.execute_system_command(command)

    assert success
    assert commands.get_current_directory() == Path.home().resolve()


async def test_cd_missing_directory(commands, tmp_path):
    success, output, _ = await commands.execute_system_command("cd missing")

    assert not success
    assert "Директория не существует" in output
    assert commands.get_current_directory() == tmp_path


async def test_cd_to_file(commands, tmp_path):
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")

    success, output, _ = await commands.execute_system_command("cd file.txt")

    assert not success
    assert "Не является директорией" in output


# --- Вспомогательные методы ---

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("!ls -la", (True, "ls -la")),
        ("  ! git status ", (True, "git status")),
        ("ls", (False, None)),
        ("/help", (False, None)),
    ],
)
def test_is_terminal_command(text, expected):
    assert CommandUtils.is_terminal_command(text) == expected


def test_format_command_output():
    assert CommandUtils.format_command_output("out", True, 0) == "```\nout\n```\n**Выполнено**"
    assert CommandUtils.format_command_output("err", False, 2).endswith("**Завершено с кодом 2**")


def test_is_file_command(commands):
    assert commands.is_file_command("ls -la")
    assert not commands.is_file_command("git status")
    assert not commands.is_file_command("")
