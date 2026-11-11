"""Isolated SQLite database manager for user progress, revision plans, and action logs."""

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from auth.context import UserContext


def get_user_db_connection(context: UserContext) -> sqlite3.Connection:
    """Connect to the user's isolated study database."""
    conn = sqlite3.connect(str(context.db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_user_db(context: UserContext) -> None:
    """Initialize the schema for progress, plans, subjects, and audit action logs."""
    conn = get_user_db_connection(context)
    with conn:
        # Table for tracked subject configurations and local-only toggles
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                local_only INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            )
            """
        )
        # Table for quiz question scores and topic mastery
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                topic TEXT NOT NULL,
                score REAL NOT NULL,
                total REAL NOT NULL,
                percentage REAL NOT NULL,
                details TEXT DEFAULT '{}',
                created_at REAL NOT NULL
            )
            """
        )
        # Table for revision plans
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                exam_date TEXT NOT NULL,
                hours_per_day REAL NOT NULL,
                topics TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                ics_path TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                created_at REAL NOT NULL
            )
            """
        )
        # Table for audit action log
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS action_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                profile_name TEXT NOT NULL,
                duration_sec REAL NOT NULL,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                tool_name TEXT NOT NULL,
                tool_args TEXT NOT NULL,
                tool_result TEXT NOT NULL,
                approval_status TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        # Table for tracking daily LLM brain calls
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_call_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_date TEXT UNIQUE NOT NULL,
                call_count INTEGER DEFAULT 1
            )
            """
        )
    conn.close()


def set_subject_local_only(context: UserContext, subject: str, local_only: bool) -> None:
    """Set the local-only brain execution toggle for a specific subject."""
    init_user_db(context)
    conn = get_user_db_connection(context)
    now = time.time()
    val = 1 if local_only else 0
    with conn:
        conn.execute(
            """
            INSERT INTO subjects (name, local_only, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET local_only = excluded.local_only
            """,
            (subject.strip(), val, now),
        )
    conn.close()


def is_subject_local_only(context: UserContext, subject: str) -> bool:
    """Check whether a subject is restricted to local-only brain processing."""
    init_user_db(context)
    conn = get_user_db_connection(context)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT local_only FROM subjects WHERE name = ?", (subject.strip(),))
        row = cursor.fetchone()
        if row:
            return bool(row["local_only"])
        return False
    finally:
        conn.close()


def list_subjects(context: UserContext) -> List[Dict[str, Any]]:
    """List all subjects recorded for this user."""
    init_user_db(context)
    conn = get_user_db_connection(context)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name, description, local_only, created_at FROM subjects ORDER BY name ASC")
        return [
            {
                "name": row["name"],
                "description": row["description"],
                "local_only": bool(row["local_only"]),
                "created_at": row["created_at"],
            }
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def record_quiz_score(
    context: UserContext,
    subject: str,
    topic: str,
    score: float,
    total: float,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a student quiz evaluation score for progress tracking."""
    init_user_db(context)
    percentage = (score / total * 100.0) if total > 0 else 0.0
    now = time.time()
    details_str = json.dumps(details or {})

    conn = get_user_db_connection(context)
    with conn:
        conn.execute(
            """
            INSERT INTO progress (subject, topic, score, total, percentage, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (subject.strip(), topic.strip(), score, total, percentage, details_str, now),
        )
    conn.close()


def get_weak_topics(
    context: UserContext,
    subject: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Query topics with the lowest average mastery percentage for targeted revision."""
    init_user_db(context)
    conn = get_user_db_connection(context)
    try:
        cursor = conn.cursor()
        if subject:
            cursor.execute(
                """
                SELECT topic, AVG(percentage) as avg_score, COUNT(*) as attempts
                FROM progress
                WHERE subject = ?
                GROUP BY topic
                ORDER BY avg_score ASC, attempts ASC
                LIMIT ?
                """,
                (subject.strip(), limit),
            )
        else:
            cursor.execute(
                """
                SELECT subject, topic, AVG(percentage) as avg_score, COUNT(*) as attempts
                FROM progress
                GROUP BY subject, topic
                ORDER BY avg_score ASC, attempts ASC
                LIMIT ?
                """,
                (limit,),
            )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def save_revision_plan(
    context: UserContext,
    subject: str,
    exam_date: str,
    hours_per_day: float,
    topics: List[str],
    plan_data: Dict[str, Any],
    ics_path: Optional[str] = None,
) -> int:
    """Save an approved spaced-repetition revision schedule in the user database."""
    init_user_db(context)
    now = time.time()
    topics_json = json.dumps(topics)
    plan_json = json.dumps(plan_data)

    conn = get_user_db_connection(context)
    with conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO plans (subject, exam_date, hours_per_day, topics, plan_json, ics_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (subject.strip(), exam_date, hours_per_day, topics_json, plan_json, ics_path or "", now),
        )
        plan_id = cursor.lastrowid
    conn.close()
    return plan_id


def get_revision_plans(
    context: UserContext,
    subject: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve saved revision plans for a user."""
    init_user_db(context)
    conn = get_user_db_connection(context)
    try:
        cursor = conn.cursor()
        if subject:
            cursor.execute(
                "SELECT * FROM plans WHERE subject = ? ORDER BY created_at DESC",
                (subject.strip(),),
            )
        else:
            cursor.execute("SELECT * FROM plans ORDER BY created_at DESC")
        rows = cursor.fetchall()
        results = []
        for row in rows:
            results.append({
                "id": row["id"],
                "subject": row["subject"],
                "exam_date": row["exam_date"],
                "hours_per_day": row["hours_per_day"],
                "topics": json.loads(row["topics"]),
                "plan": json.loads(row["plan_json"]),
                "ics_path": row["ics_path"],
                "status": row["status"],
                "created_at": row["created_at"],
            })
        return results
    finally:
        conn.close()


def log_action(
    context: UserContext,
    profile_name: str,
    duration_sec: float,
    prompt_tokens: int,
    completion_tokens: int,
    tool_name: str,
    tool_args: Dict[str, Any],
    tool_result: str,
    approval_status: str,
) -> None:
    """Record an executed action, tool call, duration, and approval status to the audit log."""
    init_user_db(context)
    now = time.time()
    args_json = json.dumps(tool_args)
    # Truncate overly long tool results for safety, never log API keys
    safe_result = tool_result[:500] if tool_result else ""

    conn = get_user_db_connection(context)
    with conn:
        conn.execute(
            """
            INSERT INTO action_log (
                user_id, profile_name, duration_sec, prompt_tokens, completion_tokens,
                tool_name, tool_args, tool_result, approval_status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                context.user_id,
                profile_name,
                duration_sec,
                prompt_tokens,
                completion_tokens,
                tool_name,
                args_json,
                safe_result,
                approval_status,
                now,
            ),
        )
    conn.close()


def get_action_logs(context: UserContext, limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve audit action logs for the user."""
    init_user_db(context)
    conn = get_user_db_connection(context)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM action_log ORDER BY created_at DESC LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "profile_name": row["profile_name"],
                "duration_sec": row["duration_sec"],
                "prompt_tokens": row["prompt_tokens"],
                "completion_tokens": row["completion_tokens"],
                "tool_name": row["tool_name"],
                "tool_args": json.loads(row["tool_args"]),
                "tool_result": row["tool_result"],
                "approval_status": row["approval_status"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def record_brain_call(context: UserContext, profile_name: str, call_date: Optional[str] = None) -> int:
    """Record an LLM call for today and return total calls made today."""
    init_user_db(context)
    if not call_date:
        from datetime import date
        call_date = date.today().isoformat()
    conn = get_user_db_connection(context)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO daily_call_usage (call_date, call_count)
                VALUES (?, 1)
                ON CONFLICT(call_date) DO UPDATE SET call_count = call_count + 1
                """,
                (call_date,),
            )
            cursor = conn.cursor()
            cursor.execute("SELECT call_count FROM daily_call_usage WHERE call_date = ?", (call_date,))
            row = cursor.fetchone()
            return row["call_count"] if row else 1
    finally:
        conn.close()


def get_daily_call_count(context: UserContext, for_date: Optional[str] = None) -> int:
    """Get the number of brain calls made by this user on a specific date (defaults to today)."""
    init_user_db(context)
    if not for_date:
        from datetime import date
        for_date = date.today().isoformat()
    conn = get_user_db_connection(context)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT call_count FROM daily_call_usage WHERE call_date = ?", (for_date,))
        row = cursor.fetchone()
        return row["call_count"] if row else 0
    finally:
        conn.close()

