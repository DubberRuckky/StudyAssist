"""Tool registry, execution dispatcher, and human approval gate."""

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from auth.context import UserContext
from config.loader import load_settings_config
from storage.db import log_action

logger = logging.getLogger(__name__)

# Registry mapping tool name -> callable implementation
_TOOL_REGISTRY: Dict[str, Callable[..., Any]] = {}

# Descriptions of registered tools for LLM tool calling schema
_TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {}


def register_tool(name: str, func: Callable[..., Any], schema: Dict[str, Any]) -> None:
    """Register a tool function with its JSON execution schema."""
    _TOOL_REGISTRY[name] = func
    _TOOL_SCHEMAS[name] = schema


def get_registered_tool_schemas() -> List[Dict[str, Any]]:
    """Return list of all registered tool schemas formatted for brain calls."""
    return list(_TOOL_SCHEMAS.values())


def get_confirmation_required_tools() -> Set[str]:
    """Retrieve the set of sensitive tool names that require human approval before execution."""
    try:
        settings = load_settings_config()
        return set(settings.get("safety", {}).get("requires_confirmation", ["schedule_revision"]))
    except Exception:
        return {"schedule_revision"}


def dispatch_tool(
    tool_name: str,
    tool_args: Dict[str, Any],
    user_context: UserContext,
    profile_name: str = "local_ollama",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    approval_callback: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
    auto_approve: bool = False,
) -> Tuple[str, str]:
    """Execute a tool through the approval gate, returning (result_text, approval_status)."""
    start_time = time.perf_counter()
    requires_confirmation = get_confirmation_required_tools()

    approval_status = "auto"

    # Human-in-the-loop confirmation check
    if tool_name in requires_confirmation:
        if auto_approve:
            approval_status = "approved"
        elif approval_callback is not None:
            user_decision = approval_callback(tool_name, tool_args)
            if user_decision:
                approval_status = "approved"
            else:
                approval_status = "rejected"
                result_text = "User declined."
                elapsed = round(time.perf_counter() - start_time, 3)
                log_action(
                    context=user_context,
                    profile_name=profile_name,
                    duration_sec=elapsed,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_result=result_text,
                    approval_status=approval_status,
                )
                return result_text, approval_status
        else:
            # No callback provided; pause for UI approval
            approval_status = "pending"
            result_text = f"Action paused. Requires human approval before executing '{tool_name}'."
            elapsed = round(time.perf_counter() - start_time, 3)
            log_action(
                context=user_context,
                profile_name=profile_name,
                duration_sec=elapsed,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                tool_name=tool_name,
                tool_args=tool_args,
                tool_result=result_text,
                approval_status=approval_status,
            )
            return result_text, approval_status

    if tool_name not in _TOOL_REGISTRY:
        result_text = f"Tool error: Unknown tool '{tool_name}'."
        approval_status = "error"
    else:
        try:
            tool_func = _TOOL_REGISTRY[tool_name]
            # Forward profile_name to tool if not explicitly specified in tool_args
            call_args = dict(tool_args)
            if "profile_name" not in call_args and profile_name:
                call_args["profile_name"] = profile_name
            raw_result = tool_func(user_context=user_context, **call_args)
            result_text = str(raw_result) if not isinstance(raw_result, str) else raw_result
        except Exception as err:
            logger.error("Error executing tool '%s': %s", tool_name, err, exc_info=True)
            result_text = f"Tool error: {type(err).__name__} - {err}"
            approval_status = "error"

    elapsed = round(time.perf_counter() - start_time, 3)
    log_action(
        context=user_context,
        profile_name=profile_name,
        duration_sec=elapsed,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        tool_name=tool_name,
        tool_args=tool_args,
        tool_result=result_text,
        approval_status=approval_status,
    )
    return result_text, approval_status
