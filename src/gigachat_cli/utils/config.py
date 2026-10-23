from pathlib import Path
import json


DEFAULT_MODEL = "GigaChat-2"


class Config:
    """Класс для управления конфигурацией приложения"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        """Реализация singleton паттерна"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Инициализация конфигурации"""
        if not self._initialized:
            # Путь к файлу конфигурации в домашней директории пользователя
            self.config_file = Path.home() / ".gigachat" / "config.json"
            # Создание директории конфигурации если не существует
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

            # Создание конфигурации по умолчанию если файл не существует
            if not self.config_file.exists():
                self._create_default_config()

            self._initialized = True

    def _create_default_config(self):
        """
        Создание конфигурации по умолчанию
        """
        self._write_config({"model": DEFAULT_MODEL})

    def _read_config(self) -> dict:
        """
        Чтение конфигурации; при отсутствии или повреждении файла возвращается конфигурация по умолчанию

        Returns:
            dict: Конфигурация
        """
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {"model": DEFAULT_MODEL}

        if not isinstance(config, dict):
            return {"model": DEFAULT_MODEL}
        return config

    def _write_config(self, config: dict):
        """
        Сохранение конфигурации

        Args:
            config: Конфигурация для сохранения
        """
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def get_model(self) -> str:
        """
        Получение текущей модели из конфигурации

        Returns:
            str: Название текущей модели
        """
        model = self._read_config().get("model")
        return model if isinstance(model, str) and model else DEFAULT_MODEL

    def set_model(self, model: str):
        """
        Установка новой модели в конфигурацию

        Args:
            model: Название модели для установки
        """
        config = self._read_config()
        config["model"] = model
        self._write_config(config)
