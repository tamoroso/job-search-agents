from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class RequirementKind(StrEnum):
    MUST_HAVE = "must_have"
    NICE_TO_HAVE = "nice_to_have"
    RESPONSIBILITY = "responsibility"
    CONTEXT = "context"


class RequirementCategory(StrEnum):
    TECH = "tech"
    DOMAIN = "domain"
    SOFT = "soft"
    EXPERIENCE = "experience"
    EDUCATION = "education"


class ExtractedRequirement(BaseModel):
    text: str = Field(max_length=300)
    kind: RequirementKind
    category: RequirementCategory


class SalaryRange(BaseModel):
    min_amount: int | None = None
    max_amount: int | None = None
    currency: str | None = None                                  # ISO 4217
    period: Literal["year", "month", "day", "hour"] | None = None


class JobAnalysis(BaseModel):
    requirements: list[ExtractedRequirement] = Field(max_length=30)
    seniority: Literal["intern", "junior", "mid", "senior", "lead", "staff", "principal"] | None = None
    job_family: Literal[
        "data_scientist", "ml_engineer", "data_engineer",
        "research_scientist", "analytics", "software", "other",
    ]
    remote_policy: Literal["onsite", "hybrid", "remote"] | None = None
    contract_type: Literal["cdi", "cdd", "freelance", "internship", "apprenticeship", "other"] | None = None
    salary: SalaryRange | None = None
    tech_stack: list[str] = Field(default_factory=list, max_length=25)
    languages_required: list[str] = Field(default_factory=list)  # ISO 639-1
    offer_language: Literal["fr", "en", "other"]
    

class FitAssessment(BaseModel):
    fit_score : int
    seniority: Literal["under", "match", "over"]
    covered_requirements: list[str]
    critical_gaps: list[str]
    differentiators: list[str]
    red_flags: list[str]
    estimated_salary_range: SalaryRange | None
    recommendation: Literal["apply", "apply_with_prep", "network_first", "skip"]
    reasoning: str
