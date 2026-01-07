import json
import time
import uuid

import frappe
import requests
from frappe.utils import now_datetime

from salla_client.services.handlers import upsert_customer, upsert_order, upsert_product, upsert_variant
from salla_client.utils import (
	SignatureError,
	build_response,
	build_signature,
	get_connection_settings,
	parse_json,
	validate_signature,
)


COMMAND_HANDLERS = {
	"upsert_product": upsert_product,
	"upsert_variant": upsert_variant,
	"upsert_customer": upsert_customer,
	"upsert_order": upsert_order,
}


@frappe.whitelist(allow_guest=True)

def receive_command():
	raw_body = frappe.request.get_data() or b""
	headers = {key: value for key, value in frappe.request.headers.items()}
	settings = get_connection_settings()

	if settings.allowed_manager_ips:
		allowed = [ip.strip() for ip in settings.allowed_manager_ips.split("\n") if ip.strip()]
		remote_ip = frappe.request.remote_addr
		if remote_ip not in allowed:
			return build_response(False, "", "rejected", ["IP not allowed"])

	try:
		instance_id, timestamp_int, nonce = validate_signature(
			headers,
			raw_body,
			settings.get_password("shared_secret"),
			settings.signature_window_seconds or 300,
		)
	except SignatureError as exc:
		return build_response(False, "", "rejected", [str(exc)])

	if instance_id != settings.instance_id:
		return build_response(False, "", "rejected", ["Instance ID mismatch"])

	idempotency_key = headers.get("X-Idempotency-Key")
	payload_data = parse_json(raw_body)
	if not idempotency_key:
		idempotency_key = payload_data.get("idempotency_key")

	if not idempotency_key:
		return build_response(False, "", "rejected", ["Missing idempotency key"])

	existing = frappe.db.get_value(
		"Client Incoming Command",
		{"idempotency_key": idempotency_key},
		["status"],
		as_dict=True,
	)
	if existing and existing.status in {"applied", "skipped"}:
		return build_response(True, idempotency_key, existing.status)

	if frappe.db.exists("Client Nonce Log", {"nonce": nonce}):
		return build_response(False, idempotency_key, "rejected", ["Nonce replay detected"])

	command_doc = frappe.get_doc({
		"doctype": "Client Incoming Command",
		"idempotency_key": idempotency_key,
		"command_id": payload_data.get("command_id"),
		"received_at": now_datetime(),
		"store_id": payload_data.get("store_account") or payload_data.get("store_id"),
		"command_type": payload_data.get("command_type"),
		"entity_type": payload_data.get("entity_type"),
		"payload": payload_data.get("payload"),
		"status": "received",
	})
	command_doc.insert(ignore_permissions=True)

	frappe.get_doc({
		"doctype": "Client Nonce Log",
		"instance_id": instance_id,
		"nonce": nonce,
		"timestamp": timestamp_int,
		"received_at": now_datetime(),
	}).insert(ignore_permissions=True)

	settings.last_seen_at = now_datetime()
	settings.save(ignore_permissions=True)

	command_type = payload_data.get("command_type")
	payload = payload_data.get("payload") or {}

	if command_type in {"upsert_product", "upsert_variant"} and not settings.enable_push_receive_products:
		command_doc.status = "skipped"
		command_doc.error_details = "disabled_by_client_settings"
		command_doc.save(ignore_permissions=True)
		return build_response(True, idempotency_key, "skipped", ["disabled_by_client_settings"])

	if command_type == "upsert_order" and not settings.enable_push_receive_orders:
		command_doc.status = "skipped"
		command_doc.error_details = "disabled_by_client_settings"
		command_doc.save(ignore_permissions=True)
		return build_response(True, idempotency_key, "skipped", ["disabled_by_client_settings"])

	sku = payload.get("sku")	
	if command_type in {"upsert_product", "upsert_variant"} and not sku:
		frappe.get_doc({
			"doctype": "SKU Skip Log",
			"store_id": command_doc.store_id,
			"entity_type": payload_data.get("entity_type"),
			"external_id": payload.get("external_id"),
			"sku": payload.get("sku"),
			"reason": "missing_sku",
			"created_at": now_datetime(),
		}).insert(ignore_permissions=True)
		command_doc.status = "skipped"
		command_doc.error_details = "missing_sku"
		command_doc.save(ignore_permissions=True)
		return build_response(True, idempotency_key, "skipped", ["missing_sku"])

	handler = COMMAND_HANDLERS.get(command_type)
	if not handler:
		command_doc.status = "failed"
		command_doc.error_details = "Unknown command type"
		command_doc.save(ignore_permissions=True)
		return build_response(False, idempotency_key, "failed", ["Unknown command type"])

	try:
		if command_type == "upsert_order":
			doc_name, status, warnings = handler(payload)
			if status == "skipped":
				command_doc.status = "skipped"
				command_doc.error_details = "no_items"
				command_doc.save(ignore_permissions=True)
				return build_response(True, idempotency_key, "skipped", warnings)

			command_doc.status = "applied"
			command_doc.append("apply_results", {
				"reference_doctype": "Sales Order",
				"reference_name": doc_name,
				"message": "Created",
				"level": "info",
			})
			for warning in warnings:
				command_doc.append("apply_results", {
					"message": warning,
					"level": "warning",
				})
			command_doc.save(ignore_permissions=True)
			return build_response(True, idempotency_key, "applied", warnings)

		doc_name, action = handler(payload)
		command_doc.status = "applied"
		command_doc.append("apply_results", {
			"reference_doctype": "Item" if command_type in {"upsert_product", "upsert_variant"} else "Customer",
			"reference_name": doc_name,
			"message": action,
			"level": "info",
		})
		command_doc.save(ignore_permissions=True)
		return build_response(True, idempotency_key, "applied")
	except Exception as exc:
		command_doc.status = "failed"
		command_doc.error_details = str(exc)
		command_doc.save(ignore_permissions=True)
		return build_response(False, idempotency_key, "failed", [str(exc)])


@frappe.whitelist()

def request_pull_from_manager(store_id=None, entity_types=None, since=None, limit=50):
	settings = get_connection_settings()
	if not settings.enable_manual_pull:
		frappe.throw("Manual pull is disabled in client settings")

	payload = {
		"store_id": store_id,
		"entity_types": entity_types or ["products", "orders", "customers"],
		"since": since,
		"limit": limit,
	}

	payload_str = json.dumps(payload, separators=(",", ":"))
	timestamp = str(int(time.time()))
	nonce = uuid.uuid4().hex
	signature = build_signature(settings.get_password("shared_secret"), timestamp, nonce, payload_str)
	idempotency_key = uuid.uuid4().hex

	headers = {
		"Content-Type": "application/json",
		"X-Instance-ID": settings.instance_id,
		"X-Timestamp": timestamp,
		"X-Nonce": nonce,
		"X-Signature": signature,
		"X-Idempotency-Key": idempotency_key,
	}

	url = f"{settings.manager_base_url}/api/method/salla_manager.api.client.request_pull"
	response = requests.post(url, headers=headers, data=payload_str, timeout=30)
	response.raise_for_status()

	try:
		return response.json()
	except ValueError:
		return {"ok": False, "response": response.text}
