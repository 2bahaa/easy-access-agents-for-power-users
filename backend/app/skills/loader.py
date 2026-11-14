"""Parse skill Markdown files: YAML frontmatter (slug, name, description) + Markdown body."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.schemas.skills import SkillWrite


class SkillFileError(ValueError):
    pass


def parse_skill_markdown(text: str, source: str = "<string>") -> SkillWrite:
    text = text.replace("\r\n", "\n").lstrip("﻿")
    if not text.startswith("---\n"):
        raise SkillFileError(f"{source}: missing YAML frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise SkillFileError(f"{source}: unterminated YAML frontmatter")

    try:
        meta = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as e:
        raise SkillFileError(f"{source}: invalid YAML frontmatter: {e}") from e
    if not isinstance(meta, dict):
        raise SkillFileError(f"{source}: frontmatter must be a mapping")

    body = text[end + len("\n---") :].strip()
    try:
        return SkillWrite(
            slug=meta.get("slug", ""),
            name=meta.get("name", ""),
            description=meta.get("description", ""),
            content_md=body,
        )
    except ValidationError as e:
        raise SkillFileError(f"{source}: {e}") from e


def load_skill_files(directory: Path) -> list[SkillWrite]:
    if not directory.is_dir():
        return []
    return [
        parse_skill_markdown(p.read_text(encoding="utf-8"), source=p.name)
        for p in sorted(directory.glob("*.md"))
    ]
