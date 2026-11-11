"""Progress tracking tool recording evaluations and returning weakest topics for targeted study."""

from typing import Any, Dict, List, Optional
from auth.context import UserContext
from agent.dispatcher import register_tool
from storage.db import get_weak_topics, record_quiz_score


def track_progress(
    user_context: UserContext,
    subject: Optional[str] = None,
    topic: Optional[str] = None,
    score: Optional[float] = None,
    total: Optional[float] = None,
    limit: int = 5,
    **kwargs: Any,
) -> str:
    """Record scores and query weakest study topics from SQLite."""
    # If a score is submitted, record it first
    if score is not None and total is not None and topic and subject:
        record_quiz_score(
            context=user_context,
            subject=subject,
            topic=topic,
            score=score,
            total=total,
            details=kwargs.get("details"),
        )

    # Retrieve weakest topics
    weak_topics = get_weak_topics(context=user_context, subject=subject, limit=limit)

    if not weak_topics:
        return (
            f"No quiz history recorded yet{' for ' + subject if subject else ''}. "
            "Take a quiz with 'generate_quiz' to begin tracking mastery."
        )

    lines = [f"=== Weak Topics Requiring Focus ({subject or 'All Subjects'}) ==="]
    for idx, item in enumerate(weak_topics, start=1):
        subj_label = f"[{item['subject']}] " if "subject" in item else ""
        avg = round(item["avg_score"], 1)
        attempts = item["attempts"]
        lines.append(f"{idx}. {subj_label}{item['topic']}: {avg}% mastery ({attempts} attempt(s))")

    lines.append("\nRecommendation: Prioritize revision on topics below 70% before moving forward.")
    return "\n".join(lines)


# Register track_progress in dispatcher
register_tool(
    name="track_progress",
    func=track_progress,
    schema={
        "type": "function",
        "function": {
            "name": "track_progress",
            "description": "Records quiz scores into SQLite and returns the weakest study topics requiring revision.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Subject filter (optional)."},
                    "topic": {"type": "string", "description": "Topic name if recording score (optional)."},
                    "score": {"type": "number", "description": "Quiz points earned (optional)."},
                    "total": {"type": "number", "description": "Total quiz points possible (optional)."},
                    "limit": {"type": "integer", "description": "Maximum number of weak topics to return (default 5)."},
                },
            },
        },
    },
)
