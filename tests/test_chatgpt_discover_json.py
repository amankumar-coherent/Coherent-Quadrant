"""DeepSeek discover must not treat truncated {} as a company list."""
from __future__ import annotations

from vendor_intel.pipeline.chatgpt_expand import (
    _assistant_message_text,
    _json_missing_required,
    _parse_json,
)


def test_truncated_empty_object_is_missing_companies():
    data = _parse_json("{}")
    assert data == {}
    assert _json_missing_required(data, "companies") is True


def test_companies_list_is_present():
    data = {"companies": [{"name": "Acme"}]}
    assert _json_missing_required(data, "companies") is False


def test_reasoning_content_json_extracted():
    class Msg:
        content = "{}"
        reasoning_content = 'thinking...\n{"companies":[{"name":"Foo"}]}'

    text = _assistant_message_text(Msg())
    parsed = _parse_json(text)
    assert parsed["companies"][0]["name"] == "Foo"
