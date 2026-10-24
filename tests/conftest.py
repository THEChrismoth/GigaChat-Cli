import os
import shlex
import subprocess
import sys
import tempfile

# Изоляция от реальной домашней директории и переменных окружения пользователя.
# Выполняется до импорта пакета: при импорте gigachat_cli.utils.core создается
# конфигурация в ~/.gigachat
_TEST_HOME = tempfile.mkdtemp(prefix="gigachat-cli-home-")
os.environ["HOME"] = _TEST_HOME
os.environ["USERPROFILE"] = _TEST_HOME
for _var in ("GIGACHAT_API_KEY", "GIGACHAT_SSL_VERIFY", "GIGACHAT_CA_BUNDLE_FILE", "GIGACHAT_VERIFY_SSL_CERTS"):
    os.environ.pop(_var, None)

import pytest  # noqa: E402

from gigachat_cli.utils.config import Config  # noqa: E402
from gigachat_cli.utils.core import GigaChatManager  # noqa: E402


def python_command(code: str) -> str:
    """Строка команды запуска текущего интерпретатора Python для выполнения через CommandUtils"""
    args = [sys.executable, "-c", code]
    if os.name == "nt":
        return subprocess.list2cmdline(args)
    return shlex.join(args)


@pytest.fixture
def config(tmp_path, monkeypatch):
    """Новый экземпляр Config с конфигурацией во временной директории"""
    monkeypatch.setattr(Config, "_instance", None)
    monkeypatch.setattr("gigachat_cli.utils.config.Path.home", lambda: tmp_path)
    return Config()


@pytest.fixture
def manager(monkeypatch):
    """Новый экземпляр GigaChatManager с пустой историей"""
    monkeypatch.setattr(GigaChatManager, "_instance", None)
    return GigaChatManager()


@pytest.fixture
def project(tmp_path):
    """Небольшой проект для поиска файлов и анализа структуры"""
    root = tmp_path / "project"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "main.py").write_text("print('pkg main')\n", encoding="utf-8")
    (root / "main.py").write_text("print('root main')\n", encoding="utf-8")
    (root / "README.md").write_text("# Project\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "lib.js").write_text("ignored", encoding="utf-8")
    (root / ".hidden.py").write_text("hidden", encoding="utf-8")
    return root
