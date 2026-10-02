"""
Shared Claude call used by every agent.

All agents need the same thing from the model: one JSON object that matches a
schema. This module asks for it with structured outputs
(`output_config.format`), which works on every current Claude model.

Why not a forced tool call: the newest models (Claude Sonnet 5.5, Opus 5.5)
reject `tool_choice: {"type": "tool"}` on every request, and older models
reject it whenever extended thinking is on. Why no `temperature`: the same
newer models return a 400 for any non-default sampling parameter.

Environment:
    ANTHROPIC_API_KEY   required for real calls (read from .env, see app/__init__.py)
    ANTHROPIC_MODEL     optional override of DEFAULT_MODEL
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any, Optional

DEFAULT_MODEL = "claude-sonnet-5-5"


class LLMError(RuntimeError):
    """The model call failed or returned something unusable."""


def get_model(model: Optional[str] = None) -> str:
    return model or os.getenv("ANTHROPIC_MODEL") or DEFAULT_MODEL


def has_api_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def make_client():
    """Create an Anthropic client from ANTHROPIC_API_KEY."""
    if not has_api_key():
        raise LLMError("ANTHROPIC_API_KEY is not set. Add it to the .env file in the project "
                       "folder and restart the app.")
    import anthropic
    return anthropic.Anthropic()


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Return a copy of `schema` in the shape structured outputs expects: every
    object closed (`additionalProperties: false`) with all of its properties
    required, so the model always returns the full structure.
    """
    out = copy.deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and isinstance(node.get("properties"), dict):
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(out)
    return out


def structured_call(client, model: str, system: str, user: str, schema: dict[str, Any],
                    max_tokens: int = 8000) -> dict[str, Any]:
    """Send one prompt and return the model's answer as a dict matching `schema`."""
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user}],
        "output_config": {"format": {"type": "json_schema", "schema": strict_schema(schema)}},
    }
    if system:
        kwargs["system"] = system
    response = client.messages.create(**kwargs)

    stop = getattr(response, "stop_reason", None)
    if stop == "max_tokens":
        raise LLMError(f"The model's answer was cut off at {max_tokens} tokens.")
    if stop == "refusal":
        raise LLMError("The model declined to answer this request.")
    text = "".join(getattr(block, "text", "") for block in response.content
                   if getattr(block, "type", None) == "text")
    if not text.strip():
        raise LLMError("The model returned no text.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"The model's answer was not valid JSON: {exc}") from exc


def check() -> tuple[bool, str]:
    """
    One tiny real call to confirm the key, the model name and structured
    outputs all work. Used by `python -m app.scout llm-check`.
    """
    try:
        client = make_client()
        model = get_model()
        answer = structured_call(
            client, model, system="",
            user="Reply with ok set to true.",
            schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            max_tokens=2000,
        )
        return bool(answer.get("ok")), f"{model}: structured call succeeded"
    except Exception as exc:  # auth, network, unknown model, bad request
        return False, f"{type(exc).__name__}: {str(exc)[:400]}"
