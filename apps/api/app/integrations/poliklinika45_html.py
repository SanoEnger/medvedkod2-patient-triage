import re
from collections import defaultdict
from datetime import date, time, timedelta
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

PROFILE_PATH = re.compile(r"/service/schedule/0/\d+/doctors/?")
ORG_PATH = re.compile(r"/service/hospitals/view/(\d+)/?")
UNIT_ID = re.compile(r"lpuunit_(\d+)")
TIMETABLE_PATH = re.compile(r"/service/schedule/\d+/timetable/?")
CITY = re.compile(r"(?:^|[ ,])(?:(?:г\.\s*|г\s+))?курган(?=,|$)", re.IGNORECASE)
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")
SPECIALTIES = {
    "терапевт": "therapist", "терапия": "therapist", "педиатр": "pediatrician", "педиатрия": "pediatrician",
    "дерматолог": "dermatologist", "дерматовенеролог": "dermatologist",
    "кардиолог": "cardiologist", "кардиология": "cardiologist", "невролог": "neurologist",
    "оториноларинголог": "otolaryngologist", "лор": "otolaryngologist", "офтальмолог": "ophthalmologist",
    "гинеколог": "gynecologist", "акушер-гинеколог": "gynecologist", "хирург": "surgeon",
    "врач общей практики": "general_practitioner", "врач общ. практики": "general_practitioner",
    "аллерголог": "allergist", "аллерголог-иммунолог": "allergist",
    "врач по лечебной физкультуре": "exercise_therapy", "лечебная физкультура": "exercise_therapy",
    "психиатр": "psychiatrist", "гериатр": "geriatrician",
    "зубной врач": "dental_practitioner", "инфекционист": "infectious_disease_specialist",
    "кардиолог детский": "pediatric_cardiologist", "детский кардиолог": "pediatric_cardiologist",
    "клинический психолог": "clinical_psychologist", "медицинский психолог": "clinical_psychologist",
    "онколог": "oncologist", "профпатолог": "occupational_physician",
    "психиатр-нарколог": "addiction_psychiatrist", "нарколог": "addiction_psychiatrist",
    "психотерапевт": "psychotherapist", "пульмонолог": "pulmonologist", "ревматолог": "rheumatologist",
    "стоматолог детский": "pediatric_dentist", "детский стоматолог": "pediatric_dentist",
    "стоматолог": "dentist", "стоматолог общ. практики": "dentist", "стоматолог общей практики": "dentist",
    "стоматолог-ортопед": "prosthodontist", "стоматолог-терапевт": "dental_therapist",
    "стоматолог-хирург": "dental_surgeon", "травматолог-ортопед": "orthopedic_traumatologist",
    "уролог": "urologist", "уролог-андролог детский": "pediatric_urologist",
    "детский уролог-андролог": "pediatric_urologist", "фельдшер": "feldsher",
    "физиотерапевт": "physiotherapist", "фтизиатр": "tb_specialist",
    "хирург детский": "pediatric_surgeon", "детский хирург": "pediatric_surgeon",
    "эндокринолог": "endocrinologist", "гастроэнтеролог": "gastroenterologist",
    "нефролог": "nephrologist", "гематолог": "hematologist", "нейрохирург": "neurosurgeon",
    "проктолог": "coloproctologist", "колопроктолог": "coloproctologist",
}


def specialty_code(label: str) -> str | None:
    value = " ".join(label.lower().replace("ё", "е").split())
    value = re.sub(r"\s*[‑–—-]\s*", "-", value)
    return SPECIALTIES.get(value) or SPECIALTIES.get(re.sub(r"^врач[ -]+|\s+участковый$", "", value))


def kurgan_address(value):
    match = CITY.search(value)
    return "Курган, " + value[match.end():].strip(" ,") if match else None


def profiles(html, url):
    page = BeautifulSoup(html, "html.parser")
    city = page.select_one('a[data-terr-text="КУРГАН"][data-terr-id]')
    if not city or not page.select_one("h1.profiles-title"):
        return []
    city_id = city["data-terr-id"]
    return [
        (anchor.get_text(" ", strip=True), urljoin(url, anchor["href"]) + "?" + urlencode({"terr_id": city_id}))
        for anchor in page.select("a[href]") if PROFILE_PATH.fullmatch(urlsplit(anchor["href"]).path)
    ]


def doctor_groups(html, url, expected_page):
    page = BeautifulSoup(html, "html.parser")
    table = page.select_one(".docsInLpuTableDetail")
    if table is None:
        if expected_page == 1 and any("По заданным критериям врачей не найдено" in title.get_text(" ", strip=True)
                                      for title in page.select("h1")):
            return [], None
        raise ValueError("Unexpected public doctor list")
    selected = page.select_one(".selectedPage")
    if selected and selected.get_text(strip=True) != str(expected_page):
        raise ValueError("Unexpected public doctor page number")
    result = []
    contacts = public_unit_contacts(page)
    for group in table.select(".Lpuunit"):
        unit = UNIT_ID.fullmatch(group.get("id", ""))
        name = group.select_one(".lpu-fullName[href]")
        if not unit or not name:
            raise ValueError("Unexpected department markup")
        organization_url = urljoin(url, name["href"])
        organization_id = ORG_PATH.fullmatch(urlsplit(organization_url).path)
        if not organization_id:
            raise ValueError("Missing public organization ID")
        organization, _, department = name.get_text(" ", strip=True).partition(" / ")
        address_node = group.select_one(".lpu-address")
        original = address_node.get_text(" ", strip=True).strip(" ,") if address_node else ""
        address = kurgan_address(original)
        if original and not address:
            continue
        names = [label.get_text(" ", strip=True) for label in group.select(".doc-row .profile")]
        if not names:
            raise ValueError("Missing public specialty fields")
        timetable = group.select_one(".doc-row .doc-name a[href]")
        timetable_url = urljoin(url, timetable["href"]) if timetable else None
        result.append({
            "unit_id": unit[1], "organization_id": organization_id[1], "organization_url": organization_url,
            "organization_name": organization, "name": department or organization, "address": address or None,
            "specialties": names, "contact": contacts.get(unit[1]),
            "timetable_url": timetable_url if timetable_url and TIMETABLE_PATH.fullmatch(urlsplit(timetable_url).path) else None,
        })
    next_link = page.select_one("a.rightPage[href]")
    next_url = urljoin(url, next_link["href"]) if next_link else None
    if next_url:
        current_query = parse_qs(urlsplit(url).query)
        next_parts = urlsplit(next_url)
        query = parse_qs(next_parts.query)
        if next_parts.path != urlsplit(url).path or query.get("page") != [str(expected_page + 1)]:
            raise ValueError("Invalid public doctor pagination")
        query.setdefault("terr_id", current_query.get("terr_id", []))
        next_url = next_parts._replace(query=urlencode(query, doseq=True)).geturl()
    if not table.select_one(".Lpuunit"):
        raise ValueError("Empty public doctor page")
    return result, next_url


def phones(text):
    numbers = set()
    for fragment in re.split(r"[,;\n/]", text):
        digits = re.sub(r"\D", "", fragment)
        if digits == "122":
            numbers.add(digits)
        elif len(digits) == 10:
            numbers.add("+7" + digits)
        elif len(digits) == 11 and digits[0] in "78":
            numbers.add("+7" + digits[1:])
    return sorted(numbers)


def public_unit_contacts(page):
    units = {}
    for script in page.find_all("script"):
        if not script.string:
            continue
        for entry in re.findall(r"units\.push\(\{(.*?)\}\)", script.string, re.DOTALL):
            unit = re.search(r"'id':\s*(\d+)", entry)
            address = re.search(r"'address':\s*'((?:\\.|[^'\\])*)'", entry)
            phone = re.search(r"'phone':\s*'((?:\\.|[^'\\])*)'", entry)
            if unit and address and phone and (normalized := kurgan_address(address[1])):
                numbers = phones(phone[1])
                if numbers:
                    units[unit[1]] = (normalized, numbers)
    return units


def organization_details(html, url, external_id):
    page = BeautifulSoup(html, "html.parser")
    body = page.select_one(".lpuDesc .data")
    identifier = page.select_one("#Lpu_id")
    if not body or not identifier or identifier.get("value") != external_id:
        raise ValueError("Unexpected public organization details")
    values = {}
    departments = defaultdict(list)
    for row in body.select(":scope > p"):
        label = row.select_one("span.label")
        if not label:
            continue
        key = label.get_text(strip=True)
        value = label.find_next_sibling("span")
        if not value:
            continue
        if key == "Отделения":
            for item in value.select(":scope > span"):
                title = item.find("strong")
                lines = list(item.stripped_strings)
                if title and len(lines) >= 3 and CITY.search(lines[-2]):
                    departments[title.get_text(" ", strip=True).casefold()].append((kurgan_address(lines[-2]), phones(lines[-1])))
        else:
            values[key] = value
    if "Название" not in values:
        raise ValueError("Missing public organization name")
    name = values["Название"].get_text(" ", strip=True)
    lowered = name.casefold()
    kind = "public" if lowered.startswith(("государствен", "муниципальн", "федеральное государственное", "гбу ", "гауз ")) else (
        "private" if lowered.startswith(("частное", "чуз ", "ооо ", "общество с ограниченной")) else None
    )
    website = None
    if site := values.get("Сайт"):
        link = site.find("a", href=True)
        if link and urlsplit(link["href"]).scheme == "https":
            website = link["href"]
    return {
        "kind": "organization", "external_id": external_id, "url": url, "name": name,
        "address": values["Адрес"].get_text(" ", strip=True) if "Адрес" in values else None,
        "phones": phones(values["Телефон"].get_text("\n", strip=True)) if "Телефон" in values else [],
        "facility_kind": kind, "official_website": website,
    }, departments


def published_schedule(html, as_of, specialty):
    page = BeautifulSoup(html, "html.parser")
    table = page.select_one("table.timeTable")
    if table is None:
        return []
    times = defaultdict(set)
    for cell in table.select("td[rel]"):
        matched = re.fullmatch(r"(\d{1,2}) ([а-я]+), [а-я]+ (\d\d:\d\d)", cell["rel"].casefold())
        if not matched or matched[2] not in MONTHS:
            continue
        month = MONTHS.index(matched[2]) + 1
        year = as_of.year + (month == 1 and as_of.month == 12) - (month == 12 and as_of.month == 1)
        day = date(year, month, int(matched[1]))
        if as_of <= day <= as_of + timedelta(days=31):
            times[day].add(time.fromisoformat(matched[3]))
    return [
        {"specialty": specialty, "date": day, "starts_at": min(hours), "ends_at": max(hours)}
        for day, hours in sorted(times.items()) if len(hours) >= 2
    ]
