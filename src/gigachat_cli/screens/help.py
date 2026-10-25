"""Экран справки с руководством пользователя."""

import importlib.resources

from textual.app import ComposeResult
from textual.screen import Screen
from textual.containers import VerticalScroll
from textual.widgets import Markdown
from textual import events

from gigachat_cli.widgets.banner import Banner

HELP_CONTENT = """
# 🚀 Руководство пользователя GigaChat

## ⚙️ Начало работы

Перед запуском приложения установите API-ключ в системе:

```Bash
export GIGACHAT_API_KEY="YOUR_API_KEY"
```
## 🎯 Основные команды

Доступные команды (автодополнение по Tab):
- `/model` - выбор модели GigaChat (Lite/Pro/Max)
- `/menu` - для возврата назад в меню
- `/help` - показать эту справку
- `/exit` - выход из приложения

## ⌨️ Управление интерфейсом

**Навигация:**
- `Tab` / `Shift+Tab` - навигация по автодополнению команд
- `↑ / ↓` - навигация в выпадающих списках (селекторах)
- `Enter` - подтвердить выбор `/` отправить сообщение
- `Escape` - отмена `/` возврат `/` закрытие справки

**Работа с текстом:**
- Просто введите текст и нажмите `Enter для отправки
- Используйте автодополнение команд (начните вводить `/`)

**Примеры Работы с проектом:**
- `Объясни что делает main.py` - автоматически найдет и проанализирует файл
- `Как улучшить код в utils.py?` - анализ и предложения по улучшению
- `Покажи структуру проекта` - анализ всей файловой структуры
- `Рефакторинг функции calculate()` - поиск и улучшение конкретной функц

## 💡 Как работать с приложением

1. **Начните диалог** - просто введите текст в поле ввода
2. **Форматируйте текст** - используйте Enter для переноса строк
3. **Отправляйте сообщения** - нажмите Shift+Enter когда текст готов
4. **![command] [key]** - используйте ! для работы с терминальными командами
5. **/menu** - используйте коману /menu для того чтобы вернуться в меню приложения
6. **/model** - используйте команду /model для переключения модели API GigaChat
7. **/exit** - используйте команду /exit для завершения работы приложения

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
