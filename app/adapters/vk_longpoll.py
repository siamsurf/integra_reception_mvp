from __future__ import annotations

import json
import logging
import os
import random
import time
import uuid

import httpx

from app.core.services.ai import generate_ai_output
from app.core.services.precheck import run_delivery_precheck
from app.core.services.reception import detect_intent_from_text, run_reception_pipeline
from app.db.models.ai_output import AIOutput
from app.db.models.lead import Lead
from app.db.models.precheck_result import PrecheckResult
from app.db.session import Base, SessionLocal, engine
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("vk_longpoll")

VK_API_BASE = "https://api.vk.com/method"


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _sanitize_for_log(value: object) -> object:
    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for k, v in value.items():
            if str(k).lower() == "key":
                sanitized[k] = "***"
            else:
                sanitized[k] = _sanitize_for_log(v)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_for_log(item) for item in value]
    return value


def _vk_api_call(
    client: httpx.Client,
    method: str,
    params: dict[str, object],
    token: str,
    version: str,
    retries: int = 3,
) -> dict[str, object]:
    payload = dict(params)
    payload["access_token"] = token
    payload["v"] = version
    data: dict[str, object] = {}

    for attempt in range(1, retries + 1):
        try:
            resp = client.post(f"{VK_API_BASE}/{method}", data=payload)
            resp.raise_for_status()
            data = resp.json()
            break
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            if attempt == retries:
                raise RuntimeError(f"VK API network error on {method}: {exc}") from exc
            logger.warning(
                "VK API network error on %s (attempt %s/%s), retrying: %s",
                method,
                attempt,
                retries,
                exc,
            )
            time.sleep(attempt)

    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected VK API payload type on {method}: {type(data).__name__}")
    return data


def _get_longpoll_server(client: httpx.Client, token: str, group_id: str, version: str) -> dict[str, object]:
    logger.info("Getting VK long poll server (group_id=%s)", group_id)
    payload = _vk_api_call(
        client=client,
        method="groups.getLongPollServer",
        params={"group_id": group_id},
        token=token,
        version=version,
    )
    logger.info(
        "groups.getLongPollServer raw=%s",
        json.dumps(_sanitize_for_log(payload), ensure_ascii=False, separators=(",", ":")),
    )
    logger.info("groups.getLongPollServer payload keys=%s", ",".join(sorted(payload.keys())))

    if "error" in payload:
        logger.error("VK API returned error on groups.getLongPollServer: %s", payload["error"])
        raise RuntimeError("VK API startup error")

    response = payload.get("response")
    if not isinstance(response, dict):
        raise RuntimeError(f"Unexpected groups.getLongPollServer response payload: {payload}")
    return response


def _longpoll_check(
    client: httpx.Client,
    server: str,
    key: str,
    ts: str,
    wait: int,
    retries: int = 3,
) -> dict[str, object]:
    params = {"act": "a_check", "key": key, "ts": ts, "wait": wait}
    for attempt in range(1, retries + 1):
        try:
            resp = client.get(server, params=params, timeout=wait + 10)
            resp.raise_for_status()
            return resp.json()
        except ValueError as exc:
            if attempt == retries:
                raise RuntimeError(f"Malformed long poll JSON: {exc}") from exc
            logger.warning("Malformed long poll JSON (attempt %s/%s), retrying", attempt, retries)
            time.sleep(attempt)
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            if attempt == retries:
                raise RuntimeError(f"Long poll network error: {exc}") from exc
            logger.warning("Long poll network error (attempt %s/%s), retrying: %s", attempt, retries, exc)
            time.sleep(attempt)
    return {}


def _process_message(text: str, peer_id: int, lang: str) -> tuple[str, str]:
    service_type = detect_intent_from_text(text)
    rid = uuid.uuid4().hex[:8]

    db = SessionLocal()
    try:
        lead = Lead(
            rid=rid,
            service_type=service_type,
            client_name=f"VK user {peer_id}",
            phone=f"vk:{peer_id}",
            email=None,
            raw_text=text.strip(),
            status="received",
        )
        db.add(lead)
        db.flush()

        reception_result = run_reception_pipeline(service_type=service_type, raw_text=lead.raw_text)

        precheck_payload: dict[str, str] | None = None
        if service_type == "delivery":
            precheck_payload = run_delivery_precheck(lead.raw_text, lang=lang)
            db.add(
                PrecheckResult(
                    lead_id=lead.id,
                    precheck_status=precheck_payload["precheck_status"],
                    missing_fields=precheck_payload["missing_fields"],
                    notes=precheck_payload["notes"],
                )
            )
            lead.status = "needs_info" if precheck_payload["precheck_status"] == "missing_info" else "ready"
        elif service_type == "supplier_check":
            lead.status = "ready"
        else:
            lead.status = "offtopic"

        ai = generate_ai_output(
            service_type=service_type,
            classification=reception_result["classification"],
            raw_text=lead.raw_text,
            precheck=precheck_payload,
            lang=lang,
        )
        db.add(
            AIOutput(
                lead_id=lead.id,
                classification=ai.classification,
                manager_summary=ai.manager_summary,
                draft_reply=ai.draft_reply,
                model_name=ai.model_name,
                fallback_used=ai.fallback_used,
            )
        )

        db.commit()
        return rid, ai.draft_reply
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _send_message(_client: httpx.Client, token: str, version: str, peer_id: int, message: str) -> bool:
    random_id = random.randint(1, 2_147_483_647)
    payload = {
        "peer_id": peer_id,
        "random_id": random_id,
        "message": message,
        "access_token": token,
        "v": version,
    }
    backoff_seconds = [1, 2, 4, 6, 8]

    for attempt, delay in enumerate(backoff_seconds, start=1):
        try:
            with httpx.Client(timeout=30, follow_redirects=True, http2=False) as send_client:
                resp = send_client.post(f"{VK_API_BASE}/messages.send", data=payload)
                resp.raise_for_status()
                data = resp.json()

            if isinstance(data, dict) and "error" in data:
                logger.error("VK messages.send API error peer_id=%s random_id=%s: %s", peer_id, random_id, data["error"])
                return False

            logger.info("VK messages.send success peer_id=%s random_id=%s", peer_id, random_id)
            return True
        except httpx.RequestError as exc:
            if attempt >= len(backoff_seconds):
                logger.error(
                    "VK messages.send failed after retries peer_id=%s random_id=%s: %s",
                    peer_id,
                    random_id,
                    exc,
                )
                return False
            logger.warning(
                "VK messages.send network error peer_id=%s random_id=%s attempt=%s/5, retrying in %ss: %s",
                peer_id,
                random_id,
                attempt,
                delay,
                exc,
            )
            time.sleep(delay)
        except httpx.HTTPStatusError as exc:
            logger.error(
                "VK messages.send HTTP error peer_id=%s random_id=%s: %s",
                peer_id,
                random_id,
                exc,
            )
            return False
        except ValueError as exc:
            logger.error(
                "VK messages.send malformed JSON peer_id=%s random_id=%s: %s",
                peer_id,
                random_id,
                exc,
            )
            return False

    return False


def _handle_update(
    update: dict[str, object],
    client: httpx.Client,
    token: str,
    version: str,
    lang: str,
) -> None:
    if update.get("type") != "message_new":
        return

    obj = update.get("object")
    if not isinstance(obj, dict):
        return

    message_obj = obj.get("message")
    if not isinstance(message_obj, dict):
        return

    text = str(message_obj.get("text") or "").strip()
    if not text:
        return

    peer_id = message_obj.get("peer_id")
    if not isinstance(peer_id, int):
        return

    rid: str | None = None
    try:
        rid, draft_reply = _process_message(text=text, peer_id=peer_id, lang=lang)
        outgoing = f"Заявка принята. Номер: {rid}\n\n{draft_reply}"
        sent = _send_message(_client=client, token=token, version=version, peer_id=peer_id, message=outgoing)
        if sent:
            logger.info("Processed VK message peer_id=%s rid=%s", peer_id, rid)
        else:
            logger.warning("Processed VK message but reply not sent peer_id=%s rid=%s", peer_id, rid)
    except Exception as exc:
        logger.exception("Failed to process VK message peer_id=%s rid=%s: %s", peer_id, rid, exc)


def run() -> None:
    token = _env("VK_TOKEN")
    group_id = _env("VK_GROUP_ID")
    version = os.getenv("VK_API_VERSION", "5.131")
    wait = int(os.getenv("VK_WAIT", "25"))
    lang = os.getenv("VK_LANG", "ru").lower()

    # Worker can run standalone without web startup.
    Base.metadata.create_all(bind=engine)

    with httpx.Client(timeout=30, follow_redirects=True, http2=False) as client:
        def refresh_longpoll() -> tuple[str, str, str]:
            server_data_local = _get_longpoll_server(client=client, token=token, group_id=group_id, version=version)
            return (
                str(server_data_local["server"]),
                str(server_data_local["key"]),
                str(server_data_local["ts"]),
            )

        try:
            server, key, ts = refresh_longpoll()
        except RuntimeError as exc:
            logger.error("VK worker startup failed while getting long poll server: %s", exc)
            return
        logger.info("Initialized long poll ts=%s", ts)

        logger.info("VK polling loop started (group_id=%s, lang=%s)", group_id, lang)
        first_poll_keys_logged = False

        while True:
            try:
                logger.info("Polling VK long poll with ts=%s", ts)
                result = _longpoll_check(client=client, server=server, key=key, ts=ts, wait=wait)
                if not isinstance(result, dict):
                    logger.warning("Malformed long poll response (not a dict), refreshing server params")
                    server, key, ts = refresh_longpoll()
                    continue
                if not first_poll_keys_logged:
                    logger.info(
                        "a_check raw(first)=%s",
                        json.dumps(_sanitize_for_log(result), ensure_ascii=False, separators=(",", ":")),
                    )
                    logger.info("a_check payload keys=%s", ",".join(sorted(result.keys())))
                    first_poll_keys_logged = True

                if "failed" in result:
                    failed_code = int(result.get("failed", 0))
                    logger.warning("Long poll returned failed=%s", failed_code)

                    if failed_code == 1:
                        failed_ts = result.get("ts")
                        if failed_ts is None or str(failed_ts).strip() == "":
                            logger.warning("Long poll failed=1 without ts, refreshing server params")
                            server, key, ts = refresh_longpoll()
                        else:
                            ts = str(failed_ts)
                        continue

                    if failed_code in {2, 3}:
                        server, key, ts = refresh_longpoll()
                        continue

                    server, key, ts = refresh_longpoll()
                    continue

                new_ts = result.get("ts")
                if new_ts is None or str(new_ts).strip() == "":
                    logger.warning("Long poll response missing ts, refreshing server params")
                    server, key, ts = refresh_longpoll()
                    continue
                ts = str(new_ts)
                logger.info("Long poll returned ts=%s", ts)

                updates = result.get("updates", [])
                if not isinstance(updates, list):
                    logger.warning("Long poll response has malformed updates, skipping batch")
                    continue
                update_types = [str(u.get("type")) for u in updates if isinstance(u, dict) and u.get("type")]
                logger.info("Long poll updates=%s types=%s", len(updates), ",".join(update_types) if update_types else "-")

                for update in updates:
                    if isinstance(update, dict):
                        _handle_update(update=update, client=client, token=token, version=version, lang=lang)

            except RuntimeError as exc:
                if "Malformed long poll JSON" in str(exc):
                    logger.warning("Malformed long poll JSON, refreshing server params")
                    server, key, ts = refresh_longpoll()
                    continue
                logger.warning("Network/runtime error in long poll, retrying: %s", exc)
                time.sleep(2)
            except Exception as exc:
                logger.exception("Unexpected worker error: %s", exc)
                time.sleep(2)


if __name__ == "__main__":
    run()
