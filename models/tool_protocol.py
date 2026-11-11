"""Universal tool calling protocol: portable JSON repair, validation, and schema definitions."""

import json
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """Normalized tool call representation."""
    name: str
    args: Dict[str, Any] = Field(default_factory=dict)
    id: Optional[str] = None


class ToolAction(BaseModel):
    """Parsed model action for portable JSON mode."""
    action: str  # e.g., tool name or "final"
    args: Dict[str, Any] = Field(default_factory=dict)
    answer: Optional[str] = None


PORTABLE_TOOL_SYSTEM_PROMPT = """You are an agent that uses tools to complete tasks.
You must reply ONLY with a valid JSON object matching one of these two structures:

1. To call a tool:
{"action": "tool_name", "args": {"param1": "value1"}}

2. To return the final answer to the student:
{"action": "final", "answer": "Your complete final answer here."}

Do NOT include any commentary, explanations, or text outside the JSON object.
"""


def repair_json_string(raw_text: str) -> str:
    """Clean and repair common LLM JSON syntax mistakes."""
    text = raw_text.strip()

    # 1. Strip markdown code fences (e.g. ```json ... ```)
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    # 2. Extract substring between the first { and last } if surrounded by prose
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    # 3. Remove trailing commas before closing braces or brackets (e.g., {"a": 1, })
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # 4. Replace single quotes around keys and strings with double quotes if needed
    # Only replace if not already valid JSON
    return text


def parse_portable_tool_response(raw_response: str) -> ToolAction:
    """Robustly parse an LLM response in portable mode into a validated ToolAction."""
    cleaned = repair_json_string(raw_response)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as err:
        # Secondary fallback: attempt basic quote and newline normalization
        normalized = cleaned.replace("'", '"')
        normalized = re.sub(r",\s*([}\]])", r"\1", normalized)
        try:
            data = json.loads(normalized)
        except Exception:
            raise ValueError(f"Failed to parse LLM JSON response: {err}. Raw text: {raw_response[:200]}")

    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object, got {type(data).__name__}")

    action = data.get("action", "")
    if not action:
        # If model returned {"tool": "name", "args": ...}
        if "tool" in data:
            action = data["tool"]
        elif "final" in data or "answer" in data:
            action = "final"
        else:
            action = "final"

    args = data.get("args", {})
    if not isinstance(args, dict):
        args = {}

    answer = data.get("answer")
    if action == "final" and not answer:
        # If model put answer under content or message
        answer = data.get("content") or data.get("message") or str(data)

    return ToolAction(action=action, args=args, answer=answer)
