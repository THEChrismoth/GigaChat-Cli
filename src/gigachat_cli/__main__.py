import sys
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    """
    Основная функция запуска приложения GigaChat CLI

    Без аргументов запускается интерактивный интерфейс (TUI),
    с аргументами - неинтерактивный режим (gigachat -p "запрос")
    """
    argv = sys.argv[1:] if argv is None else argv

    if argv:
        from gigachat_cli.cli import main as cli_main
        return cli_main(argv)

    from gigachat_cli.main import Main
    Main().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
