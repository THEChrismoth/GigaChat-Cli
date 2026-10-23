from textual.widgets import Static
from textual.reactive import reactive
from pathlib import Path
import os

from gigachat_cli.utils.file import split_path_argument


class FileList(Static):
    """Виджет автодополнения файлов"""
    
    can_focus = False 
    
    files = reactive([])
    selected_index = reactive(0)
    current_command = ""  # Сохранение полной команды
    current_path = ""     # Текущий путь для автодополнения
    visible_start = 0     # Начало видимой области
    visible_count = 5     # Количество файлов, показываемых одновременно
    
    def update_files(self, files: list[str], current_command: str, current_path: str) -> None:
        """
        Обновление списка файлов для автодополнения
        
        Args:
            files: Список файлов для отображения
            current_command: Текущая команда из поля ввода
            current_path: Текущий путь для автодополнения
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
        """Обновление отображения списка файлов"""
        if not self.files:
            return
            
        # Определение видимого диапазона файлов
        visible_files = self.files[self.visible_start:self.visible_start + self.visible_count]
        
        formatted_files = []
        for i, file_name in enumerate(visible_files):
            actual_index = self.visible_start + i
            
            # Получение полного пути для проверки типа
            full_path = Path(self.current_path) / file_name
            is_dir = full_path.is_dir()
            
            # Форматирование отображения с иконками
            icon = "📁" if is_dir else "📄"
            line = f"{icon} {file_name}"
            
            # Показ индикатора прокрутки если есть больше файлов
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
        """Выбор следующего файла в списке"""
        if self.files:
            self.selected_index = (self.selected_index + 1) % len(self.files)
            # Прокрутка если вышли за границы видимой области
            if self.selected_index >= self.visible_start + self.visible_count:
                self.visible_start += 1
            elif self.selected_index < self.visible_start:
                self.visible_start = self.selected_index
            self._update_display()
    
    def select_previous(self) -> None:
        """Выбор предыдущего файла в списке"""
        if self.files:
            self.selected_index = (self.selected_index - 1) % len(self.files)
            # Прокрутка если вышли за границы видимой области
            if self.selected_index < self.visible_start:
                self.visible_start -= 1
            elif self.selected_index >= self.visible_start + self.visible_count:
                self.visible_start = self.selected_index - self.visible_count + 1
            self._update_display()
    
    def get_selected_file(self) -> str:
        """
        Получение выбранного файла
        
        Returns:
            str: Выбранное имя файла или пустая строка
        """
        if self.files and 0 <= self.selected_index < len(self.files):
            return self.files[self.selected_index]
        return ""
    
    def apply_selection(self, input_field) -> None:
        """
        Применение выбранного файла к полю ввода
        
        Args:
            input_field: Поле ввода для обновления
        """
        selected_file = self.get_selected_file()
        if selected_file and self.current_command:
            command = self.current_command

            if command.endswith(' '):
                # Начат новый аргумент - просто добавляем файл
                new_text = command + selected_file
            else:
                # Замена введенного начала имени в последнем аргументе (путь до него сохраняется)
                _, typed_name = split_path_argument(command.split()[-1])
                new_text = command[:len(command) - len(typed_name)] + selected_file
            
            input_field.value = new_text
            input_field.cursor_position = len(new_text)
            self.add_class("hidden")
            input_field.focus()
