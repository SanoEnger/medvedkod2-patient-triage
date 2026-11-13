"""Limited lexical evidence, never a classifier or a replacement for SafetyRules."""

import re

from .schemas import Detail, ModelExtraction, Symptom

# These patterns are deliberately narrow. Unsupported paraphrases remain unknown.
PATTERNS = {
    "chest_pain": r"(?:бол(?:ь|ит|и)\s+(?:в\s+)?груд[ьи]|боль\s+за\s+грудиной)",
    "dyspnea": r"(?:тяжело дышать|трудно дышать|одышка|не хватает воздуха)",
    "dyspnea_rest": r"(?:одышка в покое|(?:тяжело|трудно) дышать в покое)",
    "loss_of_consciousness": r"(?:потер[яа]\w* сознани\w*|теря\w* сознание|без сознания|обморок)",
    "seizure": r"судорог\w*",
    "bleeding": r"(?:кровотечени\w*|ид[её]т кровь)",
    "abdominal_pain": r"(?:болит живот|(?:острая )?боль в животе)",
    "headache": r"(?:болит голова|головная боль)",
    "fever": r"(?:температура|жар)",
    "head_injury": r"(?:травма головы|удар\w* голов\w*)",
    "facial_asymmetry": r"(?:перекос\w* лиц\w*|асимметрия лица)",
    "speech_difficulty": r"(?:нарушение речи|не могу говорить|невнятная речь)",
    "arm_weakness": r"(?:слабость в руке|не могу поднять руку)",
    "throat_swelling": r"(?:от[её]к горла|отекает горло)",
    "rash": r"сыпь",
    "cough": r"кашель",
    "nausea": r"(?:тошнота|тошнит)",
}


def extract_local(text: str) -> ModelExtraction:
    """Retain explicit mentions; mark negation/context conservatively as uncertain.

    Fallback always requests clarification, even when it recognizes symptoms.
    It is not capable of proving the absence of critical symptoms.
    """
    symptoms = []
    for code, pattern in PATTERNS.items():
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start = max(text.rfind(c, 0, match.start()) for c in ".!?;\n") + 1
            clause = text[start:match.end()].lower()
            prefix = text[start:match.start()].lower()
            status = "present"
            if re.search(r"\b(нет|без|не|отрицаю|отсутствует)\b", prefix):
                status = "uncertain"
            if re.search(r"\b(если|раньше|вчера|было|была|были|возможно|кажется|пример|игнорируй|назначь|диагноз)\b", clause) or "?" in text:
                status = "uncertain"
            if not any(s.code == code and s.status == status for s in symptoms):
                symptoms.append(Symptom(code=code, evidence=match[0], status=status))
    details = []
    for kind, pattern in {
        "age": r"\b\d{1,3}\s*(?:лет|год|года|месяцев)\b",
        "temperature": r"\b(?:температура\s*)\d{2}(?:[.,]\d)?(?:\s*°?\s*[CcСс])?",
        "pregnancy": r"\bбеременна\b",
    }.items():
        for match in re.finditer(pattern, text, re.IGNORECASE):
            details.append(Detail(kind=kind, evidence=match[0]))
    duration = re.search(r"\b\d+\s*(?:минут\w*|час\w*|дн\w*|день|недел\w*)\b", text, re.I)
    # Attach a duration only for an unambiguous single mention.
    if len(symptoms) == 1 and duration:
        symptoms[0].duration = duration[0]
    return ModelExtraction(symptoms=symptoms[:40], details=details[:20], needs_clarification=True)
