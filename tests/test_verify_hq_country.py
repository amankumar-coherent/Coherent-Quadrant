"""Single-country runs keep only companies headquartered in that country."""
from vendor_intel.pipeline import chatgpt_expand as ce


def _run(monkeypatch, country, answers):
    prompts = {}

    def fake_chat(client, model, *, system, user, **k):
        prompts["system"] = system
        return {"results": answers}

    monkeypatch.setattr(ce, "_chat_json", fake_chat)
    monkeypatch.setattr(ce, "player_label", lambda q, f="": "Brand / Marketer")
    companies = [{"name": a["name"]} for a in answers]
    kept, rejected = ce.gpt_verify_market(None, "m", query="Smart Ring Market",
                                          family="general", companies=companies,
                                          country=country)
    return [k["name"] for k in kept], rejected, prompts["system"]


def _ans(name, hq):
    row = {"name": name, "in_market": True, "builds_or_owns": True,
           "role": "Brand / Marketer", "fits_criteria": True, "confidence": 90,
           "reason": "sells smart rings", "operating_status": "active"}
    if hq is not None:
        row["hq_in_country"] = hq
    return row


def test_india_run_drops_foreign_hq(monkeypatch):
    kept, rejected, system = _run(monkeypatch, "india", [
        _ans("Ultrahuman", True), _ans("Oura", False), _ans("NoAnswer Co", None)])
    assert kept == ["Ultrahuman"]
    assert "HQ RULE" in system and "india" in system
    assert all("headquarters not in india" in r["reason"] for r in rejected)


def test_global_run_has_no_hq_rule(monkeypatch):
    kept, _, system = _run(monkeypatch, "global", [_ans("Oura", None)])
    assert kept == ["Oura"]
    assert "HQ RULE" not in system


def test_company_that_no_longer_operates_is_dropped(monkeypatch):
    """A bankrupt / absorbed company still has a web footprint; verification
    keeps only companies the verifier confirms still operate today, and a
    missing status fails closed like the HQ answer."""
    gone = dict(_ans("Defunct Co", None), operating_status="defunct",
                status_note="Filed for Chapter 7 bankruptcy in 2016.")
    absorbed = dict(_ans("Absorbed Co", None), operating_status="acquired")
    unknown = {k: v for k, v in _ans("Unknown Co", None).items() if k != "operating_status"}
    kept, rejected, system = _run(monkeypatch, "global",
                                  [_ans("Oura", None), gone, absorbed, unknown])
    assert kept == ["Oura"]
    assert "STATUS RULE" in system
    reasons = {r["name"]: r["reason"] for r in rejected}
    assert "Chapter 7" in reasons["Defunct Co"] and "acquired" in reasons["Absorbed Co"]
    assert "not an active company" in reasons["Unknown Co"]
