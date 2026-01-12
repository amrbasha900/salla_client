from __future__ import annotations

from typing import Any

import frappe
import json

from .common import finalize_result, get_existing_doc_name, set_if_field
from .result import ClientApplyResult


def upsert_order_status(store_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    status_id = payload.get("external_id") or payload.get("salla_status_id")
    if not status_id:
        result = ClientApplyResult(status="failed")
        result.add_error("missing_status_id", "salla_status_id/external_id is required.")
        return result.as_dict()

    existing = frappe.db.get_value(
        "Salla Order Status", {"store_id": store_id, "salla_status_id": status_id}, "name"
    )
    created = existing is None
    if created:
        doc = frappe.get_doc({"doctype": "Salla Order Status"})
    else:
        doc = frappe.get_doc("Salla Order Status", existing)

    doc.store_id = store_id
    doc.salla_status_id = status_id
    doc.status_name = payload.get("status_name") or payload.get("name") or status_id
    doc.status_type = payload.get("status_type") or payload.get("type")
    doc.slug = payload.get("slug")
    doc.sort_order = payload.get("sort_order") or payload.get("sort")
    doc.icon = payload.get("icon")
    doc.is_active = 1 if payload.get("is_active", True) else 0

    set_if_field(doc, "message", payload.get("message"))
    translations = payload.get("translations")
    if translations is not None:
        try:
            translations = json.dumps(translations, ensure_ascii=False)
        except Exception:
            translations = str(translations)
    set_if_field(doc, "translations_json", translations)
    set_if_field(doc, "parent_status_id", payload.get("parent_status_id"))
    set_if_field(doc, "parent_status_name", payload.get("parent_status_name"))
    set_if_field(doc, "original_status_id", payload.get("original_status_id"))
    set_if_field(doc, "original_status_name", payload.get("original_status_name"))

    # Action flags
    for field in [
        "create_sales_order",
        "submit_sales_order",
        "create_sales_invoice",
        "submit_sales_invoice",
        "create_delivery_note",
        "submit_sales_delivery_note",
        "cancel_sales_order",
        "cancel_sales_invoice",
        "cancel_delivery_note",
        "make_return",
    ]:
        if field in doc.meta.fields:
            doc.set(field, 1 if payload.get(field) else 0)

    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    result = ClientApplyResult(status="applied", erp_doctype="Salla Order Status")
    return finalize_result(result, doc, created).as_dict()

