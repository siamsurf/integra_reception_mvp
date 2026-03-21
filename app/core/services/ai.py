from __future__ import annotations

import json
from dataclasses import dataclass

from openai import OpenAI

from app.core.i18n import normalize_lang
from app.core.settings import settings


@dataclass
class AIResult:
    classification: str
    manager_summary: str
    draft_reply: str
    model_name: str
    fallback_used: bool


ATTACHMENTS_NOTE_RU = (
    "Для расчёта желательно также приложить инвойс и фото товара. "
    "Я передам их нашим специалистам, фото и дополнительные документы "
    "помогут быстрее и точнее обработать заявку."
)
ATTACHMENTS_NOTE_EN = (
    "For a quote, it is also helpful to attach the invoice and product photos. "
    "I will pass them to our specialists, and photos plus additional documents "
    "help process your request faster and more accurately."
)
ATTACHMENTS_RECEIVED_RU = (
    "Документы уже получены. Я передам их нашим специалистам, это поможет быстрее и точнее обработать заявку."
)
ATTACHMENTS_RECEIVED_EN = (
    "Your documents have already been received. I will pass them to our specialists to help process your request "
    "faster and more accurately."
)
MISMATCH_REPLY_RU = (
    "Спасибо за сообщение. Чтобы не ошибиться с обработкой заявки, уточните, пожалуйста, "
    "какая услуга вас интересует: доставка или проверка поставщика?"
)
MISMATCH_REPLY_EN = (
    "Thank you for your message. To process your request correctly, please confirm which service you need: "
    "delivery or supplier check?"
)
SUSPICIOUS_REPLY_RU = (
    "Спасибо за сообщение. Для корректной обработки заявки, пожалуйста, уточните маршрут, "
    "параметры груза и нужную услугу."
)
SUSPICIOUS_REPLY_EN = (
    "Thank you for your message. To process your request correctly, please clarify your route, cargo details, "
    "and required service."
)


def _parse_missing_fields(precheck: dict[str, str] | None) -> list[str]:
    if not precheck:
        return []
    raw = precheck.get("missing_fields", "[]")
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []


def _has_route_origin_ambiguity(precheck: dict[str, str] | None) -> bool:
    if not precheck:
        return False
    raw = str(precheck.get("route_origin_ambiguous", "")).strip().lower()
    return raw in {"true", "1", "yes"}


def _is_true(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _validation_flags(validation: dict[str, object] | None) -> tuple[bool, str | None, bool]:
    if not validation:
        return False, None, False
    mismatch = _is_true(validation.get("service_type_mismatch"))
    suggested = str(validation.get("suggested_service_type") or "").strip() or None
    suspicious = _is_true(validation.get("suspicious_input"))
    return mismatch, suggested, suspicious


def _has_llm_needs_clarification(precheck: dict[str, str] | None) -> bool:
    if not precheck:
        return False
    raw = str(precheck.get("llm_needs_clarification", "")).strip().lower()
    return raw in {"true", "1", "yes"}


def _clarification_question(precheck: dict[str, str] | None, lang_code: str) -> str | None:
    if not precheck:
        return None
    key = "clarification_question_ru" if lang_code == "ru" else "clarification_question_en"
    value = str(precheck.get(key, "")).strip()
    return value or None


def _fallback_texts(
    service_type: str,
    classification: str,
    precheck: dict[str, str] | None,
    lang: str,
    attachment_types: list[str] | None = None,
    validation: dict[str, object] | None = None,
) -> tuple[str, str]:
    lang_code = normalize_lang(lang)
    missing_fields = _parse_missing_fields(precheck)
    route_origin_ambiguous = _has_route_origin_ambiguity(precheck)
    llm_needs_clarification = _has_llm_needs_clarification(precheck)
    clarification_question = _clarification_question(precheck, lang_code)
    service_mismatch, suggested_service_type, suspicious_input = _validation_flags(validation)
    provided_types = set(attachment_types or [])
    has_invoice = "invoice" in provided_types
    has_cargo_photo = "cargo_photo" in provided_types
    has_attachments = bool(provided_types)

    labels_ru = {
        "from_country": "страна отправления",
        "to_city": "город назначения",
        "weight_kg": "вес (кг)",
        "volume_m3": "объём (м³)",
        "cargo_name": "наименование груза",
        "cargo_description": "описание груза",
    }
    labels_en = {
        "from_country": "origin country",
        "to_city": "destination city",
        "weight_kg": "weight (kg)",
        "volume_m3": "volume (m3)",
        "cargo_name": "cargo name",
        "cargo_description": "cargo description",
    }

    if lang_code == "ru":
        if not has_attachments:
            attachment_tail = ATTACHMENTS_NOTE_RU
        elif has_invoice and has_cargo_photo:
            attachment_tail = ATTACHMENTS_RECEIVED_RU
        elif has_invoice:
            attachment_tail = f"Инвойс уже получен. {ATTACHMENTS_RECEIVED_RU} Если есть возможность, приложите фото товара."
        elif has_cargo_photo:
            attachment_tail = f"Фото товара уже получены. {ATTACHMENTS_RECEIVED_RU} Если есть возможность, приложите инвойс."
        else:
            attachment_tail = ATTACHMENTS_RECEIVED_RU
    else:
        if not has_attachments:
            attachment_tail = ATTACHMENTS_NOTE_EN
        elif has_invoice and has_cargo_photo:
            attachment_tail = ATTACHMENTS_RECEIVED_EN
        elif has_invoice:
            attachment_tail = (
                "The invoice has already been received. "
                f"{ATTACHMENTS_RECEIVED_EN} If possible, please also attach product photos."
            )
        elif has_cargo_photo:
            attachment_tail = (
                "Product photos have already been received. "
                f"{ATTACHMENTS_RECEIVED_EN} If possible, please also attach the invoice."
            )
        else:
            attachment_tail = ATTACHMENTS_RECEIVED_EN

    if lang_code == "ru":
        if suspicious_input:
            return (
                "Отмечен осторожный сигнал валидации: требуется уточнение входящих данных.",
                SUSPICIOUS_REPLY_RU,
            )
        if service_mismatch:
            note = (
                " По тексту сообщение похоже на запрос по доставке, но прошу подтвердить."
                if suggested_service_type == "delivery"
                else (
                    " По тексту сообщение похоже на запрос по проверке поставщика, но прошу подтвердить."
                    if suggested_service_type == "supplier_check"
                    else ""
                )
            )
            return (
                "Обнаружено несоответствие выбранного типа услуги и содержания сообщения; нужно подтверждение клиента.",
                f"{MISMATCH_REPLY_RU}{note}",
            )
        if service_type == "offtopic":
            manager_summary = (
                "Сообщение классифицировано как 'offtopic'. "
                "Запрос не относится к логистике, доставке или проверке поставщиков."
            )
            draft_reply = (
                "Я помогаю по вопросам логистики, доставки и проверки поставщиков. "
                "По этому сообщению я не могу подготовить заявку. "
                "Если вам нужен расчёт доставки, напишите маршрут, вес, объём и описание груза."
            )
            return manager_summary, draft_reply
        if service_type == "delivery":
            precheck_status = precheck["precheck_status"] if precheck else "missing_info"
            missing = ", ".join(labels_ru.get(field, field) for field in missing_fields) if missing_fields else "нет"
            manager_summary = (
                f"Заявка на доставку классифицирована как '{classification}'. "
                f"Статус предпроверки: {precheck_status}. Недостающие поля: {missing}."
            )
            if missing_fields:
                requested = ", ".join(labels_ru.get(field, field) for field in missing_fields)
                clarification = ""
                if llm_needs_clarification and clarification_question:
                    clarification = f" {clarification_question}"
                elif route_origin_ambiguous:
                    clarification = " Правильно ли я понял маршрут? Пожалуйста, уточните страну и город отправления."
                draft_reply = (
                    "Спасибо за запрос на доставку. Для расчёта, пожалуйста, уточните только недостающие данные: "
                    f"{requested}.{clarification} {attachment_tail}"
                )
            else:
                draft_reply = (
                    "Спасибо за запрос на доставку. Все ключевые данные получены, "
                    f"подготавливаем расчёт и вернёмся с предложением. {attachment_tail}"
                )
        else:
            manager_summary = (
                f"Заявка на проверку поставщика классифицирована как '{classification}'. "
                "Рекомендуется проверить данные поставщика, комплаенс-документы и ожидаемые сроки."
            )
            draft_reply = (
                "Спасибо за запрос на проверку поставщика. Пожалуйста, укажите название поставщика, "
                "состав продукции и требования комплаенса для быстрого старта."
            )
        return manager_summary, draft_reply

    if service_type == "offtopic":
        manager_summary = (
            "Message classified as 'offtopic'. "
            "The request is outside logistics, delivery, and supplier-check scope."
        )
        draft_reply = (
            "I can help with logistics, delivery, and supplier-check requests. "
            "I cannot create a lead from this message. "
            "If you need a delivery quote, please share route, weight, volume, and cargo description."
        )
    elif service_type == "delivery":
        precheck_status = precheck["precheck_status"] if precheck else "missing_info"
        missing = ", ".join(labels_en.get(field, field) for field in missing_fields) if missing_fields else "none"
        manager_summary = (
            f"Delivery lead classified as '{classification}'. "
            f"Precheck status: {precheck_status}. Missing fields: {missing}."
        )
        if missing_fields:
            requested = ", ".join(labels_en.get(field, field) for field in missing_fields)
            clarification = ""
            if llm_needs_clarification and clarification_question:
                clarification = f" {clarification_question}"
            elif route_origin_ambiguous:
                clarification = " Please confirm the route: kindly clarify the origin country and city."
            draft_reply = (
                "Thanks for your delivery request. To prepare a quote, please share only these missing details: "
                f"{requested}.{clarification} {attachment_tail}"
            )
        else:
            draft_reply = (
                f"Thanks for your delivery request. We have all key details and are preparing your quote. {attachment_tail}"
            )
    else:
        manager_summary = (
            f"Supplier check lead classified as '{classification}'. "
            "Recommend verifying supplier details, compliance docs, and expected timeline."
        )
        draft_reply = (
            "Thanks for your supplier check request. Please share supplier name, product scope, "
            "and any compliance requirements so we can proceed quickly."
        )
    return manager_summary, draft_reply


def _build_prompt(
    service_type: str,
    classification: str,
    raw_text: str,
    precheck: dict[str, str] | None,
    lang: str,
    attachment_types: list[str] | None = None,
    validation: dict[str, object] | None = None,
) -> str:
    lang_code = normalize_lang(lang)
    lang_name = "Russian" if lang_code == "ru" else "English"
    return (
        "You are an operations assistant for a reception desk. "
        f"Write all text in {lang_name}. "
        "Return valid JSON with keys manager_summary and draft_reply only.\n\n"
        "Do not claim that files are analyzed. "
        "Attachments can only be accepted and stored, then passed to specialists.\n\n"
        "If attachment_types contains invoice and/or cargo_photo, acknowledge they were received and do not ask for those again.\n\n"
        "If precheck.llm_needs_clarification is true and clarification_question exists, use it.\n"
        "If precheck.route_origin_ambiguous is true, ask a short clarification for origin country and city.\n\n"
        "If validation.service_type_mismatch is true, use a neutral clarification and do not assume selected service type.\n"
        "If validation.suspicious_input is true, keep reply polite, short, and clarifying.\n\n"
        f"service_type={service_type}\n"
        f"classification={classification}\n"
        f"precheck={precheck}\n"
        f"attachment_types={attachment_types or []}\n"
        f"validation={validation or {}}\n"
        f"raw_text={raw_text}\n"
    )


def generate_ai_output(
    service_type: str,
    classification: str,
    raw_text: str,
    precheck: dict[str, str] | None,
    lang: str,
    attachment_types: list[str] | None = None,
    validation: dict[str, object] | None = None,
) -> AIResult:
    normalized_attachment_types = sorted({item.strip().lower() for item in (attachment_types or []) if item})
    route_origin_ambiguous = _has_route_origin_ambiguity(precheck)
    llm_needs_clarification = _has_llm_needs_clarification(precheck)
    service_mismatch, _, suspicious_input = _validation_flags(validation)
    fallback_summary, fallback_reply = _fallback_texts(
        service_type,
        classification,
        precheck,
        lang,
        attachment_types=normalized_attachment_types,
        validation=validation,
    )

    if not settings.openai_api_key:
        return AIResult(
            classification=classification,
            manager_summary=fallback_summary,
            draft_reply=fallback_reply,
            model_name="fallback-template",
            fallback_used=True,
        )

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        completion = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": "Be concise and practical."},
                {
                    "role": "user",
                    "content": _build_prompt(
                        service_type,
                        classification,
                        raw_text,
                        precheck,
                        lang,
                        attachment_types=normalized_attachment_types,
                        validation=validation,
                    ),
                },
            ],
        )
        content = completion.choices[0].message.content or ""

        manager_summary = fallback_summary
        draft_reply = fallback_reply

        try:
            parsed = json.loads(content)
            manager_summary = str(parsed.get("manager_summary") or "").strip() or fallback_summary
            draft_reply = str(parsed.get("draft_reply") or "").strip() or fallback_reply
        except Exception:
            pass

        # For delivery with uploaded files, keep deterministic attachment-aware phrasing.
        if service_mismatch or suspicious_input:
            manager_summary = fallback_summary
            draft_reply = fallback_reply
        elif service_type == "delivery" and (normalized_attachment_types or route_origin_ambiguous or llm_needs_clarification):
            draft_reply = fallback_reply

        return AIResult(
            classification=classification,
            manager_summary=manager_summary,
            draft_reply=draft_reply,
            model_name=settings.openai_model,
            fallback_used=False,
        )
    except Exception:
        return AIResult(
            classification=classification,
            manager_summary=fallback_summary,
            draft_reply=fallback_reply,
            model_name="fallback-template",
            fallback_used=True,
        )
