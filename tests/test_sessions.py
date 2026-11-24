from gigachat_cli.core.sessions import SessionData, SessionStore


def test_session_history_is_partitioned_by_project(tmp_path):
    db = tmp_path / "data" / "sessions.sqlite3"
    root = tmp_path / "repo"
    data = SessionData(("Привет\n\nОтвет",), ("Привет",), (("user", "Привет"), ("assistant", "Ответ")))
    saved = SessionStore(db, root).save(data, None)

    reopened = SessionStore(db, root)
    assert reopened.load() == saved
    assert reopened.load(saved.id) == saved
    assert reopened.recent() == [(saved.id, "Привет")]
    other = SessionStore(db, tmp_path / "other")
    assert other.load() is None
    assert other.load(saved.id) is None


def test_overlapping_updates_keep_both_dialogs(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3", tmp_path)
    start = store.save(SessionData(("Начало",), ("Вопрос",), ()), None)
    left = store.save(SessionData(("Начало", "Первый"), ("Вопрос",), ()), start)
    right = store.save(SessionData(("Начало", "Второй"), ("Вопрос",), ()), start)

    assert left.id == start.id
    assert right.id != start.id
    assert store.load(left.id) == left
    assert store.load(right.id) == right
    assert store.load() == right
