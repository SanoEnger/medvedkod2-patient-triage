"""Raw-answer P0 rules plus grounded, confirmed model symptom evidence."""

import re
from typing import Any

from app.integrations.groq.schemas import ExtractionResult

# Deliberately limited synthetic-case dictionary; not an approved clinical protocol.
_RULE_FIELDS = {
    "chest_pain": "RF_CHEST_PAIN",
    "dyspnea_rest": "RF_DYSPNEA_REST",
    "loss_of_consciousness": "RF_LOSS_CONSCIOUSNESS",
    "seizure": "RF_SEIZURE",
    "bleeding": "RF_BLEEDING",
    "facial_asymmetry": "RF_FAST",
    "arm_weakness": "RF_FAST",
    "speech_difficulty": "RF_FAST",
    "anaphylaxis": "RF_ANAPHYLAXIS",
    "acute_abdominal_pain": "RF_ACUTE_ABDOMINAL_PAIN",
    "head_injury_with_loc": "RF_HEAD_INJURY_LOC",
}

_PATTERNS = {
    "RF_CHEST_PAIN": [r"бол(?:ь|ит|и)\s+(?:в\s+)?груд[ьи]", r"бол(?:ь|ит)\s+за\s+грудиной", r"боль\s+в\s+грудной\s+клетке"],
    "RF_DYSPNEA_REST": [r"одышк\w*\s+в\s+покое", r"(?:тяжело|трудно)\s+дышать\s+в\s+покое"],
    "RF_LOSS_CONSCIOUSNESS": [r"потер\w*\s+сознани\w*", r"теря\w*\s+сознани\w*", r"без\s+сознания", r"обморок"],
    "RF_SEIZURE": [r"судорог\w*", r"судорожн\w*\s+припадок"],
    "RF_BLEEDING": [r"кровотечени\w*", r"сильн\w*\s+кров\w*", r"ид[её]т\s+кровь"],
    "RF_FAST": [r"перекос\w*\s+лиц\w*", r"асимметрия\s+лица", r"невнятн\w*\s+реч\w*", r"нарушени\w*\s+реч\w*", r"не\s+могу\s+поднять\s+руку", r"слабость\s+в\s+руке"],
    "RF_ANAPHYLAXIS": [r"анафилакси\w*", r"анафилактическ\w*\s+шок", r"от[её]к\s+горла", r"отекает\s+горло"],
    "RF_ACUTE_ABDOMINAL_PAIN": [r"остр\w*\s+бол\w*\s+в\s+животе", r"резк\w*\s+бол\w*\s+в\s+животе", r"сильн\w*\s+бол\w*\s+в\s+животе"],
    "RF_HEAD_INJURY_LOC": [r"травма\s+головы\s+с\s+потер\w*\s+сознани\w*", r"удар\w*\s+голов\w*\s+и\s+потер\w*\s+сознани\w*"],
}

_NEGATION_RE = re.compile(r"(?:^|\s)(?:нет|не|без|отрицаю|отсутствует)\s*$", re.I)
_UNCERTAIN_RE = re.compile(r"\b(?:если|возможно|кажется|раньше|когда-то|гипотетически|представим|в прошлом|в детстве|у мамы|у папы|у отца|у матери)\b", re.I)


def _match_confirmed(pattern: str, text: str) -> bool:
    for match in re.finditer(pattern, text, re.I):
        boundary = max(text.rfind(c, 0, match.start()) for c in ".!?;\n")
        prefix = text[boundary + 1:match.start()]
        # Only obvious immediate negation; ambiguous narratives are NOT downgraded to P3.
        if _NEGATION_RE.search(prefix[-30:]):
            continue
        if _UNCERTAIN_RE.search(prefix):
            continue
        return True
    return False


def answer_text(question: str, value: dict[str, Any]) -> str:
    fields = {
        "primary_complaint": ("text",),
        "symptom_details": ("location", "duration", "additional_text"),
        "medical_history": tuple(value),
    }.get(question, ())
    return "\n".join(
        f"{field}: {item}" for field in fields
        for item in (value.get(field, []) if isinstance(value.get(field), list) else [value.get(field, "")])
        if isinstance(item, str) and item.strip()
    )


def find_emergency_rules(answers: dict[str, dict[str, Any]], nlp: dict[str, ExtractionResult] | None = None) -> list[str]:
    """Preserve raw-answer rules and add confirmed model flags, never treatment guidance."""
    matched: set[str] = set()
    flags = answers.get("red_flags", {})
    for field, code in _RULE_FIELDS.items():
        if flags.get(field) is True:
            matched.add(code)

    context = answers.get("patient_context", {})
    age = context.get("age_years")
    temp = context.get("temperature_c")
    if age is not None and age < 18 and temp is not None and temp > 39.5:
        matched.add("RF_CHILD_FEVER_39_5")

    texts = [answer_text(question, value) for question, value in answers.items()]
    for text in texts:
        if not isinstance(text, str):
            continue
        for code, patterns in _PATTERNS.items():
            if any(_match_confirmed(p, text) for p in patterns):
                matched.add(code)
        # head injury and unconsciousness may be mentioned separately.
        if re.search(r"(?:травма\s+головы|удар\w*\s+голов\w*)", text, re.I) and any(
            _match_confirmed(p, text) for p in _PATTERNS["RF_LOSS_CONSCIOUSNESS"]
        ):
            matched.add("RF_HEAD_INJURY_LOC")
        # A child with an explicitly described high fever, even if the form temperature is absent.
        if age is not None and age < 18:
            fever = re.search(r"(?:температура|жар)\s*(?:выше\s*)?(\d{2}(?:[.,]\d)?)", text, re.I)
            if fever and float(fever.group(1).replace(",", ".")) > 39.5:
                matched.add("RF_CHILD_FEVER_39_5")

    model_rules = {**_RULE_FIELDS, "throat_swelling": "RF_ANAPHYLAXIS"}
    for question, extraction in (nlp or {}).items():
        if extraction.source != "groq":
            continue
        text = answer_text(question, answers.get(question, {}))
        for symptom in extraction.symptoms:
            if symptom.status != "present" or symptom.evidence not in text:
                continue
            if not _match_confirmed(re.escape(symptom.evidence), text) or _UNCERTAIN_RE.search(symptom.evidence):
                continue
            if any(other.code == symptom.code and other.status != "present" and
                   (other.evidence in symptom.evidence or symptom.evidence in other.evidence)
                   for other in extraction.symptoms):
                continue
            code = model_rules.get(symptom.code)
            if code:
                matched.add(code)
    return sorted(matched)
