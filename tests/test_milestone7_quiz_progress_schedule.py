"""Unit tests for Milestone 7: Quiz generation, progress tracking, and revision scheduling (.ics)."""

from datetime import date, timedelta
import pytest

from auth.context import UserContext
from agent.dispatcher import dispatch_tool
from storage.db import get_revision_plans, get_weak_topics
from tools.generate_quiz import generate_quiz, grade_quiz_answers
from tools.schedule_revision import schedule_revision
from tools.track_progress import track_progress


@pytest.fixture
def m7_user(tmp_path):
    """Create a temporary user context for testing quiz and revision tools."""
    data_root = tmp_path / "data"
    return UserContext.create("test-m7-user", "Maya", data_root=data_root)


def test_generate_quiz_and_grading_flow(m7_user):
    """Verify quiz generation, question formatting, answer grading, and SQLite score recording."""
    # 1. Generate quiz
    quiz_output = generate_quiz(
        subject="Chemistry",
        topic="Thermodynamics",
        num_questions=1,
        user_context=m7_user,
    )
    assert "=== Grounded Quiz: Chemistry — Thermodynamics ===" in quiz_output
    assert "Question 1:" in quiz_output

    # 2. Grade student answers (Option A is correct in the fallback/generated question)
    grading_result = grade_quiz_answers(
        subject="Chemistry",
        topic="Thermodynamics",
        student_answers={1: "A"},
        user_context=m7_user,
    )
    assert grading_result["score"] == 1
    assert grading_result["percentage"] == 100.0

    # 3. Verify score passed to SQLite progress table
    weak = get_weak_topics(m7_user, subject="Chemistry")
    assert len(weak) == 1
    assert weak[0]["topic"] == "Thermodynamics"
    assert weak[0]["avg_score"] == 100.0


def test_track_progress_tool(m7_user):
    """Verify progress tracking tool logs new scores and returns ranked weak topics."""
    # Track two quiz sessions: one high score, one low score
    track_progress(m7_user, subject="Physics", topic="Optics", score=9.0, total=10.0)
    track_progress(m7_user, subject="Physics", topic="Quantum", score=2.0, total=10.0)

    report = track_progress(m7_user, subject="Physics")
    assert "Weak Topics Requiring Focus" in report
    # Quantum (20%) should be listed before Optics (90%)
    pos_quantum = report.find("Quantum")
    pos_optics = report.find("Optics")
    assert pos_quantum != -1 and pos_optics != -1
    assert pos_quantum < pos_optics


def test_schedule_revision_plan_and_ics_export(m7_user):
    """Verify revision schedule generation, iCalendar (.ics) export, and approval requirement."""
    # Target exam 10 days in the future
    future_date = (date.today() + timedelta(days=10)).isoformat()

    # 1. Test dispatch via approval gate: User declines
    result_declined, status_declined = dispatch_tool(
        tool_name="schedule_revision",
        tool_args={"exam_date": future_date, "subject": "Biology", "hours_per_day": 2.5},
        user_context=m7_user,
        approval_callback=lambda name, args: False,
    )
    assert result_declined == "User declined."
    assert status_declined == "rejected"

    # 2. Test dispatch via approval gate: User approves
    result_approved, status_approved = dispatch_tool(
        tool_name="schedule_revision",
        tool_args={"exam_date": future_date, "subject": "Biology", "hours_per_day": 2.5},
        user_context=m7_user,
        approval_callback=lambda name, args: True,
    )
    assert "=== Spaced-Repetition Revision Plan" in result_approved
    assert status_approved == "approved"

    # Verify plan stored in SQLite
    saved_plans = get_revision_plans(m7_user, subject="Biology")
    assert len(saved_plans) == 1
    assert saved_plans[0]["exam_date"] == future_date
    assert saved_plans[0]["hours_per_day"] == 2.5

    # Verify .ics file content
    ics_file = m7_user.resolve_safe_path(f"uploads/revision_biology_{future_date}.ics")
    assert ics_file.exists()
    ics_text = ics_file.read_text(encoding="utf-8")
    assert "BEGIN:VCALENDAR" in ics_text
    assert "BEGIN:VEVENT" in ics_text
    assert "SUMMARY:StudyAssist: Biology" in ics_text
    assert "END:VCALENDAR" in ics_text


def test_schedule_revision_past_date_error(m7_user):
    """Verify that scheduling revision for a past or invalid date returns a clean error."""
    past_date = (date.today() - timedelta(days=2)).isoformat()
    res = schedule_revision(
        exam_date=past_date,
        subject="History",
        hours_per_day=1.0,
        user_context=m7_user,
    )
    assert "must be in the future" in res
