from __future__ import annotations

from typing import Optional

from .config import settings


OPENAI_PROMPT = (
    "You are a helpful software planning assistant. Given a project name and a "
    "plain-language product vision, produce a concise Proposed Requirements document "
    "for an MVP. Include: Goals, Scope, Non-Goals, Functional Requirements, NFRs, and "
    "an MVP plan with a few concrete work items. Keep it under ~250 words."
)


def _try_import_openai():
    try:
        # Newer SDK style import
        from openai import OpenAI  # type: ignore

        return OpenAI
    except Exception:
        try:
            # Legacy SDK fallback
            import openai  # type: ignore

            return openai
        except Exception:
            return None


def propose_requirements_from_openai(project_name: str, vision_text: str) -> Optional[str]:
    """
    If enabled and properly configured, call OpenAI to generate a requirements draft.
    Returns None on any failure so callers can fall back to deterministic draft.
    """
    if not settings.enable_openai_planner:
        return None

    api_key = __import__("os").getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    client_cls = _try_import_openai()
    if client_cls is None:
        return None

    try:
        # Support both new and old SDKs in a best-effort manner.
        base_url = settings.openai_base_url
        model = settings.openai_model
        content = (
            f"Project: {project_name}\n\n"
            f"Vision:\n{vision_text}\n\n"
            f"Task: {OPENAI_PROMPT}"
        )

        # New SDK path
        if hasattr(client_cls, "__name__") and client_cls.__name__ == "OpenAI":
            client = client_cls(api_key=api_key, base_url=base_url)  # type: ignore
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": OPENAI_PROMPT},
                    {"role": "user", "content": content},
                ],
                temperature=0.2,
            )
            text = (resp.choices[0].message.content or "").strip()
            return text or None

        # Legacy SDK path
        else:
            openai = client_cls  # type: ignore
            if base_url:
                try:
                    # Some proxies use api_base
                    openai.api_base = base_url  # type: ignore[attr-defined]
                except Exception:
                    pass
            openai.api_key = api_key  # type: ignore[attr-defined]
            resp = openai.ChatCompletion.create(  # type: ignore[attr-defined]
                model=model,
                messages=[
                    {"role": "system", "content": OPENAI_PROMPT},
                    {"role": "user", "content": content},
                ],
                temperature=0.2,
            )
            text = (resp["choices"][0]["message"]["content"] or "").strip()
            return text or None
    except Exception:
        return None

