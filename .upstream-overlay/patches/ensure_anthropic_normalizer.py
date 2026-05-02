from pathlib import Path


target = Path("/opt/hermes/agent/anthropic_adapter.py")
text = target.read_text()
if "def normalize_anthropic_response(" in text:
    raise SystemExit(0)

patch = r'''

# Compatibility shim for Hermes builds whose run_agent.py expects this helper
# but whose bundled anthropic_adapter.py predates it.
def normalize_anthropic_response(response, strip_tool_prefix: bool = False):
    """Normalize Anthropic Messages responses into Hermes' OpenAI-like shape."""
    from types import SimpleNamespace

    def _field(obj, name, default=None):
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    text_parts = []
    reasoning_parts = []
    reasoning_details = []
    tool_calls = []

    for block in (_field(response, "content", []) or []):
        block_type = _field(block, "type")
        if block_type == "text":
            text = _field(block, "text")
            if text:
                text_parts.append(text)
        elif block_type == "thinking":
            thinking = _field(block, "thinking")
            if thinking:
                reasoning_parts.append(thinking)
            try:
                block_dict = _to_plain_data(block)
            except Exception:
                block_dict = block if isinstance(block, dict) else None
            if isinstance(block_dict, dict):
                reasoning_details.append(block_dict)
        elif block_type == "tool_use":
            name = _field(block, "name", "") or ""
            if strip_tool_prefix and name.startswith(_MCP_TOOL_PREFIX):
                name = name[len(_MCP_TOOL_PREFIX):]
            raw_input = _field(block, "input", {}) or {}
            try:
                arguments = json.dumps(_to_plain_data(raw_input), ensure_ascii=False)
            except Exception:
                arguments = json.dumps(raw_input, ensure_ascii=False, default=str)
            tool_calls.append(
                SimpleNamespace(
                    id=_field(block, "id"),
                    type="function",
                    function=SimpleNamespace(name=name, arguments=arguments),
                )
            )

    stop_reason_map = {
        "end_turn": "stop",
        "tool_use": "tool_calls",
        "max_tokens": "length",
        "stop_sequence": "stop",
        "refusal": "content_filter",
        "model_context_window_exceeded": "length",
    }
    finish_reason = stop_reason_map.get(_field(response, "stop_reason"), "stop")

    return (
        SimpleNamespace(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls or None,
            reasoning="\n\n".join(reasoning_parts) if reasoning_parts else None,
            reasoning_content=None,
            reasoning_details=reasoning_details or None,
        ),
        finish_reason,
    )
'''

target.write_text(text.rstrip() + patch + "\n")
