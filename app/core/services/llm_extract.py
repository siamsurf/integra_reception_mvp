from __future__ import annotations

import json
from dataclasses import dataclass

from openai import OpenAI

from app.core.settings import settings


@dataclass
class LLMExtractionResult:
    from_country: str | None
    from_city: str | None
    to_country: str | None
    to_city: str | None
    cargo_name: str | None
    cargo_description: str | None
    confidence: float
    needs_clarification: bool
    clarification_question_ru: str | None
    clarification_question_en: str | None


def _clean_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _build_prompt(raw_text: str) -> str:
    return (
        "Extract only logistics entities from the user text.\n"
        "Do not invent facts. If uncertain, use null and set needs_clarification=true.\n"
        "Distinguish country vs city carefully.\n"
        "Output JSON only with exact keys:\n"
        "{\n"
        '  "from_country": string | null,\n'
        '  "from_city": string | null,\n'
        '  "to_country": string | null,\n'
        '  "to_city": string | null,\n'
        '  "cargo_name": string | null,\n'
        '  "cargo_description": string | null,\n'
        '  "confidence": number,\n'
        '  "needs_clarification": boolean,\n'
        '  "clarification_question_ru": string | null,\n'
        '  "clarification_question_en": string | null\n'
        "}\n\n"
        f"User text:\n{raw_text}\n"
    )


def extract_delivery_entities_with_llm(raw_text: str) -> LLMExtractionResult | None:
    if not settings.openai_api_key:
        return None

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        completion = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0.0,
            messages=[
                {"role": "system", "content": "Return strict JSON only. No markdown."},
                {"role": "user", "content": _build_prompt(raw_text)},
            ],
        )
        content = completion.choices[0].message.content or ""
        parsed = json.loads(content)
        confidence_raw = parsed.get("confidence", 0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        return LLMExtractionResult(
            from_country=_clean_str(parsed.get("from_country")),
            from_city=_clean_str(parsed.get("from_city")),
            to_country=_clean_str(parsed.get("to_country")),
            to_city=_clean_str(parsed.get("to_city")),
            cargo_name=_clean_str(parsed.get("cargo_name")),
            cargo_description=_clean_str(parsed.get("cargo_description")),
            confidence=confidence,
            needs_clarification=bool(parsed.get("needs_clarification", False)),
            clarification_question_ru=_clean_str(parsed.get("clarification_question_ru")),
            clarification_question_en=_clean_str(parsed.get("clarification_question_en")),
        )
    except Exception:
        return None
