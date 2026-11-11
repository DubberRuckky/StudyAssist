"""Jury debate tool exposing quick mode and 6-agent deliberative answers to the agent."""

from typing import Any, Dict, Optional
from auth.context import UserContext
from agent.dispatcher import register_tool
from agent.jury import execute_jury_debate


def run_jury(
    question: str,
    subject: str,
    user_context: UserContext,
    mode: str = "quick",
    profile_name: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """Run either Quick Mode (single agent) or Full 6-Agent Jury Debate for a study question."""
    debate_result = execute_jury_debate(
        question=question,
        subject=subject,
        user_context=user_context,
        mode=mode,
        profile_name=profile_name,
    )

    answer = debate_result.get("final_answer", "")
    citations = debate_result.get("citations", [])
    mode_used = debate_result.get("mode", "quick")

    header = f"=== StudyAssist Answer ({mode_used.title()} Mode) ===\n"
    footer = ""
    if citations:
        footer = f"\n\nSources Cited:\n" + "\n".join([f"• {c}" for c in citations])

    return f"{header}\n{answer}{footer}".strip()


# Register run_jury in dispatcher
register_tool(
    name="run_jury",
    func=run_jury,
    schema={
        "type": "function",
        "function": {
            "name": "run_jury",
            "description": "Answers a student's study question using either Quick Mode or a 6-agent deliberative jury.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The concept or problem to answer."},
                    "subject": {"type": "string", "description": "Subject name to search notes within."},
                    "mode": {
                        "type": "string",
                        "enum": ["quick", "jury"],
                        "description": "Mode of execution: 'quick' (single agent, default) or 'jury' (6 agents debate).",
                    },
                },
                "required": ["question", "subject"],
            },
        },
    },
)
