from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from datetime import timedelta
from typing import Any, Dict, Optional

import frappe
import requests
from frappe.utils import now_datetime

from salla_client.services.handlers.upsert_customer import upsert_customer
from salla_client.services.handlers.upsert_order import upsert_order
from salla_client.services.handlers.upsert_product import upsert_product
from salla_client.services.handlers.upsert_product_quantity_transaction import (
    upsert_product_quantity_transaction,
)
from salla_client.services.handlers.upsert_product_quantities import upsert_product_quantities
from salla_client.services.handlers.upsert_variant import upsert_variant

SKIPPED_REASON_DISABLED = "disabled_by_client_settings"
DEFAULT_TIMESTAMP_WINDOW_SECONDS = 300

COMMAND_TOGGLE_MAP = {
    "upsert_product": "enable_push_receive_products",
    "upsert_variant": "enable_push_receive_products",
    "upsert_category": "enable_push_receive_products",
    "upsert_brand": "enable_push_receive_products",
    "upsert_product_option": "enable_push_receive_products",
    "upsert_product_quantity_transaction": "enable_push_receive_products",
    "upsert_product_quantities": "enable_push_receive_products",
    "upsert_customer_group": "enable_push_receive_products",
    "upsert_store": "enable_push_receive_products",
    "upsert_order": "enable_push_receive_orders",
    "upsert_order_status": "enable_push_receive_orders",
    "manual_pull": "enable_manual_pull",
}

HANDLERS = {
    "ping": None,  # resolved lazily to avoid circular import
    "upsert_product": upsert_product,
    "upsert_variant": upsert_variant,
    "upsert_customer": upsert_customer,
    "upsert_order": upsert_order,
    "upsert_product_quantity_transaction": upsert_product_quantity_transaction,
    "upsert_product_quantities": upsert_product_quantities,
    "upsert_order_status": None,  # lazy import
    "upsert_category": None,
    "upsert_brand": None,
    "upsert_product_option": None,
    "upsert_store": None,
    "upsert_customer_group": None,
}


def _response(ok: bool, idempotency_key: Optional[str], status: Any, errors: Optional[list] = None) -> Dict[str, Any]:
    return {
        "ok": ok,
        "idempotency_key": idempotency_key,
        "status": status,
        "ack_status": status,
        "errors": errors or [],
    }


def _get_connection_settings():
    settings = frappe.get_single("Salla Manager Connection")
    if not settings.instance_id or not settings.shared_secret:
        frappe.throw("Instance ID and Shared Secret must be configured in Salla Manager Connection.")
    return settings


def _get_shared_secret(settings) -> str:
    try:
        return settings.get_password("shared_secret")
    except Exception:
        return settings.shared_secret


def _get_raw_body() -> str:
    request = frappe.local.request
    return request.get_data(as_text=True) or ""


def _load_payload(raw_body: str) -> Dict[str, Any]:
    try:
        return json.loads(raw_body) if raw_body else {}
    except Exception as exc:
        frappe.throw(f"Invalid JSON payload: {exc}")


def _required_headers(headers: Dict[str, str]) -> Dict[str, str]:
    required_keys = [
        "X-Instance-ID",
        "X-Timestamp",
        "X-Nonce",
        "X-Signature",
        "X-Idempotency-Key",
    ]
    missing = [key for key in required_keys if not headers.get(key)]
    if missing:
        frappe.throw(f"Missing required headers: {', '.join(missing)}")
    return {key: headers.get(key) for key in required_keys}


def _noop_applied(*_args, **_kwargs):
    return {"status": "applied", "message": "noop"}


def _validate_allowed_ips(settings, remote_addr: str | None) -> None:
    allowed_ips = []
    if settings.allowed_manager_ips:
        allowed_ips = [ip.strip() for ip in settings.allowed_manager_ips.split(",") if ip.strip()]
    if allowed_ips and remote_addr and remote_addr not in allowed_ips:
        frappe.throw("Request IP is not allowed.")


def _validate_timestamp(timestamp: str, window_seconds: int) -> None:
    try:
        ts_value = int(timestamp)
    except Exception:
        frappe.throw("Invalid timestamp header.")
    now = int(time.time())
    if abs(now - ts_value) > window_seconds:
        frappe.throw("Timestamp outside allowed window.")


def _validate_signature(shared_secret: str, timestamp: str, nonce: str, raw_body: str, signature: str) -> None:
    payload = f"{timestamp}.{nonce}.{raw_body}".encode("utf-8")
    expected_signature = hmac.new(shared_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        frappe.throw("Invalid signature.")


def _validate_and_store_nonce(instance_id: str, nonce: str, window_seconds: int) -> None:
    existing = frappe.db.exists("Client Nonce Log", {"nonce": nonce, "instance_id": instance_id})
    if existing:
        frappe.throw("Nonce replay detected.")
    expires_at = now_datetime() + timedelta(seconds=window_seconds)
    doc = frappe.get_doc(
        {
            "doctype": "Client Nonce Log",
            "nonce": nonce,
            "timestamp": now_datetime(),
            "instance_id": instance_id,
            "ttl_seconds": window_seconds,
            "expires_at": expires_at,
        }
    )
    doc.insert(ignore_permissions=True)


def _command_disabled(settings, command_type: str) -> bool:
    toggle = COMMAND_TOGGLE_MAP.get(command_type)
    if not toggle:
        return False
    return not bool(settings.get(toggle))


def _get_existing_log(idempotency_key: str):
    if not idempotency_key:
        return None
    name = frappe.db.get_value("Client Incoming Command", {"idempotency_key": idempotency_key}, "name")
    if name:
        return frappe.get_doc("Client Incoming Command", name)
    return None


def _create_log_doc(idempotency_key: str, payload: Dict[str, Any]) -> Any:
    store_value = payload.get("store_id") or payload.get("store_account") or payload.get("store_account_id") or "unknown"
    return frappe.get_doc(
        {
            "doctype": "Client Incoming Command",
            "idempotency_key": idempotency_key,
            "received_at": now_datetime(),
            "store_id": store_value,
            "store_account_id": payload.get("store_account") or payload.get("store_account_id"),
            "command_type": payload.get("command_type"),
            "entity_type": payload.get("entity_type"),
            "payload": payload,
            "status": "received",
        }
    ).insert(ignore_permissions=True)


def _apply_command(log_doc, settings, payload: Dict[str, Any]):
    command_type = payload.get("command_type")
    if command_type == "ping":
        from salla_client.services.handlers.ping import ping  # local import

        handler = ping
    elif command_type == "upsert_order_status":
        from salla_client.services.handlers.upsert_order_status import upsert_order_status

        handler = upsert_order_status
    elif command_type == "upsert_category":
        from salla_client.services.handlers.upsert_category import upsert_category

        handler = upsert_category
    elif command_type == "upsert_product_option":
        from salla_client.services.handlers.upsert_product_option import upsert_product_option

        handler = upsert_product_option
    elif command_type == "upsert_customer_group":
        from salla_client.services.handlers.upsert_customer_group import upsert_customer_group

        handler = upsert_customer_group
    elif command_type == "upsert_brand":
        handler = _noop_applied
    elif command_type == "upsert_store":
        from salla_client.services.handlers.upsert_store import upsert_store

        handler = upsert_store
    else:
        handler = HANDLERS.get(command_type)
    if not handler:
        log_doc.status = "skipped"
        log_doc.skip_reason = "unsupported_command"
        log_doc.error_details = f"Unsupported command_type {command_type}"
        log_doc.save(ignore_permissions=True)
        return {"status": "skipped", "errors": [{"message": "unsupported_command"}]}

    store_id = payload.get("store_id") or payload.get("store_account") or payload.get("store_account_id")

    entity_payload = payload.get("payload")
    if isinstance(entity_payload, str):
        # Backward/defensive: Manager might send payload as JSON string.
        try:
            parsed = json.loads(entity_payload)
            if isinstance(parsed, dict):
                entity_payload = parsed
        except Exception:
            # fall back to passing the whole envelope to handler
            entity_payload = payload
    elif not isinstance(entity_payload, dict):
        # If no structured payload was provided, pass envelope (some handlers use it)
        entity_payload = payload
    result = handler(store_id, entity_payload or {})

    log_doc.set("apply_results", [])
    log_doc.append(
        "apply_results",
        {
            "erp_doctype": result.get("erp_doctype"),
            "erp_doc": result.get("erp_doc"),
            "status": result.get("status"),
            "message": result.get("message"),
            "warning_details": json.dumps(result.get("warnings") or [], ensure_ascii=False),
            "error_details": json.dumps(result.get("errors") or [], ensure_ascii=False),
        },
    )
    log_doc.status = result.get("status") or "applied"
    if result.get("status") == "skipped":
        warning_codes = [w.get("code") for w in result.get("warnings", []) if isinstance(w, dict)]
        if "sku_missing" in warning_codes:
            log_doc.skip_reason = "missing_sku"
        else:
            log_doc.skip_reason = (result.get("message") or "").lower() or "skipped"
    if result.get("errors"):
        log_doc.error_details = json.dumps(result.get("errors"), ensure_ascii=False)
    log_doc.save(ignore_permissions=True)
    return result


@frappe.whitelist(allow_guest=True)
def receive_command() -> Dict[str, Any]:
    # guest requests (Manager) should bypass CSRF
    frappe.local.no_cache = 1
    frappe.local.flags.ignore_csrf = True

    raw_body = _get_raw_body()
    settings = _get_connection_settings()
    request = frappe.local.request
    idempotency_key = None

    try:
        headers = _required_headers(request.headers)
        idempotency_key = headers["X-Idempotency-Key"]
        _validate_allowed_ips(settings, getattr(request, "remote_addr", None))
        if headers["X-Instance-ID"] != settings.instance_id:
            return _response(False, idempotency_key, "rejected", ["instance mismatch"])

        window_seconds = int(settings.timestamp_window_seconds or DEFAULT_TIMESTAMP_WINDOW_SECONDS)
        _validate_timestamp(headers["X-Timestamp"], window_seconds)
        _validate_and_store_nonce(settings.instance_id, headers["X-Nonce"], window_seconds)
        shared_secret = _get_shared_secret(settings)
        _validate_signature(shared_secret, headers["X-Timestamp"], headers["X-Nonce"], raw_body, headers["X-Signature"])

        payload = _load_payload(raw_body)

        existing_log = _get_existing_log(idempotency_key)
        if existing_log:
            return _response(True, idempotency_key, existing_log.status, [])

        log_doc = _create_log_doc(idempotency_key, payload)

        if _command_disabled(settings, payload.get("command_type")):
            log_doc.status = "skipped"
            log_doc.skip_reason = SKIPPED_REASON_DISABLED
            log_doc.save(ignore_permissions=True)
            return _response(True, idempotency_key, "skipped", [SKIPPED_REASON_DISABLED])

        result = _apply_command(log_doc, settings, payload)
        return _response(True, idempotency_key, result.get("status"), [err.get("message") for err in result.get("errors", [])])
    except Exception as exc:
        frappe.log_error(frappe.get_traceback(), "Salla Client receive_command failure")
        return _response(False, idempotency_key, "failed", [str(exc)])


@frappe.whitelist()
def request_pull_from_manager(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    settings = _get_connection_settings()
    if not settings.enable_manual_pull:
        return _response(False, None, "skipped", ["Manual pull disabled in client settings"])

    payload_data = payload or frappe.local.form_dict or {}
    if isinstance(payload_data, str):
        payload_data = json.loads(payload_data)

    manager_url = (settings.manager_base_url or "").rstrip("/")
    if not manager_url:
        return _response(False, None, "failed", ["Manager base URL is not configured"])

    raw_body = json.dumps(payload_data, separators=(",", ":"), ensure_ascii=False)
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    idempotency_key = frappe.generate_hash(length=32)
    signature_payload = f"{timestamp}.{nonce}.{raw_body}".encode("utf-8")
    shared_secret = _get_shared_secret(settings)
    signature = hmac.new(shared_secret.encode("utf-8"), signature_payload, hashlib.sha256).hexdigest()

    url = f"{manager_url}/api/method/salla_manager.api.client.request_pull"
    response = requests.post(
        url,
        data=raw_body.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Instance-ID": settings.instance_id,
            "X-Timestamp": timestamp,
            "X-Nonce": nonce,
            "X-Signature": signature,
            "X-Idempotency-Key": idempotency_key,
        },
        timeout=30,
    )

    try:
        response_payload = response.json()
    except ValueError:
        response_payload = response.text

    if response.ok:
        return _response(True, idempotency_key, response_payload, [])
    return _response(False, idempotency_key, response_payload, [f"manager responded with {response.status_code}"])
