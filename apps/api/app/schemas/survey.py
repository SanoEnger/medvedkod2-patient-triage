"""Strict question and endpoint schemas for the isolated backend contract."""

from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.integrations.groq.schemas import ExtractionResult


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class SurveyStatus(StrEnum):
    COLLECTING = "COLLECTING"
    REVIEWING = "REVIEWING"
    COMPLETED = "COMPLETED"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    EXPIRED = "EXPIRED"


class LaunchRequest(StrictModel):
    mode: Literal["host", "demo"]
    host_token: str | None = Field(default=None, max_length=6000)


class LaunchResponse(StrictModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class CreateSessionRequest(StrictModel):
    accepted_disclaimer: Literal[True]


class PrimaryComplaint(StrictModel):
    category: Literal["pain", "fever", "breathing", "digestive", "skin", "neurology", "injury", "other"]
    text: str = Field(default="", max_length=1200)


class PatientContext(StrictModel):
    sex: Literal["male", "female"] | None = None
    height_cm: float | None = Field(default=None, ge=1, le=300)
    weight_kg: float | None = Field(default=None, ge=0.1, le=1000)
    age_years: int | None = Field(default=None, ge=0, le=120)
    temperature_c: float | None = Field(default=None, ge=30, le=45)
    pregnancy: bool | None = None
    lactation: bool | None = None


class SymptomDetails(StrictModel):
    location: str = Field(default="", max_length=120)
    duration: str = Field(default="", max_length=120)
    severity_0_10: int | None = Field(default=None, ge=0, le=10)
    additional_text: str = Field(default="", max_length=1200)


class RedFlags(StrictModel):
    chest_pain: bool | None = None
    dyspnea_rest: bool | None = None
    loss_of_consciousness: bool | None = None
    seizure: bool | None = None
    bleeding: bool | None = None
    facial_asymmetry: bool | None = None
    arm_weakness: bool | None = None
    speech_difficulty: bool | None = None
    anaphylaxis: bool | None = None
    acute_abdominal_pain: bool | None = None
    head_injury_with_loc: bool | None = None


class MedicalHistory(StrictModel):
    chronic_conditions: list[str] = Field(default_factory=list, max_length=10)
    medications: list[str] = Field(default_factory=list, max_length=10)
    allergies: list[str] = Field(default_factory=list, max_length=10)
    operations_last_year: list[str] = Field(default_factory=list, max_length=10)
    hospitalizations_last_year: list[str] = Field(default_factory=list, max_length=10)
    family_history: list[str] = Field(default_factory=list, max_length=10)
    habits: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("chronic_conditions", "medications", "allergies", "operations_last_year", "hospitalizations_last_year", "family_history", "habits")
    @classmethod
    def validate_entries(cls, value: list[str]) -> list[str]:
        if any(not isinstance(x, str) or len(x) > 120 for x in value):
            raise ValueError("invalid_list_entry")
        return value


QUESTIONS: tuple[str, ...] = (
    "primary_complaint", "patient_context", "symptom_details", "red_flags", "medical_history",
)
QUESTION_MODELS: dict[str, type[StrictModel]] = {
    "primary_complaint": PrimaryComplaint,
    "patient_context": PatientContext,
    "symptom_details": SymptomDetails,
    "red_flags": RedFlags,
    "medical_history": MedicalHistory,
}


class AnswerRequest(StrictModel):
    question_key: str = Field(min_length=1, max_length=50)
    value: dict[str, Any]
    idempotency_key: UUID


class BackRequest(StrictModel):
    target_step: int = Field(ge=0)


class Progress(StrictModel):
    answered: int
    total: int
    percent: int


class SessionResponse(StrictModel):
    answers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    nlp: dict[str, ExtractionResult] = Field(default_factory=dict)
    id: UUID
    status: SurveyStatus
    state: SurveyStatus
    progress: Progress
    current_question: str | None
    next_question: str | None
    expires_at: str
    emergency: bool = False
    urgency: str | None = None
    message: str | None = None
    matched_rule_codes: list[str] = Field(default_factory=list)
    result: dict[str, Any] | None = None


class TriageResponse(StrictModel):
    urgency: Literal["EMERGENCY", "WITHIN_24H", "PLANNED", "SELF_CARE", "UNKNOWN"]
    specialty: str | None
    place: str | None
    rationale: str
    disclaimer: str
    rule_codes: list[str]
    needs_clarification: bool
