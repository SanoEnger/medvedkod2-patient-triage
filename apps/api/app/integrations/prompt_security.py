"""Conservative instruction detection and output checks, not a complete firewall.

    These checks never replace independent medical SafetyRules on the raw input.
"""

import re
import unicodedata


SAFE_REPLY = (
    "Я могу помочь уточнить жалобы и подготовить вопросы врачу. "
    "Я не раскрываю внутренние инструкции, не ставлю диагноз и не назначаю лечение. "
    "Опишите, что вас беспокоит, где и как давно."
)
OMITTED = "[Инструкция в недоверенных данных исключена]"


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return "".join(c for c in text if unicodedata.category(c) != "Cf").casefold()


_ATTACKS = tuple(re.compile(pattern, re.I | re.S) for pattern in (
    r"<\|(?:im_start|im_end|start_header_id|end_header_id|system|developer)\|>|\[/?(?:system|inst)\]",
    r"(?:^|\n)\s*(?:system|developer|система|разработчик)\s*:",
    r"(?:игнорируй|забудь|отмени|обойди|не соблюдай).{0,80}(?:инструкц|правил|ограничен|безопасност|промпт)",
    r"(?:ignore|disregard|override|forget|bypass).{0,80}(?:instruction|rule|safety|restriction|system|prompt)",
    r"(?:покажи|раскрой|выведи|напечатай|повтори|переведи).{0,80}(?:системн.{0,20}(?:промпт|инструкц)|api.?ключ|токен|секрет|переменн.{0,20}окружен)",
    r"(?:show|reveal|print|repeat|translate|dump).{0,80}(?:system prompt|developer message|api key|access token|environment variables|secrets)",
    r"(?:ты теперь|представь что ты|act as|you are now).{0,60}(?:врач|doctor|system|разработчик|unrestricted)",
    r"(?:назначь|выпиши|подбери).{0,70}(?:лекарств|дозиров|препарат)",
))


def instruction_attack(text: str) -> bool:
    value = normalized(text)
    return any(pattern.search(value) for pattern in _ATTACKS)


def scrub_data(value):
    """Omit known instruction strings in historical/context data, not stored data."""
    if isinstance(value, str):
        return OMITTED if instruction_attack(value) else value
    if isinstance(value, list):
        return [scrub_data(item) for item in value]
    if isinstance(value, dict):
        return {key: scrub_data(item) for key, item in value.items()}
    return value


_UNSAFE_OUTPUT = tuple(re.compile(pattern, re.I | re.S) for pattern in (
    r"https?://|www\.|javascript:|data:text|<\s*/?\s*[a-z][^>]*>",
    r"(?:принимайте|примите|назначаю|назначаем|начните при[её]м|take|prescribe)\b",
    r"\b\d+(?:[.,]\d+)?\s*(?:мг|мкг|mg|mcg|таблет\w*)\b",
    r"(?:ваш диагноз|у вас точно|диагноз подтвержд[её]н|you definitely have)",
    r"(?:не (?:нужно|надо|следует) (?:звонить|вызывать)|do not call).{0,30}(?:103|112|скорую|ambulance)",
    r"\bgsk_[a-z0-9]{12,}|\bbearer\s+[a-z0-9._-]{12,}|\beyj[a-z0-9_-]+\.[a-z0-9_-]+\.[a-z0-9_-]+",
))


def unsafe_output(text: str, protected_prompt: str) -> bool:
    value = normalized(text)
    if instruction_attack(text):
        return True
    if any(pattern.search(value) for pattern in _UNSAFE_OUTPUT):
        return True
    # Detect verbatim leakage of substantial prompt fragments; never log the fragment.
    prompt = normalized(protected_prompt)
    return any(prompt[index:index + 100] in value for index in range(0, max(0, len(prompt) - 99), 25))
