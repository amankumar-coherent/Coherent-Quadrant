"""Map Coherent-Quadrant DeepSeek keys onto OPENAI_* for ChatGPT expand."""
from __future__ import annotations

import os
from pathlib import Path


def apply_chatgpt_expand_env(*, root: Path | None = None) -> None:
    """Load `.env` and point the OpenAI SDK at DeepSeek when that is the provider.

    ChatGPT expand + Google AI Overview clean both read OPENAI_API_KEY / BASE_URL / MODEL.
    Coherent-Quadrant stores the paid key as DEEPSEEK_*.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None  # type: ignore[assignment]

    if root is None:
        from vendor_intel.config import _project_root

        root = _project_root()
    if load_dotenv is not None:
        load_dotenv(root / ".env")

    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    deepseek_key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()

    use_deepseek = provider == "deepseek" or (deepseek_key and not openai_key)
    if not use_deepseek:
        return

    if not openai_key and deepseek_key:
        os.environ["OPENAI_API_KEY"] = deepseek_key

    if not (os.getenv("OPENAI_BASE_URL") or "").strip():
        base = (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").strip().rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        os.environ["OPENAI_BASE_URL"] = base

    if not (os.getenv("OPENAI_MODEL") or "").strip():
        os.environ["OPENAI_MODEL"] = (
            os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-flash"
        ).strip()

    # Company Details (chatgpt_expand): only HQ (Found in) + website — not employees/turnover.
    folder = (os.getenv("EXPAND_OUTPUT_FOLDER") or "").strip().lower()
    if folder == "chatgpt_expand":
        os.environ.setdefault("GOOGLE_AI_GAP_FILL_FIELDS", "headquarters,website")
        os.environ.setdefault("GOOGLE_AI_GAP_FILL_MAX_QUERIES", "4")
        os.environ.setdefault("SEARCH_STACK_RESIDUAL_COLUMNS", "Headquarters,Website")
        # Found in = City, Country (auto wiki/known resolve in Step 6d)
        os.environ.setdefault("FOUND_IN_CITY_COUNTRY", "1")
        os.environ.setdefault("FOUND_IN_WIKI_RESOLVE", "1")
        # Drop wrong-industry / fake / R&D / regional-dupe / acquired shells
        os.environ.setdefault("EXPAND_MARKET_GATE", "1")


def deepseek_chat_config() -> tuple[str, str, str]:
    """Return (api_key, base_url, model) for DeepSeek sentence-clean + column write.

    Prefers DEEPSEEK_API_KEY. Maps onto OPENAI_* so the OpenAI SDK can call DeepSeek.
    """
    apply_chatgpt_expand_env()
    key = (
        os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    ).strip()
    base = (
        os.getenv("OPENAI_BASE_URL")
        or os.getenv("DEEPSEEK_BASE_URL")
        or "https://api.deepseek.com/v1"
    ).strip().rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    model = (
        os.getenv("GOOGLE_AI_SCRAPER_LLM_MODEL")
        or os.getenv("OPENAI_MODEL")
        or os.getenv("DEEPSEEK_MODEL")
        or "deepseek-chat"
    ).strip()
    return key, base, model
