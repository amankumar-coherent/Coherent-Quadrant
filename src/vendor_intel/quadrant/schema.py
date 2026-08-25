"""Pydantic models for CMI Quadrant_Brands + Quadrant_Scorecard (+ audit)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

QuadrantName = Literal["Leaders", "Challengers", "Trailblazers", "Emerging Players"]
TierName = Literal["Tier 1", "Tier 2", "Tier 3"]
RatingName = Literal["very-high", "high", "average", "low", "very-low"]
AxisName = str  # market-specific; legacy defaults: Solution Capability / Business Strategy
GroundingName = Literal["supported", "partial", "model_knowledge", "insufficient"]


class QuestionItem(BaseModel):
    text: str
    weight: float = 0.33


class FeatureQuestions(BaseModel):
    feature: str
    axis: AxisName
    items: list[QuestionItem] = Field(default_factory=list)


class QuadrantBrand(BaseModel):
    brand: str
    quadrant: QuadrantName
    execution: int
    innovation: int
    top_pct: int = 50
    left_pct: int = 50
    color: str = "#002857"
    tier: TierName = "Tier 2"
    overall: int = 0
    revenue: str = ""
    yoy_growth: str = ""
    top_strength: str = ""
    # Chart / Brand column: plain brand name (no acquired-by suffix)
    display_name: str = ""
    # Company column: "acquired by Parent" when known
    company: str = ""
    # "Founded in" column: location (not year); mirrors founded_location
    founded_in: str = ""
    founded_location: str = ""
    hq_location: str = ""
    # True = plotted on the quadrant graph (top 15–20); table can include many more
    on_chart: bool = False
    # Brand / Marketer (food) or Solution Developer (tech)
    commercial_role: str = ""
    company_function: str = ""

    @field_validator("execution", "innovation", "overall", "top_pct", "left_pct", mode="before")
    @classmethod
    def _intish(cls, v: Any) -> int:
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return 0


class ScorecardRow(BaseModel):
    brand: str
    axis: AxisName
    criterion: str
    rating: RatingName
    notes: str = ""


class QuestionAnswer(BaseModel):
    question: str
    weight: float = 0.33
    score: int = 3
    answer: str = ""
    evidence_urls: list[str] = Field(default_factory=list)
    evidence_snippets: list[str] = Field(default_factory=list)
    grounding: GroundingName = "insufficient"


class FeatureScoreDetail(BaseModel):
    brand: str
    feature: str
    axis: AxisName
    sub_avg: float
    contribution: float
    rating: RatingName
    answers: list[QuestionAnswer] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    brand: str
    field: str
    status: Literal["retrieved", "approximated", "unknown"] = "unknown"
    source_url: str = ""
    snippet: str = ""
    method: str = ""


class CoherentQuadrantPayload(BaseModel):
    schema_version: str = "cmi-quadrant-v1"
    market: str = ""
    geography: str = ""
    industry_group: str = ""
    industry_category: str = ""
    criteria: dict[str, Any] = Field(default_factory=dict)
    questions: list[FeatureQuestions] = Field(default_factory=list)
    brands: list[QuadrantBrand] = Field(default_factory=list)
    scorecard: list[ScorecardRow] = Field(default_factory=list)
    score_detail: list[FeatureScoreDetail] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    def to_cmi_dict(self) -> dict[str, Any]:
        return self.model_dump()
