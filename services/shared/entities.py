from __future__ import annotations

import re


EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
MONEY_RE = re.compile(r"\b\d+[\.,]?\d*\s?(?:DKK|EUR|USD)\b", re.IGNORECASE)
CPR_RE = re.compile(r"\b\d{6}-?\d{4}\b")


def extract_entities(text: str) -> list[tuple[str, str]]:
    entities: list[tuple[str, str]] = []

    for match in EMAIL_RE.findall(text):
        entities.append(("email", match))
    for match in DATE_RE.findall(text):
        entities.append(("date", match))
    for match in MONEY_RE.findall(text):
        entities.append(("money", match))
    for match in CPR_RE.findall(text):
        entities.append(("cpr", match))

    return entities
