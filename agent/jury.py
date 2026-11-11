"""Six-agent role-based jury debate, blind peer critique, and weighted synthesis engine."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from typing import Any, Dict, List, Optional, Tuple

from auth.context import UserContext
from config.loader import load_providers_config, load_settings_config
from models.brain import chat
from storage.vector_store import query_document_chunks

logger = logging.getLogger(__name__)

# Specialized role prompts for the six agents
ROLE_PROMPTS = {
    "explainer": (
        "Role: Intuitive Explainer.\n"
        "Your mission is clarity. Use relatable analogies, straightforward language, and intuitive mental models "
        "to make this concept immediately digestible for a student. Ground your explanation in the provided notes."
    ),
    "rigorous_expert": (
        "Role: Rigorous Academic Expert.\n"
        "Your mission is formal precision. Provide exact definitions, formal notations, technical boundary conditions, "
        "and mathematical/theoretical accuracy. Leave no room for ambiguity."
    ),
    "skeptic": (
        "Role: Critical Skeptic.\n"
        "Your mission is to probe weaknesses. Identify edge cases, common student misconceptions, counter-intuitive traps, "
        "and unstated assumptions. Point out what could go wrong or be easily misunderstood."
    ),
    "exam_coach": (
        "Role: Strategic Exam Coach.\n"
        "Your mission is scoring maximum marks. Highlight standard grading rubric keywords, exam patterns, "
        "bullet-point structures that graders look for, and high-yield summary takeaways."
    ),
    "example_builder": (
        "Role: Concrete Example Builder.\n"
        "Your mission is practical application. Provide a concrete, step-by-step worked example or realistic scenario "
        "demonstrating exactly how this concept applies in practice."
    ),
    "fact_checker": (
        "Role: Strict Fact-Checker.\n"
        "Your mission is verification. Audit the claim strictly against the provided source excerpts. Ensure zero "
        "unsupported leaps or hallucinations, and explicitly cite the file and page number for every key assertion."
    ),
}


def strip_role_labels(round1_answers: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Remove persona role labels so peer reviews are completely blind and unbiased."""
    anonymous_answers = {}
    label_to_role = {}

    # Sort role names for deterministic mapping
    sorted_roles = sorted(round1_answers.keys())
    for idx, role in enumerate(sorted_roles, start=1):
        anon_label = f"Candidate Answer {chr(64 + idx)}"  # Candidate Answer A, B, C...
        anonymous_answers[anon_label] = round1_answers[role]
        label_to_role[anon_label] = role

    return anonymous_answers, label_to_role


def _run_single_agent(
    role: str,
    system_prompt: str,
    user_prompt: str,
    profile_name: str,
    user_context: UserContext,
) -> Tuple[str, str]:
    """Execute a single agent prompt via the unified brain gateway."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    resp = chat(messages=messages, options={"profile": profile_name}, user_context=user_context)
    return role, resp.get("content", "")


def execute_jury_debate(
    question: str,
    subject: str,
    user_context: UserContext,
    mode: str = "quick",
    profile_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute either Quick Mode (single agent) or Full 6-Agent Jury Debate."""
    # 1. Retrieve grounded note excerpts from ChromaDB
    excerpts = query_document_chunks(user_context, subject=subject, query_text=question, n_results=4)
    if excerpts:
        context_text = "\n\n".join([
            f"[Source: {e['filename']}, Page {e['page']}, Topic: {e['topic']}]\n{e['text']}"
            for e in excerpts
        ])
    else:
        context_text = f"No specific notes found for subject '{subject}'. Rely on standard academic fundamentals."

    providers_config = load_providers_config()
    active_profile = profile_name or providers_config.get("active_profile", "local_ollama")
    profile_info = providers_config.get("profiles", {}).get(active_profile, {})
    max_workers = profile_info.get("max_parallel_calls", 1)

    # QUICK MODE: Single comprehensive answer citing sources
    if mode.lower() == "quick":
        quick_prompt = (
            f"You are StudyAssist in Quick Mode. Answer the student's question clearly, accurately, and concisely. "
            f"Cite source files and page numbers directly from the provided study excerpts.\n\n"
            f"Study Excerpts:\n{context_text}\n\nStudent Question: {question}"
        )
        resp = chat(
            messages=[{"role": "user", "content": quick_prompt}],
            options={"profile": active_profile},
            user_context=user_context,
        )
        return {
            "mode": "quick",
            "question": question,
            "final_answer": resp.get("content", ""),
            "citations": [f"{e['filename']} (p.{e['page']})" for e in excerpts],
        }

    # FULL JURY MODE: 6-Agent Debate with Blind Peer Reviews
    settings = load_settings_config()
    jury_config = settings.get("jury", {})
    roles = jury_config.get("roles", list(ROLE_PROMPTS.keys()))
    weights = jury_config.get("weights", {r: 1.0 for r in roles})

    # --- ROUND 1: Independent Answers ---
    round1_answers: Dict[str, str] = {}
    r1_prompt = f"Study Excerpts:\n{context_text}\n\nStudent Question: {question}\n\nProvide your independent answer according to your role."

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _run_single_agent,
                role,
                ROLE_PROMPTS.get(role, "You are an expert tutor."),
                r1_prompt,
                active_profile,
                user_context,
            ): role
            for role in roles
        }
        for fut in as_completed(futures):
            role, answer = fut.result()
            round1_answers[role] = answer

    # --- ROUND 2: Blind Peer Critiques ---
    # Strip role labels so peer review is completely unbiased
    anonymous_answers, label_map = strip_role_labels(round1_answers)

    anon_answers_text = "\n\n---\n\n".join([
        f"[{label}]:\n{text}"
        for label, text in anonymous_answers.items()
    ])

    r2_prompt = (
        f"Here are candidate answers to the student's question without author identities:\n\n"
        f"{anon_answers_text}\n\n"
        f"From your perspective, write a concise critique (3-4 sentences total) identifying which candidate answer "
        f"is the most accurate and what crucial nuances or corrections should be integrated."
    )

    blind_critiques: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _run_single_agent,
                role,
                ROLE_PROMPTS.get(role, ""),
                r2_prompt,
                active_profile,
                user_context,
            ): role
            for role in roles
        }
        for fut in as_completed(futures):
            role, critique = fut.result()
            blind_critiques[role] = critique

    # --- JUDGE SYNTHESIS ---
    weights_summary = ", ".join([f"{r}: weight {weights.get(r, 1.0)}" for r in roles])
    round1_summary = "\n\n".join([f"=== {role.upper()} ANSWER ===\n{ans}" for role, ans in round1_answers.items()])
    critique_summary = "\n\n".join([f"=== {role.upper()} CRITIQUE ===\n{crit}" for role, crit in blind_critiques.items()])

    judge_system = (
        "You are the Chief Judicial Synthesizer of the StudyAssist Jury. "
        "Six specialized academic agents have independently formulated answers and conducted blind peer critiques. "
        "Your task is to integrate their collective intelligence into ONE authoritative, crystal-clear, master study answer. "
        f"Honor role influence weights ({weights_summary}). "
        "Always cite source files and pages from the retrieved notes, explain the core intuition simply, include key exam keywords, "
        "and mention critical pitfalls or boundary conditions."
    )

    judge_prompt = (
        f"Study Notes Excerpts:\n{context_text}\n\n"
        f"Student Question: {question}\n\n"
        f"Round 1 Answers:\n{round1_summary}\n\n"
        f"Round 2 Blind Peer Critiques:\n{critique_summary}\n\n"
        f"Synthesize the single, best possible, cited answer for the student."
    )

    resp = chat(
        messages=[{"role": "system", "content": judge_system}, {"role": "user", "content": judge_prompt}],
        options={"profile": active_profile},
        user_context=user_context,
    )
    final_verdict = resp.get("content", "")

    return {
        "mode": "jury",
        "question": question,
        "round1_answers": round1_answers,
        "anonymous_answers": anonymous_answers,
        "blind_critiques": blind_critiques,
        "final_answer": final_verdict,
        "citations": [f"{e['filename']} (p.{e['page']})" for e in excerpts],
    }
