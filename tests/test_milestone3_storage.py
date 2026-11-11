"""Unit tests for Milestone 3: UserContext storage layer and cross-user data isolation."""

import pytest
from auth.context import UserContext
from storage.db import (
    get_action_logs,
    get_revision_plans,
    get_weak_topics,
    init_user_db,
    is_subject_local_only,
    list_subjects,
    log_action,
    record_quiz_score,
    save_revision_plan,
    set_subject_local_only,
)
from storage.memory import (
    compute_learning_order,
    delete_subject_memory,
    list_user_memory_subjects,
    load_subject_memory,
    save_subject_memory,
    update_learning_order,
)
from storage.vector_store import (
    add_document_chunks,
    delete_subject_collection,
    query_document_chunks,
)


@pytest.fixture
def two_user_contexts(tmp_path):
    """Create two completely isolated UserContext instances for User A and User B."""
    data_root = tmp_path / "data"
    user_a = UserContext.create("user-uuid-aaaa", "Alice", data_root=data_root)
    user_b = UserContext.create("user-uuid-bbbb", "Bob", data_root=data_root)
    return user_a, user_b


def test_topological_learning_order_deterministic():
    """Verify that topological sorting orders prerequisite topics before advanced topics."""
    topics = [
        {"name": "Calculus", "prerequisites": ["Algebra", "Trigonometry"]},
        {"name": "Trigonometry", "prerequisites": ["Algebra"]},
        {"name": "Algebra", "prerequisites": []},
        {"name": "Differential Equations", "prerequisites": ["Calculus"]},
    ]
    order = compute_learning_order(topics)
    assert order == ["Algebra", "Trigonometry", "Calculus", "Differential Equations"]


def test_sqlite_progress_and_weak_topics_isolation(two_user_contexts):
    """Verify that quiz scores and weak topics are strictly isolated between User A and User B."""
    user_a, user_b = two_user_contexts

    # User A scores high on Kinematics, low on Electromagnetism
    record_quiz_score(user_a, "Physics", "Kinematics", score=9.0, total=10.0)
    record_quiz_score(user_a, "Physics", "Electromagnetism", score=2.0, total=10.0)

    # User B scores opposite: low on Kinematics, high on Electromagnetism
    record_quiz_score(user_b, "Physics", "Kinematics", score=3.0, total=10.0)
    record_quiz_score(user_b, "Physics", "Electromagnetism", score=10.0, total=10.0)

    # Check User A weak topics
    weak_a = get_weak_topics(user_a, subject="Physics")
    assert len(weak_a) == 2
    assert weak_a[0]["topic"] == "Electromagnetism"
    assert weak_a[0]["avg_score"] == 20.0
    assert weak_a[1]["topic"] == "Kinematics"
    assert weak_a[1]["avg_score"] == 90.0

    # Check User B weak topics (must not see User A's data)
    weak_b = get_weak_topics(user_b, subject="Physics")
    assert len(weak_b) == 2
    assert weak_b[0]["topic"] == "Kinematics"
    assert weak_b[0]["avg_score"] == 30.0
    assert weak_b[1]["topic"] == "Electromagnetism"
    assert weak_b[1]["avg_score"] == 100.0


def test_subject_local_only_toggle_isolation(two_user_contexts):
    """Verify that per-subject local-only brain toggles are isolated per user."""
    user_a, user_b = two_user_contexts

    # User A toggles Physics as local only
    set_subject_local_only(user_a, "Physics", True)
    # User B leaves Physics as remote/cloud allowed
    set_subject_local_only(user_b, "Physics", False)

    assert is_subject_local_only(user_a, "Physics") is True
    assert is_subject_local_only(user_b, "Physics") is False


def test_action_log_isolation(two_user_contexts):
    """Verify that audit logs recorded for User A are never visible to User B."""
    user_a, user_b = two_user_contexts

    log_action(
        context=user_a,
        profile_name="local_ollama",
        duration_sec=1.5,
        prompt_tokens=50,
        completion_tokens=25,
        tool_name="search_notes",
        tool_args={"query": "quantum mechanics"},
        tool_result="Found 2 excerpts",
        approval_status="auto",
    )

    logs_a = get_action_logs(user_a)
    assert len(logs_a) == 1
    assert logs_a[0]["tool_args"]["query"] == "quantum mechanics"

    # User B action logs must be completely empty
    logs_b = get_action_logs(user_b)
    assert len(logs_b) == 0


def test_memory_file_cross_user_isolation(two_user_contexts):
    """Verify that JSON memory files for the same subject name remain isolated between users."""
    user_a, user_b = two_user_contexts

    # Save User A memory
    mem_a = {
        "topics": [{"name": "Cells"}, {"name": "Genetics"}],
        "learning_order": ["Cells", "Genetics"],
    }
    save_subject_memory(user_a, "Biology", mem_a)

    # Save User B memory
    mem_b = {
        "topics": [{"name": "Ecology"}, {"name": "Evolution"}],
        "learning_order": ["Ecology", "Evolution"],
    }
    save_subject_memory(user_b, "Biology", mem_b)

    # Load and verify
    loaded_a = load_subject_memory(user_a, "Biology")
    assert loaded_a["learning_order"] == ["Cells", "Genetics"]

    loaded_b = load_subject_memory(user_b, "Biology")
    assert loaded_b["learning_order"] == ["Ecology", "Evolution"]

    # Student manual override on User A does not alter User B
    update_learning_order(user_a, "Biology", ["Genetics", "Cells"])
    assert load_subject_memory(user_a, "Biology")["learning_order"] == ["Genetics", "Cells"]
    assert load_subject_memory(user_b, "Biology")["learning_order"] == ["Ecology", "Evolution"]


def test_chromadb_vector_store_isolation(two_user_contexts):
    """Verify that ChromaDB queries by User A cannot retrieve documents indexed by User B."""
    user_a, user_b = two_user_contexts

    # User A indexes note in Chemistry
    chunks_a = [
        {
            "id": "doc_a_1",
            "text": "Avogadro's constant is 6.022e23 particles per mole.",
            "filename": "chem_notes_a.pdf",
            "page": 12,
            "topic": "Stoichiometry",
        }
    ]
    add_document_chunks(user_a, "Chemistry", chunks_a)

    # User B indexes note in Chemistry
    chunks_b = [
        {
            "id": "doc_b_1",
            "text": "Benzene has a planar hexagonal ring of carbon atoms.",
            "filename": "chem_notes_b.pdf",
            "page": 45,
            "topic": "Organic Chemistry",
        }
    ]
    add_document_chunks(user_b, "Chemistry", chunks_b)

    # User A searches notes: must only retrieve Avogadro's constant
    res_a = query_document_chunks(user_a, "Chemistry", "particles per mole", n_results=5)
    assert len(res_a) == 1
    assert "Avogadro" in res_a[0]["text"]
    assert res_a[0]["filename"] == "chem_notes_a.pdf"

    # User B searches notes: must only retrieve Benzene
    res_b = query_document_chunks(user_b, "Chemistry", "hexagonal ring", n_results=5)
    assert len(res_b) == 1
    assert "Benzene" in res_b[0]["text"]
    assert res_b[0]["filename"] == "chem_notes_b.pdf"


def test_identical_filenames_and_deletion_independence(two_user_contexts):
    """Verify that users can have files with identical names and deleting one user leaves the other intact."""
    user_a, user_b = two_user_contexts

    # Both users write to 'uploads/syllabus.pdf'
    file_a = user_a.resolve_safe_path("uploads/syllabus.pdf")
    file_b = user_b.resolve_safe_path("uploads/syllabus.pdf")

    file_a.write_text("User A's specific syllabus content", encoding="utf-8")
    file_b.write_text("User B's completely different syllabus content", encoding="utf-8")

    assert file_a.read_text(encoding="utf-8") == "User A's specific syllabus content"
    assert file_b.read_text(encoding="utf-8") == "User B's completely different syllabus content"

    # Purge User A
    user_a.purge_user_data()
    assert not user_a.base_dir.exists()

    # User B's folder and files must remain completely intact
    assert user_b.base_dir.exists()
    assert file_b.exists()
    assert file_b.read_text(encoding="utf-8") == "User B's completely different syllabus content"
