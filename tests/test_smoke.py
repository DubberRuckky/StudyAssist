"""End-to-end smoke test validating the complete StudyAssist workflow with MockBrain."""

import json
from datetime import date, timedelta
from pathlib import Path
import pytest

from agent.dispatcher import dispatch_tool
from agent.jury import execute_jury_debate
from agent.orchestrator import run_agent
from auth.context import UserContext
from auth.service import login_account, register_account
from models.mock_brain import get_mock_brain
from storage.db import get_action_logs, get_revision_plans, get_weak_topics, init_user_db
from tools.generate_quiz import generate_quiz, grade_quiz_answers
from tools.ingest_material import ingest_material
from tools.schedule_revision import schedule_revision
from tools.search_notes import search_notes
from tools.track_progress import track_progress


@pytest.fixture
def smoke_env(tmp_path):
    """Set up clean user account and environment for end-to-end testing."""
    mock_brain = get_mock_brain()
    mock_brain.reset()

    db_path = tmp_path / "auth.db"
    data_root = tmp_path / "data"

    # Register user
    ok, msg, rec_key = register_account(
        username="smoke_student",
        password="StrongSmokePass123!",
        confirm_password="StrongSmokePass123!",
        db_path=db_path,
        data_root=data_root,
    )
    assert ok is True

    # Login user
    log_ok, log_msg, token, user_ctx = login_account(
        username="smoke_student",
        password="StrongSmokePass123!",
        db_path=db_path,
        data_root=data_root,
    )
    assert log_ok is True
    assert user_ctx is not None

    init_user_db(user_ctx)
    return user_ctx, mock_brain


def test_complete_end_to_end_smoke_flow(smoke_env, tmp_path):
    """Run full study workflow: Ingest -> Search -> Quiz -> Grade -> Schedule -> Jury Debate -> Audit Log."""
    user_ctx, mock_brain = smoke_env

    # 1. Prepare and Ingest study note
    note_file = tmp_path / "neuroscience.txt"
    note_file.write_text(
        "Action potentials are rapid electrical signals along the neuron axon. "
        "The resting membrane potential is typically -70 millivolts maintained by sodium-potassium pumps. "
        "Depolarization occurs when voltage-gated sodium channels open rapidly.",
        encoding="utf-8",
    )

    ingest_result = ingest_material(
        file_path=str(note_file),
        subject="Neuroscience",
        user_context=user_ctx,
        profile_name="mock",
    )
    assert "Successfully ingested" in ingest_result

    # 2. Search notes
    search_res = search_notes(
        query="resting membrane potential",
        subject="Neuroscience",
        user_context=user_ctx,
        n_results=2,
    )
    assert "neuroscience.txt" in search_res
    assert "-70 millivolts" in search_res

    # 3. Generate Quiz with MockBrain
    mock_brain.queue_reply({
        "content": json.dumps({
            "subject": "Neuroscience",
            "topic": "Membrane Potential",
            "questions": [
                {
                    "question": "What is the typical resting membrane potential of a neuron?",
                    "options": ["-70 mV", "+30 mV", "0 mV", "-90 mV"],
                    "correct_answer": "-70 mV",
                    "explanation": "Maintained by sodium-potassium pumps.",
                }
            ],
        }),
        "tool_calls": [],
    })

    quiz_output = generate_quiz(
        subject="Neuroscience",
        topic="Membrane Potential",
        user_context=user_ctx,
        profile_name="mock",
    )
    assert "Grounded Quiz: Neuroscience" in quiz_output
    assert "Question 1:" in quiz_output

    # 4. Grade quiz and verify progress tracking
    grade_res = grade_quiz_answers(
        subject="Neuroscience",
        topic="Membrane Potential",
        student_answers={1: "A"},
        user_context=user_ctx,
    )
    assert grade_res["score"] == 1
    assert grade_res["percentage"] == 100.0

    progress_report = track_progress(user_context=user_ctx)
    assert "Neuroscience" in progress_report

    # 5. Schedule revision through dispatcher approval gate
    exam_date = (date.today() + timedelta(days=7)).isoformat()
    disp_res, status = dispatch_tool(
        tool_name="schedule_revision",
        tool_args={"exam_date": exam_date, "subject": "Neuroscience", "hours_per_day": 1.5},
        user_context=user_ctx,
        approval_callback=lambda name, args: True,
    )
    assert status == "approved", f"Dispatch failed: {disp_res}"
    assert "Spaced-Repetition Revision Plan" in disp_res

    # Verify plan stored in SQLite
    plans = get_revision_plans(user_ctx, subject="Neuroscience")
    assert len(plans) == 1
    assert plans[0]["exam_date"] == exam_date

    # 6. Execute 6-agent deliberative jury debate
    mock_brain.queue_reply({"content": "Explaining action potentials intuitively."})
    mock_brain.queue_reply({"content": "Formal electrochemistry of ion currents."})
    mock_brain.queue_reply({"content": "Corner case: absolute refractory period."})
    mock_brain.queue_reply({"content": "Exam tip: remember threshold voltage -55mV."})
    mock_brain.queue_reply({"content": "Example: reflex arc motor neuron firing."})
    mock_brain.queue_reply({"content": "Fact-checking claims against lecture notes."})
    # 6 round 2 critiques
    for _ in range(6):
        mock_brain.queue_reply({"content": "Critique: answers are accurate."})
    # 1 synthesizer
    mock_brain.queue_reply({"content": "Synthesized Answer: Action potentials fire when threshold is reached."})

    debate = execute_jury_debate(
        question="How does a neuron generate an action potential?",
        subject="Neuroscience",
        user_context=user_ctx,
        mode="jury",
        profile_name="mock",
    )
    assert "final_answer" in debate
    assert len(debate["round1_answers"]) == 6
    assert len(debate["blind_critiques"]) == 6

    # 7. Verify audit action log
    logs = get_action_logs(user_ctx, limit=20)
    assert len(logs) >= 1
    logged_tools = [l["tool_name"] for l in logs]
    assert "schedule_revision" in logged_tools
