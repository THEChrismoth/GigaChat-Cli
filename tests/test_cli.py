import io
import json

import pytest

from gigachat_cli import __main__ as entry
from gigachat_cli import cli
from gigachat_cli.utils.core import StreamChunk, chat_manager


class FakeStdin(io.StringIO):
    """stdin с данными из конвейера (не терминал)"""

    def isatty(self):
        return False


class TerminalStdin(io.StringIO):
    """stdin-терминал без данных"""

    def isatty(self):
        return True


@pytest.fixture
def answers(monkeypatch):
    """Заглушка get_answer_stream: отдает заданные чанки и запоминает запросы"""
    calls = []

    def install(chunks):
        async def fake(prompt, clear_history=False, project_path=None):
            calls.append({"prompt": prompt, "project_path": project_path, "model": chat_manager.get_current_model()})
            for chunk in chunks:
                yield chunk
        monkeypatch.setattr(cli, "get_answer_stream", fake)
        return calls

    return install


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr("sys.stdin", TerminalStdin())
    chat_manager.model_override = None
    yield
    chat_manager.model_override = None


OK_CHUNKS = [StreamChunk("Привет"), StreamChunk(", мир"), StreamChunk("", is_final=True)]
ERROR_CHUNKS = [StreamChunk("", is_final=True, error="GIGACHAT_API_KEY не установен")]


def run(argv):
    return entry.main(argv)


# --- Формат text ---

def test_text_output(answers, capsys, tmp_path, monkeypatch):
    calls = answers(OK_CHUNKS)
    monkeypatch.chdir(tmp_path)

    assert run(["-p", "Привет?"]) == cli.EXIT_OK

    out = capsys.readouterr()
    assert out.out == "Привет, мир\n"
    assert out.err == ""
    assert calls == [{"prompt": "Привет?", "project_path": str(tmp_path), "model": "GigaChat-2"}]


def test_text_error_goes_to_stderr(answers, capsys):
    answers(ERROR_CHUNKS)

    assert run(["-p", "вопрос"]) == cli.EXIT_ERROR

    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == "Ошибка: GIGACHAT_API_KEY не установен\n"


# --- Формат json ---

def test_json_output(answers, capsys):
    answers(OK_CHUNKS)

    assert run(["-p", "вопрос", "--output-format", "json"]) == cli.EXIT_OK

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["type"] == "result"
    assert result["is_error"] is False
    assert result["result"] == "Привет, мир"
    assert result["error"] is None
    assert result["model"] == "GigaChat-2"
    assert result["files"] == []
    assert isinstance(result["duration_ms"], int)


def test_json_error(answers, capsys):
    answers(ERROR_CHUNKS)

    assert run(["-p", "вопрос", "--output-format", "json"]) == cli.EXIT_ERROR

    out = capsys.readouterr()
    result = json.loads(out.out)
    assert result["is_error"] is True
    assert result["error"] == "GIGACHAT_API_KEY не установен"
    assert out.err == ""


def test_json_is_utf8_not_escaped(answers, capsys):
    answers(OK_CHUNKS)

    run(["-p", "вопрос", "--output-format", "json"])

    assert "Привет" in capsys.readouterr().out


# --- Формат stream-json ---

def test_stream_json_output(answers, capsys):
    answers(OK_CHUNKS)

    assert run(["-p", "вопрос", "--output-format", "stream-json"]) == cli.EXIT_OK

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["type"] for event in events] == ["start", "chunk", "chunk", "result"]
    assert events[0]["model"] == "GigaChat-2"
    assert [event["content"] for event in events[1:3]] == ["Привет", ", мир"]
    assert events[-1]["result"] == "Привет, мир"


def test_stream_json_partial_answer_then_error(answers, capsys):
    answers([StreamChunk("Начало"), StreamChunk("", is_final=True, error="обрыв")])

    assert run(["-p", "вопрос", "--output-format", "stream-json"]) == cli.EXIT_ERROR

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[-1]["is_error"] is True
    assert events[-1]["result"] == "Начало"
    assert events[-1]["error"] == "обрыв"


# --- stdin ---

def test_stdin_appended_to_prompt(answers, capsys, monkeypatch):
    calls = answers(OK_CHUNKS)
    monkeypatch.setattr("sys.stdin", FakeStdin("diff --git a/x b/x\n+line\n"))

    assert run(["-p", "Напиши commit message"]) == cli.EXIT_OK

    assert calls[0]["prompt"] == "Напиши commit message\n\ndiff --git a/x b/x\n+line"


def test_stdin_only(answers, capsys, monkeypatch):
    calls = answers(OK_CHUNKS)
    monkeypatch.setattr("sys.stdin", FakeStdin("вопрос из stdin\n"))

    assert run(["-p"]) == cli.EXIT_OK

    assert calls[0]["prompt"] == "вопрос из stdin"


def test_terminal_stdin_is_not_read(answers, capsys, monkeypatch):
    calls = answers(OK_CHUNKS)
    monkeypatch.setattr("sys.stdin", TerminalStdin("не читать"))

    run(["-p", "вопрос"])

    assert calls[0]["prompt"] == "вопрос"


@pytest.mark.parametrize("argv", [["-p"], ["-p", "   "]])
def test_empty_prompt_is_usage_error(answers, capsys, argv):
    calls = answers(OK_CHUNKS)

    with pytest.raises(SystemExit) as exit_info:
        run(argv)

    assert exit_info.value.code == cli.EXIT_USAGE
    assert "пустой запрос" in capsys.readouterr().err
    assert calls == []


# --- Прочие аргументы ---

def test_model_override_is_not_saved(answers, capsys):
    calls = answers(OK_CHUNKS)

    run(["-p", "вопрос", "--model", "GigaChat-2-Max", "--output-format", "json"])

    assert calls[0]["model"] == "GigaChat-2-Max"
    assert json.loads(capsys.readouterr().out)["model"] == "GigaChat-2-Max"
    assert chat_manager.config.get_model() == "GigaChat-2"


def test_arguments_without_prompt_are_usage_error(capsys):
    with pytest.raises(SystemExit) as exit_info:
        run(["--output-format", "json"])

    assert exit_info.value.code == cli.EXIT_USAGE
    assert "-p/--print" in capsys.readouterr().err


def test_invalid_output_format(capsys):
    with pytest.raises(SystemExit) as exit_info:
        run(["-p", "вопрос", "--output-format", "xml"])

    assert exit_info.value.code == cli.EXIT_USAGE


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        run(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith("gigachat ")


def test_help_mentions_examples(capsys):
    with pytest.raises(SystemExit):
        run(["--help"])

    assert "git diff | gigachat -p" in capsys.readouterr().out


def test_no_arguments_starts_tui(monkeypatch):
    started = []
    monkeypatch.setattr("gigachat_cli.main.Main.run", lambda self: started.append(True))

    assert run([]) == 0
    assert started == [True]


def test_keyboard_interrupt(monkeypatch, capsys):
    def interrupt(coroutine):
        coroutine.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.asyncio, "run", interrupt)

    assert run(["-p", "вопрос"]) == cli.EXIT_INTERRUPTED
    assert "Прервано" in capsys.readouterr().err
