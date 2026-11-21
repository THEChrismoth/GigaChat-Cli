"""Распознавание запросов на ревью и ограничений на запись."""

import re


_REVIEW_REQUEST = re.compile(
    r"^\s*(?:(?:а|пожалуйста|давай(?:те)?|можешь|можете|можно|сделай|сделаем|сделать|"
    r"проведи|провести|сделайте|проведите|код|please|do|a|can you|could you)[,\s]+)*"
    r"(?:(?:код-)?ревью(?=\s|[:,]|[.!?]?\s*$)|code\s+review\b|"
    r"review\b(?=\s*$|\s+(?:(?:my|this|the)\s+)?(?:project|code|files?|without)\b))",
    re.IGNORECASE,
)
_FILE_OR_CODE = r"(?:файл(?:а|е|ом|ы|ов|у|ах|ами)?|код(?:а|е|ом|у)?)\b"
_READ_ONLY_REQUEST = re.compile(
    r"\b(?:без\s+(?:внесения\s+)?(?:изменени\w*|правок|редактирования)"
    rf"(?:\s+(?:в\s+)?{_FILE_OR_CODE}|(?=\s*[.!?]?\s*$))|"
    rf"не\s+(?:меняй|изменяй|трогай|редактируй)\s+(?:никакие\s+)?{_FILE_OR_CODE}|"
    r"read[- ]only\b|without\s+(?:changing|modifying|editing)\s+(?:the\s+)?files?\b)",
    re.IGNORECASE,
)


def is_review_request(prompt: str) -> bool:
    """Распознать прямую просьбу о ревью."""
    return bool(_REVIEW_REQUEST.match(prompt))


def is_read_only_request(prompt: str) -> bool:
    """Оставить ревью и запросы без записи в маршруте обычного ответа."""
    return is_review_request(prompt) or bool(_READ_ONLY_REQUEST.search(prompt))
