"""Настройки приложения в ~/.gigachat/config.json."""

from pathlib import Path
import json


DEFAULT_MODEL = "GigaChat-2"


class Config:
    """Настройки приложения (singleton): чтение и сохранение выбранной модели."""

    _instance = None
    _initialized = False

    def __new__(cls):
        """Возврат единственного экземпляра настроек."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Подготовка файла настроек: создание с моделью по умолчанию, если его нет."""
        if not self._initialized:
            self.config_file = Path.home() / ".gigachat" / "config.json"
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

            if not self.config_file.exists():
                self._create_default_config()

            self._initialized = True

    def _create_default_config(self):
        """Создание файла настроек с моделью по умолчанию."""
        self._write_config({"model": DEFAULT_MODEL})

    def _read_config(self) -> dict:
        """Чтение настроек.

        Returns:
            dict: Настройки; при отсутствии или повреждении файла - настройки по умолчанию
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
        """Сохранение настроек.

        Args:
            config: Настройки для сохранения
        """
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def get_model(self) -> str:
        """Получение выбранной модели.

        Returns:
            str: Идентификатор модели; при отсутствии или ошибке - модель по умолчанию
        """
        model = self._read_config().get("model")
        return model if isinstance(model, str) and model else DEFAULT_MODEL

    def set_model(self, model: str):
        """Сохранение выбранной модели; остальные настройки не меняются.

        Args:
            model: Идентификатор модели, например GigaChat-2-Pro
        """
        config = self._read_config()
        config["model"] = model
        self._write_config(config)
