import json

from gigachat_cli.utils.config import DEFAULT_MODEL


def test_default_config_created(config):
    assert config.config_file.exists()
    assert config.get_model() == DEFAULT_MODEL


def test_set_model_persists(config):
    config.set_model("GigaChat-2-Pro")

    assert config.get_model() == "GigaChat-2-Pro"
    assert json.loads(config.config_file.read_text(encoding="utf-8"))["model"] == "GigaChat-2-Pro"


def test_set_model_keeps_other_keys(config):
    config.config_file.write_text(json.dumps({"model": "GigaChat-2", "theme": "dark"}), encoding="utf-8")

    config.set_model("GigaChat-2-Max")

    assert json.loads(config.config_file.read_text(encoding="utf-8")) == {"model": "GigaChat-2-Max", "theme": "dark"}


def test_corrupted_config_falls_back_to_default(config):
    config.config_file.write_text("{broken", encoding="utf-8")
    assert config.get_model() == DEFAULT_MODEL


def test_non_dict_config_falls_back_to_default(config):
    config.config_file.write_text("[1, 2]", encoding="utf-8")
    assert config.get_model() == DEFAULT_MODEL


def test_missing_model_key_falls_back_to_default(config):
    config.config_file.write_text("{}", encoding="utf-8")
    assert config.get_model() == DEFAULT_MODEL


def test_set_model_repairs_corrupted_config(config):
    config.config_file.write_text("{broken", encoding="utf-8")

    config.set_model("GigaChat-2-Pro")

    assert config.get_model() == "GigaChat-2-Pro"


def test_missing_config_file_falls_back_to_default(config):
    config.config_file.unlink()
    assert config.get_model() == DEFAULT_MODEL
