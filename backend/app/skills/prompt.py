"""Compose the system prompt from the agent's instructions and its attached skills."""

from collections.abc import Sequence
from typing import Protocol


class SkillLike(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def content_md(self) -> str: ...


SKILLS_HEADER = (
    "## Skills\n\nThe following skills describe how you should work. Apply them whenever relevant."
)


def compose_system_prompt(instructions: str, skills: Sequence[SkillLike]) -> str:
    parts = [instructions.strip()] if instructions.strip() else []
    sections = [f"### {s.name}\n\n{s.content_md.strip()}" for s in skills if s.content_md.strip()]
    if sections:
        parts.append(SKILLS_HEADER + "\n\n" + "\n\n".join(sections))
    return "\n\n".join(parts)
