from pathlib import Path

import pytest

from app.config import BACKEND_DIR
from app.skills.loader import SkillFileError, load_skill_files, parse_skill_markdown

VALID = """---
slug: test-skill
name: Test skill
description: For tests
---

# Body

Some **markdown**.
"""


def test_parses_frontmatter_and_body() -> None:
    skill = parse_skill_markdown(VALID)
    assert skill.slug == "test-skill"
    assert skill.name == "Test skill"
    assert skill.description == "For tests"
    assert skill.content_md == "# Body\n\nSome **markdown**."


def test_handles_crlf_and_bom() -> None:
    skill = parse_skill_markdown("﻿" + VALID.replace("\n", "\r\n"))
    assert skill.slug == "test-skill"
    assert "\r" not in skill.content_md


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("# no frontmatter", "missing YAML frontmatter"),
        ("---\nslug: x\nname: X\n", "unterminated"),
        ("---\n- a\n- b\n---\nbody", "must be a mapping"),
        ("---\nslug: Bad Slug\nname: X\n---\nbody", "slug"),
        ("---\nslug: ok\n---\nbody", "name"),
    ],
)
def test_rejects_invalid_files(text: str, message: str) -> None:
    with pytest.raises(SkillFileError, match=message):
        parse_skill_markdown(text)


def test_load_skill_files(tmp_path: Path) -> None:
    (tmp_path / "b.md").write_text(VALID.replace("test-skill", "b-skill"), encoding="utf-8")
    (tmp_path / "a.md").write_text(VALID, encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("x", encoding="utf-8")
    assert [s.slug for s in load_skill_files(tmp_path)] == ["test-skill", "b-skill"]
    assert load_skill_files(tmp_path / "missing") == []


def test_builtin_skill_files_are_valid() -> None:
    assert load_skill_files(BACKEND_DIR / "skills"), "expected at least one built-in skill"
