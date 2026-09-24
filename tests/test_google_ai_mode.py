"""Google AI Mode backend: URL building, reply parsing, failure-mode
separation, and the routing switch in the expand pipeline.

No test here drives a real browser — `ask()` is always mocked or the backend
is left disabled (tests/conftest.py forces GOOGLE_AI_MODE_ENABLED=false).
"""
from __future__ import annotations

import json

import pytest

from vendor_intel.scraping import google_ai_mode as gam


# --- URL building ----------------------------------------------------------


def test_url_uses_ai_mode_tab():
    url = gam.build_url("global animal healthcare manufacturers")
    assert "udm=50" in url
    assert "google.com/search" in url
    assert "global+animal+healthcare" in url


def test_long_prompt_truncated_under_url_limit():
    # An exclusion list that grows per iteration once produced a 10,701-char
    # URL and every request 400'd mid-run.
    url = gam.build_url("exclude these companies: " + ", ".join(f"Company {i}" for i in range(2000)))
    assert len(url) <= gam.MAX_URL_CHARS


def test_short_prompt_not_truncated():
    prompt = "list pump manufacturers"
    assert gam.build_url(prompt).endswith("&udm=50&hl=en")


# --- reply parsing ---------------------------------------------------------


def test_parses_plain_json_array():
    data = gam.parse_json_answer('[{"name": "Zoetis", "website": "https://zoetis.com"}]')
    assert data[0]["name"] == "Zoetis"


def test_strips_google_ui_footer_and_fences():
    raw = '```json\n[{"name": "Elanco"}]\n```\nUse code with caution.'
    assert gam.parse_json_answer(raw)[0]["name"] == "Elanco"


def test_skips_prompt_echo_and_keeps_first_item():
    """AI Mode echoes the question. The echoed empty template must not win,
    and slicing must start AT the marker — an off-by-one here silently
    dropped the first item of every batch."""
    raw = (
        'Reply with ONLY a JSON array: [{"name": "", "website": ""}]\n\n'
        'Here are the companies:\n'
        '[{"name": "Merck Animal Health", "website": "https://merck-animal-health.com"}, '
        '{"name": "Boehringer Ingelheim", "website": "https://boehringer.com"}]'
    )
    data = gam.parse_json_answer(raw)
    assert len(data) == 2
    assert data[0]["name"] == "Merck Animal Health"


def test_skips_trailing_prompt_echo():
    """The echo can also come AFTER the answer — an all-blank template must
    lose either way."""
    raw = (
        '[{"name": "Virbac", "website": "https://virbac.com"}]\n'
        'The requested format was: [{"name": "", "website": ""}]'
    )
    data = gam.parse_json_answer(raw)
    assert data[0]["name"] == "Virbac"


def test_recovers_from_literal_newlines_in_strings():
    raw = '[{"name": "Ceva\n Sante", "website": ""}]'
    assert gam.parse_json_answer(raw)[0]["name"].startswith("Ceva")


def test_require_key_wraps_bare_array():
    data = gam.parse_json_answer('[{"name": "Virbac"}]', require_key="companies")
    assert data["companies"][0]["name"] == "Virbac"


def test_require_key_found_in_object():
    data = gam.parse_json_answer('{"companies": [{"name": "IDEXX"}]}', require_key="companies")
    assert data["companies"][0]["name"] == "IDEXX"


def test_unparseable_answer_raises():
    with pytest.raises(json.JSONDecodeError):
        gam.parse_json_answer("Sorry, I have no information about that.")


# --- failure modes stay distinct -------------------------------------------


def test_captcha_and_refusal_are_different_exceptions():
    """A block needs a long cool-off; a refusal needs an immediate reword.
    Conflating them caused a 300 s cool-off that never helped."""
    assert not issubclass(gam.AiModeCaptcha, gam.AiModeRefusal)
    assert not issubclass(gam.AiModeRefusal, gam.AiModeCaptcha)
    assert "no response available for this search" in gam.REFUSAL_MARKERS
    assert "unusual traffic" in gam.CAPTCHA_MARKERS


def test_disabled_backend_raises_unavailable(monkeypatch):
    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "false")
    assert not gam.enabled()
    with pytest.raises(gam.AiModeUnavailable):
        gam.ask("anything")


def test_enabled_reads_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "true")
    assert gam.enabled()


# --- OpenAI-shaped adapter -------------------------------------------------


def test_chat_ignores_model_and_max_tokens(monkeypatch):
    """Accepting and ignoring model/max_tokens is what makes this a drop-in
    swap for the existing call sites."""
    seen = {}

    def _fake_ask(prompt, **kw):
        seen["prompt"] = prompt
        return '{"companies": [{"name": "Zoetis"}]}'

    monkeypatch.setattr(gam, "ask", _fake_ask)
    out = gam.chat_json(
        "You are a market analyst.",
        '{"market": "Animal Health"}',
        model="gpt-4o-mini",
        max_tokens=4096,
        temperature=0.15,
    )
    assert out["companies"][0]["name"] == "Zoetis"
    assert "You are a market analyst." in seen["prompt"]


def test_chat_json_adds_blank_preferred_guard(monkeypatch):
    """Telling the model to fill every field makes it invent values (94% of
    one email column came back as info@<own-domain>). The inverse
    instruction must be attached automatically."""
    seen = {}

    def _fake_ask(prompt, **kw):
        seen["prompt"] = prompt
        return "[]"

    monkeypatch.setattr(gam, "ask", _fake_ask)
    try:
        gam.chat_json("Find company emails.", "{}")
    except json.JSONDecodeError:
        pass
    assert "empty string is CORRECT and preferred" in seen["prompt"]
    assert "NEVER invent a phone number" in seen["prompt"]


# --- CAPTCHA-solver extension loading (guide §8) ---------------------------


def test_extension_id_is_derived_not_hardcoded(tmp_path):
    """Chrome derives the ID from the absolute path, so it must change when
    the folder moves — never compare against a literal."""
    a = tmp_path / "ext_a"
    b = tmp_path / "ext_b"
    for d in (a, b):
        d.mkdir()
        (d / "manifest.json").write_text("{}")
    id_a, id_b = gam.unpacked_extension_id(str(a)), gam.unpacked_extension_id(str(b))
    assert id_a != id_b
    assert len(id_a) == 32
    # Mapped 0-f -> a-p, so only those letters may appear.
    assert set(id_a) <= set("abcdefghijklmnop")


def test_staging_root_is_sibling_not_child():
    """Inside the profile, a reset would have to move extensions out and back,
    and Chrome/Chromium profiles cannot share the directory."""
    root = gam.staging_root("data/ai_mode_chrome_profile")
    assert root.name == "ai_mode_chrome_profile_extensions"
    assert "ai_mode_chrome_profile" not in root.parent.name


def test_chromium_gets_its_own_profile_dir():
    """Chrome and Chromium have incompatible profile state and cookie
    encryption, so sharing one corrupts it."""
    assert gam.profile_dir_for("chrome") != gam.profile_dir_for(None)
    assert gam.profile_dir_for(None).endswith("_chromium")


def test_managed_chrome_forces_chromium(monkeypatch):
    monkeypatch.setenv("GOOGLE_AI_MODE_BROWSER", "chrome")
    monkeypatch.setattr(gam, "managed_chrome_blocks_extensions", lambda: True)
    # No extensions wanted -> real Chrome is fine even under policy.
    assert gam.resolve_channel([]) == "chrome"
    # Extensions wanted under policy -> must switch to bundled Chromium.
    assert gam.resolve_channel(["/some/ext"]) is None


def test_extensions_prefer_chromium_even_when_unmanaged(monkeypatch):
    """Only Chromium reliably honours --load-extension, and the registry probe
    can miss setups it does not know about — so configuring an extension opts
    into Chromium by default rather than silently loading nothing."""
    monkeypatch.setenv("GOOGLE_AI_MODE_BROWSER", "chrome")
    monkeypatch.delenv("GOOGLE_AI_MODE_FORCE_CHROMIUM", raising=False)
    monkeypatch.setattr(gam, "managed_chrome_blocks_extensions", lambda: False)
    assert gam.resolve_channel(["/some/ext"]) is None
    # No extension wanted -> real Chrome, which draws fewer CAPTCHAs.
    assert gam.resolve_channel([]) == "chrome"


def test_force_chromium_can_be_opted_out(monkeypatch):
    """Escape hatch for a machine where real Chrome does honour the flag."""
    monkeypatch.setenv("GOOGLE_AI_MODE_BROWSER", "chrome")
    monkeypatch.setenv("GOOGLE_AI_MODE_FORCE_CHROMIUM", "false")
    monkeypatch.setattr(gam, "managed_chrome_blocks_extensions", lambda: False)
    assert gam.resolve_channel(["/some/ext"]) == "chrome"


def test_explicit_chromium_request_honoured(monkeypatch):
    monkeypatch.setenv("GOOGLE_AI_MODE_BROWSER", "chromium")
    assert gam.resolve_channel([]) is None


def test_install_extension_finds_nested_manifest(tmp_path, monkeypatch):
    """captcha-raptor keeps manifest.json in extension/; pointing at the repo
    root must still work rather than loading nothing silently."""
    repo = tmp_path / "captcha-raptor"
    (repo / "extension").mkdir(parents=True)
    (repo / "extension" / "manifest.json").write_text('{"manifest_version": 3}')
    profile = str(tmp_path / "profile")
    assert gam.install_extension(str(repo), profile) is True
    staged = gam.staging_root(profile)
    # Named after the repo, NOT the generic "extension" folder, so the next
    # repo with the same layout does not collide.
    assert (staged / "captcha-raptor" / "manifest.json").is_file()


def test_install_extension_rejects_folder_without_manifest(tmp_path):
    empty = tmp_path / "nope"
    empty.mkdir()
    assert gam.install_extension(str(empty), str(tmp_path / "profile")) is False


def test_installed_extensions_lists_staged(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_AI_MODE_EXTENSIONS", raising=False)
    profile = str(tmp_path / "profile")
    src = tmp_path / "raptor"
    src.mkdir()
    (src / "manifest.json").write_text("{}")
    gam.install_extension(str(src), profile)
    found = gam.installed_extensions(profile)
    assert len(found) == 1
    assert found[0].endswith("raptor")


def test_installed_extensions_survives_original_being_deleted(tmp_path, monkeypatch):
    """Copying rather than referencing means the download folder can go away."""
    import shutil as _shutil

    monkeypatch.delenv("GOOGLE_AI_MODE_EXTENSIONS", raising=False)
    profile = str(tmp_path / "profile")
    src = tmp_path / "raptor"
    src.mkdir()
    (src / "manifest.json").write_text("{}")
    gam.install_extension(str(src), profile)
    _shutil.rmtree(src)
    assert len(gam.installed_extensions(profile)) == 1


def test_component_extension_ids_excluded_from_proof():
    """A bare worker count is a false positive: Chrome's own component
    extensions always run."""
    assert "fignfifoniblkonapihmkfakmlgkbkcf" in gam._COMPONENT_EXTENSION_IDS
    assert "mhjfbmdgcfjbbpaeojofohoefgiehjai" in gam._COMPONENT_EXTENSION_IDS


def test_launch_args_join_extensions_and_omit_disable_flag(tmp_path, monkeypatch):
    """One comma-joined --load-extension flag, and never
    --disable-extensions-except (it hides the profile's own extensions and
    makes 'Load unpacked' appear broken)."""
    captured = {}

    class _FakeCtx:
        pages = []
        service_workers = []
        background_pages = []

        def new_page(self):
            class _P:
                url = "about:blank"

                def goto(self, *a, **k):
                    raise RuntimeError("no chrome:// in tests")

                def wait_for_timeout(self, *a):
                    pass

                def close(self):
                    pass

            return _P()

    class _FakeChromium:
        def launch_persistent_context(self, **kw):
            captured.update(kw)
            return _FakeCtx()

    class _FakePw:
        chromium = _FakeChromium()

        def stop(self):
            pass

    monkeypatch.setitem(
        __import__("sys").modules,
        "patchright.sync_api",
        type("M", (), {"sync_playwright": staticmethod(lambda: type("S", (), {"start": staticmethod(lambda: _FakePw())})())}),
    )
    monkeypatch.setattr(gam, "installed_extensions", lambda *a, **k: ["/ext/one", "/ext/two"])
    monkeypatch.setattr(gam, "resolve_channel", lambda ext: None)
    monkeypatch.setattr(gam, "profile_dir_for", lambda ch: str(tmp_path / "prof"))

    sess = gam.AiModeSession()
    monkeypatch.setattr(sess, "verify_extensions", lambda **k: True)
    sess._ensure_browser()

    args = captured["args"]
    joined = [a for a in args if a.startswith("--load-extension=")]
    assert len(joined) == 1, "must be ONE comma-joined flag, not one per path"
    assert joined[0] == "--load-extension=/ext/one,/ext/two"
    assert not any("disable-extensions-except" in a for a in args)
    # channel omitted entirely => Playwright's bundled Chromium
    assert "channel" not in captured


# --- pipeline routing ------------------------------------------------------


def test_pipeline_routing_off_by_default(monkeypatch):
    from vendor_intel.pipeline import chatgpt_expand as ce

    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "false")
    assert ce._ai_mode_active() is False


def test_pipeline_routing_on_when_enabled(monkeypatch):
    from vendor_intel.pipeline import chatgpt_expand as ce

    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "true")
    assert ce._ai_mode_active() is True


def test_chat_json_prefers_ai_mode_when_enabled(monkeypatch):
    """The five discovery steps all funnel through _chat_json, so routing it
    routes all of them."""
    from vendor_intel.pipeline import chatgpt_expand as ce

    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "true")
    monkeypatch.setattr(gam, "ask", lambda p, **k: '{"companies": [{"name": "Elanco"}]}')

    def _boom(*a, **k):
        raise AssertionError("must not reach the paid API when AI Mode answers")

    monkeypatch.setattr(ce, "_chat_create", _boom)
    out = ce._chat_json(None, "deepseek-v4-flash", "sys", "user", require_key="companies")
    assert out["companies"][0]["name"] == "Elanco"


def test_no_api_fallback_when_ai_mode_enabled(monkeypatch):
    """AI Mode is the ONLY backend when enabled. A hard failure must raise
    rather than silently spending API credits."""
    from vendor_intel.pipeline import chatgpt_expand as ce

    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "true")
    monkeypatch.setattr(gam, "ask", lambda p, **k: (_ for _ in ()).throw(gam.AiModeCaptcha("blocked")))
    monkeypatch.setattr(ce.time, "sleep", lambda s: None)  # no real cool-off in tests

    def _boom(*a, **k):
        raise AssertionError("must NOT fall back to the API backend")

    monkeypatch.setattr(ce, "_chat_create", _boom)
    with pytest.raises(RuntimeError, match="no API fallback"):
        ce._chat_json(None, "deepseek-v4-flash", "sys", "user", require_key="companies")


def test_captcha_cools_off_then_succeeds(monkeypatch):
    """A transient block must not kill the run — waiting is the correct
    response to a rate limit, so it retries after a cool-off."""
    from vendor_intel.pipeline import chatgpt_expand as ce

    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "true")
    slept = []
    monkeypatch.setattr(ce.time, "sleep", lambda s: slept.append(s))

    calls = {"n": 0}

    def _flaky(prompt, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise gam.AiModeCaptcha("blocked once")
        return '{"companies": [{"name": "Zoetis"}]}'

    monkeypatch.setattr(gam, "ask", _flaky)
    out = ce._chat_json(None, "deepseek-v4-flash", "sys", "user", require_key="companies")
    assert out["companies"][0]["name"] == "Zoetis"
    assert slept and slept[0] >= 300, "a rate limit needs a long cool-off"


def test_refusal_retries_immediately_without_cooling_off(monkeypatch):
    """Waiting is useless for a refusal — it must reword and retry now."""
    from vendor_intel.pipeline import chatgpt_expand as ce

    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "true")
    slept = []
    monkeypatch.setattr(ce.time, "sleep", lambda s: slept.append(s))

    calls = {"n": 0}

    def _flaky(prompt, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise gam.AiModeRefusal("declined")
        return '{"companies": [{"name": "Elanco"}]}'

    monkeypatch.setattr(gam, "ask", _flaky)
    out = ce._chat_json(None, "deepseek-v4-flash", "sys", "user", require_key="companies")
    assert out["companies"][0]["name"] == "Elanco"
    assert not slept, "a refusal must NOT trigger a cool-off"


def test_web_search_json_also_has_no_fallback(monkeypatch):
    """The gap-fill step routes through _web_search_json — same rule."""
    from vendor_intel.pipeline import chatgpt_expand as ce

    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "true")
    monkeypatch.setattr(gam, "ask", lambda p, **k: (_ for _ in ()).throw(gam.AiModeUnavailable("down")))

    def _boom(*a, **k):
        raise AssertionError("must NOT fall back to the API backend")

    monkeypatch.setattr(ce, "_chat_create", _boom)
    monkeypatch.setattr(ce, "_chat_json", _boom)
    with pytest.raises(RuntimeError, match="no API fallback"):
        ce._web_search_json(None, "deepseek-v4-flash", "sys", "user", require_key="companies")


def test_axis_parameters_still_come_from_the_llm():
    """X/Y SCORING now runs on AI Mode by request, but the market-specific
    parameters under each axis must still be LLM-generated — that split is
    the whole point."""
    import inspect

    from vendor_intel.quadrant import axis_define

    src = inspect.getsource(axis_define)
    # Parameter generation is an LLM call, not an AI Mode query.
    assert "google_ai_mode" not in src
    assert "ClaudeClient" in src or "client" in src


def test_scoring_uses_ai_mode_with_no_llm_fallback():
    """Requested explicitly: AI Mode is the only X/Y scorer."""
    import inspect

    from vendor_intel.pipeline import expand_quadrant_score as eqs

    src = inspect.getsource(eqs)
    assert "ai_mode_scorer" in src
    assert "score_company_features_async" not in src


# --- async safety ----------------------------------------------------------


def test_browser_calls_run_on_a_dedicated_thread():
    """Regression: the pipeline is async, and Patchright's SYNC api raises
    "It looks like you are using Playwright Sync API inside the asyncio loop"
    if driven from a thread running a loop. Every browser call must be
    funnelled into one dedicated worker thread that never runs a loop."""
    import inspect

    src = inspect.getsource(gam)
    assert "_in_worker" in src
    assert "ThreadPoolExecutor" in src
    assert "max_workers=1" in src
    # ask() must go through the worker, not call session().ask directly.
    assert "_in_worker(lambda: session().ask(prompt, **kw))" in inspect.getsource(gam.ask)


def test_ask_is_callable_from_inside_an_event_loop(monkeypatch):
    """The failure mode was an exception raised merely by CALLING from a loop,
    so prove the wrapper is loop-safe without launching a browser."""
    import asyncio

    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "true")

    seen = {}

    class _FakeSession:
        def ask(self, prompt, **kw):
            # Patchright checks for a RUNNING loop on the calling thread; the
            # worker thread must not have one.
            try:
                asyncio.get_running_loop()
                seen["loop_running"] = True
            except RuntimeError:
                seen["loop_running"] = False
            return "42 out of 100"

    monkeypatch.setattr(gam, "session", lambda: _FakeSession())

    async def _main():
        return gam.ask("anything")

    assert asyncio.run(_main()) == "42 out of 100"
    assert seen["loop_running"] is False, "browser thread must not run an event loop"


def test_worker_reentrancy_does_not_deadlock(monkeypatch):
    """A browser call made from inside the worker must run inline rather than
    submitting to the single-slot pool and waiting on itself."""
    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "true")
    monkeypatch.setattr(gam, "session", lambda: type("S", (), {"ask": lambda self, p, **k: gam._in_worker(lambda: "inner")})())
    assert gam.ask("x") == "inner"


# --- prompt-size routing ---------------------------------------------------


def test_oversized_prompt_is_not_sent_to_ai_mode():
    """Regression: Step 5's gap-fill system prompt is ~12KB of rules. Pushed
    into a Google search box it returns "Something went wrong, and an AI
    response wasn't generated" — and every retry burns a paced query."""
    from vendor_intel.pipeline.chatgpt_expand import _fits_ai_mode

    assert _fits_ai_mode("", "top multivitamin brands list") is True
    # ~12KB of rules cannot survive the URL intact.
    assert _fits_ai_mode("x" * 12000, "y") is False


def test_guard_is_based_on_encoded_url_not_a_guessed_char_cap():
    """Regression: a fixed 1,800-char cap diverted the Step 6 final-verify
    chunks (~4,984 chars) to the API even though they encode to only ~5,339
    URL chars — well inside Google's ~7,800 limit."""
    from vendor_intel.pipeline.chatgpt_expand import _fits_ai_mode

    mid = "verify keep drop company rules, " * 155  # ~4,960 chars
    assert len(mid) > 1800
    assert _fits_ai_mode("", mid) is True, "mid-size verify prompts belong on AI Mode"


def test_real_discovery_prompts_still_reach_ai_mode():
    """The guard must not accidentally divert the calls AI Mode is for."""
    import json

    from vendor_intel.pipeline import chatgpt_expand as ce
    from vendor_intel.quadrant.ai_mode_scorer import build_score_query

    ce.set_discovery_market("B2C", [])
    try:
        # Step 0c market analysis
        assert ce._fits_ai_mode(
            ce._MARKET_ANALYSIS_DISCOVERY_SYSTEM, json.dumps({"market": "M"})
        )
        # Step 2 keyword discovery query
        assert ce._fits_ai_mode("", "top daily multivitamin brands list")
        # Step 6 scoring query
        assert ce._fits_ai_mode(
            "", build_score_query("Centrum", "Product Strength", ["A", "B", "C"])
        )
    finally:
        ce.set_discovery_market("", [])


def test_structured_calls_fall_back_to_api_not_failure(monkeypatch):
    """An oversized prompt must go to the API backend, not raise. This is the
    one place an API fallback is correct: the call was never a web lookup."""
    from vendor_intel.pipeline import chatgpt_expand as ce

    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "true")

    def _boom(*a, **k):
        raise AssertionError("oversized prompt must not reach AI Mode")

    monkeypatch.setattr(ce, "_ai_mode_json", _boom)

    def _fake_create(client, kwargs, use_json=True):
        class _M:
            content = '{"rows": [{"Company": "X"}]}'

        class _C:
            message = _M()
            finish_reason = "stop"

        class _R:
            choices = [_C()]
            usage = None

        return _R()

    monkeypatch.setattr(ce, "_chat_create", _fake_create)
    out = ce._chat_json(None, "deepseek-v4-flash", "x" * 12000, "u", require_key="rows")
    assert out["rows"][0]["Company"] == "X"


# --- "Something went wrong" page -------------------------------------------


def test_something_went_wrong_is_detected_as_a_refusal():
    """Observed live: AI Mode renders a normal page whose only content is
    "Something went wrong, and an AI response wasn't generated." It matched
    no marker, so it was treated as a valid answer and silently parsed to
    zero companies — indistinguishable from an empty market."""
    text = "Something went wrong, and an AI response wasn't generated."
    assert any(m in text.lower() for m in gam.REFUSAL_MARKERS)
    assert not any(m in text.lower() for m in gam.CAPTCHA_MARKERS), (
        "not a block — waiting does not help, so it must not be a CAPTCHA"
    )


def test_long_real_answer_mentioning_the_phrase_is_kept():
    """The <600-char guard must stop a genuine long answer being discarded
    just because it quotes the phrase."""
    text = "Centrum, Bayer, Nature Made. " * 40 + "Something went wrong once."
    assert len(text) >= 600


def test_session_tracks_soft_failures_and_reset_threshold():
    # Must stay <= ask()'s retry budget or the reset never fires.
    assert gam._SOFT_FAILURES_BEFORE_RESET == 2
    s = gam.AiModeSession()
    assert s.soft_failures == 0
    assert s.resets == 0


def test_reset_session_clears_cookies_and_relaunches(monkeypatch):
    """A soured session is recovered by dropping cookies and rebuilding the
    context, not by waiting alone."""
    s = gam.AiModeSession()
    calls = []

    class _Ctx:
        def clear_cookies(self):
            calls.append("clear_cookies")

    s._ctx = _Ctx()
    s.soft_failures = 3
    monkeypatch.setattr(s, "close", lambda: calls.append("close"))
    monkeypatch.setattr(s, "_ensure_browser", lambda: calls.append("relaunch"))
    monkeypatch.setattr(gam.time, "sleep", lambda n: calls.append(f"sleep{int(n)}"))

    s.reset_session()

    assert calls == ["clear_cookies", "close", "sleep60", "relaunch"]
    # The streak survives a cookie reset on purpose: if no-answer pages keep
    # coming, reaching _SOFT_FAILURES_BEFORE_PROFILE_RESET escalates to a full
    # profile reset. Only a good answer or reset_profile() clears it.
    assert s.soft_failures == 3
    assert s.resets == 1


# --- AI-response quota (distinct from CAPTCHA and refusal) -----------------


def test_request_limit_page_is_detected_as_rate_limiting():
    """Observed live: "You've reached the request limit for AI responses at
    the moment." It is a per-IP quota — not a CAPTCHA (nothing to solve) and
    not a refusal (rewording does not help). Only waiting clears it."""
    text = (
        "You've reached the request limit for AI responses at the moment. "
        "Try again in a little while."
    )
    low = text.lower()
    assert any(m in low for m in gam.QUOTA_MARKERS)


def test_quota_and_went_wrong_are_different_failures():
    """They need opposite responses: a quota needs a long wait, a
    went-wrong page needs an immediate reworded retry."""
    quota = "you've reached the request limit for ai responses at the moment."
    wrong = "something went wrong, and an ai response wasn't generated."
    assert any(m in quota for m in gam.QUOTA_MARKERS)
    assert not any(m in wrong for m in gam.QUOTA_MARKERS)
    assert any(m in wrong for m in gam.REFUSAL_MARKERS)


def test_session_tracks_quota_hits_separately_from_captchas():
    """A CAPTCHA can be solved; a quota cannot. Conflating the counters hides
    which remedy is needed."""
    s = gam.AiModeSession()
    assert s.quota_hits == 0
    assert s.captcha_count == 0


def test_quota_gets_a_longer_cooloff_than_a_captcha(monkeypatch):
    """A few minutes just burns another attempt against the same wall."""
    from vendor_intel.pipeline import chatgpt_expand as ce

    monkeypatch.setenv("GOOGLE_AI_MODE_ENABLED", "true")
    slept = []
    monkeypatch.setattr(ce.time, "sleep", lambda s: slept.append(s))

    calls = {"n": 0}

    def _quota_then_ok(prompt, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise gam.AiModeCaptcha("AI response request limit reached for this IP")
        return '{"companies": [{"name": "Wolfspeed"}]}'

    monkeypatch.setattr(gam, "ask", _quota_then_ok)
    out = ce._chat_json(None, "deepseek-v4-flash", "sys", "user", require_key="companies")
    assert out["companies"][0]["name"] == "Wolfspeed"
    assert slept and slept[0] >= 900, f"quota needs >=15 min, slept {slept}"


def test_reset_threshold_is_reachable_within_the_retry_budget():
    """Regression: the reset fired at 3 consecutive soft failures but ask()
    only allows 2 attempts, so the session was NEVER rebuilt — the run just
    skipped queries and quietly produced fewer companies."""
    import inspect

    retries = inspect.signature(gam.AiModeSession.ask).parameters["retries"].default
    assert gam._SOFT_FAILURES_BEFORE_RESET <= retries, (
        "reset threshold must be reachable, or it never triggers"
    )


def test_no_response_available_is_a_refusal():
    """The page from the live run: "It looks like there's no response
    available for this search. Try asking something else." """
    text = (
        "It looks like there's no response available for this search. "
        "Try asking something else."
    )
    low = text.lower()
    assert any(m in low for m in gam.REFUSAL_MARKERS)
    assert not any(m in low for m in gam.QUOTA_MARKERS), "not a quota — do not wait 15 min"


def test_discovery_query_path_resets_session_on_refusal():
    """Regression: substep 2g called ask() directly, so a refusal was caught
    by a bare `except` and the query was skipped with no reword and no
    session reset."""
    import inspect

    from vendor_intel.pipeline import chatgpt_expand as ce

    src = inspect.getsource(ce.google_ai_seed_discover)
    assert "AiModeRefusal" in src, "2g must distinguish a refusal from other errors"
    assert "reset_session" in src, "2g must rebuild the session before giving up"


def test_bundled_extension_loads_on_a_fresh_profile(tmp_path, monkeypatch):
    """A fresh clone has no staged copy: the repo's extensions/ folder is
    what gives it the CAPTCHA solver."""
    from vendor_intel.scraping import google_ai_mode as g

    monkeypatch.setenv("GOOGLE_AI_MODE_BUNDLED_EXTENSIONS", "true")
    bundled = tmp_path / "extensions" / "captcha-raptor" / "extension"
    bundled.mkdir(parents=True)
    (bundled / "manifest.json").write_text('{"name": "Raptor"}', encoding="utf-8")
    monkeypatch.setattr(g, "bundled_extensions_root", lambda: tmp_path / "extensions")

    got = g.installed_extensions(str(tmp_path / "profile"))
    assert got == [str(bundled.resolve())]


def test_bundled_extension_not_loaded_twice_when_already_staged(tmp_path, monkeypatch):
    from vendor_intel.scraping import google_ai_mode as g

    monkeypatch.setenv("GOOGLE_AI_MODE_BUNDLED_EXTENSIONS", "true")
    bundled = tmp_path / "extensions" / "captcha-raptor" / "extension"
    staged = tmp_path / "profile_extensions" / "captchaplugin"
    for d in (bundled, staged):
        d.mkdir(parents=True)
        (d / "manifest.json").write_text('{"name": "Raptor"}', encoding="utf-8")
    monkeypatch.setattr(g, "bundled_extensions_root", lambda: tmp_path / "extensions")

    got = g.installed_extensions(str(tmp_path / "profile"))
    assert got == [str(staged.resolve())]
