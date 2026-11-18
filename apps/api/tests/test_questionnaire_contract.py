"""Backward-compatible questionnaire extensions; only synthetic input."""

import pytest
from app.schemas.survey import MedicalHistory, PatientContext
from app.services.sessions import SessionService
from pydantic import ValidationError


def test_old_context_payload_remains_valid_and_unknown_lactation_is_not_false():
    value = PatientContext.model_validate({"age_years": 30}).model_dump()
    assert value["age_years"] == 30
    assert value["pregnancy"] is None
    assert value["lactation"] is None


def test_lactation_is_preserved_by_the_answer_validator():
    value = SessionService._validate("patient_context", {"age_years": 30, "lactation": True})
    assert value["lactation"] is True
    assert value["pregnancy"] is None


def test_hospitalizations_are_preserved_separately_from_operations():
    value = SessionService._validate("medical_history", {
        "operations_last_year": ["Synthetic operation"],
        "hospitalizations_last_year": ["Synthetic admission"],
    })
    assert value["operations_last_year"] == ["Synthetic operation"]
    assert value["hospitalizations_last_year"] == ["Synthetic admission"]


@pytest.mark.parametrize("entries", [["Synthetic admission"] * 11, ["x" * 121]])
def test_hospitalization_limits_match_the_other_history_fields(entries):
    with pytest.raises(ValidationError):
        MedicalHistory.model_validate({"hospitalizations_last_year": entries})
