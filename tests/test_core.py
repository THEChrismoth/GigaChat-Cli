import json
import subprocess
import os
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from gigachat_cli.core import model as core
from gigachat_cli.core.file_edit import FileEditError, read_snapshot


class FakeGiga:
    """Заглушка клиента GigaChat: возвращает заданные чанки и запоминает запросы"""

    def __init__(self, chunks=(), error=None):
        self.chunks = chunks
        self.error = error
        self.requests = []

    def stream(self, messages):
        self.requests.append(messages)
        for content in self.chunks:
            yield SimpleNamespace(content=content)
        if self.error:
            raise self.error


@pytest.fixture
def fake_giga(manager, monkeypatch):
    giga = FakeGiga(chunks=["При", "вет"])
    monkeypatch.setattr(manager, "_get_giga_chat_instance", lambda: giga)
    return giga


async def collect(stream):
    return [chunk async for chunk in stream]


# --- Поиск упоминаний файлов и кода в запросе ---

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("объясни main.py", ["main.py"]),
        ("сравни src/gigachat_cli/core/session.py и README.md", ["src/gigachat_cli/core/session.py", "README.md"]),
        ("посмотри pkg\\main.py", ["pkg\\main.py"]),
        ("main.py и еще раз main.py", ["main.py"]),
        ("CONFIG.YAML", ["CONFIG.YAML"]),
        ("открой github.com", []),
        ("что делает os.path.join", []),
        ("e.g. пример", []),
        ("скачай https://example.com/script.py", []),
        ("файл main.pyc", []),
    ],
)
def test_extract_file_references(manager, text, expected):
    assert manager._extract_file_references(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("объясни ```print(1)```", ["print(1)"]),
        ("```python\nx = 1\ny = 2\n```", ["x = 1\ny = 2"]),
        ("``` ``` пусто", []),
        ("без кода", []),
    ],
)
def test_extract_code_blocks(manager, text, expected):
    assert manager._extract_code_blocks(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("refactor tests with requests", "python"),
        ("explain this python code", "python"),
        ("explain this js", "javascript"),
        ("что делает app.js", "javascript"),
        ("typescript generics", "typescript"),
        ("файл index.ts", "typescript"),
        ("points and lists", "python"),
    ],
)
def test_detect_language(manager, text, expected):
    assert manager._detect_language(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Покажи структуру проекта", True),
        ("Проанализируй проект", True),
        ("analyze this project", True),
        ("как назвать проект?", False),
        ("сделай анализ данных", False),
        ("давай сделаем код-ревью проекта", True),
        ("что значит ревью?", False),
        ("ревью.md", False),
    ],
)
def test_is_project_analysis_request(text, expected):
    assert core.GigaChatManager._is_project_analysis_request(text) is expected


# --- Настройки SSL и клиент GigaChat ---

@pytest.mark.parametrize("verify", ["0", " False ", "NO", "off"])
def test_ssl_verify_disabled(monkeypatch, verify):
    monkeypatch.setenv("GIGACHAT_SSL_VERIFY", verify)
    assert core.GigaChatManager._get_ssl_settings() == {"verify_ssl_certs": False, "ca_bundle_file": ""}


@pytest.mark.parametrize("verify", ["1", "true"])
def test_ssl_verify_enabled(monkeypatch, verify):
    monkeypatch.setenv("GIGACHAT_SSL_VERIFY", verify)
    assert core.GigaChatManager._get_ssl_settings() == {"verify_ssl_certs": True}


def test_ssl_disabled_overrides_ca_bundle(monkeypatch, tmp_path):
    # Путь к сертификату (даже несуществующий) не должен включать проверку обратно
    monkeypatch.setenv("GIGACHAT_SSL_VERIFY", "0")
    monkeypatch.setenv("GIGACHAT_CA_BUNDLE_FILE", str(tmp_path / "missing.cer"))
    assert core.GigaChatManager._get_ssl_settings() == {"verify_ssl_certs": False, "ca_bundle_file": ""}


def test_ssl_disabled_ignores_ca_bundle_in_sdk(monkeypatch, tmp_path):
    # Проверка на реальном SDK: он сам читает GIGACHAT_CA_BUNDLE_FILE из окружения
    from gigachat.client import _get_kwargs
    from gigachat.settings import Settings

    monkeypatch.setenv("GIGACHAT_SSL_VERIFY", "0")
    monkeypatch.setenv("GIGACHAT_CA_BUNDLE_FILE", str(tmp_path / "missing.cer"))

    settings = Settings(**core.GigaChatManager._get_ssl_settings())

    assert _get_kwargs(settings)["verify"] is False


def test_sdk_models_work_on_current_python():
    # Регрессия: на Python 3.14 с pydantic 2.12 модели SDK (pydantic.v1) не создаются:
    # 'unable to infer type for attribute "x_headers"'
    from gigachat.models import ChatCompletionChunk

    chunk = ChatCompletionChunk.parse_obj({
        "choices": [{"delta": {"content": "x", "role": "assistant"}, "index": 0}],
        "created": 1,
        "model": "GigaChat-2",
        "object": "chat.completion",
    })
    chunk.x_headers = {"x-request-id": "1"}

    assert chunk.x_headers == {"x-request-id": "1"}


def test_missing_ca_bundle_file(monkeypatch, tmp_path):
    monkeypatch.setenv("GIGACHAT_CA_BUNDLE_FILE", str(tmp_path / "missing.cer"))
    with pytest.raises(Exception, match="GIGACHAT_CA_BUNDLE_FILE не найден"):
        core.GigaChatManager._get_ssl_settings()


def test_ssl_settings_not_passed_by_default():
    # Без переменных параметры не передаются, и SDK использует свои настройки
    assert core.GigaChatManager._get_ssl_settings() == {}


def test_ssl_empty_value_ignored(monkeypatch):
    monkeypatch.setenv("GIGACHAT_SSL_VERIFY", "  ")
    assert core.GigaChatManager._get_ssl_settings() == {}


def test_ca_bundle_env(monkeypatch, tmp_path):
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text("cert", encoding="utf-8")
    monkeypatch.setenv("GIGACHAT_CA_BUNDLE_FILE", f" {ca_file} ")
    assert core.GigaChatManager._get_ssl_settings() == {"ca_bundle_file": str(ca_file)}


def test_giga_client_is_cached(manager, monkeypatch):
    created = []

    def fake_client(**kwargs):
        created.append(kwargs)
        return object()

    model = {"name": "GigaChat-2"}
    monkeypatch.setattr(core, "GigaChat", fake_client)
    monkeypatch.setattr(manager.config, "get_model", lambda: model["name"])
    monkeypatch.setenv("GIGACHAT_API_KEY", "key")

    first = manager._get_giga_chat_instance()
    assert manager._get_giga_chat_instance() is first
    assert len(created) == 1
    assert created[0]["model"] == "GigaChat-2"
    assert "verify_ssl_certs" not in created[0]

    model["name"] = "GigaChat-2-Pro"
    assert manager._get_giga_chat_instance() is not first
    assert created[-1]["model"] == "GigaChat-2-Pro"

    monkeypatch.setenv("GIGACHAT_SSL_VERIFY", "0")
    manager._get_giga_chat_instance()
    assert len(created) == 3
    assert created[-1]["verify_ssl_certs"] is False


# --- Отправка сообщений ---

@pytest.mark.parametrize(
    ("content", "finish_reason", "valid"),
    [
        ('{"content":"new text\n"}'.replace("\n", "\\n"), "stop", True),
        ('{"content":"shortened"}', "length", False),
        ('{"path":"other.txt","content":"changed"}', "stop", False),
        ("Обычный ответ вместо предложения", "stop", False),
    ],
)
async def test_propose_file_edit_is_isolated(manager, monkeypatch, tmp_path, content, finish_reason, valid):
    target = tmp_path / "notes.txt"
    target.write_bytes(b"original")
    snapshot = read_snapshot(tmp_path, target.name)
    manager.conversation_history.append(HumanMessage(content="Другое сообщение"))

    async def invoke(messages):
        assert len(messages) == 2
        assert '"path": "notes.txt"' in messages[-1].content
        assert '"content": "original"' in messages[-1].content
        assert "Измени текст" in messages[-1].content
        return AIMessage(content=content, response_metadata={"finish_reason": finish_reason})

    monkeypatch.setattr(manager, "_get_giga_chat_instance", lambda: SimpleNamespace(ainvoke=invoke))
    if valid:
        change = await manager.propose_file_edit(snapshot, "Измени текст")
        assert "+new text\n" in change.diff()
    else:
        with pytest.raises(FileEditError):
            await manager.propose_file_edit(snapshot, "Измени текст")
    assert target.read_bytes() == b"original"
    assert [message.content for message in manager.conversation_history] == ["Другое сообщение"]


@pytest.mark.parametrize("corrected", [True, False])
async def test_python_proposal_retries_syntax_error_once(manager, monkeypatch, tmp_path, corrected):
    target = tmp_path / "example.py"
    broken = "return 1\n"
    replies = iter([broken, 'print("ok")\n' if corrected else broken])
    requests = []

    async def invoke(messages):
        requests.append(json.loads(messages[-1].content))
        return AIMessage(content=json.dumps({"content": next(replies)}))

    monkeypatch.setattr(manager, "_get_giga_chat_instance", lambda: SimpleNamespace(ainvoke=invoke))
    snapshot = read_snapshot(tmp_path, target.name)
    if corrected:
        edit = await manager.propose_file_edit(snapshot, "Выведи ok")
        assert edit.after == b'print("ok")\n'
    else:
        with pytest.raises(FileEditError, match="Ошибка синтаксиса Python в строке 1"):
            await manager.propose_file_edit(snapshot, "Выведи ok")

    assert len(requests) == 2
    assert requests[1]["instruction"] == requests[0]["instruction"] == "Выведи ok"
    assert requests[1]["path"] == requests[0]["path"] == target.name
    assert requests[1]["previous_proposal"] == broken
    assert "outside function" in requests[1]["syntax_error"]
    assert not target.exists()


@pytest.mark.parametrize(("opening", "closing"), [("python\n```", "```"), ("```python", "``` ```")])
async def test_new_python_proposal_preserves_docstring_quotes(manager, monkeypatch, tmp_path, opening, closing):
    source = 'def greeting():\n    """Вернуть приветствие."""\n    return "Привет!"\n'

    async def invoke(messages):
        return AIMessage(content=f"{opening}\n{source}{closing}")

    monkeypatch.setattr(manager, "_get_giga_chat_instance", lambda: SimpleNamespace(ainvoke=invoke))

    edit = await manager.propose_file_edit(read_snapshot(tmp_path, "greeting.py"), "Напиши функцию с docstring")

    assert edit.after == source.encode()


async def test_send_message_stream(manager, fake_giga):
    chunks = await collect(manager.send_message_stream("Привет?", "system"))

    assert "".join(chunk.content for chunk in chunks) == "Привет"
    assert chunks[-1].is_final
    assert not any(chunk.error for chunk in chunks)

    messages = fake_giga.requests[0]
    assert isinstance(messages[0], SystemMessage) and messages[0].content == "system"
    assert messages[-1].content == "Привет?"

    assert [type(message) for message in manager.conversation_history] == [HumanMessage, AIMessage]
    assert manager.conversation_history[1].content == "Привет"


async def test_history_is_sent_with_next_message(manager, fake_giga):
    await collect(manager.send_message_stream("первый"))
    await collect(manager.send_message_stream("второй"))

    contents = [message.content for message in fake_giga.requests[1]]
    assert contents[1:] == ["первый", "Привет", "второй"]


async def test_history_prompt_is_saved_instead_of_full_prompt(manager, fake_giga):
    await collect(manager.send_message_stream("большой промпт с файлами", history_prompt="короткий"))

    assert manager.conversation_history[0].content == "короткий"
    assert fake_giga.requests[0][-1].content == "большой промпт с файлами"


async def test_history_is_limited(manager, fake_giga):
    for i in range(15):
        await collect(manager.send_message_stream(f"сообщение {i}"))

    assert len(manager.conversation_history) == 20
    assert manager.conversation_history[0].content == "сообщение 5"


async def test_stream_error_is_reported(manager, monkeypatch):
    giga = FakeGiga(chunks=["частичный"], error=RuntimeError("boom"))
    monkeypatch.setattr(manager, "_get_giga_chat_instance", lambda: giga)

    chunks = await collect(manager.send_message_stream("вопрос"))

    assert chunks[-1].is_final
    assert "boom" in chunks[-1].error
    assert manager.conversation_history == []


async def test_ssl_error_contains_hint(manager, monkeypatch):
    giga = FakeGiga(error=RuntimeError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"))
    monkeypatch.setattr(manager, "_get_giga_chat_instance", lambda: giga)

    chunks = await collect(manager.send_message_stream("вопрос"))

    assert "GIGACHAT_CA_BUNDLE_FILE" in chunks[-1].error
    assert "GIGACHAT_SSL_VERIFY=0" in chunks[-1].error


async def test_missing_api_key_is_reported(manager):
    chunks = await collect(manager.send_message_stream("вопрос"))

    assert len(chunks) == 1
    assert "GIGACHAT_API_KEY" in chunks[0].error


# --- Маршрутизация запросов ---

async def test_file_mention_loads_file_from_project_path(manager, fake_giga, project):
    await collect(manager.get_answer_stream("Объясни что делает main.py", project_path=str(project)))

    prompt = fake_giga.requests[0][-1].content
    assert "print('root main')" in prompt
    assert "Объясни что делает main.py" in prompt
    # В историю попадает исходный запрос без содержимого файла
    assert manager.conversation_history[0].content == "Объясни что делает main.py"
    assert manager.get_conversation_stats()["last_files_context"] == ["main.py"]


async def test_missing_file_falls_back_to_plain_request(manager, fake_giga, project):
    await collect(manager.get_answer_stream("что в nope.py?", project_path=str(project)))

    assert fake_giga.requests[0][-1].content == "что в nope.py?"


async def test_project_analysis_uses_project_path(manager, fake_giga, project):
    await collect(manager.get_answer_stream("Покажи структуру проекта", project_path=str(project)))

    prompt = fake_giga.requests[0][-1].content
    assert "Структура проекта (3 файлов)" in prompt
    assert os.path.join("pkg", "main.py") in prompt
    assert "lib.js" not in prompt
    assert manager.conversation_history[0].content == "Покажи структуру проекта"


@pytest.mark.parametrize("prompt", ["Сделай ревью моего проекта", "Ревью без изменения файлов", "/review main.py"])
async def test_review_requests_and_reads_source_without_executing_writes(manager, monkeypatch, project, prompt):
    calls = iter([
        ("search_code", {"query": "root main"}),
        ("read_file", {"path": "main.py", "start_line": 1, "line_count": 1}),
        ("write_file", {"path": "main.py", "content": "changed"}),
    ])
    requests = []

    async def invoke(messages):
        requests.append(list(messages))
        call = next(calls, None)
        if call:
            name, args = call
            return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": name}])
        return AIMessage(content="Замечание в main.py:1")

    def bind(tools, *, tool_choice):
        assert {tool["name"] for tool in tools} == {"list_files", "search_code", "read_file"}
        return SimpleNamespace(ainvoke=invoke)

    monkeypatch.setattr(manager, "_get_giga_chat_instance", lambda: SimpleNamespace(bind_tools=bind))
    chunks = await collect(manager.get_answer_stream(prompt, project_path=str(project)))

    assert chunks[0].content == "Замечание в main.py:1" and chunks[-1].is_final
    assert json.loads(requests[1][-1].content)["matches"][0]["path"] == "main.py"
    assert json.loads(requests[2][-1].content)["lines"] == [{"line": 1, "text": "print('root main')"}]
    assert "error" in json.loads(requests[3][-1].content)
    assert (project / "main.py").read_text() == "print('root main')\n"
    assert [message.content for message in manager.conversation_history] == [prompt, chunks[0].content]
    assert manager.get_conversation_stats()["last_files_context"] == ["main.py"]


async def test_review_stops_tool_calls_at_budget(manager, monkeypatch, project):
    choices = []

    def bind(tools, *, tool_choice):
        choices.append(tool_choice)

        async def invoke(messages):
            if tool_choice == "none":
                assert len([message for message in messages if message.type == "tool"]) == core._REVIEW_TOOL_LIMIT
                return AIMessage(content="Итоги просмотренного кода")
            return AIMessage(content="", tool_calls=[{"name": "list_files", "args": {}, "id": str(len(messages))}])

        return SimpleNamespace(ainvoke=invoke)

    monkeypatch.setattr(manager, "_get_giga_chat_instance", lambda: SimpleNamespace(bind_tools=bind))
    chunks = await collect(manager.get_answer_stream("/review", project_path=str(project)))
    assert choices == ["auto", "none"]
    assert chunks[0].content == "Итоги просмотренного кода"


async def test_explain_inline_code(manager, fake_giga):
    await collect(manager.get_answer_stream("объясни ```print(1)```"))

    prompt = fake_giga.requests[0][-1].content
    assert prompt.startswith("Код для объяснения:")
    assert "print(1)" in prompt


async def test_refactor_inline_code(manager, fake_giga):
    await collect(manager.get_answer_stream("рефакторинг ```x=1```"))

    assert fake_giga.requests[0][-1].content.startswith("Код для рефакторинга:")


async def test_plain_request(manager, fake_giga):
    await collect(manager.get_answer_stream("как дела?"))

    assert fake_giga.requests[0][-1].content == "как дела?"


async def test_clear_history(manager, fake_giga):
    await collect(manager.send_message_stream("вопрос"))

    chunks = await collect(manager.get_answer_stream("", clear_history=True))

    assert chunks[0].content == "История диалога очищена"
    assert manager.conversation_history == []


# --- Поиск файлов в проекте ---

def test_find_file_by_name_prefers_shallow_file(manager, project):
    assert manager._find_file_in_project("main.py", str(project)) == str(project / "main.py")


@pytest.mark.parametrize("name", ["pkg/main.py", "pkg\\main.py", "./pkg/main.py", "PKG/MAIN.PY"])
def test_find_file_by_relative_path(manager, project, name):
    assert manager._find_file_in_project(name, str(project)) == str(project / "pkg" / "main.py")


def test_find_file_ignores_service_and_hidden_files(manager, project):
    assert manager._find_file_in_project("lib.js", str(project)) is None
    assert manager._find_file_in_project(".hidden.py", str(project)) is None


def test_find_file_rebuilds_stale_index(manager, project):
    assert manager._find_file_in_project("new.py", str(project)) is None

    (project / "new.py").write_text("x", encoding="utf-8")

    assert manager._find_file_in_project("new.py", str(project)) == str(project / "new.py")


def test_find_file_rebuilds_index_on_directory_change(manager, project, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "main.py").write_text("other", encoding="utf-8")

    assert manager._find_file_in_project("main.py", str(project)) == str(project / "main.py")
    assert manager._find_file_in_project("main.py", str(other)) == str(other / "main.py")


def test_find_file_does_not_match_substring(manager, project):
    assert manager._find_file_in_project("ain.py", str(project)) is None


async def test_load_file_content(manager, project, tmp_path):
    assert await manager.load_file_content(str(project / "main.py")) == "print('root main')\n"
    assert await manager.load_file_content(str(tmp_path / "missing.py")) is None

    big = tmp_path / "big.txt"
    big.write_text("x" * 100, encoding="utf-8")
    assert (await manager.load_file_content(str(big), max_size=10)).startswith("[Файл слишком большой")

    binary = tmp_path / "data.bin"
    binary.write_bytes(b"\xff\xfe\x00\x81")
    assert await manager.load_file_content(str(binary)) == "[Бинарный файл или неподдерживаемая кодировка]"


async def test_load_project_context(manager, project):
    context = await manager.load_project_context(str(project))

    # Служебные директории и скрытые файлы не попадают в структуру
    assert sorted(context["file_structure"]) == sorted(["README.md", "main.py", os.path.join("pkg", "main.py")])
    # README.md - конфигурационный файл, поэтому идет первым
    assert next(iter(context["key_files"])) == "README.md"


async def test_automatic_context_respects_gitignore(manager, project):
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / ".gitignore").write_text("private.py\n", encoding="utf-8")
    (project / "private.py").write_text("secret_marker = 42\n", encoding="utf-8")
    context = await manager.load_project_context(str(project))
    assert "private.py" not in context["file_structure"]
    files = await manager.load_multiple_files(["private.py"], str(project))
    assert "secret_marker" not in files["private.py"]
