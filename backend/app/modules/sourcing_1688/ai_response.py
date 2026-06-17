from __future__ import annotations

import json
from typing import Any


def parse_ai_response_json(response: Any) -> dict[str, Any]:
    text = extract_ai_response_text(response)
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end < start:
            raise ValueError(f"AI response is not valid JSON: {cleaned[:500]}")
        parsed = json.loads(cleaned[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("AI response JSON must be an object")
    return parsed


def extract_ai_response_text(response: Any) -> str:
    if response is None:
        raise ValueError("AI response is empty")
    if isinstance(response, str):
        return response
    if isinstance(response, bytes):
        return response.decode("utf-8", errors="replace")
    if isinstance(response, dict):
        return extract_text_from_mapping(response)

    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        return output_text

    for method_name in ("model_dump", "to_dict", "dict"):
        method = getattr(response, method_name, None)
        if not callable(method):
            continue
        try:
            dumped = method()
        except Exception:
            continue
        if isinstance(dumped, dict):
            return extract_text_from_mapping(dumped)

    choices = getattr(response, "choices", None)
    choice_text = extract_text_from_choices(choices)
    if choice_text:
        return choice_text

    output = getattr(response, "output", None)
    output_text = extract_text_from_output(output)
    if output_text:
        return output_text

    raise ValueError(f"AI response did not contain text: {str(response)[:500]}")


def extract_text_from_mapping(value: dict[str, Any]) -> str:
    output_text = value.get("output_text")
    if isinstance(output_text, str):
        return output_text

    choice_text = extract_text_from_choices(value.get("choices"))
    if choice_text:
        return choice_text

    output_text = extract_text_from_output(value.get("output"))
    if output_text:
        return output_text

    fallback = find_first_text(value, {"text", "output_text", "content"})
    if fallback:
        return fallback
    raise ValueError(f"AI response did not contain text: {json.dumps(value, ensure_ascii=False)[:500]}")


def extract_text_from_choices(choices: Any) -> str:
    if not isinstance(choices, list):
        return ""
    chunks: list[str] = []
    for choice in choices:
        message = get_value(choice, "message")
        content = get_value(message, "content") if message is not None else get_value(choice, "content")
        text = extract_text_from_content(content)
        if text:
            chunks.append(text)
            continue
        direct_text = get_value(choice, "text")
        if isinstance(direct_text, str):
            chunks.append(direct_text)
    return "\n".join(chunks).strip()


def extract_text_from_output(output: Any) -> str:
    if not isinstance(output, list):
        return ""
    chunks: list[str] = []
    for item in output:
        content = get_value(item, "content")
        text = extract_text_from_content(content)
        if text:
            chunks.append(text)
            continue
        direct_text = get_value(item, "text") or get_value(item, "output_text")
        if isinstance(direct_text, str):
            chunks.append(direct_text)
    return "\n".join(chunks).strip()


def extract_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [extract_text_from_content(item) for item in content]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(content, dict):
        for key in ("text", "output_text", "content"):
            text = extract_text_from_content(content.get(key))
            if text:
                return text
    if content is not None:
        for key in ("text", "output_text", "content"):
            value = getattr(content, key, None)
            text = extract_text_from_content(value)
            if text:
                return text
    return ""


def find_first_text(value: Any, keys: set[str]) -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys:
                text = extract_text_from_content(item)
                if text:
                    return text
        for item in value.values():
            text = find_first_text(item, keys)
            if text:
                return text
    if isinstance(value, list):
        for item in value:
            text = find_first_text(item, keys)
            if text:
                return text
    return ""


def get_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    if value is not None:
        return getattr(value, key, None)
    return None


def contains_cjk(value: Any) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in str(value or ""))
