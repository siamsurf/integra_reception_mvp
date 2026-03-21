from __future__ import annotations

import json
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.core.i18n import normalize_lang, t
from app.core.settings import settings
from app.core.services.ai import generate_ai_output
from app.core.services.precheck import run_delivery_precheck
from app.core.services.reception import build_validation_flags, run_reception_pipeline
from app.db.models.ai_output import AIOutput
from app.db.models.attachment import Attachment
from app.db.models.lead import Lead
from app.db.models.precheck_result import PrecheckResult
from app.db.session import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
ATTACHMENTS_DIR = Path("app/static/uploads")


def _get_lang(request: Request) -> str:
    q_lang = request.query_params.get("lang")
    if q_lang in {"ru", "en"}:
        return q_lang

    c_lang = request.cookies.get("lang")
    if c_lang in {"ru", "en"}:
        return c_lang

    return "ru"


def _context(request: Request, lang: str, **extra: object) -> dict[str, object]:
    next_path = request.url.path or "/"

    def tr(key: str, **kwargs: object) -> str:
        return t(lang, key, **kwargs)

    payload: dict[str, object] = {
        "request": request,
        "lang": lang,
        "tr": tr,
        "next_path": next_path,
        "next_path_q": quote(next_path, safe="/"),
    }
    payload.update(extra)
    return payload


def _attachment_accept_attr() -> str:
    return ",".join(f".{ext}" for ext in settings.attachment_allowed_extensions)


def _attachment_extension(file_name: str) -> str:
    dot_idx = file_name.rfind(".")
    if dot_idx == -1 or dot_idx == len(file_name) - 1:
        return ""
    return file_name[dot_idx + 1 :].lower()


def _store_attachments(
    *,
    db: Session,
    lead: Lead,
    lang: str,
    attachment_type: str,
    files: list[UploadFile],
) -> set[str]:
    uploads = [file for file in files if file.filename and file.filename.strip()]
    if not uploads:
        return set()

    allowed_types = set(settings.attachment_types)
    normalized_type = attachment_type.strip().lower()
    if normalized_type not in allowed_types:
        raise ValueError(
            t(lang, "error_attachment_type_invalid", value=attachment_type, allowed=", ".join(settings.attachment_types))
        )

    existing_count = db.query(Attachment).filter(Attachment.lead_id == lead.id).count()
    if existing_count + len(uploads) > settings.attachment_max_files_per_lead:
        raise ValueError(
            t(
                lang,
                "error_attachment_too_many",
                limit=settings.attachment_max_files_per_lead,
            )
        )

    max_bytes = settings.attachment_max_file_size_mb * 1024 * 1024
    allowed_exts = set(settings.attachment_allowed_extensions)
    lead_dir = ATTACHMENTS_DIR / lead.rid
    lead_dir.mkdir(parents=True, exist_ok=True)

    for upload in uploads:
        original_name = Path(upload.filename or "").name
        extension = _attachment_extension(original_name)
        if extension not in allowed_exts:
            raise ValueError(
                t(lang, "error_attachment_extension_invalid", allowed=", ".join(settings.attachment_allowed_extensions))
            )

        stored_name = f"{uuid.uuid4().hex}_{original_name}"
        stored_path = lead_dir / stored_name
        total_size = 0
        try:
            with stored_path.open("wb") as out:
                while True:
                    chunk = upload.file.read(1024 * 1024)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > max_bytes:
                        raise ValueError(
                            t(
                                lang,
                                "error_attachment_too_large",
                                limit_mb=settings.attachment_max_file_size_mb,
                                file_name=original_name,
                            )
                        )
                    out.write(chunk)
        except Exception:
            if stored_path.exists():
                stored_path.unlink()
            raise
        finally:
            upload.file.close()

        db.add(
            Attachment(
                lead_id=lead.id,
                source_channel="web",
                attachment_type=normalized_type,
                file_name=original_name,
                file_ref=f"/static/uploads/{lead.rid}/{stored_name}",
                mime_type=upload.content_type,
            )
        )
    return {normalized_type}


@router.get("/set-lang")
def set_lang(
    lang: str = Query("ru"),
    next: str = Query("/"),
) -> RedirectResponse:
    selected = normalize_lang(lang)
    safe_next = next if next.startswith("/") else "/"

    response = RedirectResponse(url=safe_next, status_code=303)
    response.set_cookie(
        key="lang",
        value=selected,
        max_age=60 * 60 * 24 * 365,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    lang = _get_lang(request)
    return templates.TemplateResponse("index.html", _context(request, lang))


@router.get("/new", response_class=HTMLResponse)
def new_lead_form(request: Request) -> HTMLResponse:
    lang = _get_lang(request)
    return templates.TemplateResponse(
        "new_lead.html",
        _context(
            request,
            lang,
            result=None,
            error=None,
            attachment_allowed_extensions=settings.attachment_allowed_extensions,
            attachment_accept_attr=_attachment_accept_attr(),
            attachment_max_files_per_lead=settings.attachment_max_files_per_lead,
            attachment_max_file_size_mb=settings.attachment_max_file_size_mb,
        ),
    )


@router.post("/new", response_class=HTMLResponse)
def create_lead(
    request: Request,
    service_type: str = Form(...),
    client_name: str = Form(...),
    phone: str = Form(...),
    email: str | None = Form(default=None),
    raw_text: str = Form(...),
    attachments: list[UploadFile] | None = File(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    lang = _get_lang(request)
    service_type = service_type.strip().lower()
    if service_type not in {"delivery", "supplier_check"}:
        raise HTTPException(status_code=400, detail="service_type must be delivery or supplier_check")

    rid = uuid.uuid4().hex[:8]

    lead = Lead(
        rid=rid,
        service_type=service_type,
        client_name=client_name.strip(),
        phone=phone.strip(),
        email=(email.strip() if email else None),
        raw_text=raw_text.strip(),
        status="received",
    )
    db.add(lead)
    db.flush()

    reception_result = run_reception_pipeline(service_type=service_type, raw_text=lead.raw_text)
    validation_flags = build_validation_flags(service_type, lead.raw_text)

    precheck_payload: dict[str, str] | None = None
    if service_type == "delivery":
        precheck_payload = run_delivery_precheck(lead.raw_text, lang=lang)
        precheck_row = PrecheckResult(
            lead_id=lead.id,
            precheck_status=precheck_payload["precheck_status"],
            missing_fields=precheck_payload["missing_fields"],
            notes=precheck_payload["notes"],
        )
        db.add(precheck_row)
        lead.status = "needs_info" if precheck_payload["precheck_status"] == "missing_info" else "ready"
    else:
        lead.status = "ready"

    attachment_types: set[str] = set()
    try:
        attachment_types = _store_attachments(
            db=db,
            lead=lead,
            lang=lang,
            attachment_type="other",
            files=attachments or [],
        )
    except ValueError as exc:
        db.rollback()
        return templates.TemplateResponse(
            "new_lead.html",
            _context(
                request,
                lang,
                result=None,
                error=str(exc),
                attachment_allowed_extensions=settings.attachment_allowed_extensions,
                attachment_accept_attr=_attachment_accept_attr(),
                attachment_max_files_per_lead=settings.attachment_max_files_per_lead,
                attachment_max_file_size_mb=settings.attachment_max_file_size_mb,
            ),
            status_code=400,
        )

    ai = generate_ai_output(
        service_type=service_type,
        classification=reception_result["classification"],
        raw_text=lead.raw_text,
        precheck=precheck_payload,
        lang=lang,
        attachment_types=sorted(attachment_types),
        validation=validation_flags,
    )
    ai_row = AIOutput(
        lead_id=lead.id,
        classification=ai.classification,
        manager_summary=ai.manager_summary,
        draft_reply=ai.draft_reply,
        model_name=ai.model_name,
        fallback_used=ai.fallback_used,
    )
    db.add(ai_row)

    db.commit()

    next_steps = t(lang, "next_steps_needs_info") if lead.status == "needs_info" else t(lang, "next_steps_ready")

    return templates.TemplateResponse(
        "new_lead.html",
        _context(
            request,
            lang,
            result={"rid": rid, "status": lead.status, "next_steps": next_steps},
            error=None,
            attachment_allowed_extensions=settings.attachment_allowed_extensions,
            attachment_accept_attr=_attachment_accept_attr(),
            attachment_max_files_per_lead=settings.attachment_max_files_per_lead,
            attachment_max_file_size_mb=settings.attachment_max_file_size_mb,
        ),
    )


@router.get("/admin", response_class=HTMLResponse)
def admin_list(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    lang = _get_lang(request)
    leads = db.query(Lead).order_by(Lead.created_at.desc()).all()
    return templates.TemplateResponse("admin_list.html", _context(request, lang, leads=leads))


@router.get("/admin/{rid}", response_class=HTMLResponse)
def admin_detail(rid: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    lang = _get_lang(request)
    lead = (
        db.query(Lead)
        .options(joinedload(Lead.ai_outputs), joinedload(Lead.precheck_results), joinedload(Lead.attachments))
        .filter(Lead.rid == rid)
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    ai_output = lead.ai_outputs[-1] if lead.ai_outputs else None
    precheck = lead.precheck_results[-1] if lead.precheck_results else None

    missing_fields: list[str] = []
    if precheck and precheck.missing_fields:
        try:
            missing_fields = json.loads(precheck.missing_fields)
        except json.JSONDecodeError:
            missing_fields = [precheck.missing_fields]
    validation_flags = build_validation_flags(lead.service_type, lead.raw_text)

    return templates.TemplateResponse(
        "admin_detail.html",
        _context(
            request,
            lang,
            lead=lead,
            ai=ai_output,
            precheck=precheck,
            missing_fields=missing_fields,
            attachments=lead.attachments,
            validation_flags=validation_flags,
        ),
    )


@router.get("/admin/{rid}/export.json", response_class=JSONResponse)
def admin_export_json(rid: str, db: Session = Depends(get_db)) -> JSONResponse:
    lead = (
        db.query(Lead)
        .options(joinedload(Lead.ai_outputs), joinedload(Lead.precheck_results), joinedload(Lead.attachments))
        .filter(Lead.rid == rid)
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    ai_output = lead.ai_outputs[-1] if lead.ai_outputs else None
    precheck = lead.precheck_results[-1] if lead.precheck_results else None

    missing_fields: list[str] = []
    if precheck and precheck.missing_fields:
        try:
            parsed = json.loads(precheck.missing_fields)
            if isinstance(parsed, list):
                missing_fields = [str(item) for item in parsed]
        except json.JSONDecodeError:
            missing_fields = [precheck.missing_fields]
    validation_flags = build_validation_flags(lead.service_type, lead.raw_text)

    structured_precheck: dict[str, str] | None = None
    if lead.service_type == "delivery":
        structured_precheck = run_delivery_precheck(lead.raw_text, lang="ru")

    payload = {
        "rid": lead.rid,
        "service_type": lead.service_type,
        "status": lead.status,
        "client": {
            "name": lead.client_name,
            "phone": lead.phone,
            "email": lead.email,
        },
        "raw_text": lead.raw_text,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "ai": (
            {
                "classification": ai_output.classification,
                "manager_summary": ai_output.manager_summary,
                "draft_reply": ai_output.draft_reply,
                "model_name": ai_output.model_name,
                "fallback_used": ai_output.fallback_used,
            }
            if ai_output
            else None
        ),
        "precheck": (
            {
                "status": precheck.precheck_status,
                "missing_fields": missing_fields,
                "notes": precheck.notes,
                "from_country": (structured_precheck or {}).get("from_country"),
                "to_city": (structured_precheck or {}).get("to_city"),
                "to_country": (structured_precheck or {}).get("to_country"),
                "cargo_name": (structured_precheck or {}).get("cargo_name"),
                "cargo_description": (structured_precheck or {}).get("cargo_description"),
                "llm_fallback_used": (structured_precheck or {}).get("llm_fallback_used"),
                "llm_extraction_confidence": (structured_precheck or {}).get("llm_extraction_confidence"),
            }
            if precheck
            else None
        ),
        "validation": validation_flags,
    }
    return JSONResponse(content=payload)
