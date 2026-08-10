"""AI Overview cache, queue, bridge, and the two consumers that read it."""
from __future__ import annotations

import asyncio

import pytest

from vendor_intel.evidence.ai_overview import (
    AiOverviewStore,
    Question,
    clean_overview_markdown,
    extract_entries,
    extract_names,
    market_slug,
    question_key,
)


# ── keys and slugs ────────────────────────────────────────────────────────
def test_question_key_ignores_case_and_whitespace():
    assert question_key("Who makes  X?") == question_key("who makes x?")
    assert question_key("a") != question_key("b")


def test_market_slug_is_folder_safe():
    assert market_slug("Avocado Oil Market") == "avocado_oil_market"
    assert market_slug("ICT, Automation & Semiconductor") == "ict_automation_semiconductor"
    assert market_slug("") == "market"


# ── cleaning ──────────────────────────────────────────────────────────────
def test_clean_strips_serp_chrome():
    raw = "AI Overview\nSkip to main content\nImages\nAcme makes pumps.\nPeople also ask\nShow more"
    assert clean_overview_markdown(raw) == "Acme makes pumps."


def test_clean_drops_language_toggle_furniture():
    assert "Acme" in clean_overview_markdown("हिन्दी Acme Corp makes pumps.")


# ── extraction ────────────────────────────────────────────────────────────
def test_extract_keeps_companies_and_rejects_debris():
    md = (
        "- **Apple Inc.** — makes iPhones\n"
        "- Samsung Electronics: Korean OEM\n"
        "- Top 10 vendors\n"
        "- Workflow assistance\n"
        "- Singapore\n"
        "- Bed Count vs. Scale\n"
        "- Apollo Hospitals has\n"
    )
    names = extract_names(md)
    assert "Apple Inc." in names          # trailing abbreviation period survives
    assert "Samsung Electronics" in names
    for junk in ("Top 10 vendors", "Workflow assistance", "Singapore",
                 "Bed Count vs. Scale", "Apollo Hospitals has"):
        assert junk not in names


def test_extract_entries_keeps_descriptions():
    entries = extract_entries("- **Olivado** — a New Zealand avocado oil producer")
    assert entries[0].name == "Olivado"
    assert "New Zealand" in entries[0].description


def test_acronyms_survive_as_whole_names():
    assert "AT&T" in extract_names("- AT&T: US carrier")


# ── store ─────────────────────────────────────────────────────────────────
@pytest.fixture()
def store(tmp_path):
    return AiOverviewStore(tmp_path)


def test_miss_enqueues_and_hit_dequeues(store):
    q = Question(text="who makes rupture discs", market="Rupture Disc Market")
    assert store.ask(q) is None
    assert [p.text for p in store.pending()] == ["who makes rupture discs"]

    store.put(q, "- **Fike Corporation** — US maker")
    answer = store.ask(q)
    assert answer is not None and answer.ok
    assert store.pending() == []
    assert store.hits == 1 and store.misses == 1


def test_answer_survives_a_new_store_instance(tmp_path):
    q = Question(text="q1")
    AiOverviewStore(tmp_path).put(q, "Acme makes pumps.")
    assert AiOverviewStore(tmp_path).ask(q).markdown == "Acme makes pumps."


def test_empty_markdown_is_recorded_as_missing(store):
    q = Question(text="q2")
    assert store.put(q, "   ").overview_missing is True
    assert store.ask(q).ok is False


def test_cleaning_is_retroactive_on_read(store):
    """Answers are re-cleaned when read, so regex fixes apply to old cache rows."""
    q = Question(text="q3")
    store.put(q, "AI Overview\nShow more\nAcme makes pumps.")
    assert store.get(q).markdown == "Acme makes pumps."


def test_ttl_zero_treats_everything_as_stale(tmp_path):
    q = Question(text="q4")
    AiOverviewStore(tmp_path).put(q, "Acme makes pumps.")
    assert AiOverviewStore(tmp_path, ttl_days=0).get(q) is None


def test_manifest_round_trip(store, tmp_path):
    store.enqueue(Question(text="who makes valves"))
    manifest = store.write_manifest(tmp_path / "questions.json")
    assert manifest.is_file()

    (tmp_path / "answers.json").write_text(
        '{"answers":[{"question":"who makes valves","markdown":"- **Emerson** — maker"}]}',
        encoding="utf-8",
    )
    assert store.ingest_manifest(tmp_path / "answers.json") == 1
    assert store.pending() == []


# ── bridge ────────────────────────────────────────────────────────────────
@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("AI_OVERVIEW_CACHE_DIR", str(tmp_path))
    import vendor_intel.evidence.bridge as bridge

    bridge._stores.clear()  # module-level cache would leak between tests
    return TestClient(bridge.create_app("Test Market"))


def test_bridge_enqueue_pending_answer_cycle(client):
    assert client.get("/health").json()["ok"] is True

    client.post("/enqueue", json={"text": "who makes rupture discs"})
    pending = client.get("/pending", params={"limit": 10}).json()
    assert pending["count"] == 1

    posted = client.post(
        "/answers",
        json={
            "question": pending["questions"][0]["text"],
            "markdown": "- **Fike Corporation** — US maker",
            "citations": [{"title": "Fike", "url": "https://fike.com"}],
        },
    )
    assert posted.json() == {"saved": 1, "skipped": 0}
    assert client.get("/pending").json()["count"] == 0


def test_bridge_accepts_key_only_answer(client):
    client.post("/enqueue", json={"text": "who leads satcom"})
    key = client.get("/pending").json()["questions"][0]["key"]
    assert client.post("/answers", json={"key": key, "markdown": "- **Viasat** — operator"}).json()["saved"] == 1


def test_bridge_rejects_unresolvable_answer(client):
    assert client.post("/answers", json={"markdown": "orphan"}).status_code == 400


def test_bridge_enqueue_requires_text(client):
    assert client.post("/enqueue", json={"text": "  "}).status_code == 400


# ── quadrant KB consumer ──────────────────────────────────────────────────
def test_kb_queues_on_miss_then_absorbs_the_answer(tmp_path, monkeypatch):
    from vendor_intel.evidence.ai_overview import default_cache_dir
    from vendor_intel.quadrant.company_kb import build_company_kb

    monkeypatch.setenv("AI_OVERVIEW_CACHE_DIR", str(tmp_path))
    row = {"company": "Fike Corporation", "domain": "fike.com", "summary": "Maker of rupture discs."}
    market = "Rupture Disc Market"

    class OptedIn:
        ai_overview_enabled = True

    cold = asyncio.run(build_company_kb(row, market=market, settings=OptedIn()))
    assert cold["source"] == "pipeline_evidence_snapshot"

    store = AiOverviewStore(default_cache_dir(market))
    queued = store.pending()
    assert queued, "a cold KB build must queue questions for the extension"

    store.put(queued[0], "Fike Corporation makes rupture discs. Revenue is around $500 million.")
    warm = asyncio.run(build_company_kb(row, market=market, settings=OptedIn()))
    assert warm["source"] == "pipeline_evidence_snapshot+ai_overview"
    assert warm["revenue"] == "$500 million"
    assert any(c["origin"] == "ai_overview" for c in warm["chunks"])


def test_settings_flag_beats_stray_env_var(tmp_path, monkeypatch):
    """`Settings.load()` pushes .env into os.environ — an opted-out caller must stay out.

    Without this, running any pipeline with AI_OVERVIEW_ENABLED=true in .env made
    unrelated callers start writing queue files into the default cache directory.
    """
    from vendor_intel.quadrant.company_kb import build_company_kb

    monkeypatch.setenv("AI_OVERVIEW_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("AI_OVERVIEW_ENABLED", "true")  # the stray global

    class OptedOut:
        ai_overview_enabled = False

    kb = asyncio.run(build_company_kb({"company": "Acme"}, market="dental", settings=OptedOut()))
    assert kb["source"] == "pipeline_evidence_snapshot"
    assert not (tmp_path / "dental").exists(), "opted-out caller must not create a cache dir"


def test_kb_skips_ai_overview_without_a_market(tmp_path, monkeypatch):
    from vendor_intel.quadrant.company_kb import build_company_kb

    monkeypatch.setenv("AI_OVERVIEW_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("AI_OVERVIEW_ENABLED", "true")
    class OptedIn:
        ai_overview_enabled = True

    kb = asyncio.run(build_company_kb({"company": "Acme"}, market="", settings=OptedIn()))
    assert kb["source"] == "pipeline_evidence_snapshot"
    assert not list(tmp_path.iterdir())


def test_kb_ignores_ai_overview_when_disabled(tmp_path, monkeypatch):
    from vendor_intel.quadrant.company_kb import build_company_kb

    monkeypatch.setenv("AI_OVERVIEW_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("AI_OVERVIEW_ENABLED", raising=False)
    # no settings at all -> feature stays off
    kb = asyncio.run(build_company_kb({"company": "Acme"}, market="Some Market"))
    assert kb["source"] == "pipeline_evidence_snapshot"
    assert not (tmp_path / "some_market" / "_pending.jsonl").exists()


# ── uncapped selection ────────────────────────────────────────────────────
def test_pick_companies_uncapped_when_max_is_zero():
    from vendor_intel.quadrant.synthesize import _pick_companies

    rows = [{"company": f"C{i}", "quality_score": 1.0, "is_relevant": True} for i in range(50)]
    assert len(_pick_companies(rows, 0)) == 50
    assert len(_pick_companies(rows, 12)) == 12


def test_pick_companies_still_drops_irrelevant_rows():
    from vendor_intel.quadrant.synthesize import _pick_companies

    rows = [
        {"company": "In Scope", "quality_score": 0.9, "is_relevant": True},
        {"company": "Out Of Scope", "quality_score": 0.99, "is_relevant": False},
    ]
    assert [r["company"] for r in _pick_companies(rows, 0)] == ["In Scope"]


# ── uncapped export ───────────────────────────────────────────────────────
def test_export_cap_of_zero_means_uncapped():
    """`0 or default` silently restored the cap — 0 must survive as "no limit"."""
    from vendor_intel.pipeline.geo_limits import pipeline_limits

    class S:
        pipeline_export_max_rows = 0
        pipeline_global_export_max_rows = 0

    for country in ("Brazil", "global"):
        assert pipeline_limits(S(), recall=False, country=country)["export_max"] == 0


def test_export_cap_default_still_applies_when_unset():
    from vendor_intel.pipeline.geo_limits import pipeline_limits

    class S:
        pass

    assert pipeline_limits(S(), recall=False, country="Brazil")["export_max"] == 200
    assert pipeline_limits(S(), recall=False, country="global")["export_max"] == 240


def test_filter_for_export_uncapped_keeps_every_vetted_row():
    """max_rows=0 ships every row that cleared the gates; the gates still run."""
    from vendor_intel.pipeline.quality_export import filter_for_export

    query_context = {"industry": "Rupture Disc Market", "country": "global"}
    scope = {
        "market": "Rupture Disc Market",
        "relevance_keywords": ["rupture disc", "pressure relief"],
        "industry_terms": ["rupture disc"],
    }
    rows = [
        {
            "company": f"Co{i}",
            "domain": f"co{i}.com",
            "is_relevant": True,
            "confidence": 0.9,
            "role": "Manufacturer",
            "summary": "Manufactures rupture discs and pressure relief devices.",
            "key_products": "rupture discs, pressure relief devices",
            "main_product": "rupture discs",
        }
        for i in range(8)
    ]
    enriched = {
        f"Co{i}": {
            "page_text": "We manufacture rupture discs and pressure relief devices for industrial plants.",
            "data": {"business": {"products": ["rupture discs"]}},
        }
        for i in range(8)
    }

    uncapped, _ = filter_for_export(
        rows, enriched, query_context, scope=scope, max_rows=0, min_quality=0.0
    )
    capped, _ = filter_for_export(
        rows, enriched, query_context, scope=scope, max_rows=3, min_quality=0.0
    )
    assert len(uncapped) == 8
    assert len(capped) == 3


def test_filter_for_export_uncapped_still_drops_off_scope_rows():
    """Uncapping must not become "export everything" — the scope gate still bites."""
    from vendor_intel.pipeline.quality_export import filter_for_export

    query_context = {"industry": "Rupture Disc Market", "country": "global"}
    scope = {"market": "Rupture Disc Market", "relevance_keywords": ["rupture disc"]}
    off_scope = [
        {
            "company": "Bakery Co",
            "domain": "bakery.com",
            "is_relevant": True,
            "confidence": 0.9,
            "role": "Manufacturer",
            "summary": "Bakes bread and pastries for supermarkets.",
            "key_products": "bread, pastries",
        }
    ]
    enriched = {"Bakery Co": {"page_text": "We bake bread and pastries for supermarkets."}}
    kept, rejected = filter_for_export(
        off_scope, enriched, query_context, scope=scope, max_rows=0, min_quality=0.0
    )
    assert kept == []
    assert rejected and rejected[0]["export_reject"]


# ── one cache key per market ──────────────────────────────────────────────
def test_market_key_prefers_operator_string_over_normalised_topic():
    """Discovery and the quadrant must land in the SAME cache directory.

    scope["market"] is the normalised search topic ("rupture disc"); the operator
    typed "Rupture Disc Market" and passes that to `run_ai_bridge.py --market`.
    Keying off scope split one market across two directories.
    """
    from vendor_intel.evidence.ai_overview import market_slug, resolve_market_key

    qc = {"industry": "Rupture Disc Market", "country": "USA"}
    scope = {"market": "rupture disc"}
    assert resolve_market_key(qc, scope) == "Rupture Disc Market"
    assert market_slug(resolve_market_key(qc, scope)) == "rupture_disc_market"


def test_market_key_falls_back_through_scope_then_query():
    from vendor_intel.evidence.ai_overview import resolve_market_key

    assert resolve_market_key({}, {"market": "rupture disc"}) == "rupture disc"
    assert resolve_market_key({"query": "who makes discs"}, {}) == "who makes discs"
    assert resolve_market_key({}, {}) == ""


def test_both_consumers_resolve_to_the_same_directory():
    from vendor_intel.evidence.ai_overview import default_cache_dir, resolve_market_key

    qc = {"industry": "Rupture Disc Market"}
    scope = {"market": "rupture disc"}
    # discovery (orchestrator) and quadrant (synthesize) now call the same resolver
    assert default_cache_dir(resolve_market_key(qc, scope)) == default_cache_dir(
        resolve_market_key(qc, scope)
    )
    assert default_cache_dir(resolve_market_key(qc, scope)).name == "rupture_disc_market"


# ── cross-process queue visibility ────────────────────────────────────────
def test_store_reload_picks_up_another_processes_enqueue(tmp_path):
    """The pipeline enqueues from its own process while the bridge is running."""
    bridge_side = AiOverviewStore(tmp_path)
    assert bridge_side.pending() == []

    AiOverviewStore(tmp_path).enqueue(Question(text="queued by the pipeline"))
    assert bridge_side.pending() == [], "in-memory queue is stale until reloaded"

    assert bridge_side.reload_queue() == 1
    assert [q.text for q in bridge_side.pending()] == ["queued by the pipeline"]


def test_bridge_pending_sees_questions_queued_after_startup(client, tmp_path):
    """Regression: the collect-and-rerun loop died after the first batch.

    /pending served the queue as it was when the bridge booted, so anything the
    pipeline enqueued mid-run was invisible and the extension idled forever.
    """
    assert client.get("/pending").json()["count"] == 0

    # simulate the pipeline process writing to the same cache dir
    from vendor_intel.evidence.ai_overview import default_cache_dir

    AiOverviewStore(default_cache_dir("Test Market")).enqueue(
        Question(text="which companies make rupture discs", market="Test Market")
    )

    served = client.get("/pending").json()
    assert served["count"] == 1
    assert served["questions"][0]["text"] == "which companies make rupture discs"


# ── extraction hardening (from real AI Overview answers) ──────────────────
def test_locative_tail_is_cut_not_rejected():
    """These were real rows: cutting the tail RECOVERS the company."""
    from vendor_intel.evidence.ai_overview import strip_trailing_clause

    cases = {
        "Continental Disc Corporation located in Liberty": "Continental Disc Corporation",
        "ZOOK Enterprises LLC based in Chagrin Falls": "ZOOK Enterprises LLC",
        "BS&B Safety Systems located in Tulsa": "BS&B Safety Systems",
        "Fike Corporation headquartered in Blue Springs": "Fike Corporation",
        "Acme Corp which supplies discs": "Acme Corp",
        "Fike Corporation": "Fike Corporation",
    }
    for raw, want in cases.items():
        assert strip_trailing_clause(raw) == want


def test_us_states_and_provinces_are_not_companies():
    """Splitting "…in Liberty, Missouri" left the state standing alone."""
    names = extract_names(
        "- Missouri\n- Ohio\n- Oklahoma\n- Ontario\n- Quebec\n- Alberta\n- Fike Corporation"
    )
    assert names == ["Fike Corporation"]


def test_assistant_filler_is_rejected():
    assert extract_names("- I can help you find rupture disc suppliers") == []
    assert extract_names("- Let me know if you need more") == []


def test_swallowed_marketing_blurb_is_rejected():
    """Real row: "About ZOOK. Your Pressure Relief Partner. ZOOK"."""
    assert extract_names("- About ZOOK. Your Pressure Relief Partner. ZOOK") == []


def test_conjoined_companies_split_into_two_leads():
    from vendor_intel.evidence.ai_overview import split_conjoined_names

    assert split_conjoined_names("Fike Corporation & Continental Disc Corporation") == [
        "Fike Corporation",
        "Continental Disc Corporation",
    ]
    assert extract_names("- Fike Corporation & Continental Disc Corporation") == [
        "Fike Corporation",
        "Continental Disc Corporation",
    ]


def test_ampersand_names_are_not_split():
    """Splitting must not damage real names containing an ampersand."""
    from vendor_intel.evidence.ai_overview import split_conjoined_names

    for name in ("Procter & Gamble", "BS&B Safety Systems", "Rembe GmbH Safety + Control"):
        assert split_conjoined_names(name) == [name]


def test_real_companies_still_survive_the_new_filters():
    """The hardening must not cost recall on the names we actually want."""
    md = (
        "- **Spartan Controls** — Canadian distributor\n"
        "- Unified Valve Group\n"
        "- ParVal Equipment Ltd.\n"
        "- Matheson Control Solutions Inc.\n"
        "- ATEX do Brasil\n"
        "- OsecoElfab\n"
        "- Haskel International\n"
    )
    names = extract_names(md)
    for want in ("Spartan Controls", "Unified Valve Group", "ParVal Equipment Ltd.",
                 "Matheson Control Solutions Inc.", "ATEX do Brasil", "OsecoElfab",
                 "Haskel International"):
        assert want in names, f"lost a real company: {want}"


def test_put_does_not_resurrect_a_cleared_queue(tmp_path):
    """The bridge clobbered an external reset by writing its stale queue back.

    Real symptom: pending went 4 -> 498 after another process cleared the queue,
    because the next answer POST rewrote the whole file from memory.
    """
    writer = AiOverviewStore(tmp_path)
    for i in range(5):
        writer.enqueue(Question(text=f"q{i}"))

    holder = AiOverviewStore(tmp_path)          # loads all 5 into memory
    assert len(holder.pending()) == 5

    AiOverviewStore(tmp_path).reset_queue()     # another process clears it
    holder.put(Question(text="q0"), "an answer")  # holder must not restore q1..q4

    assert AiOverviewStore(tmp_path).pending() == []


def test_enqueue_does_not_erase_another_processes_questions(tmp_path):
    a = AiOverviewStore(tmp_path)
    b = AiOverviewStore(tmp_path)
    a.enqueue(Question(text="from A"))
    b.enqueue(Question(text="from B"))   # b's in-memory copy predates A's write
    assert {q.text for q in AiOverviewStore(tmp_path).pending()} == {"from A", "from B"}
