"""Выпадающий список автодополнения файлов для терминальных команд."""

from textual.widgets import Static
from textual.reactive import reactive
from pathlib import Path

from gigachat_cli.utils.file import complete_path_argument


class FileList(Static):
    """Виджет автодополнения файлов с иконками и прокруткой."""

    can_focus = False

    files = reactive([])
    selected_index = reactive(0)
    current_command = ""  # Текст команды, для которой подобраны файлы
    current_path = ""     # Директория, в которой искались файлы
    visible_start = 0     # Индекс первого видимого файла
    visible_count = 5     # Количество файлов, показываемых одновременно

    def update_files(self, files: list[str], current_command: str, current_path: str) -> None:
        """Обновление списка файлов; пустой список скрывает виджет.

        Args:
            files: Имена файлов и директорий
            current_command: Текст команды из поля ввода
            current_path: Директория, в которой искались файлы
        """
        if files:
            self.files = files
            self.current_command = current_command
            self.current_path = current_path
            self.selected_index = 0
            self.visible_start = 0
            self.remove_class("hidden")
            self._update_display()
        else:
            self.add_class("hidden")
            self.files = []

    def _update_display(self) -> None:
        """Отрисовка видимой части списка с выделением выбранного файла."""
        if not self.files:
            return

        visible_files = self.files[self.visible_start:self.visible_start + self.visible_count]

        formatted_files = []
        for i, file_name in enumerate(visible_files):
            actual_index = self.visible_start + i

            full_path = Path(self.current_path) / file_name
            is_dir = full_path.is_dir()

            icon = "📁" if is_dir else "📄"
            line = f"{icon} {file_name}"

            # У выбранного файла показывается позиция, если список не помещается целиком
            if actual_index == self.selected_index:
                if len(self.files) > self.visible_count:
                    line = f"➤ {line} [{actual_index + 1}/{len(self.files)}]"
                else:
                    line = f"➤ {line}"
            else:
                line = f"  {line}"

            formatted_files.append(line)

        self.update("\n".join(formatted_files))

    def select_next(self) -> None:
        """Выбор следующего файла (после последнего - переход к первому)."""
        if self.files:
            self.selected_index = (self.selected_index + 1) % len(self.files)
            # Прокрутка, чтобы выбранный файл оставался видимым
            if self.selected_index >= self.visible_start + self.visible_count:
                self.visible_start += 1
            elif self.selected_index < self.visible_start:
                self.visible_start = self.selected_index
            self._update_display()

    def select_previous(self) -> None:
        """Выбор предыдущего файла (перед первым - переход к последнему)."""
        if self.files:
            self.selected_index = (self.selected_index - 1) % len(self.files)
            # Прокрутка, чтобы выбранный файл оставался видимым
            if self.selected_index < self.visible_start:
                self.visible_start -= 1
            elif self.selected_index >= self.visible_start + self.visible_count:
                self.visible_start = self.selected_index - self.visible_count + 1
            self._update_display()

    def get_selected_file(self) -> str:
        """Получение выбранного файла.

        Returns:
            str: Имя выбранного файла или пустая строка
        """
        if self.files and 0 <= self.selected_index < len(self.files):
            return self.files[self.selected_index]
        return ""

    def apply_selection(self, input_field) -> None:
        """Подстановка выбранного файла в поле ввода с экранированием пробелов и спецсимволов.

        Args:
            input_field: Поле ввода для обновления
        """
        selected_file = self.get_selected_file()
        if selected_file and self.current_command:
            new_text = complete_path_argument(self.current_command, selected_file)

            input_field.value = new_text
            input_field.cursor_position = len(new_text)
            self.add_class("hidden")
            input_field.focus()
