"""Локальное хранилище завершённых обменов и контекста модели."""

from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Iterator
from uuid import uuid4


MAX_SAVED_EXCHANGES = 60


class SessionStoreError(RuntimeError):
    """Локальное хранилище недоступно."""


@dataclass(frozen=True)
class SessionData:
    """Состояние диалога, пригодное для восстановления."""

    exchanges: tuple[str, ...]
    prompts: tuple[str, ...]
    model_history: tuple[tuple[str, str], ...]

    @classmethod
    def decode(cls, payload: str) -> "SessionData":
        """Прочитать JSON и проверить типы записей."""
        item = json.loads(payload)
        if not isinstance(item, dict):
            raise ValueError("Некорректный формат сессии.")
        exchanges = item.get("exchanges")
        prompts = item.get("prompts")
        history = item.get("model_history")
        if not (
            isinstance(exchanges, list) and all(isinstance(value, str) for value in exchanges)
            and isinstance(prompts, list) and all(isinstance(value, str) for value in prompts)
            and isinstance(history, list) and all(
                isinstance(row, list) and len(row) == 2
                and row[0] in ("user", "assistant") and isinstance(row[1], str)
                for row in history
            )
        ):
            raise ValueError("Некорректные записи в сессии.")
        return cls(tuple(exchanges[-MAX_SAVED_EXCHANGES:]), tuple(prompts[-100:]), tuple(map(tuple, history[-20:])))


@dataclass(frozen=True)
class SavedSession:
    """Идентификатор, ревизия и сохранённые данные диалога."""

    id: str
    revision: int
    data: SessionData


class SessionStore:
    """Хранить отдельные диалоги для стартовой директории проекта."""

    def __init__(self, path: Path, root: Path) -> None:
        """Привязать операции к базе и каноническому пути проекта."""
        self.path = path
        self._project = os.path.normcase(str(root.resolve()))

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Открыть транзакцию и закрыть базу после завершения операции."""
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
            with closing(sqlite3.connect(self.path, timeout=1)) as connection, connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id TEXT PRIMARY KEY,
                        project TEXT NOT NULL,
                        revision INTEGER NOT NULL,
                        updated INTEGER NOT NULL,
                        title TEXT NOT NULL,
                        payload TEXT NOT NULL
                    )
                """)
                yield connection
        except (OSError, sqlite3.Error) as error:
            raise SessionStoreError("Не удалось открыть или обновить хранилище диалогов.") from error

    def load(self, session_id: str | None = None) -> SavedSession | None:
        """Открыть указанный диалог или последний доступный диалог проекта."""
        with self._connection() as connection:
            if session_id is None:
                rows = connection.execute(
                    "SELECT id, revision, payload FROM sessions WHERE project = ? ORDER BY updated DESC LIMIT 20",
                    (self._project,),
                )
            else:
                rows = connection.execute(
                    "SELECT id, revision, payload FROM sessions WHERE project = ? AND id = ?",
                    (self._project, session_id),
                )
            for saved_id, revision, payload in rows:
                try:
                    return SavedSession(saved_id, revision, SessionData.decode(payload))
                except (TypeError, ValueError):
                    continue
        return None

    def recent(self) -> list[tuple[str, str]]:
        """Вернуть идентификаторы и заголовки последних диалогов проекта."""
        with self._connection() as connection:
            return connection.execute(
                "SELECT id, title FROM sessions WHERE project = ? ORDER BY updated DESC LIMIT 20",
                (self._project,),
            ).fetchall()

    def save(self, data: SessionData, previous: SavedSession | None) -> SavedSession:
        """Сохранить диалог, создав отдельную копию при конкурирующем обновлении."""
        payload = json.dumps(asdict(data), ensure_ascii=False)
        title = " ".join(data.prompts[0].split())[:80] if data.prompts else "Диалог"
        now = time.time_ns()
        with self._connection() as connection:
            if previous is not None:
                updated = connection.execute(
                    "UPDATE sessions SET payload = ?, revision = revision + 1, updated = ? "
                    "WHERE project = ? AND id = ? AND revision = ?",
                    (payload, now, self._project, previous.id, previous.revision),
                )
                if updated.rowcount:
                    return SavedSession(previous.id, previous.revision + 1, data)
            session_id = uuid4().hex[:12]
            connection.execute(
                "INSERT INTO sessions (id, project, revision, updated, title, payload) VALUES (?, ?, 1, ?, ?, ?)",
                (session_id, self._project, now, title, payload),
            )
            return SavedSession(session_id, 1, data)
