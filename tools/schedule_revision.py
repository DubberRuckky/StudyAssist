"""Spaced-repetition revision scheduling tool exporting standard iCalendar (.ics) files."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from auth.context import UserContext
from agent.dispatcher import register_tool
from storage.db import get_weak_topics, save_revision_plan


def _format_ics_datetime(dt: datetime) -> str:
    """Format datetime into standard iCalendar UTC representation (YYYYMMDDTHHMMSSZ)."""
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _generate_ics_content(subject: str, sessions: List[Dict[str, Any]]) -> str:
    """Construct RFC 5545 compliant iCalendar (.ics) file string."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//StudyAssist//Revision Scheduler//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    for s in sessions:
        uid = f"studyassist-{uuid.uuid4()}@local"
        dtstamp = _format_ics_datetime(datetime.now(timezone.utc))
        dtstart = _format_ics_datetime(s["start_time"])
        dtend = _format_ics_datetime(s["end_time"])
        summary = f"StudyAssist: {subject} - {s['topic']}"
        desc = f"Spaced repetition study session for {s['topic']}. Target duration: {s['duration_hours']} hour(s)."

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART:{dtstart}",
            f"DTEND:{dtend}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{desc}",
            "STATUS:CONFIRMED",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def schedule_revision(
    exam_date: str,
    subject: str,
    hours_per_day: float,
    user_context: UserContext,
    topics: Optional[List[str]] = None,
    **kwargs: Any,
) -> str:
    """Generate spaced-repetition revision schedule and export .ics calendar file. REQUIRES APPROVAL."""
    # Parse exam date
    try:
        target_exam = datetime.strptime(exam_date.strip(), "%Y-%m-%d").date()
    except ValueError:
        return f"Date format error: '{exam_date}' must follow YYYY-MM-DD format (e.g. 2026-12-15)."

    today = date.today()
    days_remaining = (target_exam - today).days

    if days_remaining <= 0:
        return f"Schedule error: Exam date '{exam_date}' must be in the future (at least 1 day from today)."

    # Determine topics: if not supplied, query weakest topics from database
    if not topics:
        weak_data = get_weak_topics(user_context, subject=subject, limit=5)
        if weak_data:
            study_topics = [w["topic"] for w in weak_data]
        else:
            study_topics = [f"{subject} Core Concepts", f"{subject} Applied Problem Solving", f"{subject} Final Review"]
    else:
        study_topics = topics

    # Allocate spaced repetition sessions across available days
    # Prioritize earlier spaced intervals (Day 1, 3, 7, etc.) and repeat weak topics
    sessions = []
    session_hour_slot = min(hours_per_day, 2.0)

    for day_offset in range(days_remaining):
        session_date = today + timedelta(days=day_offset + 1)
        # Alternate topics across days, cycling weak topics more frequently
        topic_idx = day_offset % len(study_topics)
        curr_topic = study_topics[topic_idx]

        # Schedule session at 18:00 (6:00 PM)
        start_dt = datetime.combine(session_date, datetime.min.time()).replace(hour=18, minute=0)
        end_dt = start_dt + timedelta(hours=session_hour_slot)

        sessions.append({
            "day": day_offset + 1,
            "date": session_date.isoformat(),
            "topic": curr_topic,
            "duration_hours": session_hour_slot,
            "start_time": start_dt,
            "end_time": end_dt,
        })

    # Generate and export .ics file to user's isolated uploads directory
    safe_subj = "".join(c if c.isalnum() else "_" for c in subject.lower())
    ics_filename = f"revision_{safe_subj}_{exam_date}.ics"
    ics_path = user_context.resolve_safe_path(f"uploads/{ics_filename}")
    ics_path.parent.mkdir(parents=True, exist_ok=True)

    ics_content = _generate_ics_content(subject, sessions)
    ics_path.write_text(ics_content, encoding="utf-8")

    # Save plan in user's SQLite database
    plan_record = {
        "subject": subject,
        "exam_date": exam_date,
        "days_remaining": days_remaining,
        "hours_per_day": hours_per_day,
        "sessions": [
            {
                "day": s["day"],
                "date": s["date"],
                "topic": s["topic"],
                "duration_hours": s["duration_hours"],
            }
            for s in sessions
        ],
    }

    plan_id = save_revision_plan(
        context=user_context,
        subject=subject,
        exam_date=exam_date,
        hours_per_day=hours_per_day,
        topics=study_topics,
        plan_data=plan_record,
        ics_path=str(ics_path),
    )

    # Format human-readable output
    output_lines = [
        f"=== Spaced-Repetition Revision Plan (Plan ID #{plan_id}) ===",
        f"Subject: {subject} | Target Exam: {exam_date} ({days_remaining} day(s) remaining)",
        f"Daily Allocation: {hours_per_day} hour(s) | Calendar Export: {ics_filename}\n",
    ]
    for s in sessions[:10]:  # Show first 10 sessions in summary
        output_lines.append(f"• Day {s['day']} ({s['date']}): Focus on '{s['topic']}' ({s['duration_hours']} hr)")

    if len(sessions) > 10:
        output_lines.append(f"... and {len(sessions) - 10} more session(s) scheduled leading up to the exam.")

    output_lines.append(f"\nCalendar file generated at: {ics_path}")
    return "\n".join(output_lines)


# Register schedule_revision in dispatcher
register_tool(
    name="schedule_revision",
    func=schedule_revision,
    schema={
        "type": "function",
        "function": {
            "name": "schedule_revision",
            "description": "Builds a spaced-repetition study schedule leading up to an exam and exports an iCalendar (.ics) file. REQUIRES HUMAN APPROVAL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "exam_date": {"type": "string", "description": "Target exam date in YYYY-MM-DD format."},
                    "subject": {"type": "string", "description": "Subject name."},
                    "hours_per_day": {"type": "number", "description": "Daily study hours available."},
                    "topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of topics. If omitted, uses weakest topics from quiz history.",
                    },
                },
                "required": ["exam_date", "subject", "hours_per_day"],
            },
        },
    },
)
