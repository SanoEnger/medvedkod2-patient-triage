import re

from app.integrations.prompt_security import instruction_attack, normalized

PAIN_LOCATIONS = (
    ("Боль в колене", r"колен(?:о|е|а|ом|и|ях|ей)|коленн\w*\s+сустав\w*"),
    ("Боль в спине", r"спин(?:а|е|у|ы|ой)|поясниц(?:а|е|у|ы|ей)"),
    ("Головная боль", r"голов(?:а|е|у|ы|ой)"),
    ("Боль в животе", r"живот(?:а|е|ом)?"),
    ("Боль в горле", r"горл(?:о|е|а|ом)"),
    ("Боль в груди", r"груд(?:ь|и|ью)|грудин(?:а|е|ой)"),
    ("Боль в шее", r"ше(?:я|е|ю|и|ей)"),
    ("Боль в плече", r"плеч(?:о|е|а|ом|и|ах)"),
    ("Боль в руке", r"рук(?:а|е|у|и|ой|ах)"),
    ("Боль в ноге", r"ног(?:а|е|у|и|ой|ах)"),
    ("Боль в суставах", r"сустав(?:а|е|ом|ы|ах|ов)?"),
    ("Боль в ухе", r"ух(?:о|е|а|ом)|уш(?:и|ах|ей)"),
    ("Зубная боль", r"зуб(?:а|е|ом|ы|ах|ов)?"),
)
PAIN = r"(?:болит|болят|болел[аио]?|боль|боли|ноет|ноют)"
OTHER_COMPLAINTS = (
    ("Головная боль", r"головн\w*\s+бол[ьи]"),
    ("Зубная боль", r"зубн\w*\s+бол[ьи]"),
    ("Кашель", r"кашель|кашляю|кашляет"),
    ("Температура", r"температур\w*|жар"),
    ("Сыпь", r"сыпь|высыпани\w*"),
    ("Тошнота", r"тошнот\w*|тошнит"),
    ("Головокружение", r"головокружени\w*|кружится голова"),
    ("Затруднённое дыхание", r"одышк\w*|трудно дышать|тяжело дышать"),
    ("Насморк", r"насморк|заложенность носа"),
)
CATEGORY_TITLES = {
    "pain": "Боль",
    "fever": "Температура",
    "breathing": "Вопрос о дыхании",
    "digestive": "Вопрос о пищеварении",
    "skin": "Вопрос о коже",
    "neurology": "Неврологические симптомы",
    "injury": "Травма",
}


def complaint_title(text, *, category=None, location=""):
    text = "" if instruction_attack(text) else normalized(text).replace("ё", "е")
    location = "" if instruction_attack(location) else normalized(location)
    for title, area in PAIN_LOCATIONS:
        area = rf"\b(?:{area})\b"
        if re.search(rf"\b{PAIN}\b(?:\s+\w+){{0,3}}\s+{area}|{area}(?:\s+\w+){{0,2}}\s+\b{PAIN}\b", text):
            return title
        if category == "pain" and re.search(area, location):
            return title
    return next(
        (title for title, pattern in OTHER_COMPLAINTS if re.search(rf"\b(?:{pattern})\b", text)),
        CATEGORY_TITLES.get(category),
    )
