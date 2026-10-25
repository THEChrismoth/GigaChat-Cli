"""Работа с GigaChat: отправка запросов, история диалога и контекст файлов проекта."""

import os
import asyncio
import re
from typing import List, Dict, Optional, AsyncGenerator, Any, Tuple
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_gigachat.chat_models import GigaChat

from gigachat_cli.utils.config import Config


# Значения переменной окружения, отключающие проверку SSL
_FALSE_VALUES = {"0", "false", "no", "off"}

# Служебные директории, которые не индексируются
_IGNORED_DIRS = {'__pycache__', 'node_modules', 'venv', '.venv', '.git', '.vscode', '.idea'}

# Ограничение на количество файлов при обходе проекта
_MAX_PROJECT_FILES = 5000

# Расширения файлов, упоминание которых в запросе подгружает файл в контекст
_FILE_EXTENSIONS = (
    'py', 'js', 'ts', 'jsx', 'tsx', 'json', 'md', 'yaml', 'yml', 'toml', 'ini', 'cfg',
    'txt', 'html', 'css', 'xml', 'java', 'cpp', 'c', 'h', 'go', 'rs', 'sh',
)

# Упоминание файла в запросе: имя или относительный путь с известным расширением.
# Совпадения внутри URL и путей (после /, ., :) не учитываются
_FILE_REFERENCE_PATTERN = re.compile(
    r'(?<![\w./\\:-])((?:[\w.-]+[/\\])*[\w-][\w.-]*\.(?:' + '|'.join(_FILE_EXTENSIONS) + r'))\b',
    re.IGNORECASE,
)

_SSL_HINT = (
    "\n\nПохоже на ошибку проверки SSL-сертификата. Установите корневой сертификат "
    "Минцифры и укажите путь к нему в GIGACHAT_CA_BUNDLE_FILE, либо отключите проверку: "
    "GIGACHAT_SSL_VERIFY=0"
)


@dataclass
class StreamChunk:
    """Часть потокового ответа."""

    content: str                  # Текст части ответа
    is_final: bool = False        # Последняя часть ответа
    error: Optional[str] = None   # Текст ошибки (в последней части)


def _iter_project_files(project_path: str):
    """Обход файлов проекта без служебных директорий и скрытых файлов.

    Args:
        project_path: Корневая директория проекта

    Yields:
        Tuple[str, str]: (путь относительно проекта, полный путь); не более _MAX_PROJECT_FILES файлов
    """
    count = 0
    for root, dirs, files in os.walk(project_path):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in _IGNORED_DIRS)
        for file in sorted(files):
            if file.startswith('.'):
                continue
            file_path = os.path.join(root, file)
            yield os.path.relpath(file_path, project_path), file_path
            count += 1
            if count >= _MAX_PROJECT_FILES:
                return


def _normalize_path_key(path: str) -> str:
    """Приведение пути к ключу индекса файлов: прямые слеши, нижний регистр, без ./ в начале.

    Args:
        path: Путь к файлу

    Returns:
        str: Ключ для поиска в индексе
    """
    key = path.replace('\\', '/').lower()
    while key.startswith('./'):
        key = key[2:]
    return key


class GigaChatManager:
    """Клиент GigaChat (singleton): история диалога, выбор типа запроса и контекст файлов проекта."""

    _instance = None

    def __new__(cls):
        """Возврат единственного экземпляра менеджера."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Инициализация состояния при первом создании."""
        if not hasattr(self, '_initialized') or not self._initialized:
            self.conversation_history = []
            self.config = Config()
            self.project_context = {}
            self._file_index: Dict[str, str] = {}
            self._file_index_path: Optional[str] = None
            self._last_files_context = []
            self._giga: Optional[GigaChat] = None
            self._giga_key: Optional[Tuple] = None
            # Модель на время запуска (--model), без сохранения в конфигурацию
            self.model_override: Optional[str] = None
            self._initialized = True

    def _get_api_key(self) -> str:
        """Получение ключа API из переменной окружения GIGACHAT_API_KEY.

        Returns:
            str: Ключ API

        Raises:
            Exception: Переменная не задана
        """
        api_key = os.getenv("GIGACHAT_API_KEY")
        if not api_key:
            raise Exception("GIGACHAT_API_KEY не установен. Пожалуйста, установите переменную окружения.")
        return api_key

    @staticmethod
    def _get_ssl_settings() -> Dict[str, Any]:
        """Получение настроек SSL из переменных окружения.

        GIGACHAT_SSL_VERIFY=0/false/no/off отключает проверку сертификата,
        GIGACHAT_CA_BUNDLE_FILE задает путь к сертификату. Если переменные не заданы,
        параметры не передаются, и SDK GigaChat использует собственные настройки
        (GIGACHAT_VERIFY_SSL_CERTS и т.д.).

        Returns:
            Dict[str, Any]: Параметры verify_ssl_certs и ca_bundle_file для клиента GigaChat

        Raises:
            Exception: Файл из GIGACHAT_CA_BUNDLE_FILE не найден
        """
        settings = {}
        verify = os.getenv("GIGACHAT_SSL_VERIFY")
        if verify is not None and verify.strip():
            settings["verify_ssl_certs"] = verify.strip().lower() not in _FALSE_VALUES

        if settings.get("verify_ssl_certs") is False:
            # SDK сам читает GIGACHAT_CA_BUNDLE_FILE, и путь к сертификату перекрывает verify=False.
            # Пустая строка (не None - None SDK отбрасывает) отключает использование сертификата
            settings["ca_bundle_file"] = ""
            return settings

        ca_bundle = os.getenv("GIGACHAT_CA_BUNDLE_FILE")
        if ca_bundle and ca_bundle.strip():
            ca_bundle = ca_bundle.strip()
            if not os.path.isfile(ca_bundle):
                raise Exception(f"Файл сертификата из GIGACHAT_CA_BUNDLE_FILE не найден: {ca_bundle}")
            settings["ca_bundle_file"] = ca_bundle
        return settings

    def _get_giga_chat_instance(self) -> GigaChat:
        """Получение клиента GigaChat.

        Клиент создается заново только при смене модели, ключа или настроек SSL,
        чтобы не запрашивать токен доступа на каждое сообщение.

        Returns:
            GigaChat: Клиент для текущей модели
        """
        current_model = self.get_current_model()
        api_key = self._get_api_key()
        ssl_settings = self._get_ssl_settings()

        key = (current_model, api_key, tuple(sorted(ssl_settings.items())))
        if self._giga is None or self._giga_key != key:
            self._giga = GigaChat(
                credentials=api_key,
                model=current_model,
                scope="GIGACHAT_API_PERS",
                temperature=0.1,
                max_tokens=4000,
                timeout=60,
                **ssl_settings
            )
            self._giga_key = key
        return self._giga

    @staticmethod
    def _format_error(error: str) -> str:
        """Добавление к тексту ошибки подсказки по ее исправлению (для ошибок SSL).

        Args:
            error: Текст ошибки

        Returns:
            str: Текст ошибки с подсказкой, если она есть
        """
        if "CERTIFICATE_VERIFY_FAILED" in error or "SSLCertVerificationError" in error:
            return error + _SSL_HINT
        return error

    async def send_message_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history_prompt: Optional[str] = None
    ) -> AsyncGenerator[StreamChunk, None]:
        """Отправка сообщения с историей диалога и получение ответа по частям.

        Ошибки не выбрасываются, а возвращаются в последней части ответа (StreamChunk.error).
        Успешный обмен сохраняется в историю (не более 20 последних сообщений).

        Args:
            prompt: Запрос пользователя (может включать содержимое файлов)
            system_prompt: Системный промпт (опционально)
            history_prompt: Текст запроса для сохранения в историю
                (по умолчанию prompt; позволяет не хранить в истории содержимое файлов)

        Yields:
            StreamChunk: Части ответа; последняя - с is_final=True
        """
        try:
            giga = self._get_giga_chat_instance()

            messages = [SystemMessage(content=system_prompt or "Ты - полезный AI-ассистент для разработчиков.")]
            messages.extend(self.conversation_history)
            messages.append(HumanMessage(content=prompt))

            full_response = ""

            # Клиент GigaChat синхронный: каждая часть ответа читается в пуле потоков,
            # чтобы не блокировать цикл событий интерфейса
            loop = asyncio.get_running_loop()

            def sync_stream():
                """Синхронное чтение ответа с преобразованием ошибок в последнюю часть."""
                try:
                    for chunk in giga.stream(messages):
                        if hasattr(chunk, 'content') and chunk.content:
                            yield StreamChunk(content=chunk.content)
                    yield StreamChunk(content="", is_final=True)
                except Exception as e:
                    yield StreamChunk(content="", is_final=True, error=str(e))

            sync_gen = sync_stream()

            while True:
                chunk = await loop.run_in_executor(None, next, sync_gen, None)
                if chunk is None:
                    break

                if chunk.error:
                    raise Exception(f"Ошибка API: {chunk.error}")

                if chunk.content:
                    full_response += chunk.content

                yield chunk

                if chunk.is_final:
                    break

            if full_response:
                self.conversation_history.append(HumanMessage(content=history_prompt or prompt))
                self.conversation_history.append(AIMessage(content=full_response))

                if len(self.conversation_history) > 20:
                    self.conversation_history = self.conversation_history[-20:]

        except Exception as e:
            yield StreamChunk(content="", is_final=True, error=self._format_error(str(e)))

    def _build_file_index(self, project_path: str) -> Dict[str, str]:
        """Построение индекса файлов проекта.

        Args:
            project_path: Корневая директория проекта

        Returns:
            Dict[str, str]: Относительный путь и имя файла (в виде ключа индекса) -> полный путь
        """
        file_index = {}
        try:
            for relative_path, file_path in _iter_project_files(project_path):
                # При совпадении имен приоритет у первого найденного (менее вложенного) файла
                file_index.setdefault(_normalize_path_key(relative_path), file_path)
                file_index.setdefault(os.path.basename(relative_path).lower(), file_path)
        except OSError:
            return {}
        return file_index

    def _lookup_file(self, filename: str) -> Optional[str]:
        """Поиск файла в текущем индексе по относительному пути, затем по имени.

        Args:
            filename: Имя файла или относительный путь

        Returns:
            Optional[str]: Полный путь к существующему файлу или None
        """
        key = _normalize_path_key(filename)
        for candidate in (key, os.path.basename(key)):
            found_path = self._file_index.get(candidate)
            if found_path and os.path.isfile(found_path):
                return found_path
        return None

    def _find_file_in_project(self, filename: str, project_path: str) -> Optional[str]:
        """Поиск файла в проекте, включая поддиректории.

        Индекс перестраивается при смене директории проекта и при промахе
        (файл мог быть создан или перемещен после построения индекса).

        Args:
            filename: Имя файла или относительный путь
            project_path: Корневая директория проекта

        Returns:
            Optional[str]: Полный путь к файлу или None
        """
        project_path = os.path.abspath(project_path)

        if self._file_index_path != project_path:
            self._file_index = self._build_file_index(project_path)
            self._file_index_path = project_path
            return self._lookup_file(filename)

        found_path = self._lookup_file(filename)
        if found_path:
            return found_path

        self._file_index = self._build_file_index(project_path)
        return self._lookup_file(filename)

    async def load_file_content(self, file_path: str, max_size: int = 15000) -> Optional[str]:
        """Чтение текстового файла для передачи в контекст.

        Args:
            file_path: Полный путь к файлу
            max_size: Максимальный размер файла в байтах

        Returns:
            Optional[str]: Содержимое файла, None если файла нет, или сообщение в [скобках]
                для слишком большого, бинарного или нечитаемого файла
        """
        def read() -> Optional[str]:
            if not os.path.exists(file_path):
                return None

            file_size = os.path.getsize(file_path)
            if file_size > max_size:
                return f"[Файл слишком большой: {file_size} байт, лимит: {max_size} байт]"

            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()

        try:
            return await asyncio.to_thread(read)
        except UnicodeDecodeError:
            return "[Бинарный файл или неподдерживаемая кодировка]"
        except Exception as e:
            return f"[Ошибка чтения файла: {str(e)}]"

    async def load_multiple_files(self, file_names: List[str], project_path: Optional[str] = None) -> Dict[str, str]:
        """Поиск и чтение нескольких файлов проекта.

        Args:
            file_names: Имена файлов или относительные пути
            project_path: Корневая директория проекта (по умолчанию - текущая директория процесса)

        Returns:
            Dict[str, str]: Путь относительно проекта -> содержимое или сообщение в [скобках]
        """
        project_path = project_path or os.getcwd()
        files_content = {}

        for file_name in file_names:
            full_path = await asyncio.to_thread(self._find_file_in_project, file_name, project_path)

            if full_path:
                content = await self.load_file_content(full_path)
                relative_path = os.path.relpath(full_path, project_path)
                files_content[relative_path] = content
            else:
                files_content[file_name] = f"[Файл не найден в проекте: {file_name}]"

        return files_content

    def _extract_file_references(self, text: str) -> List[str]:
        """Поиск упоминаний файлов в тексте запроса.

        Args:
            text: Текст запроса

        Returns:
            List[str]: Уникальные упоминания в порядке появления
        """
        found_files = []
        for match in _FILE_REFERENCE_PATTERN.findall(text):
            if match not in found_files:
                found_files.append(match)
        return found_files

    async def get_contextual_answer_stream(self, prompt: str, project_path: Optional[str] = None) -> AsyncGenerator[StreamChunk, None]:
        """Ответ на запрос с содержимым упомянутых в нем файлов проекта.

        Если ни один файл не найден, запрос отправляется без контекста.
        В историю сохраняется исходный запрос, без содержимого файлов.

        Args:
            prompt: Запрос пользователя
            project_path: Корневая директория проекта (по умолчанию - текущая директория процесса)

        Yields:
            StreamChunk: Части ответа
        """
        project_path = project_path or os.getcwd()

        referenced_files = self._extract_file_references(prompt)

        system_message = "Ты - опытный разработчик. Тебе предоставлено содержимое файлов проекта."

        if referenced_files:
            files_content = await self.load_multiple_files(referenced_files, project_path)

            context_info = "Содержимое файлов проекта:\n\n"
            loaded_files = []

            # Сообщения в [скобках] (файл не найден, слишком большой и т.д.) в контекст не попадают
            for file_path, content in files_content.items():
                if content and not content.startswith('['):
                    context_info += f"--- {file_path} ---\n{content}\n\n"
                    loaded_files.append(file_path)

            if loaded_files:
                self._last_files_context = loaded_files
                full_prompt = f"{context_info}\n\nЗапрос пользователя: {prompt}"

                system_message = """Ты - опытный разработчик. Тебе предоставлено содержимое файлов проекта.
                Анализируй конкретный код из этих файлов и давай точные ответы с примерами.
                Цитируй конкретные строки кода из предоставленных файлов.
                Если предлагаешь изменения - покажи конкретный код ДО и ПОСЛЕ."""

                async for chunk in self.send_message_stream(full_prompt, system_message, history_prompt=prompt):
                    yield chunk
                return

        async for chunk in self.send_message_stream(prompt, system_message):
            yield chunk

    def _collect_project_context(self, project_path: str) -> Dict:
        """Сбор структуры проекта и начала ключевых файлов (синхронно, выполняется в пуле потоков).

        Args:
            project_path: Корневая директория проекта

        Returns:
            Dict: project_path, file_structure (список путей), key_files (путь -> начало содержимого),
                dependencies
        """
        context = {
            "project_path": project_path,
            "file_structure": [],
            "key_files": {},
            "dependencies": []
        }

        try:
            key_candidates = []
            for relative_path, file_path in _iter_project_files(project_path):
                context["file_structure"].append(relative_path)
                file_name = os.path.basename(relative_path)
                if self._is_key_file(file_name):
                    # Сначала конфигурационные файлы, затем менее вложенные
                    priority = 0 if file_name in self._KEY_FILE_NAMES else 1
                    key_candidates.append((priority, relative_path.count(os.sep), relative_path, file_path))

            # В запрос попадают только первые 5 ключевых файлов - читаем только их
            for _, _, relative_path, file_path in sorted(key_candidates)[:5]:
                try:
                    if os.path.getsize(file_path) >= 10000:
                        continue
                    with open(file_path, 'r', encoding='utf-8') as f:
                        context["key_files"][relative_path] = f.read(5000)
                except (OSError, UnicodeDecodeError):
                    context["key_files"][relative_path] = "[binary or unreadable file]"
        except OSError:
            pass

        return context

    async def load_project_context(self, project_path: Optional[str] = None) -> Dict:
        """Сбор структуры проекта и ключевых файлов без блокировки цикла событий.

        Args:
            project_path: Корневая директория проекта (по умолчанию - текущая директория процесса)

        Returns:
            Dict: Контекст проекта (см. _collect_project_context)
        """
        project_path = os.path.abspath(project_path or os.getcwd())
        return await asyncio.to_thread(self._collect_project_context, project_path)

    # Конфигурационные файлы: в контекст проекта попадают в первую очередь
    _KEY_FILE_NAMES = {
        'Dockerfile', 'docker-compose.yml', '.env.example', 'README.md',
        'config.py', 'settings.py', 'package.json', 'requirements.txt',
        'pyproject.toml', 'setup.py', 'Makefile', 'CMakeLists.txt'
    }

    def _is_key_file(self, filename: str) -> bool:
        """Проверка, является ли файл ключевым (исходный код или конфигурация).

        Args:
            filename: Имя файла

        Returns:
            bool: True для файлов с исходным кодом и конфигурационных файлов
        """
        key_extensions = {
            '.py', '.js', '.ts', '.jsx', '.tsx', '.json', '.yaml', '.yml',
            '.md', '.txt', '.html', '.css', '.xml', '.java', '.cpp', '.h'
        }

        ext = os.path.splitext(filename)[1].lower()
        return ext in key_extensions or filename in self._KEY_FILE_NAMES

    async def get_code_analysis_stream(self, prompt: str, project_path: Optional[str] = None) -> AsyncGenerator[StreamChunk, None]:
        """Анализ проекта: запрос со структурой проекта и началом ключевых файлов.

        Args:
            prompt: Запрос пользователя
            project_path: Корневая директория проекта (по умолчанию - текущая директория процесса)

        Yields:
            StreamChunk: Части ответа
        """
        context = await self.load_project_context(project_path)

        system_message = """Ты - опытный разработчик-ассистент. Анализируй код проекта и давай конкретные,
        практические советы. Фокусируйся на:
        1. Качестве кода и лучших практиках
        2. Возможных ошибках и уязвимостях
        3. Оптимизации производительности
        4. Архитектурных улучшениях

        Будь конкретен и приводи примеры исправлений."""

        file_structure = context.get("file_structure", [])
        key_files = context.get("key_files", {})

        context_info = f"Структура проекта ({len(file_structure)} файлов):\n"
        context_info += "\n".join(file_structure[:25])

        if len(file_structure) > 25:
            context_info += f"\n... и еще {len(file_structure) - 25} файлов"

        context_info += "\n\n"

        if key_files:
            context_info += "Ключевые файлы:\n"
            for file, content in key_files.items():
                context_info += f"\n--- {file} ---\n{content[:1000]}\n"

        full_prompt = f"{context_info}\n\nЗапрос: {prompt}"

        async for chunk in self.send_message_stream(full_prompt, system_message, history_prompt=prompt):
            yield chunk

    @staticmethod
    def _is_project_analysis_request(prompt: str) -> bool:
        """Проверка, просит ли запрос проанализировать весь проект.

        Args:
            prompt: Запрос пользователя

        Returns:
            bool: True, если в запросе есть и «проект», и «анализ»/«структура»/«обзор»
        """
        lower = prompt.lower()
        mentions_project = 'проект' in lower or 'project' in lower
        mentions_analysis = any(keyword in lower for keyword in ['анализ', 'структур', 'обзор', 'analy', 'structure', 'overview'])
        return mentions_project and mentions_analysis

    async def get_answer_stream(
        self,
        prompt: str,
        clear_history: bool = False,
        project_path: Optional[str] = None
    ) -> AsyncGenerator[StreamChunk, None]:
        """Ответ на сообщение пользователя с выбором типа запроса.

        Порядок выбора: объяснение или рефакторинг кода из запроса (```код```),
        запрос с упомянутыми файлами, анализ всего проекта, обычный вопрос.

        Args:
            prompt: Сообщение пользователя
            clear_history: Только очистить историю диалога, без запроса
            project_path: Директория проекта для поиска файлов и анализа

        Yields:
            StreamChunk: Части ответа
        """
        if clear_history:
            yield StreamChunk(content=self.clear_history(), is_final=True)
            return

        lower = prompt.lower()
        code_blocks = self._extract_code_blocks(prompt)

        if code_blocks:
            language = self._detect_language(prompt)
            if any(keyword in lower for keyword in ['объясни', 'explain', 'как работает']):
                async for chunk in self.explain_code_stream(code_blocks[0], language):
                    yield chunk
                return
            if any(keyword in lower for keyword in ['рефакторинг', 'refactor', 'улучши код']):
                async for chunk in self.refactor_suggestion_stream(code_blocks[0], language):
                    yield chunk
                return

        if self._extract_file_references(prompt):
            async for chunk in self.get_contextual_answer_stream(prompt, project_path):
                yield chunk
            return

        if self._is_project_analysis_request(prompt):
            async for chunk in self.get_code_analysis_stream(prompt, project_path):
                yield chunk
            return

        system_message = "Ты - полезный AI-ассистент для разработчиков."
        async for chunk in self.send_message_stream(prompt, system_message):
            yield chunk

    async def explain_code_stream(self, code: str, language: str = "python") -> AsyncGenerator[StreamChunk, None]:
        """Объяснение кода.

        Args:
            code: Код для объяснения
            language: Язык программирования

        Yields:
            StreamChunk: Части ответа
        """
        system_message = f"""Ты - преподаватель программирования. Объясни этот {language} код простым языком:
        1. Что делает этот код?
        2. Как он работает пошагово?
        3. Какие ключевые конструкции используются?
        4. Есть ли потенциальные проблемы?"""

        full_prompt = f"Код для объяснения:\n```{language}\n{code}\n```"

        async for chunk in self.send_message_stream(full_prompt, system_message):
            yield chunk

    async def refactor_suggestion_stream(self, code: str, language: str = "python") -> AsyncGenerator[StreamChunk, None]:
        """Предложения по рефакторингу кода.

        Args:
            code: Код для рефакторинга
            language: Язык программирования

        Yields:
            StreamChunk: Части ответа
        """
        system_message = f"""Ты - senior разработчик. Проанализируй этот {language} код и предложи улучшения:
        1. Улучшение читаемости
        2. Оптимизация производительности
        3. Следование best practices
        4. Устранение code smells

        Покажи конкретные примеры до/после."""

        full_prompt = f"Код для рефакторинга:\n```{language}\n{code}\n```"

        async for chunk in self.send_message_stream(full_prompt, system_message):
            yield chunk

    def _extract_code_blocks(self, text: str) -> List[str]:
        """Извлечение блоков кода, в том числе однострочных (```код```).

        Args:
            text: Текст запроса

        Returns:
            List[str]: Непустые блоки кода без обрамляющих пробелов
        """
        blocks = re.findall(r'```(?:\w+\n)?(.*?)```', text, re.DOTALL)
        return [block.strip() for block in blocks if block.strip()]

    def _detect_language(self, text: str) -> str:
        """Определение языка программирования по упоминаниям в тексте.

        Args:
            text: Текст запроса

        Returns:
            str: python, typescript или javascript (по умолчанию python)
        """
        lower = text.lower()
        if re.search(r'\bpython\b|```py(?:thon)?\b|\.py\b', lower):
            return 'python'
        if re.search(r'\btypescript\b|```ts\b|\.ts\b|\bts\b', lower):
            return 'typescript'
        if re.search(r'\bjavascript\b|```js\b|\.js\b|\bjs\b', lower):
            return 'javascript'
        return 'python'

    def clear_history(self) -> str:
        """Очистка истории диалога.

        Returns:
            str: Сообщение для пользователя
        """
        self.conversation_history.clear()
        self._last_files_context.clear()
        return "История диалога очищена"

    def get_current_model(self) -> str:
        """Получение модели для запросов: переопределенной на запуск или из настроек.

        Returns:
            str: Идентификатор модели
        """
        return self.model_override or self.config.get_model()

    def get_conversation_stats(self) -> Dict:
        """Получение статистики текущего диалога.

        Returns:
            Dict: Количество сообщений, текущая модель и файлы последнего запроса с контекстом
        """
        user_messages = sum(1 for msg in self.conversation_history if isinstance(msg, HumanMessage))
        ai_messages = sum(1 for msg in self.conversation_history if isinstance(msg, AIMessage))

        return {
            "total_messages": len(self.conversation_history),
            "user_messages": user_messages,
            "ai_messages": ai_messages,
            "current_model": self.get_current_model(),
            "last_files_context": self._last_files_context
        }


chat_manager = GigaChatManager()


# Функции модуля - обертки над общим экземпляром chat_manager

async def get_answer_stream(
    prompt: str,
    clear_history: bool = False,
    project_path: Optional[str] = None
) -> AsyncGenerator[StreamChunk, None]:
    """Ответ на сообщение пользователя (см. GigaChatManager.get_answer_stream).

    Args:
        prompt: Сообщение пользователя
        clear_history: Только очистить историю диалога, без запроса
        project_path: Директория проекта для поиска файлов и анализа

    Yields:
        StreamChunk: Части ответа
    """
    async for chunk in chat_manager.get_answer_stream(prompt, clear_history, project_path):
        yield chunk

def clear_chat_history() -> str:
    """Очистка истории диалога.

    Returns:
        str: Сообщение для пользователя
    """
    return chat_manager.clear_history()

def get_current_model() -> str:
    """Получение модели для запросов.

    Returns:
        str: Идентификатор модели
    """
    return chat_manager.get_current_model()

async def analyze_project_stream(prompt: str, project_path: str = None) -> AsyncGenerator[StreamChunk, None]:
    """Анализ проекта (см. GigaChatManager.get_code_analysis_stream).

    Args:
        prompt: Запрос пользователя
        project_path: Корневая директория проекта

    Yields:
        StreamChunk: Части ответа
    """
    async for chunk in chat_manager.get_code_analysis_stream(prompt, project_path):
        yield chunk

async def explain_code_stream(code: str, language: str = "python") -> AsyncGenerator[StreamChunk, None]:
    """Объяснение кода.

    Args:
        code: Код для объяснения
        language: Язык программирования

    Yields:
        StreamChunk: Части ответа
    """
    async for chunk in chat_manager.explain_code_stream(code, language):
        yield chunk

async def refactor_code_stream(code: str, language: str = "python") -> AsyncGenerator[StreamChunk, None]:
    """Предложения по рефакторингу кода.

    Args:
        code: Код для рефакторинга
        language: Язык программирования

    Yields:
        StreamChunk: Части ответа
    """
    async for chunk in chat_manager.refactor_suggestion_stream(code, language):
        yield chunk

async def get_contextual_answer_stream(prompt: str, project_path: str = None) -> AsyncGenerator[StreamChunk, None]:
    """Ответ с содержимым упомянутых файлов (см. GigaChatManager.get_contextual_answer_stream).

    Args:
        prompt: Запрос пользователя
        project_path: Корневая директория проекта

    Yields:
        StreamChunk: Части ответа
    """
    async for chunk in chat_manager.get_contextual_answer_stream(prompt, project_path):
        yield chunk

def get_conversation_stats() -> Dict:
    """Получение статистики текущего диалога.

    Returns:
        Dict: Количество сообщений, текущая модель и файлы последнего запроса с контекстом
    """
    return chat_manager.get_conversation_stats()
