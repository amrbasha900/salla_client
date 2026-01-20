from __future__ import annotations

import json
from typing import Any

import frappe

from .result import ClientApplyResult


def _resolve_item_by_sku(sku: str | None) -> str | None:
    if not sku:
        return None
    item_name = frappe.db.get_value("Item", {"item_code": sku}, "name")
    if item_name:
        return item_name
    if frappe.db.exists("Item", {"salla_sku": sku}):
        return frappe.db.get_value("Item", {"salla_sku": sku}, "name")
    return None


def upsert_product_quantity_transaction(store_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    external_id = payload.get("external_id")
    target_store = payload.get("store_id") or store_id
    existing_name = frappe.db.get_value(
        "Salla Product Quantity Transaction",
        {"external_id": external_id, "store_id": target_store},
        "name",
    )
    created = existing_name is None
    if created:
        doc = frappe.get_doc({"doctype": "Salla Product Quantity Transaction"})
    else:
        doc = frappe.get_doc("Salla Product Quantity Transaction", existing_name)

    doc.store_id = target_store
    doc.external_id = external_id
    doc.sku = payload.get("sku")
    doc.item = _resolve_item_by_sku(doc.sku)
    doc.product_name = payload.get("name")
    doc.variant = payload.get("variant")
    doc.image = payload.get("image")
    doc.created_at = payload.get("created_at")
    doc.old_quantity = payload.get("old_quantity")
    doc.new_quantity = payload.get("new_quantity")
    doc.unlimited_quantity = 1 if payload.get("unlimited_quantity") else 0
    doc.reason = payload.get("reason")
    doc.user_id = payload.get("user_id")
    doc.user_type = payload.get("user_type")
    doc.user_first_name = payload.get("user_first_name")

    raw = payload.get("raw")
    if isinstance(raw, (dict, list)):
        raw = json.dumps(raw, ensure_ascii=False)
    doc.raw = raw

    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    result = ClientApplyResult(status="applied", erp_doctype="Salla Product Quantity Transaction")
    result.erp_doc = doc.name
    result.message = "Created" if created else "Updated"
    return result.as_dict()
