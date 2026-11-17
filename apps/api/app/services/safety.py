"""Deterministic P0 rules: evaluate raw answers independently from any LLM."""

import re
from typing import Any

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
_UNCERTAIN_RE = re.compile(r"\b(?:если|возможно|кажется|раньше|когда-то|гипотетически|представим)\b", re.I)


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


def find_emergency_rules(answers: dict[str, dict[str, Any]]) -> list[str]:
    """Return independently verified P0 codes, no LLM or treatment guidance."""
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

    texts = [answers.get("primary_complaint", {}).get("text", ""), answers.get("symptom_details", {}).get("additional_text", "")]
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

    return sorted(matched)
