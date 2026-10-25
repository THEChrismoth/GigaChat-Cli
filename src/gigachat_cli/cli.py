"""Неинтерактивный режим: один запрос из командной строки без TUI"""

import argparse
import asyncio
import json
import os
import sys
import time
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Dict, List, Optional, TextIO

from gigachat_cli.utils.core import chat_manager, get_answer_stream


OUTPUT_FORMATS = ("text", "json", "stream-json")

# Коды возврата
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


def _package_version() -> str:
    """Версия установленного пакета"""
    try:
        return version("gigachat-cli")
    except PackageNotFoundError:
        return "unknown"


def build_parser() -> argparse.ArgumentParser:
    """Парсер аргументов командной строки"""
    parser = argparse.ArgumentParser(
        prog="gigachat",
        description="GigaChat CLI. Без аргументов запускается интерактивный интерфейс.",
        epilog=(
            "Примеры:\n"
            '  gigachat -p "Объясни что делает main.py"\n'
            '  git diff | gigachat -p "Напиши commit message"\n'
            '  gigachat -p "Покажи структуру проекта" --output-format json'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-p", "--print",
        dest="prompt",
        nargs="?",
        const="",
        default=None,
        metavar="PROMPT",
        help="выполнить один запрос и вывести ответ без интерактивного интерфейса; "
             "данные из stdin добавляются к запросу (без PROMPT запросом считается stdin)",
    )
    parser.add_argument(
        "--output-format",
        choices=OUTPUT_FORMATS,
        default="text",
        help="формат вывода для -p: text - только ответ (по умолчанию), "
             "json - один JSON-объект с результатом, stream-json - события JSON Lines по мере генерации",
    )
    parser.add_argument(
        "--model",
        help="модель GigaChat на этот запуск (например, GigaChat-2-Pro), без сохранения в настройках",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_package_version()}")
    return parser


def read_prompt(prompt: str, stdin: TextIO) -> str:
    """
    Сборка запроса из аргумента и stdin

    Args:
        prompt: Запрос из аргумента -p (может быть пустым)
        stdin: Стандартный ввод

    Returns:
        str: Итоговый запрос (пустая строка, если запроса нет)
    """
    piped = "" if stdin is None or stdin.isatty() else stdin.read()
    parts = [part.strip() for part in (prompt, piped) if part and part.strip()]
    return "\n\n".join(parts)


def _write_json(stream: TextIO, data: Dict[str, Any]) -> None:
    """Вывод JSON-объекта одной строкой"""
    stream.write(json.dumps(data, ensure_ascii=False) + "\n")
    stream.flush()


async def run_prompt(prompt: str, output_format: str, stdout: TextIO, stderr: TextIO) -> int:
    """
    Выполнение одного запроса с выводом в заданном формате

    Args:
        prompt: Запрос пользователя
        output_format: text, json или stream-json
        stdout: Поток вывода ответа
        stderr: Поток вывода ошибок (для формата text)

    Returns:
        int: Код возврата
    """
    started = time.monotonic()
    model = chat_manager.get_current_model()
    response: List[str] = []
    error: Optional[str] = None

    if output_format == "stream-json":
        _write_json(stdout, {"type": "start", "model": model})

    async for chunk in get_answer_stream(prompt, project_path=os.getcwd()):
        if chunk.content:
            response.append(chunk.content)
            if output_format == "text":
                stdout.write(chunk.content)
                stdout.flush()
            elif output_format == "stream-json":
                _write_json(stdout, {"type": "chunk", "content": chunk.content})
        if chunk.error:
            error = chunk.error
        if chunk.is_final:
            break

    result = {
        "type": "result",
        "is_error": error is not None,
        "result": "".join(response),
        "error": error,
        "model": model,
        "files": list(chat_manager.get_conversation_stats()["last_files_context"]),
        "duration_ms": round((time.monotonic() - started) * 1000),
    }

    if output_format == "text":
        if response:
            stdout.write("\n")
            stdout.flush()
        if error:
            stderr.write(f"Ошибка: {error}\n")
            stderr.flush()
    else:
        _write_json(stdout, result)

    return EXIT_ERROR if error else EXIT_OK


def _use_utf8_output() -> None:
    """Вывод в UTF-8 независимо от кодировки консоли (важно для Windows и перенаправления в файл)"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: Optional[List[str]] = None) -> int:
    """
    Точка входа неинтерактивного режима

    Args:
        argv: Аргументы командной строки (по умолчанию sys.argv[1:])

    Returns:
        int: Код возврата
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.prompt is None:
        parser.error("для неинтерактивного режима укажите -p/--print")

    _use_utf8_output()

    prompt = read_prompt(args.prompt, sys.stdin)
    if not prompt:
        parser.error("пустой запрос: передайте текст после -p или через stdin")

    if args.model:
        chat_manager.model_override = args.model

    try:
        return asyncio.run(run_prompt(prompt, args.output_format, sys.stdout, sys.stderr))
    except KeyboardInterrupt:
        sys.stderr.write("Прервано\n")
        return EXIT_INTERRUPTED
