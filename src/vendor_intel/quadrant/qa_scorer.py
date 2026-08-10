"""Answer evaluation questions using KB evidence + model knowledge when needed."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from vendor_intel.quadrant.company_kb import kb_text_blob
from vendor_intel.quadrant.criteria_catalog import load_scoring_weights
from vendor_intel.quadrant.schema import FeatureQuestions, QuestionAnswer

# ClaudeClient / Settings imported lazily to keep unit tests light.

_SYSTEM_ONE = """You are a market-research analyst scoring a vendor evaluation question for a Coherent Quadrant.

Return JSON only:
{
  "score": 1-10 integer,
  "answer": "one sentence explaining the score",
  "evidence_urls": ["urls from the knowledge base if any"],
  "evidence_snippets": ["short quotes from KB and/or concise model-knowledge notes"],
  "grounding": "supported" | "partial" | "model_knowledge" | "insufficient"
}

Scoring policy (IMPORTANT):
- Prefer the knowledge_base / evidence_snippets when they answer the question → grounding=supported (or partial if incomplete).
- If the KB is thin or silent, you MUST still score using your own knowledge of the brand, domain, market role, and typical industry standing for a company of this type. Use grounding=model_knowledge.
- Do NOT give a low score (1–3) merely because crawl evidence is missing. Low scores are only for weak real-world capability on that question.
- Score 1–10 relative to global peers in this market. Well-known leaders should score high; niche/emerging players lower — based on substance, not evidence availability.
- Never invent precise financial figures, certifications, or customer names as hard facts when unsupported; you may still judge capability qualitatively from known brand position.
- Prefer grounding=insufficient only when the brand is unknown / unassessable; even then keep score in a neutral mid band (4–6), not 1–2."""

_SYSTEM_BATCH = """You are a market-research analyst scoring MULTIPLE vendor evaluation questions for ONE brand (Coherent Quadrant).

Return JSON only:
{
  "answers": [
    {
      "id": "exact id from input",
      "score": 1-10 integer,
      "answer": "one sentence explaining the score",
      "evidence_urls": ["urls from the knowledge base if any"],
      "evidence_snippets": ["short quotes from KB and/or concise model-knowledge notes"],
      "grounding": "supported" | "partial" | "model_knowledge" | "insufficient"
    }
  ]
}

Scoring policy (IMPORTANT):
- Return one entry per input question id — same ids, same count.
- Prefer knowledge_base / evidence when present → grounding=supported or partial.
- If KB is thin or silent for a question, score using your own knowledge of the brand, domain, and market role → grounding=model_knowledge.
- Do NOT give scores of 1–3 merely because crawl evidence is missing. Low scores only for genuinely weak capability on that criterion versus peers.
- Score 1–10 relative to global peers. Famous leaders score high; niche brands lower — based on substance, not evidence availability.
- Do not invent precise unsupported financials/certs/customer lists as hard facts; qualitative judgment from known brand position is allowed.
- grounding=insufficient only if the brand is truly unknown; then use a neutral mid score (4–6), never 1–2."""


def _heuristic_score(
    question: str,
    kb_text: str,
    *,
    brand: str = "",
    score_floor: int = 4,
) -> QuestionAnswer:
    """Keyword fallback when LLM is unavailable — never collapses to 1–2."""
    q = (question or "").lower()
    text = (kb_text or "").lower()
    brand_l = (brand or "").lower()
    floor = max(1, min(10, int(score_floor)))

    if len(text) < 40:
        # Unknown evidence — neutral mid score, not a penalty
        base = 5 if brand_l else floor
        return QuestionAnswer(
            question=question,
            score=max(floor, base),
            answer=(
                f"No crawl KB for {brand or 'this company'}; "
                "heuristic neutral score pending LLM knowledge scoring."
            ),
            grounding="model_knowledge",
        )

    tokens = [t for t in re_tokens(q) if len(t) > 3]
    hits = sum(1 for t in tokens if t in text)
    if hits == 0:
        return QuestionAnswer(
            question=question,
            score=max(floor, 5),
            answer="KB silent on this question; heuristic uses neutral mid-band score.",
            grounding="model_knowledge",
            evidence_snippets=[kb_text[:180]] if kb_text else [],
        )
    ratio = hits / max(len(tokens), 1)
    score = int(round(floor + ratio * (10 - floor)))
    score = max(floor, min(10, score))
    return QuestionAnswer(
        question=question,
        score=score,
        answer="Signal found in knowledge base (heuristic).",
        evidence_snippets=[kb_text[:180]],
        grounding="partial",
    )


def re_tokens(s: str) -> list[str]:
    import re

    return re.findall(r"[a-z0-9]+", (s or "").lower())


def _clamp_answer_fields(
    *,
    question: str,
    weight: float,
    raw: dict[str, Any],
    score_floor: int,
    allow_model_knowledge: bool,
) -> QuestionAnswer:
    grounding = str(raw.get("grounding") or "model_knowledge").lower().strip()
    if grounding not in ("supported", "partial", "model_knowledge", "insufficient"):
        # Map legacy / unknown labels
        if grounding in ("kb", "evidence"):
            grounding = "supported"
        elif grounding in ("llm", "knowledge", "prior"):
            grounding = "model_knowledge"
        else:
            grounding = "model_knowledge" if allow_model_knowledge else "insufficient"
    try:
        score = int(round(float(raw.get("score"))))
    except (TypeError, ValueError):
        score = max(4, score_floor)
    score = max(1, min(10, score))

    # Never punish missing crawl evidence with 1–3.
    floor = max(1, min(10, int(score_floor)))
    if allow_model_knowledge and score < floor:
        score = floor
    if grounding == "insufficient" and allow_model_knowledge and score < 4:
        score = 4

    urls = [str(u) for u in (raw.get("evidence_urls") or []) if u][:5]
    snippets = [str(s) for s in (raw.get("evidence_snippets") or []) if s][:5]
    return QuestionAnswer(
        question=question,
        weight=weight,
        score=score,
        answer=str(raw.get("answer") or "")[:400],
        evidence_urls=urls,
        evidence_snippets=snippets,
        grounding=grounding,  # type: ignore[arg-type]
    )


def answer_question(
    question: str,
    weight: float,
    kb: dict[str, Any],
    *,
    settings: Any = None,
    client: Any = None,
) -> QuestionAnswer:
    """Single-question path (tests / fallback). Prefer batched scorers in production."""
    cfg = load_scoring_weights()
    score_floor = int(cfg.get("score_floor") or 4)
    allow_mk = bool(cfg.get("allow_model_knowledge", True))
    max_chars = int(cfg.get("kb_total_chars") or 12000)
    kb_text = kb_text_blob(kb, max_chars=max_chars)
    brand = str(kb.get("brand") or "")

    from vendor_intel.clients.claude import ClaudeClient
    from vendor_intel.config import Settings

    settings = settings or Settings.load()
    client = client or ClaudeClient(settings)
    if not client.available:
        ans = _heuristic_score(
            question, kb_text, brand=brand, score_floor=score_floor
        )
        ans.weight = weight
        return ans

    try:
        user = {
            "brand": brand,
            "domain": kb.get("domain"),
            "market_context": kb.get("market") or kb.get("industry") or "",
            "question": question,
            "knowledge_base": kb_text
            or "(empty — score from your knowledge of this brand/domain)",
            "policy": "Use KB when present; otherwise use model knowledge. Do not penalize missing crawl text.",
        }
        raw = client.complete_json(
            _SYSTEM_ONE,
            json.dumps(user, ensure_ascii=False),
            model=getattr(settings, "classifier_model", None),
            max_tokens=800,
        )
        if not isinstance(raw, dict):
            ans = _heuristic_score(
                question, kb_text, brand=brand, score_floor=score_floor
            )
            ans.weight = weight
            return ans
        return _clamp_answer_fields(
            question=question,
            weight=weight,
            raw=raw,
            score_floor=score_floor,
            allow_model_knowledge=allow_mk,
        )
    except Exception as exc:
        print(f"  [quadrant] QA LLM failed: {exc}", flush=True)
        ans = _heuristic_score(
            question, kb_text, brand=brand, score_floor=score_floor
        )
        ans.weight = weight
        return ans


def _flatten_questions_full(
    feature_questions: list[FeatureQuestions],
) -> list[tuple[str, str, str, str, float]]:
    """Return [(id, feature, axis, question_text, weight), ...]."""
    out: list[tuple[str, str, str, str, float]] = []
    for fi, fq in enumerate(feature_questions):
        for qi, item in enumerate(fq.items):
            out.append((f"f{fi}_q{qi}", fq.feature, fq.axis, item.text, float(item.weight)))
    return out


def _answers_from_batch_raw(
    raw: Any,
    items: list[tuple[str, str, str, str, float]],
    kb_text: str,
    *,
    brand: str,
    score_floor: int,
    allow_model_knowledge: bool,
) -> dict[str, QuestionAnswer]:
    by_id: dict[str, QuestionAnswer] = {}
    rows = []
    if isinstance(raw, dict):
        rows = raw.get("answers") or raw.get("results") or []
    elif isinstance(raw, list):
        rows = raw

    parsed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or row.get("question_id") or "").strip()
        if not rid and "question" in row:
            qtext = str(row.get("question") or "").strip()
            for qid, _f, _a, text, _w in items:
                if text == qtext:
                    rid = qid
                    break
        if rid:
            parsed[rid] = row

    for qid, _feat, _axis, text, weight in items:
        if qid in parsed:
            by_id[qid] = _clamp_answer_fields(
                question=text,
                weight=weight,
                raw=parsed[qid],
                score_floor=score_floor,
                allow_model_knowledge=allow_model_knowledge,
            )
        else:
            ans = _heuristic_score(
                text, kb_text, brand=brand, score_floor=score_floor
            )
            ans.weight = weight
            by_id[qid] = ans
    return by_id


def _pack_feature_results(
    feature_questions: list[FeatureQuestions],
    by_id: dict[str, QuestionAnswer],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fi, fq in enumerate(feature_questions):
        answers: list[QuestionAnswer] = []
        scores: list[float] = []
        weights: list[float] = []
        for qi, item in enumerate(fq.items):
            qid = f"f{fi}_q{qi}"
            ans = by_id.get(qid)
            if ans is None:
                ans = QuestionAnswer(
                    question=item.text,
                    weight=float(item.weight),
                    score=5,
                    grounding="model_knowledge",
                    answer="",
                )
            answers.append(ans)
            scores.append(float(ans.score))
            weights.append(float(ans.weight or item.weight))
        out.append(
            {
                "feature": fq.feature,
                "axis": fq.axis,
                "answers": answers,
                "scores": scores,
                "weights": weights,
            }
        )
    return out


def _llm_batch_score(
    *,
    client: Any,
    settings: Any,
    brand: str,
    domain: str,
    kb_text: str,
    items: list[tuple[str, str, str, str, float]],
) -> Any:
    payload = {
        "brand": brand,
        "domain": domain,
        "knowledge_base": kb_text
        or "(empty — score each question from your knowledge of this brand/domain)",
        "policy": (
            "Prefer KB evidence when present. If KB is thin/silent, use model knowledge. "
            "Do not assign low scores only because crawl evidence is missing."
        ),
        "questions": [
            {"id": qid, "feature": feat, "axis": axis, "question": text}
            for qid, feat, axis, text, _w in items
        ],
    }
    return client.complete_json(
        _SYSTEM_BATCH,
        json.dumps(payload, ensure_ascii=False),
        model=getattr(settings, "classifier_model", None),
        max_tokens=min(8192, 400 + 250 * max(len(items), 1)),
    )


def score_company_features(
    kb: dict[str, Any],
    feature_questions: list[FeatureQuestions],
    *,
    settings: Any = None,
    client: Any = None,
    batch_mode: str | None = None,
) -> list[dict[str, Any]]:
    """
    Score all features for one company.

    batch_mode:
      - "company" (default): one LLM call for all questions
      - "feature": one LLM call per feature (3 questions)
      - "none": one LLM call per question (legacy)
    """
    cfg = load_scoring_weights()
    mode = (batch_mode or cfg.get("qa_batch_mode") or "company").strip().lower()
    if mode not in ("company", "feature", "none"):
        mode = "company"

    score_floor = int(cfg.get("score_floor") or 4)
    allow_mk = bool(cfg.get("allow_model_knowledge", True))
    max_chars = int(cfg.get("kb_total_chars") or 12000)
    kb_text = kb_text_blob(kb, max_chars=max_chars)
    brand = str(kb.get("brand") or "")
    domain = str(kb.get("domain") or "")

    llm_ok = bool(client is not None and getattr(client, "available", False))
    if client is None:
        try:
            from vendor_intel.clients.claude import ClaudeClient
            from vendor_intel.config import Settings

            settings = settings or Settings.load()
            client = ClaudeClient(settings)
            llm_ok = bool(client.available)
        except Exception:
            llm_ok = False

    # No LLM → heuristics only (still floors scores — never 1–2 for empty KB)
    if not llm_ok:
        by_id: dict[str, QuestionAnswer] = {}
        for qid, _f, _a, text, weight in _flatten_questions_full(feature_questions):
            ans = _heuristic_score(
                text, kb_text, brand=brand, score_floor=score_floor
            )
            ans.weight = weight
            by_id[qid] = ans
        return _pack_feature_results(feature_questions, by_id)

    # Thin KB is OK: still call LLM so it can use model knowledge of the brand.
    if settings is None:
        try:
            from vendor_intel.config import Settings

            settings = Settings.load()
        except Exception:
            settings = None

    if mode == "none":
        out: list[dict[str, Any]] = []
        for fq in feature_questions:
            answers: list[QuestionAnswer] = []
            scores: list[float] = []
            weights: list[float] = []
            for item in fq.items:
                ans = answer_question(
                    item.text, item.weight, kb, settings=settings, client=client
                )
                answers.append(ans)
                scores.append(float(ans.score))
                weights.append(float(ans.weight or item.weight))
            out.append(
                {
                    "feature": fq.feature,
                    "axis": fq.axis,
                    "answers": answers,
                    "scores": scores,
                    "weights": weights,
                }
            )
        return out

    if mode == "feature":
        by_id = {}
        for fi, fq in enumerate(feature_questions):
            items = [
                (f"f{fi}_q{qi}", fq.feature, fq.axis, item.text, float(item.weight))
                for qi, item in enumerate(fq.items)
            ]
            try:
                raw = _llm_batch_score(
                    client=client,
                    settings=settings,
                    brand=brand,
                    domain=domain,
                    kb_text=kb_text,
                    items=items,
                )
                by_id.update(
                    _answers_from_batch_raw(
                        raw,
                        items,
                        kb_text,
                        brand=brand,
                        score_floor=score_floor,
                        allow_model_knowledge=allow_mk,
                    )
                )
            except Exception as exc:
                print(f"  [quadrant] feature-batch QA failed ({fq.feature[:40]}): {exc}", flush=True)
                for qid, _f, _a, text, weight in items:
                    ans = _heuristic_score(
                        text, kb_text, brand=brand, score_floor=score_floor
                    )
                    ans.weight = weight
                    by_id[qid] = ans
        return _pack_feature_results(feature_questions, by_id)

    # company batch — single call (works with thin or empty KB)
    items = _flatten_questions_full(feature_questions)
    try:
        raw = _llm_batch_score(
            client=client,
            settings=settings,
            brand=brand,
            domain=domain,
            kb_text=kb_text,
            items=items,
        )
        by_id = _answers_from_batch_raw(
            raw,
            items,
            kb_text,
            brand=brand,
            score_floor=score_floor,
            allow_model_knowledge=allow_mk,
        )
    except Exception as exc:
        print(f"  [quadrant] company-batch QA failed ({brand[:40]}): {exc}", flush=True)
        by_id = {}
        for qid, _f, _a, text, weight in items:
            ans = _heuristic_score(
                text, kb_text, brand=brand, score_floor=score_floor
            )
            ans.weight = weight
            by_id[qid] = ans
    return _pack_feature_results(feature_questions, by_id)


async def score_company_features_async(
    kb: dict[str, Any],
    feature_questions: list[FeatureQuestions],
    *,
    settings: Any = None,
    client: Any = None,
    batch_mode: str | None = None,
) -> list[dict[str, Any]]:
    """Run sync batched scorer in a worker thread so brand pool can overlap LLM I/O."""
    return await asyncio.to_thread(
        score_company_features,
        kb,
        feature_questions,
        settings=settings,
        client=client,
        batch_mode=batch_mode,
    )
