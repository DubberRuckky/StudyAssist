"""Unified LLM gateway interface for StudyAssist supporting native and portable tool execution."""

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

# Disable litellm remote cost map network fetches and telemetry for instant offline startup
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
import requests
import litellm
litellm.telemetry = False

from auth.context import UserContext
from auth.keyring_service import get_user_secret
from config.loader import load_providers_config, load_settings_config
from models.mock_brain import get_mock_brain
from models.tool_protocol import (
    PORTABLE_TOOL_SYSTEM_PROMPT,
    ToolCall,
    parse_portable_tool_response,
)
from storage.db import get_daily_call_count, is_subject_local_only, log_action, record_brain_call

logger = logging.getLogger(__name__)

# Single brain queue lock to prevent overlapping calls across users or threads
_BRAIN_QUEUE_LOCK = threading.Lock()

# Global set of users who have already seen the one-time remote provider warning
_NOTIFIED_REMOTE_USERS = set()


def _call_ollama(
    profile: Dict[str, Any],
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]] = None,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute chat completion using local or remote Ollama HTTP endpoint."""
    base_url = profile.get("base_url", "http://localhost:11434").rstrip("/")
    model = profile.get("model", "qwen2.5-coder:7b")
    timeout = profile.get("timeout_seconds", 60)
    opts = options or {}

    settings = load_settings_config()
    ctx_len = opts.get("context_length") or profile.get("context_length", 2048)
    keep_alive = opts.get("keep_alive") or settings.get("hardware", {}).get("keep_alive", "5m")

    # Native vs Portable Tool Handling
    native_tools = profile.get("native_tools", False)
    payload_messages = [dict(m) for m in messages]

    if tools and not native_tools:
        # Portable mode: prepend JSON formatting rules
        if payload_messages and payload_messages[0]["role"] == "system":
            payload_messages[0]["content"] += f"\n\n{PORTABLE_TOOL_SYSTEM_PROMPT}"
        else:
            payload_messages.insert(0, {"role": "system", "content": PORTABLE_TOOL_SYSTEM_PROMPT})

    payload = {
        "model": model,
        "messages": payload_messages,
        "stream": False,
        "keep_alive": keep_alive,
        "options": {
            "num_ctx": ctx_len,
            "temperature": opts.get("temperature", 0.7),
        },
    }

    if tools and native_tools:
        payload["tools"] = tools

    url = f"{base_url}/api/chat"
    max_retries = 2
    resp = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            if resp.status_code == 200:
                break
            if resp.status_code >= 500 and attempt < max_retries:
                time.sleep(0.5 * (2 ** attempt))
                continue
            raise RuntimeError(f"Ollama error {resp.status_code}: {resp.text}")
        except (requests.ConnectionError, requests.Timeout) as conn_err:
            if attempt < max_retries:
                time.sleep(0.5 * (2 ** attempt))
                continue
            raise RuntimeError(f"Ollama connection error: {conn_err}")

    if not resp or resp.status_code != 200:
        raise RuntimeError("Failed to obtain valid response from Ollama endpoint.")

    data = resp.json()
    message = data.get("message", {})
    raw_content = message.get("content", "")
    native_tool_calls = message.get("tool_calls", [])

    usage = {
        "prompt_tokens": data.get("prompt_eval_count", 0),
        "completion_tokens": data.get("eval_count", 0),
        "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
    }

    # Format tool calls
    parsed_calls: List[Dict[str, Any]] = []

    if tools:
        if native_tools and native_tool_calls:
            for tc in native_tool_calls:
                func = tc.get("function", {})
                parsed_calls.append({
                    "name": func.get("name", ""),
                    "args": func.get("arguments", {}),
                })
        elif not native_tools:
            # Portable mode: parse JSON action
            retries = 2
            current_raw = raw_content
            action = None
            last_err = None

            for attempt in range(retries + 1):
                try:
                    action = parse_portable_tool_response(current_raw)
                    break
                except ValueError as err:
                    last_err = err
                    if attempt < retries:
                        # Corrective retry prompt
                        correction_msgs = payload_messages + [
                            {"role": "assistant", "content": current_raw},
                            {"role": "user", "content": f"JSON syntax error: {err}. Please return ONLY valid JSON matching the schema."}
                        ]
                        retry_payload = dict(payload, messages=correction_msgs)
                        retry_resp = requests.post(url, json=retry_payload, timeout=timeout)
                        if retry_resp.status_code == 200:
                            current_raw = retry_resp.json().get("message", {}).get("content", "")

            if action:
                if action.action == "final":
                    raw_content = action.answer or raw_content
                else:
                    parsed_calls.append({"name": action.action, "args": action.args})
            elif last_err:
                logger.warning("Portable mode tool parsing failed after retries: %s", last_err)

    return {
        "content": raw_content,
        "tool_calls": parsed_calls,
        "usage": usage,
    }


def _call_colab_tunnel(
    profile: Dict[str, Any],
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]] = None,
    options: Optional[Dict[str, Any]] = None,
    user_context: Optional[UserContext] = None,
) -> Dict[str, Any]:
    """Execute chat via Colab tunnel using bearer token stored in user keyring."""
    base_url = profile.get("base_url", "").rstrip("/")
    if not base_url:
        raise ValueError("Colab profile requires a tunnel base_url in providers.json or settings.")

    token = None
    if user_context:
        token = get_user_secret(user_context.user_id, "colab_token")

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    model = profile.get("model", "qwen2.5:7b")
    timeout = profile.get("timeout_seconds", 90)

    # Use OpenAI-compatible v1/chat/completions endpoint
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": (options or {}).get("temperature", 0.7),
    }

    url = f"{base_url}/v1/chat/completions"
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"Colab tunnel error {resp.status_code}: {resp.text}")

    data = resp.json()
    choice = data.get("choices", [{}])[0].get("message", {})
    return {
        "content": choice.get("content", ""),
        "tool_calls": [],
        "usage": data.get("usage", {}),
    }


def _call_litellm(
    profile: Dict[str, Any],
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]] = None,
    options: Optional[Dict[str, Any]] = None,
    user_context: Optional[UserContext] = None,
) -> Dict[str, Any]:
    """Execute chat completion via LiteLLM using API key from user keyring."""
    model = profile.get("model", "gpt-4o-mini")
    api_key = None
    if user_context:
        api_key = get_user_secret(user_context.user_id, "cloud_api_key")

    resp = None
    max_retries = 2
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = litellm.completion(
                model=model,
                messages=messages,
                tools=tools,
                api_key=api_key,
                timeout=profile.get("timeout_seconds", 60),
            )
            break
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(0.5 * (2 ** attempt))
                continue
            raise RuntimeError(f"LiteLLM completion error after retries: {last_err}") from last_err

    msg = resp.choices[0].message
    content = msg.content or ""
    tool_calls = []
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            args = tc.function.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    pass
            tool_calls.append({"name": tc.function.name, "args": args})

    usage = {
        "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0),
        "completion_tokens": getattr(resp.usage, "completion_tokens", 0),
        "total_tokens": getattr(resp.usage, "total_tokens", 0),
    }

    return {
        "content": content,
        "tool_calls": tool_calls,
        "usage": usage,
    }


def chat(
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]] = None,
    options: Optional[Dict[str, Any]] = None,
    user_context: Optional[UserContext] = None,
) -> Dict[str, Any]:
    """Single global brain gateway enforcing single-threading queue and fallback."""
    opts = options or {}
    providers_config = load_providers_config()
    active_profile_name = opts.get("profile") or providers_config.get("active_profile", "local_ollama")
    fallback_order = providers_config.get("fallback_order", ["local_ollama", "local_fallback", "colab_ollama"])

    # Check per-subject local-only toggle
    subject = opts.get("subject")
    enforce_local = False
    if subject and user_context:
        enforce_local = is_subject_local_only(user_context, subject)

    # Enforce daily call cap if configured
    settings = load_settings_config()
    daily_cap = settings.get("safety", {}).get("daily_call_cap", 100)
    if user_context and daily_cap > 0:
        current_daily_count = get_daily_call_count(user_context)
        if current_daily_count >= daily_cap:
            raise RuntimeError(
                f"Daily call cap exceeded ({daily_cap} calls). "
                "Limit resets tomorrow to prevent runaway compute or costs."
            )

    # Sequence of candidate profiles to attempt
    candidates = [active_profile_name] + [p for p in fallback_order if p != active_profile_name]

    with _BRAIN_QUEUE_LOCK:
        last_exception = None
        start_time = time.perf_counter()

        for idx, profile_name in enumerate(candidates):
            profile = providers_config.get("profiles", {}).get(profile_name)
            if not profile:
                continue

            # If subject requires local only, skip non-local providers
            if enforce_local and not profile.get("is_local", True):
                continue

            # One-time warning check for non-local brains
            warning_issued = False
            if not profile.get("is_local", True) and user_context:
                if user_context.user_id not in _NOTIFIED_REMOTE_USERS:
                    _NOTIFIED_REMOTE_USERS.add(user_context.user_id)
                    warning_issued = True
                    logger.info(
                        "Remote Brain Notice: Questions and retrieved excerpts will be sent to %s. "
                        "All uploads, databases, and memory files remain strictly on your local PC.",
                        profile_name,
                    )

            provider_type = profile.get("provider_type", "ollama")
            try:
                if provider_type == "mock":
                    res = get_mock_brain().chat(messages, tools, options)
                elif provider_type == "ollama":
                    res = _call_ollama(profile, messages, tools, options)
                elif provider_type == "colab_tunnel":
                    res = _call_colab_tunnel(profile, messages, tools, options, user_context)
                elif provider_type == "litellm":
                    res = _call_litellm(profile, messages, tools, options, user_context)
                else:
                    raise ValueError(f"Unknown provider_type '{provider_type}' in profile '{profile_name}'")

                elapsed = round(time.perf_counter() - start_time, 2)
                res["duration_sec"] = elapsed
                res["profile_used"] = profile_name
                res["fallback_occurred"] = (idx > 0)
                res["remote_warning_issued"] = warning_issued

                # Track successful call count against daily quota
                if user_context:
                    record_brain_call(user_context, profile_name)

                return res

            except Exception as err:
                logger.warning("Brain profile '%s' failed: %s. Attempting fallback.", profile_name, err)
                last_exception = err
                continue

        # If all candidates failed, protect user data and return clear remediation guidance
        attempted_str = ", ".join(candidates)
        raise RuntimeError(
            f"All configured brain profiles failed ({attempted_str}). "
            "Your local files, notes, and study database remain safe. "
            "To fix: Ensure Ollama is running (`ollama serve`), verify network/tunnel connections, "
            f"or select the 'mock' profile in Brain & Settings. Details: {last_exception}"
        )


def test_brain_connection(profile_name: str, user_context: Optional[UserContext] = None) -> Dict[str, Any]:
    """Test reachability and operational readiness of a given brain profile."""
    providers_config = load_providers_config()
    profile = providers_config.get("profiles", {}).get(profile_name)
    if not profile:
        return {"status": "error", "message": f"Profile '{profile_name}' not found."}

    ptype = profile.get("provider_type", "ollama")
    try:
        if ptype == "mock":
            return {"status": "ok", "message": "Mock profile is operational (offline)."}

        elif ptype == "ollama":
            base_url = profile.get("base_url", "http://localhost:11434").rstrip("/")
            model = profile.get("model", "qwen2.5:7b")
            resp = requests.get(f"{base_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return {"status": "error", "message": f"Ollama HTTP {resp.status_code}: {resp.text}"}
            installed_models = [m.get("name") for m in resp.json().get("models", [])]
            model_found = any(model in m or m.startswith(model) for m in installed_models)
            if model_found:
                return {"status": "ok", "message": f"Connected to Ollama! Model '{model}' is ready."}
            return {
                "status": "warning",
                "message": f"Connected to Ollama at {base_url}, but model '{model}' is not installed yet (found: {installed_models}).",
            }

        elif ptype == "colab_tunnel":
            base_url = profile.get("base_url", "").rstrip("/")
            if not base_url:
                return {"status": "error", "message": "Colab tunnel base_url is not configured."}
            token = get_user_secret(user_context.user_id, "colab_token") if user_context else None
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            resp = requests.get(f"{base_url}/v1/models", headers=headers, timeout=5)
            if resp.status_code == 200:
                return {"status": "ok", "message": "Colab tunnel connected successfully."}
            return {"status": "error", "message": f"Colab tunnel returned HTTP {resp.status_code}: {resp.text}"}

        elif ptype == "litellm":
            api_key = get_user_secret(user_context.user_id, "cloud_api_key") if user_context else None
            if not api_key:
                return {"status": "warning", "message": "LiteLLM profile configured, but no API key saved in keyring."}
            return {"status": "ok", "message": "LiteLLM API key detected in secure keyring."}

        return {"status": "error", "message": f"Unsupported provider type '{ptype}'."}

    except Exception as err:
        return {"status": "error", "message": f"Connection check failed: {err}"}


def estimate_jury_cost(
    profile_name: str,
    num_agents: int = 6,
    avg_tokens_per_call: int = 800,
) -> Dict[str, Any]:
    """Estimate total LLM calls and token expense for multi-agent jury deliberation."""
    providers_config = load_providers_config()
    profile = providers_config.get("profiles", {}).get(profile_name, {})
    is_local = profile.get("is_local", True)
    model = profile.get("model", "unknown")

    # 6 agents Round 1 + 6 agents Round 2 + 1 Synthesizer = 13 calls
    total_calls = (num_agents * 2) + 1
    total_tokens_est = total_calls * avg_tokens_per_call

    if is_local:
        return {
            "total_calls": total_calls,
            "estimated_tokens": total_tokens_est,
            "estimated_cost_usd": 0.0,
            "is_local": True,
            "summary": f"Estimated {total_calls} calls (~{total_tokens_est} tokens). Free (Local hardware).",
        }

    # Approximate blended pricing: ~$0.50 per 1M tokens for mid-tier cloud models
    cost = round((total_tokens_est / 1_000_000.0) * 0.50, 4)
    return {
        "total_calls": total_calls,
        "estimated_tokens": total_tokens_est,
        "estimated_cost_usd": cost,
        "is_local": False,
        "summary": f"Estimated {total_calls} calls (~{total_tokens_est} tokens). Approx ${cost:.4f} USD on {model}.",
    }

