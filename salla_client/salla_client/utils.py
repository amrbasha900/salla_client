import hashlib
import hmac
import json
import time
from typing import Dict, Tuple

import frappe


class SignatureError(Exception):
	pass


def get_connection_settings():
	return frappe.get_single("Salla Manager Connection")


def normalize_body(body: bytes) -> str:
	return body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)


def build_signature(shared_secret: str, timestamp: str, nonce: str, raw_body: str) -> str:
	payload = f"{timestamp}.{nonce}.{raw_body}"
	return hmac.new(shared_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def validate_signature(headers: Dict[str, str], raw_body: bytes, shared_secret: str, window_seconds: int):
	instance_id = headers.get("X-Instance-ID")
	timestamp = headers.get("X-Timestamp")
	nonce = headers.get("X-Nonce")
	signature = headers.get("X-Signature")

	if not all([instance_id, timestamp, nonce, signature]):
		raise SignatureError("Missing required signature headers")

	try:
		timestamp_int = int(timestamp)
	except ValueError:
		raise SignatureError("Invalid timestamp header")

	now = int(time.time())
	if abs(now - timestamp_int) > window_seconds:
		raise SignatureError("Timestamp outside allowed window")

	raw_body_str = normalize_body(raw_body)
	expected = build_signature(shared_secret, timestamp, nonce, raw_body_str)
	if not hmac.compare_digest(expected, signature):
		raise SignatureError("Signature mismatch")

	return instance_id, timestamp_int, nonce


def parse_json(raw_body: bytes) -> Dict:
	raw_body_str = normalize_body(raw_body)
	if not raw_body_str:
		return {}
	return json.loads(raw_body_str)


def get_default_item_group() -> str:
	if frappe.db.exists("Item Group", "All Item Groups"):
		return "All Item Groups"
	item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	return item_group or "All Item Groups"


def get_default_customer_group() -> str:
	if frappe.db.exists("Customer Group", "All Customer Groups"):
		return "All Customer Groups"
	group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	return group or "All Customer Groups"


def get_default_territory() -> str:
	if frappe.db.exists("Territory", "All Territories"):
		return "All Territories"
	territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
	return territory or "All Territories"


def build_response(ok: bool, idempotency_key: str, status: str, errors=None):
	return {
		"ok": ok,
		"idempotency_key": idempotency_key,
		"status": status,
		"errors": errors or [],
	}
