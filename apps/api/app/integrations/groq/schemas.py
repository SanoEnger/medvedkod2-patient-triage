"""Temporary extraction contract, independent of urgency and diagnoses."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SymptomCode = Literal[
    "chest_pain", "dyspnea", "dyspnea_rest", "loss_of_consciousness",
    "seizure", "bleeding", "abdominal_pain", "headache", "fever",
    "head_injury", "facial_asymmetry", "speech_difficulty", "arm_weakness",
    "throat_swelling", "rash", "cough", "nausea",
]
ShortText = Annotated[str, Field(min_length=1, max_length=200)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class Symptom(StrictModel):
    code: SymptomCode
    evidence: ShortText
    status: Literal["present", "negated", "uncertain"]
    location: ShortText | None = None
    duration: ShortText | None = None


class Detail(StrictModel):
    kind: Literal["age", "temperature", "pregnancy", "history", "medication", "allergy"]
    evidence: ShortText


class ModelExtraction(StrictModel):
    symptoms: list[Symptom] = Field(max_length=40)
    details: list[Detail] = Field(max_length=20)
    needs_clarification: bool


class ExtractionResult(ModelExtraction):
    source: Literal["groq", "fallback"]
    mode: Literal["live", "mock"]
    fallback_reason: Literal[
        "empty_input", "missing_configuration", "timeout", "network_error",
        "rate_limited", "server_error", "http_error", "invalid_response",
        "provider_error", "untrusted_instructions",
    ] | None = None
