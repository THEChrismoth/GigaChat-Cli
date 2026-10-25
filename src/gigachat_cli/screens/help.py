"""Экран справки с руководством пользователя."""

import importlib.resources

from textual.app import ComposeResult
from textual.screen import Screen
from textual.containers import VerticalScroll
from textual.widgets import Markdown
from textual import events

from gigachat_cli.widgets.banner import Banner

HELP_CONTENT = """
# 🚀 Руководство пользователя GigaChat CLI

## ⚙️ Начало работы

Перед запуском задайте ключ API в переменной окружения `GIGACHAT_API_KEY`.

Linux и macOS:

```bash
export GIGACHAT_API_KEY="ваш_ключ"
```

Windows (PowerShell):

```powershell
$env:GIGACHAT_API_KEY = "ваш_ключ"
```

## 🎯 Команды

Начните вводить `/` - появится автодополнение команд:
- `/model` - выбор модели GigaChat (Lite, Pro, Max)
- `/help` - краткая справка в чате
- `/menu` - возврат в меню
- `/exit` - выход из приложения

Терминальные команды начинаются с `!` и выполняются в текущей директории чата:
- `!git status`, `!ls -la` - любая команда системы
- `!cd src` - смена директории (показывается в строке состояния)
- для пути к файлу работает автодополнение, в том числе для имен с пробелами

## ⌨️ Управление

- `Enter` - отправить сообщение или подтвердить выбор
- `Tab` / `Shift+Tab` - перемещение по автодополнению
- `↑` / `↓` - перемещение по списку выбора (например, моделей)
- `Esc` - отмена выбора, прерывание запроса или команды, закрытие справки

## 📁 Работа с проектом

Упомяните файл в запросе - его содержимое будет передано GigaChat:
- `Объясни что делает main.py`
- `Как улучшить код в src/utils/core.py?`

Другие запросы:
- `Покажи структуру проекта` - анализ структуры и ключевых файлов
- ```` Объясни ```print(sum(range(10)))``` ```` - объяснение кода прямо из запроса

## 💡 Неинтерактивный режим

Для скриптов и конвейеров - запрос без интерфейса:

```bash
gigachat -p "Объясни что делает main.py"
git diff | gigachat -p "Напиши commit message"
```

---
*Для возврата в меню нажмите Escape*
"""

class HelpScreen(Screen):
    """Экран справки с руководством пользователя."""

    CSS = importlib.resources.files("gigachat_cli.styles").joinpath("help.css").read_text()

    def compose(self) -> ComposeResult:
        """Создание виджетов экрана.

        Yields:
            Прокручиваемый контейнер с баннером и текстом справки
        """
        yield VerticalScroll(
            Banner(),
            Markdown(HELP_CONTENT)
        )

    def on_key(self, event: events.Key) -> None:
        """Возврат на предыдущий экран по Escape.

        Args:
            event: Событие нажатия клавиши
        """
        if event.key == "escape":
            self.app.pop_screen()
