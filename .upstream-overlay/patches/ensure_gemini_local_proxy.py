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


def main() -> None:
    patch_gemini_native_adapter()
    patch_auth_base_url_resolution()


if __name__ == "__main__":
    main()
