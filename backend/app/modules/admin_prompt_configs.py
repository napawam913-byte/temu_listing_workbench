from __future__ import annotations

from typing import Any

from app.modules.prompt_templates import (
    list_prompt_templates,
    restore_prompt_template_default,
    upsert_prompt_template,
)


def list_admin_prompt_configs() -> list[dict[str, Any]]:
    return list_prompt_templates()


def update_admin_prompt_config(template_id: str, content: str, *, updated_by: str | None = None) -> dict[str, Any]:
    return upsert_prompt_template(template_id, content, updated_by=updated_by)


def restore_admin_prompt_config(template_id: str, *, updated_by: str | None = None) -> dict[str, Any]:
    return restore_prompt_template_default(template_id, updated_by=updated_by)
