"""Built-in workflow templates (starting points; models/agents are adjusted by the user)."""

from typing import Any

MODEL = "qwen3:4b"


def _n(nid: str, ntype: str, x: float, y: float, label: str = "", **config: Any) -> dict[str, Any]:
    return {
        "id": nid,
        "type": ntype,
        "label": label,
        "config": config,
        "position": {"x": x, "y": y},
    }


TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "summarize-and-translate",
        "name": "Summarize, then translate",
        "description": "Two LLM steps in sequence: summarize a text, then translate the summary.",
        "spec": {
            "nodes": [
                _n(
                    "start",
                    "start",
                    0,
                    0,
                    "Start",
                    inputs=[
                        {"name": "text", "description": "Text to process"},
                        {"name": "language", "description": "Target language"},
                    ],
                ),
                _n(
                    "summary",
                    "llm",
                    260,
                    0,
                    "Summarize",
                    model=MODEL,
                    system="You write concise summaries.",
                    prompt="Summarize in 3 sentences:\n\n{{ input.text }}",
                ),
                _n(
                    "translation",
                    "llm",
                    520,
                    0,
                    "Translate",
                    model=MODEL,
                    prompt="Translate into {{ input.language }}:\n\n{{ summary }}",
                ),
                _n("end", "end", 780, 0, "Result", output="{{ translation }}"),
            ],
            "edges": [
                {"source": "start", "target": "summary"},
                {"source": "summary", "target": "translation"},
                {"source": "translation", "target": "end"},
            ],
        },
    },
    {
        "id": "triage-router",
        "name": "Triage and route",
        "description": "An LLM router classifies a request and sends it down the matching branch.",
        "spec": {
            "nodes": [
                _n("start", "start", 0, 100, "Start", inputs=[{"name": "request"}]),
                _n(
                    "triage",
                    "router",
                    260,
                    100,
                    "Triage",
                    model=MODEL,
                    routes=["question", "complaint"],
                    input="{{ input.request }}",
                    instructions="Is this a question or a complaint?",
                ),
                _n(
                    "answer",
                    "llm",
                    520,
                    0,
                    "Answer",
                    model=MODEL,
                    prompt="Answer helpfully:\n\n{{ input.request }}",
                ),
                _n(
                    "apology",
                    "llm",
                    520,
                    200,
                    "De-escalate",
                    model=MODEL,
                    prompt="Write an empathetic reply to this complaint:\n\n{{ input.request }}",
                ),
                _n("end", "end", 780, 100, "Reply", output="{{ answer }}{{ apology }}"),
            ],
            "edges": [
                {"source": "start", "target": "triage"},
                {"source": "triage", "target": "answer", "source_handle": "question"},
                {"source": "triage", "target": "apology", "source_handle": "complaint"},
                {"source": "answer", "target": "end"},
                {"source": "apology", "target": "end"},
            ],
        },
    },
    {
        "id": "parallel-review-with-approval",
        "name": "Parallel drafts with human approval",
        "description": "Two drafts in parallel, merged, then a human approves before publishing.",
        "spec": {
            "nodes": [
                _n("start", "start", 0, 100, "Start", inputs=[{"name": "topic"}]),
                _n("fanout", "parallel", 220, 100, "In parallel"),
                _n(
                    "formal",
                    "llm",
                    440,
                    0,
                    "Formal draft",
                    model=MODEL,
                    prompt="Write a formal paragraph about {{ input.topic }}.",
                ),
                _n(
                    "casual",
                    "llm",
                    440,
                    200,
                    "Casual draft",
                    model=MODEL,
                    prompt="Write a casual paragraph about {{ input.topic }}.",
                ),
                _n(
                    "merge",
                    "llm",
                    660,
                    100,
                    "Merge",
                    model=MODEL,
                    prompt="Combine the best of both:\n\nA) {{ formal }}\n\nB) {{ casual }}",
                ),
                _n(
                    "review",
                    "approval",
                    880,
                    100,
                    "Human review",
                    message="Publish this text?\n\n{{ merge }}",
                ),
                _n("published", "end", 1100, 0, "Published", output="{{ merge }}"),
                _n("rejected", "end", 1100, 200, "Rejected", output="Not published: {{ review }}"),
            ],
            "edges": [
                {"source": "start", "target": "fanout"},
                {"source": "fanout", "target": "formal"},
                {"source": "fanout", "target": "casual"},
                {"source": "formal", "target": "merge"},
                {"source": "casual", "target": "merge"},
                {"source": "merge", "target": "review"},
                {"source": "review", "target": "published", "source_handle": "approved"},
                {"source": "review", "target": "rejected", "source_handle": "rejected"},
            ],
        },
    },
]
