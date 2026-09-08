import os
import asyncio
import aiofiles
import re
from typing import List, Dict, Optional, AsyncGenerator, Union, Any
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_gigachat.chat_models import GigaChat

from gigachat_cli.utils.config import Config


@dataclass
class StreamChunk:
    """Чанк потокового ответа"""
    content: str
    is_final: bool = False
    error: Optional[str] = None


class GigaChatManager:
    """Менеджер для работы с GigaChat API"""
    
    _instance = None
    
    def __new__(cls):
        """Реализация singleton паттерна"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Инициализация менеджера"""
        if not hasattr(self, '_initialized') or not self._initialized:
            self.conversation_history = []
            self.config = Config()
            self.project_context = {}
            self._file_cache = {}
            self._file_index = {}
            self._last_files_context = []
            self._last_user_messages = []
            self._initialized = True
    
    def _get_api_key(self) -> str:
        """Получение API ключа из переменных окружения"""
        api_key = os.getenv("GIGACHAT_API_KEY")
        if not api_key:
            raise Exception("GIGACHAT_API_KEY не установен. Пожалуйста, установите переменную окружения.")
        return api_key
    
    def _get_giga_chat_instance(self) -> GigaChat:
        """Создание экземпляра GigaChat с текущей моделью из конфига"""
        current_model = self.config.get_model()
        
        verify_ssl = os.getenv("GIGACHAT_SSL_VERIFY", "1") not in ("0", "false", "no")
        return GigaChat(
            credentials=self._get_api_key(),
            verify_ssl_certs=verify_ssl,
            model=current_model,
            scope="GIGACHAT_API_PERS",
            temperature=0.1,
            max_tokens=4000,
            timeout=60
        )
    
    async def send_message_stream(self, prompt: str, system_prompt: Optional[str] = None) -> AsyncGenerator[StreamChunk, None]:
        """
        Потоковая отправка сообщения
        
        Args:
            prompt: Запрос пользователя
            system_prompt: Системный промпт (опционально)
            
        Yields:
            StreamChunk: Чанки потокового ответа
        """
        try:
            giga = self._get_giga_chat_instance()
            
            # Сохранение сообщения пользователя для контекста
            self._last_user_messages.append(prompt)
            if len(self._last_user_messages) > 5:
                self._last_user_messages = self._last_user_messages[-5:]
            
            # Подготовка сообщений с полной историей диалога
            messages = []
            
            # Добавление системного промпта с контекстом
            enhanced_system_prompt = self._enhance_system_prompt(system_prompt)
            if enhanced_system_prompt:
                messages.append(SystemMessage(content=enhanced_system_prompt))
                
            # Добавление всей истории диалога
            messages.extend(self.conversation_history)
            
            # Добавление текущего запроса
            messages.append(HumanMessage(content=prompt))
            
            full_response = ""
            
            # Запуск потокового запроса в отдельном потоке
            loop = asyncio.get_event_loop()
            
            def sync_stream():
                """Синхронная потоковая обработка"""
                try:
                    stream = giga.stream(messages)
                    for chunk in stream:
                        if hasattr(chunk, 'content') and chunk.content:
                            yield StreamChunk(content=chunk.content)
                    yield StreamChunk(content="", is_final=True)
                except Exception as e:
                    yield StreamChunk(content="", is_final=True, error=str(e))
            
            # Создание синхронного генератора
            sync_gen = sync_stream()
            
            # Обработка чанков из синхронного генератора
            while True:
                try:
                    # Получение чанка в отдельном потоке
                    chunk = await loop.run_in_executor(None, lambda: next(sync_gen))
                    
                    if chunk.error:
                        raise Exception(f"Ошибка API: {chunk.error}")
                    
                    if chunk.content:
                        full_response += chunk.content
                    
                    yield chunk
                    
                    if chunk.is_final:
                        break
                        
                except StopIteration:
                    break
            
            # Сохранение в историю диалога
            if full_response:
                self.conversation_history.append(HumanMessage(content=prompt))
                self.conversation_history.append(AIMessage(content=full_response))
                
                # Ограничение размера истории
                if len(self.conversation_history) > 20:
                    self.conversation_history = self.conversation_history[-20:]
                    
        except Exception as e:
            yield StreamChunk(content="", is_final=True, error=str(e))
    
    def _enhance_system_prompt(self, system_prompt: Optional[str] = None) -> str:
        """Добавление контекста предыдущих сообщений в системный промпт"""
        base_prompt = system_prompt or "Ты - полезный AI-ассистент для разработчиков."
        
        # Добавление информации о последних сообщениях пользователя
        if len(self._last_user_messages) > 1:
            previous_messages = self._last_user_messages[:-1]
            context_info = f"Предыдущие запросы пользователя: {'; '.join(previous_messages[-3:])}"
            return f"{base_prompt} {context_info}. Учитывай этот контекст при ответе."
        
        return base_prompt

    def _build_file_index(self, project_path: str = None) -> Dict[str, str]:
        """Построение индекса всех файлов в проекте для быстрого поиска"""
        if not project_path:
            project_path = os.getcwd()
        
        file_index = {}
        
        try:
            for root, dirs, files in os.walk(project_path):
                # Игнорирование служебных директорий
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in [
                    '__pycache__', 'node_modules', 'venv', '.git', '.vscode', '.idea'
                ]]
                
                for file in files:
                    if file.startswith('.'):
                        continue
                    
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, project_path)
                    
                    # Сохранение полного пути и относительного пути
                    file_index[file] = file_path
                    file_index[relative_path] = file_path
                    file_index[file.lower()] = file_path
            
            return file_index
            
        except Exception as e:
            print(f"Ошибка построения индекса файлов: {e}")
            return {}
    
    def _find_file_in_project(self, filename: str, project_path: str = None) -> Optional[str]:
        """Поиск полного пути к файлу в проекте включая поддиректории"""
        if not project_path:
            project_path = os.getcwd()
        
        # Построение индекса если еще не построен
        if not hasattr(self, '_file_index') or not self._file_index:
            self._file_index = self._build_file_index(project_path)
        
        # Поиск по разным вариантам
        search_patterns = [
            filename,
            filename.lower(),
            os.path.basename(filename),
            os.path.basename(filename).lower(),
        ]
        
        for pattern in search_patterns:
            if pattern in self._file_index:
                found_path = self._file_index[pattern]
                if os.path.exists(found_path):
                    return found_path
        
        # Рекурсивный поиск если не нашли в индексе
        try:
            for root, dirs, files in os.walk(project_path):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                for file in files:
                    if file.lower() == filename.lower() or file == filename:
                        return os.path.join(root, file)
                    
                    if filename.lower() in file.lower():
                        return os.path.join(root, file)
        except:
            pass
        
        return None
   
    async def load_file_content(self, file_path: str, max_size: int = 15000) -> Optional[str]:
        """Загрузка содержимого файла"""
        try:
            if not os.path.exists(file_path):
                return None
            
            file_size = os.path.getsize(file_path)
            if file_size > max_size:
                return f"[Файл слишком большой: {file_size} байт, лимит: {max_size} байт]"
            
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                content = await f.read()
                return content
                
        except UnicodeDecodeError:
            return "[Бинарный файл или неподдерживаемая кодировка]"
        except Exception as e:
            return f"[Ошибка чтения файла: {str(e)}]"
    
    async def load_multiple_files(self, file_names: List[str], project_path: str = None) -> Dict[str, str]:
        """Загрузка содержимого нескольких файлов по их именам"""
        files_content = {}
        
        for file_name in file_names:
            full_path = self._find_file_in_project(file_name, project_path)
            
            if full_path and os.path.exists(full_path):
                content = await self.load_file_content(full_path)
                relative_path = os.path.relpath(full_path, project_path or os.getcwd())
                files_content[relative_path] = content
            else:
                files_content[file_name] = f"[Файл не найден в проекте: {file_name}]"
        
        return files_content
    
    def _extract_file_references(self, text: str) -> List[str]:
        """Извлечение упоминаний файлов из текста запроса"""
        patterns = [
            r'(\w+\.py)', r'(\w+\.js)', r'(\w+\.ts)', r'(\w+\.json)', r'(\w+\.md)', r'(\w+\.yaml)', r'(\w+\.yml)',
            r'(\w+\.txt)', r'(\w+\.html)', r'(\w+\.css)', r'(\w+\.xml)', r'(\w+\.java)', r'(\w+\.cpp)', r'(\w+\.h)',
            r'файл[а-я]*\s+["\']?([^"\'\s]+)["\']?',
            r'file\s+["\']?([^"\'\s]+)["\']?',
            r'([a-zA-Z_][a-zA-Z0-9_]*\.[a-z]+)',
        ]
        
        found_files = set()
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if match and not match.startswith(('.', '/', '\\')):
                    found_files.add(match)
        
        quoted_patterns = [
            r'["\']([^"\']+\.[a-z]+)["\']',
            r'\(([^)]+\.[a-z]+)\)',
            r'\[([^]]+\.[a-z]+)\]',
        ]
        
        for pattern in quoted_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if match and not match.startswith(('.', '/', '\\')):
                    found_files.add(match)
        
        return list(found_files)
    
    async def get_contextual_answer_stream(self, prompt: str, project_path: str = None) -> AsyncGenerator[StreamChunk, None]:
        """Потоковая версия с контекстом файлов"""
        if not project_path:
            project_path = os.getcwd()
        
        referenced_files = self._extract_file_references(prompt)
        
        system_message = "Ты - опытный разработчик. Тебе предоставлено содержимое файлов проекта."
        
        if referenced_files:
            files_content = await self.load_multiple_files(referenced_files, project_path)
            
            context_info = "Содержимое файлов проекта:\n\n"
            files_found = False
            
            for file_path, content in files_content.items():
                if not content.startswith('['):
                    context_info += f"--- {file_path} ---\n{content}\n\n"
                    files_found = True
            
            if files_found:
                full_prompt = f"{context_info}\n\nЗапрос пользователя: {prompt}"
                
                system_message = """Ты - опытный разработчик. Тебе предоставлено содержимое файлов проекта. 
                Анализируй конкретный код из этих файлов и давай точные ответы с примерами.
                Цитируй конкретные строки кода из предоставленных файлов.
                Если предлагаешь изменения - покажи конкретный код ДО и ПОСЛЕ."""
                
                async for chunk in self.send_message_stream(full_prompt, system_message):
                    yield chunk
                return
        
        async for chunk in self.send_message_stream(prompt, system_message):
            yield chunk
    
    async def load_project_context(self, project_path: str = None) -> Dict:
        """Загрузка контекста проекта"""
        if not project_path:
            project_path = os.getcwd()
        
        context = {
            "project_path": project_path,
            "file_structure": [],
            "key_files": {},
            "dependencies": []
        }
        
        try:
            self._file_index = self._build_file_index(project_path)
            
            for root, dirs, files in os.walk(project_path):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in [
                    '__pycache__', 'node_modules', 'venv', '.git'
                ]]
                
                for file in files:
                    if file.startswith('.'):
                        continue
                        
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, project_path)
                    
                    context["file_structure"].append(relative_path)
                    
                    if self._is_key_file(file) and os.path.getsize(file_path) < 10000:
                        try:
                            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                                content = await f.read()
                                context["key_files"][relative_path] = content[:5000]
                        except:
                            context["key_files"][relative_path] = "[binary or unreadable file]"
            
            return context
            
        except Exception as e:
            print(f"Ошибка загрузки контекста проекта: {e}")
            return context
    
    def _is_key_file(self, filename: str) -> bool:
        """Определение является ли файл ключевым для проекта"""
        key_extensions = {
            '.py', '.js', '.ts', '.jsx', '.tsx', '.json', '.yaml', '.yml', 
            '.md', '.txt', '.html', '.css', '.xml', '.java', '.cpp', '.h'
        }
        key_files = {
            'Dockerfile', 'docker-compose.yml', '.env.example', 'README.md', 
            'config.py', 'settings.py', 'package.json', 'requirements.txt',
            'pyproject.toml', 'setup.py', 'Makefile', 'CMakeLists.txt'
        }
        
        ext = os.path.splitext(filename)[1].lower()
        return ext in key_extensions or filename in key_files
    
    async def get_code_analysis_stream(self, prompt: str, project_path: str = None) -> AsyncGenerator[StreamChunk, None]:
        """Потоковая версия анализа кода"""
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
            key_files_items = list(key_files.items())[:5]
            for file, content in key_files_items:
                context_info += f"\n--- {file} ---\n{content[:1000]}\n"
        
        full_prompt = f"{context_info}\n\nЗапрос: {prompt}"
        
        async for chunk in self.send_message_stream(full_prompt, system_message):
            yield chunk

    async def get_answer_stream(self, prompt: str, clear_history: bool = False) -> AsyncGenerator[StreamChunk, None]:
        """Потоковая версия основного метода"""
        if clear_history:
            self.conversation_history.clear()
            self._last_files_context.clear()
            self._last_user_messages.clear()
            yield StreamChunk(content="История диалога очищена", is_final=True)
            return
        
        # Автоматическое определение типа запроса
        if any(keyword in prompt.lower() for keyword in ['анализ', 'проект', 'project', 'структур']):
            async for chunk in self.get_code_analysis_stream(prompt):
                yield chunk
            return
        
        elif any(keyword in prompt.lower() for keyword in ['объясни', 'explain', 'как работает']):
            code_blocks = self._extract_code_blocks(prompt)
            if code_blocks:
                async for chunk in self.explain_code_stream(code_blocks[0], self._detect_language(prompt)):
                    yield chunk
                return
        
        elif any(keyword in prompt.lower() for keyword in ['рефакторинг', 'refactor', 'улучши код']):
            code_blocks = self._extract_code_blocks(prompt)
            if code_blocks:
                async for chunk in self.refactor_suggestion_stream(code_blocks[0], self._detect_language(prompt)):
                    yield chunk
                return
        
        # Использование контекстного ответа для запросов с упоминанием файлов
        elif self._extract_file_references(prompt):
            async for chunk in self.get_contextual_answer_stream(prompt):
                yield chunk
            return
        
        # Стандартный запрос с полной историей диалога
        system_message = "Ты - полезный AI-ассистент для разработчиков."
        async for chunk in self.send_message_stream(prompt, system_message):
            yield chunk

    async def explain_code_stream(self, code: str, language: str = "python") -> AsyncGenerator[StreamChunk, None]:
        """Потоковое объяснение кода"""
        system_message = f"""Ты - преподаватель программирования. Объясни этот {language} код простым языком:
        1. Что делает этот код?
        2. Как он работает пошагово?
        3. Какие ключевые конструкции используются?
        4. Есть ли потенциальные проблемы?"""
        
        full_prompt = f"Код для объяснения:\n```{language}\n{code}\n```"
        
        async for chunk in self.send_message_stream(full_prompt, system_message):
            yield chunk
    
    async def refactor_suggestion_stream(self, code: str, language: str = "python") -> AsyncGenerator[StreamChunk, None]:
        """Потоковые предложения по рефакторингу кода"""
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
        """Извлечение блоков кода из текста"""
        code_blocks = re.findall(r'```(?:\w+)?\n(.*?)\n```', text, re.DOTALL)
        return code_blocks

    def _detect_language(self, text: str) -> str:
        """Определение языка программирования из текста"""
        if 'python' in text.lower() or '.py' in text:
            return 'python'
        elif 'javascript' in text.lower() or 'js' in text:
            return 'javascript'
        elif 'typescript' in text.lower() or 'ts' in text:
            return 'typescript'
        else:
            return 'python'
    
    def clear_history(self) -> str:
        """Очистка истории диалога"""
        self.conversation_history.clear()
        self._last_files_context.clear()
        self._last_user_messages.clear()
        return "История диалога очищена"
    
    def get_current_model(self) -> str:
        """Получение текущей модели"""
        return self.config.get_model()
    
    def get_conversation_stats(self) -> Dict:
        """Получение статистики текущей сессии"""
        user_messages = sum(1 for msg in self.conversation_history if isinstance(msg, HumanMessage))
        ai_messages = sum(1 for msg in self.conversation_history if isinstance(msg, AIMessage))
        
        return {
            "total_messages": len(self.conversation_history),
            "user_messages": user_messages,
            "ai_messages": ai_messages,
            "current_model": self.get_current_model(),
            "last_files_context": self._last_files_context
        }


# Создание глобального инстанса
chat_manager = GigaChatManager()


# Функции для обратной совместимости
async def get_answer_stream(prompt: str, clear_history: bool = False) -> AsyncGenerator[StreamChunk, None]:
    """Потоковая версия получения ответа"""
    async for chunk in chat_manager.get_answer_stream(prompt, clear_history):
        yield chunk

def clear_chat_history() -> str:
    """Очистка истории чата"""
    return chat_manager.clear_history()

def get_current_model() -> str:
    """Получение текущей модели"""
    return chat_manager.get_current_model()

# Потоковые версии функций
async def analyze_project_stream(prompt: str, project_path: str = None) -> AsyncGenerator[StreamChunk, None]:
    """Потоковая версия анализа проекта"""
    async for chunk in chat_manager.get_code_analysis_stream(prompt, project_path):
        yield chunk

async def explain_code_stream(code: str, language: str = "python") -> AsyncGenerator[StreamChunk, None]:
    """Потоковая версия объяснения кода"""
    async for chunk in chat_manager.explain_code_stream(code, language):
        yield chunk

async def refactor_code_stream(code: str, language: str = "python") -> AsyncGenerator[StreamChunk, None]:
    """Потоковая версия рефакторинга"""
    async for chunk in chat_manager.refactor_suggestion_stream(code, language):
        yield chunk

async def get_contextual_answer_stream(prompt: str, project_path: str = None) -> AsyncGenerator[StreamChunk, None]:
    """Потоковая версия контекстного ответа"""
    async for chunk in chat_manager.get_contextual_answer_stream(prompt, project_path):
        yield chunk

def get_conversation_stats() -> Dict:
    """Получение статистики диалога"""
    return chat_manager.get_conversation_stats()
