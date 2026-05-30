from __future__ import annotations

import re
from typing import Any

from app.modules.creative_generation.sensitive_terms_catalog import DEFAULT_SENSITIVE_TERMS


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def find_sensitive_terms(text: Any) -> list[str]:
    return [match["term"] for match in find_sensitive_term_matches(text)]


def find_sensitive_term_matches(text: Any) -> list[dict[str, Any]]:
    value = clean_text(text)
    if not value:
        return []

    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in get_sensitive_term_rules():
        term = clean_text(rule.get("term"))
        if not term:
            continue
        if not rule_matches(rule, value):
            continue
        normalized = rule.get("normalized_term") or term.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        matches.append(rule)
    return matches


def sanitize_marketplace_text(text: Any) -> tuple[str, list[str]]:
    value = clean_text(text)
    matches = find_sensitive_term_matches(value)
    sanitized = value
    for rule in sorted(matches, key=lambda item: len(clean_text(item.get("term"))), reverse=True):
        term = clean_text(rule.get("term"))
        replacement = clean_text(rule.get("replacement"))
        sanitized = replace_rule_match(rule, sanitized, replacement)
    sanitized = re.sub(r"\s{2,}", " ", sanitized)
    sanitized = re.sub(r"\s+([,.;:])", r"\1", sanitized)
    return sanitized.strip(" -_/|,.;:"), [match["term"] for match in matches]


def get_sensitive_term_rules() -> list[dict[str, Any]]:
    try:
        from app.core.database import list_enabled_sensitive_terms

        rules = list_enabled_sensitive_terms()
        if rules:
            return rules
    except Exception:
        pass
    return fallback_sensitive_terms()


def fallback_sensitive_terms() -> list[dict[str, Any]]:
    return [
        {
            "term": item["term"],
            "normalized_term": clean_text(item["term"]).lower(),
            "language": item.get("language", "mixed"),
            "category": item.get("category", "general"),
            "severity": item.get("severity", "block"),
            "match_type": item.get("match_type", "contains"),
            "replacement": item.get("replacement", ""),
            "enabled": True,
            "source": item.get("source", "system"),
            "notes": item.get("notes"),
        }
        for item in DEFAULT_SENSITIVE_TERMS
    ]


def rule_matches(rule: dict[str, Any], value: str) -> bool:
    term = clean_text(rule.get("term"))
    match_type = clean_text(rule.get("match_type")) or "contains"
    if match_type == "regex":
        try:
            return bool(re.search(term, value, flags=re.IGNORECASE))
        except re.error:
            return False
    if match_type == "word":
        return bool(re.search(rf"\b{re.escape(term)}\b", value, flags=re.IGNORECASE))
    return term.lower() in value.lower()


def replace_rule_match(rule: dict[str, Any], value: str, replacement: str) -> str:
    term = clean_text(rule.get("term"))
    match_type = clean_text(rule.get("match_type")) or "contains"
    if match_type == "regex":
        try:
            return re.sub(term, replacement, value, flags=re.IGNORECASE)
        except re.error:
            return value
    if match_type == "word":
        return re.sub(rf"\b{re.escape(term)}\b", replacement, value, flags=re.IGNORECASE)
    return re.sub(re.escape(term), replacement, value, flags=re.IGNORECASE)
