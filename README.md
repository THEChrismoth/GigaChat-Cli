<h1 align="center">GigaChat CLI</h1>

<p align="center">
  <b>AI-ассистент для разработчиков в терминале на базе <a href="https://developers.sber.ru/gigachat">GigaChat</a></b>
</p>

<p align="center">
  Чат с нейросетью, контекст файлов проекта, встроенный терминал и неинтерактивный режим для скриптов и CI
</p>

<p align="center">
  <a href="https://pypi.org/project/gigachat-cli/"><img src="https://img.shields.io/pypi/v/gigachat-cli.svg" alt="PyPI"></a>
  <a href="https://pypi.org/project/gigachat-cli/"><img src="https://img.shields.io/pypi/pyversions/gigachat-cli.svg" alt="Python"></a>
  <a href="https://github.com/THEChrismoth/GigaChat-Cli/actions/workflows/test.yml"><img src="https://github.com/THEChrismoth/GigaChat-Cli/actions/workflows/test.yml/badge.svg" alt="Tests"></a>
  <a href="https://github.com/THEChrismoth/GigaChat-Cli/blob/master/LICENSE.md"><img src="https://img.shields.io/pypi/l/gigachat-cli.svg" alt="License"></a>
  <a href="https://gitverse.ru/THEChrismoth/GigaChat-Cli"><img src="https://img.shields.io/badge/GitVerse-mirror-blue.svg" alt="GitVerse"></a>
</p>

<p align="center">
  <a href="#возможности">Возможности</a> •
  <a href="#установка">Установка</a> •
  <a href="#настройка">Настройка</a> •
  <a href="#использование">Использование</a> •
  <a href="#неинтерактивный-режим">Неинтерактивный режим</a> •
  <a href="#разработка">Разработка</a> •
  <a href="#решение-проблем">Решение проблем</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/THEChrismoth/GigaChat-Cli/master/docs/images/chat.png" alt="Ответ GigaChat с учетом содержимого файла проекта" width="800">
</p>

## Возможности

- 💬 **Чат с GigaChat** в терминале: ответ выводится по мере генерации, история диалога сохраняется
- 📁 **Контекст проекта**: упомяните файл в запросе (`объясни main.py`) — его содержимое будет передано модели; запросы вида «покажи структуру проекта» анализируют весь проект
- 🖥️ **Встроенный терминал**: команды с префиксом `!` (`!git status`, `!cd src`) выполняются прямо из чата
- ⌨️ **Автодополнение** команд чата и путей к файлам, в том числе с пробелами в имени
- 🔀 **Выбор модели**: GigaChat 2 Lite, Pro и Max
- 🤖 **Неинтерактивный режим** для скриптов, конвейеров и CI: `gigachat -p "запрос"` с выводом в текст, JSON или JSON Lines
- 🪟 **Linux, macOS и Windows**

## Установка

Требуется Python 3.13 или новее.

```bash
pip install gigachat-cli
```

Или в изолированном окружении (рекомендуется для утилит командной строки):

```bash
uv tool install gigachat-cli
# или
pipx install gigachat-cli
```

<details>
<summary>Установка из исходного кода</summary>

```bash
git clone https://github.com/THEChrismoth/GigaChat-Cli.git
cd GigaChat-Cli
uv sync
uv run gigachat
```

</details>

## Настройка

### Ключ API

1. Войдите в [личный кабинет GigaChat API](https://developers.sber.ru/studio/login)
2. Создайте проект GigaChat API и получите ключ авторизации
3. Сохраните ключ в переменной окружения `GIGACHAT_API_KEY`:

**Linux и macOS**

```bash
export GIGACHAT_API_KEY="ваш_ключ"
# чтобы не вводить каждый раз:
echo 'export GIGACHAT_API_KEY="ваш_ключ"' >> ~/.bashrc
```

**Windows (PowerShell)**

```powershell
$env:GIGACHAT_API_KEY = "ваш_ключ"          # для текущего окна
setx GIGACHAT_API_KEY "ваш_ключ"            # насовсем (для новых окон)
```

> **Важно:** `setx` действует только для программ, запущенных после него. Перезапустите терминал или редактор (Zed, VS Code, PyCharm) целиком.

### SSL-сертификат

Сервисы GigaChat используют сертификат, подписанный [корневым сертификатом Минцифры](https://www.gosuslugi.ru/crt), которого нет в стандартных хранилищах. Если запросы завершаются ошибкой `CERTIFICATE_VERIFY_FAILED`, скачайте сертификат и укажите путь к нему:

```bash
export GIGACHAT_CA_BUNDLE_FILE="/path/to/russian_trusted_root_ca.cer"
```

Сертификат должен быть в текстовом формате PEM (начинается со строки `-----BEGIN CERTIFICATE-----`).

### Переменные окружения

| Переменная | Назначение |
|---|---|
| `GIGACHAT_API_KEY` | Ключ авторизации GigaChat API (обязательно) |
| `GIGACHAT_CA_BUNDLE_FILE` | Путь к корневому сертификату Минцифры (PEM) |
| `GIGACHAT_SSL_VERIFY` | `0`, `false`, `no` или `off` отключает проверку сертификата (небезопасно) |

Если `GIGACHAT_SSL_VERIFY` не задана, учитываются стандартные переменные SDK GigaChat (например, `GIGACHAT_VERIFY_SSL_CERTS`).
Выбранная модель хранится в `~/.gigachat/config.json`.

## Использование

```bash
gigachat
```

В меню выберите «Начать использование» и задавайте вопросы.

### Команды чата

| Команда | Действие |
|---|---|
| `/model` | Выбор модели: GigaChat 2 Lite, Pro или Max |
| `/help` | Краткая справка |
| `/menu` | Возврат в меню |
| `/exit` | Выход из приложения |
| `!команда` | Выполнение команды в терминале |

### Управление

| Клавиша | Действие |
|---|---|
| `Enter` | Отправить сообщение / подтвердить выбор |
| `Tab` / `Shift+Tab` | Перемещение по автодополнению |
| `↑` / `↓` | Перемещение по списку выбора |
| `Esc` | Отмена выбора, прерывание запроса или команды, закрытие справки |

### Работа с проектом

Файлы и структура проекта берутся из текущей директории чата — она показана в строке состояния и меняется командой `!cd`.

| Запрос | Что происходит |
|---|---|
| `Объясни что делает main.py` | Файл ищется в проекте, его содержимое передается модели |
| `Как улучшить код в src/utils/core.py?` | То же для относительного пути |
| `Покажи структуру проекта` | Модель получает список файлов и начало ключевых файлов |
| ```` Объясни ```print(sum(range(10)))``` ```` | Объяснение кода прямо из запроса (также «рефакторинг») |

В модель передаются только файлы с известными расширениями (`.py`, `.js`, `.ts`, `.md`, `.json`, `.toml` и др.) размером до 15 КБ. Служебные директории (`.git`, `node_modules`, `venv`) и скрытые файлы не учитываются.

### Терминальные команды

Сообщение, начинающееся с `!`, выполняется как команда системы:

```text
!git status
!ls -la
!cd "My Projects"/app
```

- Для `cd`, `ls`, `cat`, `cp`, `mv` и других файловых команд работает автодополнение путей (`Tab`), в том числе для имен с пробелами: подставляется `My\ Docs` в Linux и macOS или `"My Docs"` в Windows
- Ввод с клавиатуры командам недоступен, время выполнения ограничено 60 секундами, `Esc` прерывает команду
- В Windows команды выполняются через `cmd.exe` (доступны `dir`, `type` и другие встроенные команды)

### Скриншоты

<table>
  <tr>
    <td align="center"><img src="https://raw.githubusercontent.com/THEChrismoth/GigaChat-Cli/master/docs/images/menu.png" alt="Главное меню" width="400"><br>Главное меню</td>
    <td align="center"><img src="https://raw.githubusercontent.com/THEChrismoth/GigaChat-Cli/master/docs/images/autocomplete.png" alt="Автодополнение путей" width="400"><br>Автодополнение путей</td>
  </tr>
  <tr>
    <td align="center"><img src="https://raw.githubusercontent.com/THEChrismoth/GigaChat-Cli/master/docs/images/terminal.png" alt="Терминальная команда" width="400"><br>Терминальная команда</td>
    <td align="center"><img src="https://raw.githubusercontent.com/THEChrismoth/GigaChat-Cli/master/docs/images/model.png" alt="Выбор модели" width="400"><br>Выбор модели</td>
  </tr>
</table>

## Неинтерактивный режим

Один запрос без интерфейса — для скриптов, конвейеров и CI:

```bash
gigachat -p "Объясни что делает main.py"
git diff | gigachat -p "Напиши commit message"
gigachat -p "Покажи структуру проекта" --output-format json
gigachat -p "Сравни подходы" --model GigaChat-2-Max
```

| Параметр | Описание |
|---|---|
| `-p`, `--print [PROMPT]` | Запрос. Данные из stdin добавляются к нему; без `PROMPT` запросом считается stdin |
| `--output-format text` | Только ответ, по мере генерации; ошибки — в stderr (по умолчанию) |
| `--output-format json` | Один JSON-объект с результатом |
| `--output-format stream-json` | События [JSON Lines](https://jsonlines.org/) по мере генерации |
| `--model MODEL` | Модель на этот запуск, без сохранения в настройках |
| `--version`, `--help` | Версия и справка |

Пример `--output-format json`:

```json
{
  "type": "result",
  "is_error": false,
  "result": "GigaChat — это нейросетевая модель, разработанная SberAI, способная понимать и генерировать естественный язык...",
  "error": null,
  "model": "GigaChat-2",
  "files": [],
  "duration_ms": 2497
}
```

При `--output-format stream-json` выводится событие `start`, затем `chunk` на каждую часть ответа и в конце `result` с теми же полями:

```json
{"type": "start", "model": "GigaChat-2"}
{"type": "chunk", "content": "GigaChat — это"}
{"type": "chunk", "content": " нейросетевая модель..."}
{"type": "result", "is_error": false, "result": "GigaChat — это нейросетевая модель...", "error": null, "model": "GigaChat-2", "files": [], "duration_ms": 2497}
```

Коды возврата: `0` — успех, `1` — ошибка API, `2` — неверные аргументы или пустой запрос, `130` — прервано (`Ctrl+C`). Вывод всегда в UTF-8.

## Разработка

Нужен [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/THEChrismoth/GigaChat-Cli.git
cd GigaChat-Cli
uv sync                        # окружение и зависимости, включая dev
uv run gigachat                # запуск из исходников
uv run pytest                  # тесты
uv run ruff check src tests    # линтер
```

- Тесты не обращаются к GigaChat API: клиент подменяется заглушкой, интерфейс проверяется через `App.run_test()` Textual
- Комментарии и docstring пишутся на русском, docstring — по PEP 257 в формате Google (проверяется ruff)

<details>
<summary>Структура проекта</summary>

```text
src/gigachat_cli/
├── __main__.py          # точка входа: TUI или неинтерактивный режим
├── cli.py               # неинтерактивный режим (gigachat -p)
├── main.py              # приложение Textual
├── screens/             # экраны: меню, чат, справка
├── handler/             # обработчики /help, /model и !команд
├── widgets/             # виджеты интерфейса
├── styles/              # CSS экранов
└── utils/
    ├── core.py          # запросы к GigaChat, история, контекст файлов
    ├── command.py       # разбор и выполнение терминальных команд
    ├── file.py          # автодополнение путей
    └── config.py        # настройки (~/.gigachat/config.json)
```

</details>

### CI/CD

- **Tests** — ruff и pytest на Linux, Windows и macOS для Python 3.13 и 3.14 (и экспериментально 3.15) при каждом push и pull request
- **Upload Python Package** — при публикации релиза на GitHub пакет собирается и публикуется в PyPI только после успешных тестов; релиз дублируется на GitVerse
- **Mirror to GitVerse** — ветки и теги автоматически повторяются в [зеркале на GitVerse](https://gitverse.ru/THEChrismoth/GigaChat-Cli)

Разработка ведется на GitHub: issues и pull requests принимаются [там](https://github.com/THEChrismoth/GigaChat-Cli/issues).

## Решение проблем

<details>
<summary><code>GIGACHAT_API_KEY не установлен</code></summary>

Задайте переменную окружения (см. [Ключ API](#ключ-api)). После `setx` в Windows перезапустите терминал или редактор. Проверить, что переменная видна:

```powershell
$env:GIGACHAT_API_KEY    # PowerShell
echo $GIGACHAT_API_KEY   # bash/zsh
```

</details>

<details>
<summary><code>CERTIFICATE_VERIFY_FAILED</code></summary>

Укажите путь к корневому сертификату Минцифры в `GIGACHAT_CA_BUNDLE_FILE` (см. [SSL-сертификат](#ssl-сертификат)). Если указанного файла нет, приложение сообщит об этом отдельной ошибкой. Временно проверку можно отключить: `GIGACHAT_SSL_VERIFY=0`.

</details>

<details>
<summary><code>unable to infer type for attribute "x_headers"</code></summary>

Ошибка SDK GigaChat на Python 3.14 со старой версией pydantic. Обновите пакет — он требует pydantic 2.13 или новее:

```bash
pip install -U gigachat-cli
```

</details>

<details>
<summary>Команда <code>gigachat</code> запускает старую версию</summary>

Проверьте, нет ли второй установки (например, через `pipx` или в системном Python): `pipx list`, `pip show gigachat-cli`. При разработке запускайте приложение через `uv run gigachat`.

</details>

## Лицензия

[MIT](https://github.com/THEChrismoth/GigaChat-Cli/blob/master/LICENSE.md)
