import json

import frappe


SKIPPED_REASON_DISABLED = "disabled_by_client_settings"

COMMAND_TOGGLE_MAP = {
    "upsert_product": "enable_push_receive_products",
    "upsert_variant": "enable_push_receive_products",
    "upsert_category": "enable_push_receive_products",
    "upsert_brand": "enable_push_receive_products",
    "upsert_order": "enable_push_receive_orders",
    "upsert_order_status": "enable_push_receive_orders",
    "manual_pull": "enable_manual_pull",
}


def _get_payload():
    if hasattr(frappe, "request") and frappe.request:
        payload = frappe.request.get_json(silent=True)
        if payload:
            return payload
    return frappe.local.form_dict or {}


def _log_incoming_command(payload):
    return frappe.get_doc(
        {
            "doctype": "Salla Incoming Log",
            "command_id": payload.get("command_id"),
            "command_type": payload.get("command_type"),
            "entity_type": payload.get("entity_type"),
            "store_account": payload.get("store_account"),
            "customer_account": payload.get("customer_account"),
            "erp_instance": payload.get("erp_instance"),
            "idempotency_key": payload.get("idempotency_key"),
            "payload": json.dumps(payload, ensure_ascii=False, default=str),
        }
    ).insert(ignore_permissions=True)


def _update_log_ack(log_doc, ack_status, ack_reason=None):
    values = {"ack_status": ack_status}
    if ack_reason:
        values["ack_reason"] = ack_reason
    frappe.db.set_value("Salla Incoming Log", log_doc.name, values, update_modified=True)


def _is_command_disabled(payload):
    command_type = payload.get("command_type")
    toggle_field = COMMAND_TOGGLE_MAP.get(command_type)
    if not toggle_field:
        return False
    settings = frappe.get_single("Salla Connection Settings")
    return not settings.get(toggle_field)


@frappe.whitelist(allow_guest=True)
def receive():
    payload = _get_payload()
    log_doc = _log_incoming_command(payload)

    if _is_command_disabled(payload):
        _update_log_ack(log_doc, "skipped", SKIPPED_REASON_DISABLED)
        return {
            "ack_status": "skipped",
            "ack_payload": {"reason": SKIPPED_REASON_DISABLED},
        }

    _update_log_ack(log_doc, "applied")
    return {
        "ack_status": "applied",
        "ack_payload": {"message": "received"},
    }
