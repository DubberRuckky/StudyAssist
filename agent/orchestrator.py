"""Agent orchestrator implementing the Goal, Plan, Act, Approve, Log execution loop."""

import time
from typing import Any, Callable, Dict, List, Optional

from auth.context import UserContext
from agent.dispatcher import dispatch_tool, get_registered_tool_schemas
from models.brain import chat

DEFAULT_SYSTEM_PROMPT = """You are StudyAssist, an intelligent, patient, and methodical study companion.
Your goal is to help the student master their coursework, plan revision, and prepare for exams.
You have access to tools to search notes, run jury debates on difficult concepts, generate quizzes, and schedule revision.
Always cite your sources (files and pages) when using retrieved notes.
"""


def run_agent(
    task: str,
    system_prompt: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    max_iterations: int = 10,
    timeout_seconds: int = 120,
    user_context: Optional[UserContext] = None,
    approval_callback: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
    auto_approve: bool = False,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute the Goal -> Plan -> Act -> Approve -> Log agent loop."""
    if not user_context:
        raise ValueError("UserContext is required for running the agent loop to maintain strict isolation.")

    start_time = time.perf_counter()
    active_tools = tools if tools is not None else get_registered_tool_schemas()
    opts = dict(options or {})

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": f"Student Goal: {task}"},
    ]

    iterations = 0
    tool_history: List[Dict[str, Any]] = []
    final_answer = ""
    status = "completed"
    approval_pending = None

    while iterations < max_iterations:
        iterations += 1
        elapsed = time.perf_counter() - start_time
        if elapsed > timeout_seconds:
            status = "timeout"
            final_answer = "Execution reached the timeout limit before completing all steps."
            break

        # 1. PLAN: Ask brain for next action / tool calls
        brain_resp = chat(
            messages=messages,
            tools=active_tools if active_tools else None,
            options=opts,
            user_context=user_context,
        )

        content = brain_resp.get("content", "")
        tool_calls = brain_resp.get("tool_calls", [])
        profile_used = brain_resp.get("profile_used", "unknown")
        usage = brain_resp.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        # 2. ACT & APPROVE: If the model called tools, dispatch them
        if tool_calls:
            # Append model's response to history
            messages.append({"role": "assistant", "content": content or f"Calling {len(tool_calls)} tool(s)."})

            all_declined = False
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})

                # Execute tool via approval gate and log action
                result_text, approval_status = dispatch_tool(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    user_context=user_context,
                    profile_name=profile_used,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    approval_callback=approval_callback,
                    auto_approve=auto_approve,
                )

                tool_history.append({
                    "iteration": iterations,
                    "tool": tool_name,
                    "args": tool_args,
                    "result": result_text,
                    "approval": approval_status,
                })

                if approval_status == "pending":
                    status = "pending_approval"
                    approval_pending = {"tool": tool_name, "args": tool_args}
                    final_answer = result_text
                    break

                if approval_status == "rejected":
                    all_declined = True

                # Provide tool output back to the brain as observation
                messages.append({
                    "role": "user",
                    "content": f"[Tool Result for '{tool_name}']: {result_text}"
                })

            if status == "pending_approval":
                break

        else:
            # No tool calls: model returned final answer
            final_answer = content
            status = "completed"
            break

    if iterations >= max_iterations and status == "completed" and not final_answer:
        status = "iteration_limit_reached"
        final_answer = "Agent loop reached the iteration cap without producing a final answer."

    total_duration = round(time.perf_counter() - start_time, 2)
    return {
        "status": status,
        "final_answer": final_answer,
        "iterations": iterations,
        "duration_sec": total_duration,
        "tool_history": tool_history,
        "approval_pending": approval_pending,
        "messages": messages,
    }
