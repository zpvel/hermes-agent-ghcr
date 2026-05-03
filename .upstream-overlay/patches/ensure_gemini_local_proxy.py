"""Patch the upstream image for local native Gemini proxies.

The upstream Gemini native adapter only recognizes Google's public
``generativelanguage.googleapis.com`` host.  Self-hosted aggregators such as
sub2api can expose the same native ``/v1beta`` Gemini REST surface locally.

This patch also lets provider base URL overrides come from Hermes' ``.env``
file, matching how API keys are already resolved.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path("/opt/hermes")


def patch_gemini_native_adapter() -> None:
    path = ROOT / "agent" / "gemini_native_adapter.py"
    text = path.read_text(encoding="utf-8")

    old = '''def is_native_gemini_base_url(base_url: str) -> bool:
    """Return True when the endpoint speaks Gemini's native REST API."""
    normalized = str(base_url or "").strip().rstrip("/").lower()
    if not normalized:
        return False
    if "generativelanguage.googleapis.com" not in normalized:
        return False
    return not normalized.endswith("/openai")
'''
    new = '''def is_native_gemini_base_url(base_url: str) -> bool:
    """Return True when the endpoint speaks Gemini's native REST API."""
    normalized = str(base_url or "").strip().rstrip("/").lower()
    if not normalized:
        return False
    if "generativelanguage.googleapis.com" in normalized:
        return not normalized.endswith("/openai")
    # Allow local/self-hosted Gemini proxies that expose the native v1beta REST
    # surface, e.g. sub2api at http://host:3020/v1beta.
    return normalized.endswith("/v1beta")
'''

    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Expected Gemini native URL detector not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_auth_base_url_resolution() -> None:
    path = ROOT / "hermes_cli" / "auth.py"
    text = path.read_text(encoding="utf-8")

    old = '''    env_url = ""
    if pconfig.base_url_env_var:
        env_url = os.getenv(pconfig.base_url_env_var, "").strip()
'''
    new = '''    env_url = ""
    if pconfig.base_url_env_var:
        try:
            from hermes_cli.config import get_env_value
            env_url = (get_env_value(pconfig.base_url_env_var) or "").strip()
        except Exception:
            env_url = ""
        if not env_url:
            env_url = os.getenv(pconfig.base_url_env_var, "").strip()
'''

    if old not in text:
        if new in text:
            return
        raise RuntimeError(f"Expected provider base URL lookup block not found in {path}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def patch_gemini_tool_response_grouping() -> None:
    path = ROOT / "agent" / "gemini_native_adapter.py"
    text = path.read_text(encoding="utf-8")

    old = '''def _build_gemini_contents(messages: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    system_text_parts: List[str] = []
    contents: List[Dict[str, Any]] = []
    tool_name_by_call_id: Dict[str, str] = {}

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user")

        if role == "system":
            system_text_parts.append(_coerce_content_to_text(msg.get("content")))
            continue

        if role in {"tool", "function"}:
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        _translate_tool_result_to_gemini(
                            msg,
                            tool_name_by_call_id=tool_name_by_call_id,
                        )
                    ],
                }
            )
            continue

        gemini_role = "model" if role == "assistant" else "user"
        parts: List[Dict[str, Any]] = []

        content_parts = _extract_multimodal_parts(msg.get("content"))
        parts.extend(content_parts)

        tool_calls = msg.get("tool_calls") or []
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if isinstance(tool_call, dict):
                    tool_call_id = str(tool_call.get("id") or tool_call.get("call_id") or "")
                    tool_name = str(((tool_call.get("function") or {}).get("name") or ""))
                    if tool_call_id and tool_name:
                        tool_name_by_call_id[tool_call_id] = tool_name
                    parts.append(_translate_tool_call_to_gemini(tool_call))

        if parts:
            contents.append({"role": gemini_role, "parts": parts})

    system_instruction = None
    joined_system = "\\n".join(part for part in system_text_parts if part).strip()
    if joined_system:
        system_instruction = {"parts": [{"text": joined_system}]}
    return contents, system_instruction
'''
    new = '''def _build_gemini_contents(messages: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    system_text_parts: List[str] = []
    contents: List[Dict[str, Any]] = []
    tool_name_by_call_id: Dict[str, str] = {}

    pending_call_index: Optional[int] = None
    pending_response_count = 0
    pending_response_parts: List[Dict[str, Any]] = []

    def _remove_pending_call_parts() -> None:
        nonlocal pending_call_index
        if pending_call_index is None or pending_call_index >= len(contents):
            return
        content = contents[pending_call_index]
        parts = [part for part in content.get("parts", []) if not isinstance(part, dict) or "functionCall" not in part]
        if parts:
            content["parts"] = parts
        else:
            contents.pop(pending_call_index)
        pending_call_index = None

    def _flush_pending_responses() -> None:
        nonlocal pending_call_index, pending_response_count, pending_response_parts
        if not pending_response_count:
            pending_response_parts = []
            pending_call_index = None
            return
        if len(pending_response_parts) == pending_response_count:
            contents.append({"role": "user", "parts": list(pending_response_parts)})
        else:
            # Gemini requires the user functionResponse turn to contain exactly
            # one response part per functionCall in the immediately preceding
            # model turn.  Gateway/session histories can contain interrupted
            # or provider-filtered tool calls, so strip the dangling calls
            # instead of poisoning every later Gemini request with HTTP 400.
            _remove_pending_call_parts()
        pending_call_index = None
        pending_response_count = 0
        pending_response_parts = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user")

        if role == "system":
            system_text_parts.append(_coerce_content_to_text(msg.get("content")))
            continue

        if role in {"tool", "function"}:
            if pending_response_count and len(pending_response_parts) < pending_response_count:
                pending_response_parts.append(
                    _translate_tool_result_to_gemini(
                        msg,
                        tool_name_by_call_id=tool_name_by_call_id,
                    )
                )
            continue

        _flush_pending_responses()

        gemini_role = "model" if role == "assistant" else "user"
        parts: List[Dict[str, Any]] = []

        content_parts = _extract_multimodal_parts(msg.get("content"))
        parts.extend(content_parts)

        tool_calls = msg.get("tool_calls") or []
        function_call_count = 0
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if isinstance(tool_call, dict):
                    tool_call_id = str(tool_call.get("id") or tool_call.get("call_id") or "")
                    tool_name = str(((tool_call.get("function") or {}).get("name") or ""))
                    if tool_call_id and tool_name:
                        tool_name_by_call_id[tool_call_id] = tool_name
                    parts.append(_translate_tool_call_to_gemini(tool_call))
                    function_call_count += 1

        if parts:
            contents.append({"role": gemini_role, "parts": parts})
            if gemini_role == "model" and function_call_count:
                pending_call_index = len(contents) - 1
                pending_response_count = function_call_count
                pending_response_parts = []

    _flush_pending_responses()

    system_instruction = None
    joined_system = "\\n".join(part for part in system_text_parts if part).strip()
    if joined_system:
        system_instruction = {"parts": [{"text": joined_system}]}
    return contents, system_instruction
'''

    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Expected Gemini content builder not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    patch_gemini_native_adapter()
    patch_auth_base_url_resolution()
    patch_gemini_tool_response_grouping()


if __name__ == "__main__":
    main()
