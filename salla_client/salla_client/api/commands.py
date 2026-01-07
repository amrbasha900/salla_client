import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Dict, Optional

import frappe
import requests

DEFAULT_TIMESTAMP_WINDOW_SECONDS = 300
REPLAY_CACHE_PREFIX = "salla_client_nonce"


def _response(ok: bool, idempotency_key: Optional[str], status: Any, errors: Optional[list] = None) -> Dict[str, Any]:
    return {
        "ok": ok,
        "idempotency_key": idempotency_key,
        "status": status,
        "errors": errors or [],
    }


def _get_shared_secret() -> str:
    shared_secret = frappe.conf.get("salla_client_shared_secret")
    if not shared_secret:
        frappe.throw("Missing shared secret configuration for salla_client.")
    return shared_secret


def _get_instance_id() -> str:
    instance_id = frappe.conf.get("salla_client_instance_id")
    if not instance_id:
        frappe.throw("Missing instance id configuration for salla_client.")
    return instance_id


def _get_timestamp_window_seconds() -> int:
    return int(frappe.conf.get("salla_client_signature_window_seconds", DEFAULT_TIMESTAMP_WINDOW_SECONDS))


def _feature_enabled(flag_name: str) -> bool:
    return frappe.conf.get(flag_name, True)


def _get_required_headers(headers: Dict[str, str]) -> Dict[str, str]:
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


def _validate_signature(shared_secret: str, timestamp: str, nonce: str, raw_body: str, signature: str) -> None:
    payload = f"{timestamp}.{nonce}.{raw_body}".encode("utf-8")
    expected_signature = hmac.new(shared_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        frappe.throw("Invalid signature.")


def _validate_timestamp(timestamp: str) -> None:
    try:
        timestamp_value = int(timestamp)
    except ValueError:
        frappe.throw("Invalid timestamp header.")
    now = int(time.time())
    window = _get_timestamp_window_seconds()
    if abs(now - timestamp_value) > window:
        frappe.throw("Timestamp outside allowed window.")


def _validate_nonce(instance_id: str, nonce: str) -> None:
    cache_key = f"{REPLAY_CACHE_PREFIX}:{instance_id}:{nonce}"
    cache = frappe.cache()
    if cache.get_value(cache_key):
        frappe.throw("Nonce replay detected.")
    cache.set_value(cache_key, True, expires_in_sec=_get_timestamp_window_seconds())


def _enforce_idempotency(idempotency_key: str) -> bool:
    if frappe.db.exists("Client Incoming Command", {"idempotency_key": idempotency_key}):
        return False
    doc = frappe.get_doc(
        {
            "doctype": "Client Incoming Command",
            "idempotency_key": idempotency_key,
            "status": "received",
        }
    )
    doc.insert(ignore_permissions=True)
    return True


@frappe.whitelist()
def receive_command() -> Dict[str, Any]:
    if not _feature_enabled("salla_client_enable_receive_command"):
        return _response(False, None, "disabled", ["receive_command feature is disabled"])

    request = frappe.local.request
    idempotency_key = None
    try:
        headers = _get_required_headers(request.headers)
        idempotency_key = headers["X-Idempotency-Key"]
        instance_id = _get_instance_id()
        if headers["X-Instance-ID"] != instance_id:
            return _response(False, idempotency_key, "rejected", ["instance mismatch"])

        raw_body = request.get_data(as_text=True) or ""
        _validate_timestamp(headers["X-Timestamp"])
        _validate_nonce(instance_id, headers["X-Nonce"])
        _validate_signature(
            _get_shared_secret(),
            headers["X-Timestamp"],
            headers["X-Nonce"],
            raw_body,
            headers["X-Signature"],
        )

        if not _enforce_idempotency(idempotency_key):
            return _response(True, idempotency_key, "duplicate", [])

        return _response(True, idempotency_key, "accepted", [])
    except Exception as exc:
        return _response(False, idempotency_key, "rejected", [str(exc)])


@frappe.whitelist()
def request_pull_from_manager(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not _feature_enabled("salla_client_enable_request_pull"):
        return _response(False, None, "disabled", ["request_pull_from_manager feature is disabled"])

    payload_data = payload or frappe.local.form_dict or {}
    if isinstance(payload_data, str):
        payload_data = json.loads(payload_data)

    manager_url = frappe.conf.get("salla_manager_url")
    if not manager_url:
        return _response(False, None, "failed", ["missing salla_manager_url configuration"])

    raw_body = json.dumps(payload_data, separators=(",", ":"), ensure_ascii=False)
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    idempotency_key = frappe.generate_hash(length=32)
    signature_payload = f"{timestamp}.{nonce}.{raw_body}".encode("utf-8")
    signature = hmac.new(_get_shared_secret().encode("utf-8"), signature_payload, hashlib.sha256).hexdigest()

    url = manager_url.rstrip("/") + "/api/method/salla_manager.api.client.request_pull"
    response = requests.post(
        url,
        data=raw_body.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Instance-ID": _get_instance_id(),
            "X-Timestamp": timestamp,
            "X-Nonce": nonce,
            "X-Signature": signature,
            "X-Idempotency-Key": idempotency_key,
        },
        timeout=30,
    )

    response_payload: Any
    try:
        response_payload = response.json()
    except ValueError:
        response_payload = response.text

    if response.ok:
        return _response(True, idempotency_key, response_payload, [])
    return _response(False, idempotency_key, response_payload, [f"manager responded with {response.status_code}"])
