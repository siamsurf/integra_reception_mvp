import json
import re

from app.core.services.llm_extract import LLMExtractionResult, extract_delivery_entities_with_llm

RE_FROM_COUNTRY = re.compile(r"(?:from|origin)\s*[:\-]?\s*([A-Za-z][A-Za-z\s]{1,40})", re.IGNORECASE)
RE_TO_CITY = re.compile(r"(?:to|destination)\s*[:\-]?\s*([A-Za-z][A-Za-z\s]{1,40})", re.IGNORECASE)
RE_WEIGHT = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:кг|kg|kgs|kilogram|kilograms)\b",
    re.IGNORECASE,
)
RE_VOLUME = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:м3|м³|m3|cbm|куб(?:а|ов)?|cubic\s*meters?)\b",
    re.IGNORECASE,
)
RE_DIMENSIONS = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*[*x×]\s*(\d+(?:[.,]\d+)?)\s*[*x×]\s*(\d+(?:[.,]\d+)?)\s*"
    r"(мм|mm|см|cm|метр(?:а|ов)?|meters?|meter|м|m)\b",
    re.IGNORECASE,
)
RE_PACKAGE_COUNT = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:штук|шт|короб(?:ка|ки|ок)?|мест(?:о|а)?|мест|boxes?|packages?)\b",
    re.IGNORECASE,
)
RE_ROUTE_RU = re.compile(r"\bиз\s+([^\n,.;:]+?)\s+в\s+([^\n,.;:]+)", re.IGNORECASE)
RE_ROUTE_EN = re.compile(r"\bfrom\s+([^\n,.;:]+?)\s+to\s+([^\n,.;:]+)", re.IGNORECASE)
RE_CARGO_BEFORE_ROUTE_RU = re.compile(
    r"\b(?:нужно\s+доставить|необходимо\s+доставить|доставить|отправить)\s+(.{2,120}?)\s+\bиз\b\s+[^\n,.;:]+?\s+\bв\b",
    re.IGNORECASE,
)
RE_CARGO_BEFORE_ROUTE_EN = re.compile(
    r"\b(?:need\s+to\s+deliver|deliver|ship|send)\s+(.{2,120}?)\s+\bfrom\b\s+[^\n,.;:]+?\s+\bto\b",
    re.IGNORECASE,
)
RE_CARGO_LABELED = re.compile(
    r"(?:наименование\s+груза|cargo\s*name|cargo|груз|товар|продукц(?:ия|ии)|product)\s*[:\-]\s*([^\n,.;]{3,120})",
    re.IGNORECASE,
)

CHINA_SIGNALS = [
    "guangzhou",
    "广州",
    "гуанчжоу",
    "foshan",
    "佛山",
    "фошань",
    "shenzhen",
    "深圳",
    "шэньчжэнь",
    "yiwu",
    "义乌",
    "иу",
    "ningbo",
    "宁波",
    "нинбо",
    "shanghai",
    "上海",
    "шанхай",
    "xiamen",
    "厦门",
    "сямынь",
    "qingdao",
    "青岛",
    "циндао",
    "tianjin",
    "天津",
    "тяньцзинь",
    "beijing",
    "北京",
    "пекин",
    "changsha",
    "长沙",
    "чангша",
    "hong kong",
    "香港",
    "гонконг",
    "china",
    "prc",
    "кнр",
    "китай",
]
KNOWN_CHINA_ORIGIN_CITIES = {"Shanghai", "Guangzhou", "Shenzhen", "Ningbo", "Yiwu", "Changsha"}
COUNTRY_ALIASES = {
    "china": "China",
    "prc": "China",
    "китай": "China",
    "китая": "China",
    "russia": "Russia",
    "россия": "Russia",
    "россии": "Russia",
    "kazakhstan": "Kazakhstan",
    "казахстан": "Kazakhstan",
    "казахстана": "Kazakhstan",
    "uzbekistan": "Uzbekistan",
    "узбекистан": "Uzbekistan",
    "узбекистана": "Uzbekistan",
    "kyrgyzstan": "Kyrgyzstan",
    "кыргызстан": "Kyrgyzstan",
    "кыргызстана": "Kyrgyzstan",
    "tajikistan": "Tajikistan",
    "таджикистан": "Tajikistan",
    "таджикистана": "Tajikistan",
    "belarus": "Belarus",
    "беларусь": "Belarus",
    "беларуси": "Belarus",
    "armenia": "Armenia",
    "армения": "Armenia",
    "армении": "Armenia",
    "georgia": "Georgia",
    "грузия": "Georgia",
    "грузии": "Georgia",
    "azerbaijan": "Azerbaijan",
    "азербайджан": "Azerbaijan",
    "азербайджана": "Azerbaijan",
    "turkey": "Turkey",
    "turkiye": "Turkey",
    "турция": "Turkey",
    "турции": "Turkey",
    "uae": "United Arab Emirates",
    "u.a.e": "United Arab Emirates",
    "united arab emirates": "United Arab Emirates",
    "united-arab-emirates": "United Arab Emirates",
    "oae": "United Arab Emirates",
    "оаэ": "United Arab Emirates",
    "объединенные арабские эмираты": "United Arab Emirates",
    "объединённых арабских эмиратов": "United Arab Emirates",
    "объединенных арабских эмиратов": "United Arab Emirates",
    "саудовская аравия": "Saudi Arabia",
    "саудовской аравии": "Saudi Arabia",
    "saudi arabia": "Saudi Arabia",
    "saudi-arabia": "Saudi Arabia",
    "india": "India",
    "индия": "India",
    "индии": "India",
    "vietnam": "Vietnam",
    "вьетнам": "Vietnam",
    "вьетнама": "Vietnam",
    "thailand": "Thailand",
    "таиланд": "Thailand",
    "таиланда": "Thailand",
    "malaysia": "Malaysia",
    "малайзия": "Malaysia",
    "малайзии": "Malaysia",
    "indonesia": "Indonesia",
    "индонезия": "Indonesia",
    "индонезии": "Indonesia",
    "south korea": "South Korea",
    "south-korea": "South Korea",
    "korea": "South Korea",
    "южная корея": "South Korea",
    "южной кореи": "South Korea",
    "japan": "Japan",
    "япония": "Japan",
    "японии": "Japan",
    "germany": "Germany",
    "германия": "Germany",
    "германии": "Germany",
    "france": "France",
    "франция": "France",
    "франции": "France",
    "italy": "Italy",
    "италия": "Italy",
    "италии": "Italy",
    "spain": "Spain",
    "испания": "Spain",
    "испании": "Spain",
    "poland": "Poland",
    "польша": "Poland",
    "польши": "Poland",
    "netherlands": "Netherlands",
    "the netherlands": "Netherlands",
    "нидерланды": "Netherlands",
    "нидерландов": "Netherlands",
    "united kingdom": "United Kingdom",
    "united-kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "great britain": "United Kingdom",
    "great-britain": "United Kingdom",
    "англия": "United Kingdom",
    "великобритания": "United Kingdom",
    "великобритании": "United Kingdom",
    "соединенное королевство": "United Kingdom",
    "соединённое королевство": "United Kingdom",
    "соединенного королевства": "United Kingdom",
    "соединённого королевства": "United Kingdom",
    "united states": "United States",
    "usa": "United States",
    "us": "United States",
    "сша": "United States",
    "canada": "Canada",
    "канада": "Canada",
    "канады": "Canada",
    "mexico": "Mexico",
    "мексика": "Mexico",
    "мексики": "Mexico",
    "brazil": "Brazil",
    "бразилия": "Brazil",
    "бразилии": "Brazil",
    "argentina": "Argentina",
    "аргентина": "Argentina",
    "аргентины": "Argentina",
    "uruguay": "Uruguay",
    "уругвай": "Uruguay",
    "уругвая": "Uruguay",
    "paraguay": "Paraguay",
    "парагвай": "Paraguay",
    "парагвая": "Paraguay",
    "egypt": "Egypt",
    "египет": "Egypt",
    "египта": "Egypt",
    "south africa": "South Africa",
    "south-africa": "South Africa",
    "южная африка": "South Africa",
    "южной африки": "South Africa",
    "юар": "South Africa",
    "zimbabwe": "Zimbabwe",
    "зимбабве": "Zimbabwe",
    "burkina faso": "Burkina Faso",
    "burkina-faso": "Burkina Faso",
    "буркина фасо": "Burkina Faso",
    "буркина-фасо": "Burkina Faso",
    "australia": "Australia",
    "австралия": "Australia",
    "австралии": "Australia",
}

CITY_NORMALIZATION = {
    "спб": "Санкт-Петербург",
    "с-пб": "Санкт-Петербург",
    "saintpetersburg": "Санкт-Петербург",
    "stpetersburg": "Санкт-Петербург",
    "санктпетербург": "Санкт-Петербург",
    "санктпетербурга": "Санкт-Петербург",
    "санктпетербургу": "Санкт-Петербург",
    "москва": "Москва",
    "москву": "Москва",
    "москве": "Москва",
    "moscow": "Москва",
    "екатеринбург": "Екатеринбург",
    "екатеринбурга": "Екатеринбург",
    "новосибирск": "Новосибирск",
    "новосибирска": "Новосибирск",
    "шанхай": "Shanghai",
    "шанхая": "Shanghai",
    "shanghai": "Shanghai",
    "гуанчжоу": "Guangzhou",
    "guangzhou": "Guangzhou",
    "шэньчжэнь": "Shenzhen",
    "шэньчжэня": "Shenzhen",
    "shenzhen": "Shenzhen",
    "нинбо": "Ningbo",
    "ningbo": "Ningbo",
    "иу": "Yiwu",
    "yiwu": "Yiwu",
    "чангша": "Changsha",
    "changsha": "Changsha",
    "长沙": "Changsha",
    "нижнийтагил": "Нижний Тагил",
}
INCOTERM_MARKERS = ("exw", "fob", "cif", "ddp", "fca", "cpt", "cfr", "dap", "dat", "dpu")
JUNK_PHRASES = (
    "привед медвед",
    "привет",
    "добрый день",
    "здравствуйте",
    "hello",
    "hi",
    "нужна доставка",
)
PRODUCT_KEYWORDS = (
    "светиль",
    "коляск",
    "мебел",
    "обув",
    "одежд",
    "стан",
    "запчаст",
    "электрон",
    "продукц",
    "товар",
    "оборуд",
    "игруш",
    "текстил",
    "ламп",
    "furniture",
    "clothes",
    "shoes",
    "equipment",
    "electronics",
    "product",
    "cargo",
)
SHORT_CARGO_STOPWORDS = {
    "для",
    "на",
    "в",
    "из",
    "to",
    "from",
    "for",
    "and",
}
LOCATION_REJECT_PATTERN = re.compile(
    r"\b(?:товар|cargo|product|описан(?:ие)?|description|образц(?:ы)?|замок|заст[её]ж|слайдер\w*|zipper|fittings?)\b",
    re.IGNORECASE,
)
LLM_EXTRACTION_MIN_CONFIDENCE = 0.65


def _to_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _has_china_signal(text: str) -> bool:
    lowered = text.lower()
    return any(signal in lowered for signal in CHINA_SIGNALS)


def _extract_volume_from_dimensions(raw_text: str) -> float | None:
    dims_match = RE_DIMENSIONS.search(raw_text)
    count_match = RE_PACKAGE_COUNT.search(raw_text)
    if not dims_match:
        return None

    length_mm = _to_float(dims_match.group(1))
    width_mm = _to_float(dims_match.group(2))
    height_mm = _to_float(dims_match.group(3))
    unit = (dims_match.group(4) or "").lower()
    count = _to_float(count_match.group(1)) if count_match else 1.0

    if None in (length_mm, width_mm, height_mm, count):
        return None
    if count <= 0:
        return None

    if unit in {"мм", "mm"}:
        factor = 1000.0
    elif unit in {"см", "cm"}:
        factor = 100.0
    else:
        factor = 1.0

    return round((length_mm / factor) * (width_mm / factor) * (height_mm / factor) * count, 6)


def _normalize_city(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip(" \t,;.-")
    key = cleaned.lower().replace(" ", "").replace(".", "")
    return CITY_NORMALIZATION.get(key, cleaned)


def _is_location_like(value: str | None) -> bool:
    if not value:
        return False
    candidate = value.strip(" \t,;.-")
    if len(candidate) < 2 or len(candidate) > 80:
        return False
    if re.search(r"\s[—–]\s", candidate):
        return False
    if ":" in candidate:
        return False
    if re.search(r"\d", candidate):
        return False
    if re.search(r"(?:кг|kg|м3|м³|m3|cbm|куб|мм|mm|см|cm)\b", candidate, re.IGNORECASE):
        return False
    if re.search(r"\b(из|from)\b.+\b(в|to)\b", candidate, re.IGNORECASE):
        return False
    if LOCATION_REJECT_PATTERN.search(candidate):
        return False
    return True


def _strip_destination_tail(value: str) -> str:
    return re.sub(
        r"\s+\d+(?:[.,]\d+)?\s*(?:кг|kg|м3|м³|m3|cbm|куб(?:а|ов)?|штук|шт|boxes?|короб(?:ка|ки|ок)?|мест(?:о|а)?)\b.*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()


def _extract_route_entities(raw_text: str) -> tuple[str | None, str | None]:
    route_match = RE_ROUTE_RU.search(raw_text)
    if route_match:
        return route_match.group(1).strip(), _strip_destination_tail(route_match.group(2).strip())

    route_match = RE_ROUTE_EN.search(raw_text)
    if route_match:
        return route_match.group(1).strip(), _strip_destination_tail(route_match.group(2).strip())

    return None, None


def _extract_to_city(raw_text: str) -> str | None:
    first_line = raw_text.splitlines()[0] if raw_text.splitlines() else raw_text
    if first_line:
        parts = re.split(r"\s*(?:→|->|—|–)\s*|\s-\s", first_line)
        if len(parts) > 1:
            dest = parts[-1].split(",", 1)[0].strip()
            dest = re.sub(
                r"\s+\d+(?:[.,]\d+)?\s*(?:штук|шт|boxes?|короб(?:ка|ки|ок)?|мест(?:о|а)?|кг|kg)\b.*$",
                "",
                dest,
                flags=re.IGNORECASE,
            ).strip()
            return _normalize_city(dest)

    to_city_match = RE_TO_CITY.search(raw_text)
    if to_city_match:
        return _normalize_city(to_city_match.group(1).strip())
    return None


def _country_case_candidates(value: str) -> set[str]:
    variants = {value}
    parts = value.split()
    if not parts:
        return variants

    last = parts[-1]
    last_candidates = {last}
    if last.endswith("ии"):
        last_candidates.add(f"{last[:-2]}ия")
    if last.endswith("еи"):
        last_candidates.add(f"{last[:-2]}ея")
    if last.endswith("ая"):
        last_candidates.add(f"{last[:-2]}ай")

    prefixes = [parts[:-1]]
    if len(parts) >= 2 and parts[0].endswith("ой"):
        alt_prefix = [parts[0][:-2] + "ая", *parts[1:-1]]
        prefixes.append(alt_prefix)

    for prefix in prefixes:
        for candidate_last in last_candidates:
            variants.add(" ".join([*prefix, candidate_last]).strip())
    return variants


def _normalize_country_key(value: str) -> str:
    key = value.lower().replace("ё", "е")
    key = re.sub(r"[\-–—_]+", " ", key)
    key = re.sub(r"\s+", " ", key)
    return key.strip(" \t,;.")


def _normalize_country(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = _normalize_country_key(value)
    for candidate in _country_case_candidates(cleaned):
        normalized = COUNTRY_ALIASES.get(candidate)
        if normalized:
            return normalized
    return None


def _classify_route_origin(raw_text: str, route_origin_raw: str | None) -> tuple[str | None, bool]:
    if not route_origin_raw:
        return None, False

    normalized_city = _normalize_city(route_origin_raw)
    if normalized_city in KNOWN_CHINA_ORIGIN_CITIES or _has_china_signal(raw_text):
        return "China", False

    country = _normalize_country(route_origin_raw)
    if country:
        return country, False

    recognized_city = normalized_city is not None and normalized_city != route_origin_raw.strip(" \t,;.-")
    if recognized_city:
        return None, False

    return None, True


def _should_try_llm_fallback(*, route_origin_ambiguous: bool, extracted: dict[str, object]) -> bool:
    if route_origin_ambiguous:
        return True
    return any(extracted.get(key) is None for key in ("from_country", "to_city", "cargo_name", "cargo_description"))


def _merge_llm_extraction(
    *,
    extracted: dict[str, object],
    llm_result: LLMExtractionResult | None,
) -> tuple[dict[str, object], bool, float | None, bool, str | None, str | None]:
    if not llm_result:
        return extracted, False, None, False, None, None

    merged = dict(extracted)
    confidence = llm_result.confidence
    used = False
    if confidence >= LLM_EXTRACTION_MIN_CONFIDENCE:
        from_country_normalized = _normalize_country(llm_result.from_country)
        from_country_raw = (llm_result.from_country or "").strip(" \t,;.-")
        from_country = from_country_normalized or (from_country_raw if len(from_country_raw) >= 2 else None)
        to_city = _normalize_city(llm_result.to_city)
        if not _is_location_like(to_city):
            to_city = None
        to_country_normalized = _normalize_country(llm_result.to_country)
        to_country_raw = (llm_result.to_country or "").strip(" \t,;.-")
        to_country = to_country_normalized or (to_country_raw if len(to_country_raw) >= 2 else None)
        cargo_name_raw = (llm_result.cargo_name or "").strip(" \t,;.-")
        cargo_description_raw = (llm_result.cargo_description or "").strip(" \t,;.-")

        if merged.get("from_country") is None and from_country:
            merged["from_country"] = from_country
            used = True
        if merged.get("to_city") is None and to_city:
            merged["to_city"] = to_city
            used = True
        if merged.get("to_country") is None and to_country:
            merged["to_country"] = to_country
            used = True
        if merged.get("cargo_name") is None and cargo_name_raw:
            cargo_name = cargo_name_raw if _is_meaningful_description_clause(cargo_name_raw) else None
            if cargo_name is None and _looks_like_short_cargo_phrase(cargo_name_raw):
                cargo_name = cargo_name_raw
            if cargo_name:
                merged["cargo_name"] = cargo_name
                used = True
        if merged.get("cargo_description") is None and cargo_description_raw:
            cargo_description = cargo_description_raw if _is_meaningful_description_clause(cargo_description_raw) else None
            if cargo_description is None and len(cargo_description_raw) >= 10:
                cargo_description = cargo_description_raw
            if cargo_description:
                merged["cargo_description"] = cargo_description
                used = True

    return (
        merged,
        used,
        confidence,
        llm_result.needs_clarification,
        llm_result.clarification_question_ru,
        llm_result.clarification_question_en,
    )


def _is_meaningful_description_clause(clause: str) -> bool:
    normalized = clause.strip().lower()
    if not normalized:
        return False
    if any(normalized == phrase or normalized.startswith(f"{phrase} ") for phrase in JUNK_PHRASES):
        return False
    if len(normalized) < 8:
        return False
    if not re.search(r"[a-zа-яё]", normalized, re.IGNORECASE):
        return False
    if any(marker in normalized for marker in INCOTERM_MARKERS):
        return False
    if re.search(r"\b(из|from)\b.+\b(в|to)\b", normalized, re.IGNORECASE):
        return False
    if re.search(r"(?:кг|kg|м3|м³|m3|cbm|куб|мм|mm|см|cm)\b", normalized, re.IGNORECASE):
        return False
    if normalized.startswith(("нужна доставка", "доставка", "need delivery", "shipping needed")):
        return False
    return True


def _has_product_signal(clause: str) -> bool:
    normalized = clause.lower()
    return any(keyword in normalized for keyword in PRODUCT_KEYWORDS)


def _looks_like_short_cargo_phrase(fragment: str) -> bool:
    normalized = fragment.strip(" \t,;.-")
    if not normalized:
        return False
    if ":" in normalized:
        return False
    lowered = normalized.lower()
    if any(lowered == phrase or lowered.startswith(f"{phrase} ") for phrase in JUNK_PHRASES):
        return False
    if re.search(r"\b(из|from)\b.+\b(в|to)\b", lowered, re.IGNORECASE):
        return False
    if re.search(r"(?:кг|kg|м3|м³|m3|cbm|куб|мм|mm|см|cm)\b", lowered, re.IGNORECASE):
        return False
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9+-]+", normalized)
    if not (1 <= len(words) <= 3):
        return False
    if any(word.lower() in SHORT_CARGO_STOPWORDS for word in words):
        return False
    if not any(re.search(r"[A-Za-zА-Яа-яЁё]", word) for word in words):
        return False
    return len(normalized) <= 40


def _extract_cargo_name(raw_text: str) -> str | None:
    labeled_match = RE_CARGO_LABELED.search(raw_text)
    if labeled_match:
        candidate = labeled_match.group(1).strip(" \t,;.-")
        if len(candidate) >= 3 and _is_meaningful_description_clause(candidate):
            return candidate
        return None

    route_cargo_match = RE_CARGO_BEFORE_ROUTE_RU.search(raw_text) or RE_CARGO_BEFORE_ROUTE_EN.search(raw_text)
    if route_cargo_match:
        candidate = route_cargo_match.group(1).strip(" \t,;.-")
        candidate = re.sub(r"\s+(?:на|for)\s*$", "", candidate, flags=re.IGNORECASE).strip(" \t,;.-")
        if len(candidate) >= 3 and not re.search(r"\b(из|from)\b.+\b(в|to)\b", candidate, re.IGNORECASE):
            return candidate

    fragments = [part.strip() for part in re.split(r"[\n.;]", raw_text) if part.strip()]
    if not fragments:
        return None
    first = fragments[0]
    if _is_meaningful_description_clause(first) and _has_product_signal(first):
        return first

    last = fragments[-1].strip(" \t,;.-")
    if _looks_like_short_cargo_phrase(last):
        return last
    return None


def _extract_cargo_description(raw_text: str, cargo_name: str | None) -> str | None:
    fragments = [part.strip() for part in re.split(r"[\n.;]", raw_text) if part.strip()]
    for fragment in fragments:
        if _is_meaningful_description_clause(fragment) and _has_product_signal(fragment):
            return fragment
    if cargo_name and _is_meaningful_description_clause(cargo_name) and _has_product_signal(cargo_name):
        return cargo_name
    return None


def run_delivery_precheck(raw_text: str, lang: str = "ru") -> dict[str, str]:
    from_country_match = RE_FROM_COUNTRY.search(raw_text)
    weight_match = RE_WEIGHT.search(raw_text)
    volume_match = RE_VOLUME.search(raw_text)
    route_origin_raw, route_destination_raw = _extract_route_entities(raw_text)
    cargo_name = _extract_cargo_name(raw_text)
    cargo_description = _extract_cargo_description(raw_text, cargo_name)

    weight_value = _to_float(weight_match.group(1).strip() if weight_match else None)
    volume_value = _to_float(volume_match.group(1).strip() if volume_match else None)
    if volume_value is None:
        volume_value = _extract_volume_from_dimensions(raw_text)

    from_country_value = _normalize_country(from_country_match.group(1).strip()) if from_country_match else None
    route_country_value, route_origin_ambiguous = _classify_route_origin(raw_text, route_origin_raw)
    if not from_country_value and route_country_value:
        from_country_value = route_country_value

    to_city_value = _normalize_city(route_destination_raw) or _extract_to_city(raw_text)
    if not _is_location_like(to_city_value):
        to_city_value = None

    extracted: dict[str, object] = {
        "from_country": from_country_value,
        "to_city": to_city_value,
        "to_country": None,
        "weight_kg": weight_value,
        "volume_m3": volume_value,
        "cargo_name": cargo_name,
        "cargo_description": cargo_description,
    }

    llm_used = False
    llm_confidence: float | None = None
    llm_needs_clarification = False
    llm_clarification_ru: str | None = None
    llm_clarification_en: str | None = None
    if _should_try_llm_fallback(route_origin_ambiguous=route_origin_ambiguous, extracted=extracted):
        (
            extracted,
            llm_used,
            llm_confidence,
            llm_needs_clarification,
            llm_clarification_ru,
            llm_clarification_en,
        ) = _merge_llm_extraction(
            extracted=extracted,
            llm_result=extract_delivery_entities_with_llm(raw_text),
        )

    if extracted.get("from_country") is not None and not llm_needs_clarification:
        route_origin_ambiguous = False
    else:
        route_origin_ambiguous = route_origin_ambiguous or bool(llm_needs_clarification)

    required_fields = ("from_country", "to_city", "weight_kg", "volume_m3", "cargo_name", "cargo_description")
    missing_fields = [key for key in required_fields if extracted.get(key) is None]
    status = "ok" if not missing_fields else "missing_info"

    is_ru = (lang or "ru").lower() == "ru"
    if status == "ok":
        if is_ru:
            notes = (
                f"Обнаружен маршрут {extracted['from_country']} -> {extracted['to_city']}; "
                f"вес {extracted['weight_kg']} кг; объем {extracted['volume_m3']} м3."
            )
        else:
            notes = (
                f"Detected route {extracted['from_country']} -> {extracted['to_city']}; "
                f"weight {extracted['weight_kg']}kg; volume {extracted['volume_m3']}m3."
            )
    else:
        if route_origin_ambiguous:
            notes = (
                "Маршрут найден, но страна отправления определена неоднозначно. Нужна уточняющая информация."
                if is_ru
                else "Route was found, but origin country is ambiguous. Clarification is required."
            )
        else:
            notes = (
                "Не хватает ключевых данных для предварительной оценки."
                if is_ru
                else "Missing critical fields for delivery quote precheck."
            )

    if llm_confidence is not None:
        notes = f"{notes} LLM fallback: {'yes' if llm_used else 'no'}; confidence: {llm_confidence:.2f}."
    else:
        notes = f"{notes} LLM fallback: no."

    return {
        "precheck_status": status,
        "missing_fields": json.dumps(missing_fields),
        "notes": notes,
        "from_country": str(extracted.get("from_country") or ""),
        "to_city": str(extracted.get("to_city") or ""),
        "to_country": str(extracted.get("to_country") or ""),
        "cargo_name": str(extracted.get("cargo_name") or ""),
        "cargo_description": str(extracted.get("cargo_description") or ""),
        "route_origin_ambiguous": "true" if route_origin_ambiguous else "false",
        "llm_fallback_used": "true" if llm_used else "false",
        "llm_extraction_confidence": f"{llm_confidence:.2f}" if llm_confidence is not None else "",
        "llm_needs_clarification": "true" if llm_needs_clarification else "false",
        "clarification_question_ru": llm_clarification_ru or "",
        "clarification_question_en": llm_clarification_en or "",
    }
