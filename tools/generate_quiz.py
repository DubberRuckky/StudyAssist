"""Quiz generation and evaluation tool grounded in retrieved notes."""

import json
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from auth.context import UserContext
from agent.dispatcher import register_tool
from models.brain import chat
from storage.db import record_quiz_score
from storage.vector_store import query_document_chunks


class QuizQuestion(BaseModel):
    """Schema for a single grounded quiz question."""
    id: int
    question: str
    options: List[str] = Field(default_factory=list)
    correct_option: str  # e.g., "A", "B", "C", "D"
    explanation: str
    source_citation: str = ""


class QuizSet(BaseModel):
    """Schema for a collection of generated quiz questions."""
    subject: str
    topic: str
    questions: List[QuizQuestion]


def _clean_json_text(text: str) -> str:
    """Strip markdown code blocks and extract JSON content."""
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)
        clean = clean.strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start != -1 and end != -1 and end > start:
        clean = clean[start:end + 1]
    return clean


def generate_quiz(
    subject: str,
    topic: str,
    user_context: UserContext,
    num_questions: int = 3,
    profile_name: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """Generate grounded multiple-choice questions from retrieved notes with one retry."""
    # Retrieve relevant notes for grounding
    excerpts = query_document_chunks(user_context, subject=subject, query_text=topic, n_results=4)
    if not excerpts:
        context_text = f"Subject: {subject}, Topic: {topic}. Generate standard fundamental questions for this subject."
        citation = f"{subject} general knowledge"
    else:
        context_text = "\n\n".join([f"Source: {e['filename']} p.{e['page']}: {e['text']}" for e in excerpts])
        citation = f"{excerpts[0]['filename']} p.{excerpts[0]['page']}"

    prompt_messages = [
        {
            "role": "system",
            "content": (
                "You are an academic test generator. Generate multiple-choice quiz questions GROUNDED in the provided study notes. "
                "Output ONLY a valid JSON object matching this schema:\n"
                "{\n"
                '  "subject": "...",\n'
                '  "topic": "...",\n'
                '  "questions": [\n'
                '    {\n'
                '      "id": 1,\n'
                '      "question": "...",\n'
                '      "options": ["A) ...", "B) ...", "C) ...", "D) ..."],\n'
                '      "correct_option": "A",\n'
                '      "explanation": "...",\n'
                '      "source_citation": "..."\n'
                "    }\n"
                "  ]\n"
                "}\n"
                "Do not include any commentary or markdown outside the JSON."
            ),
        },
        {
            "role": "user",
            "content": f"Study Notes:\n{context_text}\n\nGenerate {num_questions} questions for topic: '{topic}'.",
        },
    ]

    # Attempt generation with one retry on failure
    quiz_data: Optional[QuizSet] = None
    last_err = None

    for attempt in range(2):
        try:
            resp = chat(messages=prompt_messages, options={"profile": profile_name or "mock"}, user_context=user_context)
            raw = resp.get("content", "")
            cleaned = _clean_json_text(raw)
            parsed = json.loads(cleaned)
            quiz_data = QuizSet(**parsed)
            break
        except Exception as err:
            last_err = err
            prompt_messages.append({"role": "user", "content": f"JSON parse error: {err}. Please return valid JSON only."})

    if not quiz_data:
        # Fallback scripted quiz if offline or generation failed
        quiz_data = QuizSet(
            subject=subject,
            topic=topic,
            questions=[
                QuizQuestion(
                    id=1,
                    question=f"Which of the following best defines the primary mechanism of {topic}?",
                    options=[
                        f"A) The fundamental governing equation of {topic}",
                        "B) An unrelated random process",
                        "C) Static non-varying condition",
                        "D) Inverted inverse constant",
                    ],
                    correct_option="A",
                    explanation=f"Option A represents the foundational definition established in the {subject} study materials.",
                    source_citation=citation,
                )
            ],
        )

    # Format human-readable output
    lines = [f"=== Grounded Quiz: {quiz_data.subject} — {quiz_data.topic} ===\n"]
    for q in quiz_data.questions:
        lines.append(f"Question {q.id}: {q.question}")
        for opt in q.options:
            lines.append(f"  {opt}")
        lines.append(f"Citation: {q.source_citation or citation}")
        lines.append("")

    # Also store the questions JSON for subsequent grading
    quiz_json_path = user_context.resolve_safe_path(f"memory/quiz_latest_{subject}_{topic}.json")
    with open(quiz_json_path, "w", encoding="utf-8") as f:
        f.write(quiz_data.model_dump_json(indent=2))

    return "\n".join(lines).strip()


def grade_quiz_answers(
    subject: str,
    topic: str,
    student_answers: Dict[int, str],
    user_context: UserContext,
) -> Dict[str, Any]:
    """Grade submitted student answers against the latest generated quiz and update progress in SQLite."""
    quiz_json_path = user_context.resolve_safe_path(f"memory/quiz_latest_{subject}_{topic}.json")
    if not quiz_json_path.exists():
        return {"error": f"No active quiz found for {subject} - {topic}."}

    with open(quiz_json_path, "r", encoding="utf-8") as f:
        quiz_dict = json.load(f)

    questions = quiz_dict.get("questions", [])
    total = len(questions)
    correct_count = 0
    feedback = []

    for q in questions:
        qid = q["id"]
        correct = q["correct_option"].strip().upper()
        # Student answer might be "A" or "A) ..."
        raw_ans = student_answers.get(qid, "").strip().upper()
        clean_ans = raw_ans[0] if raw_ans else ""

        is_correct = (clean_ans == correct)
        if is_correct:
            correct_count += 1
            feedback.append(f"Q{qid}: Correct! ({q['explanation']})")
        else:
            feedback.append(f"Q{qid}: Incorrect. You answered '{raw_ans}', correct was '{correct}'. {q['explanation']}")

    # Record score in SQLite database
    record_quiz_score(
        context=user_context,
        subject=subject,
        topic=topic,
        score=float(correct_count),
        total=float(total),
        details={"feedback": feedback},
    )

    pct = round((correct_count / total * 100.0), 1) if total > 0 else 0.0
    return {
        "subject": subject,
        "topic": topic,
        "score": correct_count,
        "total": total,
        "percentage": pct,
        "feedback": feedback,
    }


# Register generate_quiz in dispatcher
register_tool(
    name="generate_quiz",
    func=generate_quiz,
    schema={
        "type": "function",
        "function": {
            "name": "generate_quiz",
            "description": "Generates grounded multiple choice quiz questions for a topic using retrieved notes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Subject name."},
                    "topic": {"type": "string", "description": "Specific topic to test."},
                    "num_questions": {"type": "integer", "description": "Number of questions (default 3)."},
                },
                "required": ["subject", "topic"],
            },
        },
    },
)
