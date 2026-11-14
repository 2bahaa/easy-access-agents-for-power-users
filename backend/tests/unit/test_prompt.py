from app.runtime.types import SkillContent
from app.skills.prompt import SKILLS_HEADER, compose_system_prompt


def skill(name: str, content: str) -> SkillContent:
    return SkillContent(slug=name.lower(), name=name, content_md=content)


def test_instructions_only() -> None:
    assert compose_system_prompt("  Be helpful.  ", []) == "Be helpful."


def test_skills_appended_in_order() -> None:
    prompt = compose_system_prompt("Be helpful.", [skill("A", "Do A."), skill("B", "Do B.\n")])
    assert prompt == f"Be helpful.\n\n{SKILLS_HEADER}\n\n### A\n\nDo A.\n\n### B\n\nDo B."


def test_skills_without_instructions_and_empty_skills_skipped() -> None:
    prompt = compose_system_prompt("", [skill("Empty", "   "), skill("A", "Do A.")])
    assert prompt == f"{SKILLS_HEADER}\n\n### A\n\nDo A."
    assert compose_system_prompt("", []) == ""
