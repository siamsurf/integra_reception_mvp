import re

DELIVERY_SIGNALS = [
    "доставка",
    "логист",
    "груз",
    "контейнер",
    "маршрут",
    "kg",
    "кг",
    "м3",
    "м³",
    "куб",
    "cbm",
    "exw",
    "fob",
    "freight",
    "cargo",
    "shipment",
]
SUPPLIER_SIGNALS = [
    "поставщик",
    "проверка поставщика",
    "supplier check",
    "supplier",
    "factory audit",
    "vendor",
    "audit",
    "комплаенс",
]


def detect_intent_from_text(raw_text: str) -> str:
    text = raw_text.lower()

    if any(k in text for k in SUPPLIER_SIGNALS):
        return "supplier_check"

    has_delivery_word = any(k in text for k in DELIVERY_SIGNALS)
    has_route_pattern = bool(re.search(r"\bиз\b.+\bв\b|\bfrom\b.+\bto\b|->|→|—|–", text, re.IGNORECASE))
    has_metrics = bool(re.search(r"\b\d+(?:[.,]\d+)?\s*(?:кг|kg|м3|м³|m3|куб|cbm)\b", text, re.IGNORECASE))
    has_geo_hint = bool(
        re.search(r"\b(country|city|страна|город|moscow|москва|shanghai|шанхай|guangzhou|гуанчжоу)\b", text)
    )

    if has_delivery_word or (has_route_pattern and has_metrics) or (has_geo_hint and has_metrics):
        return "delivery"

    return "offtopic"


def _rule_based_classification(service_type: str, raw_text: str) -> str:
    if service_type == "delivery":
        return "delivery"
    if service_type == "supplier_check":
        return "supplier_check"
    if service_type == "offtopic":
        return "offtopic"
    return detect_intent_from_text(raw_text)


def _normalize_service_type(value: str) -> str:
    return re.sub(r"\s+", "_", value.strip().lower())


def run_reception_pipeline(service_type: str, raw_text: str) -> dict[str, str]:
    normalized = _normalize_service_type(service_type)
    if normalized not in {"delivery", "supplier_check", "offtopic"}:
        normalized = detect_intent_from_text(raw_text)
    classification = _rule_based_classification(normalized, raw_text)
    return {
        "service_type": normalized,
        "classification": classification,
    }


def _detect_suspicious_input(raw_text: str, selected_service_type: str, suggested_service_type: str) -> tuple[bool, str | None]:
    text = raw_text.strip()
    lowered = text.lower()
    if not text:
        return True, "empty_or_blank"

    urls = len(re.findall(r"https?://|www\.", lowered))
    if urls >= 3:
        return True, "too_many_links"

    if re.search(r"(.{4,})\1{3,}", lowered):
        return True, "flood_repetition"

    spam_words = (
        "казино",
        "casino",
        "bet",
        "ставк",
        "порно",
        "sex",
        "crypto giveaway",
        "airdrop",
        "заработок без вложений",
        "buy now",
    )
    if any(word in lowered for word in spam_words):
        return True, "spam_wording"

    alpha_tokens = re.findall(r"[A-Za-zА-Яа-яЁё]{2,}", text)
    if len(alpha_tokens) <= 1 and len(text) < 20:
        return True, "too_low_information"

    if selected_service_type == "supplier_check" and suggested_service_type == "delivery":
        has_supplier_markers = any(k in lowered for k in SUPPLIER_SIGNALS)
        has_delivery_markers = any(k in lowered for k in DELIVERY_SIGNALS)
        if has_delivery_markers and not has_supplier_markers:
            return True, "service_text_conflict"

    return False, None


def build_validation_flags(service_type: str, raw_text: str) -> dict[str, str | bool | None]:
    selected = _normalize_service_type(service_type)
    suggested = detect_intent_from_text(raw_text)
    service_type_mismatch = selected in {"delivery", "supplier_check", "offtopic"} and suggested != selected
    suspicious_input, suspicious_reason = _detect_suspicious_input(raw_text, selected, suggested)

    return {
        "service_type_mismatch": service_type_mismatch,
        "suggested_service_type": suggested if service_type_mismatch else None,
        "suspicious_input": suspicious_input,
        "suspicious_reason": suspicious_reason,
    }
