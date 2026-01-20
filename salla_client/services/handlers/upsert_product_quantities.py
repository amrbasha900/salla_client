from __future__ import annotations

import json
from typing import Any

import frappe

from .common import resolve_store_link
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


def upsert_product_quantities(store_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    external_id = payload.get("external_id")
    target_store = resolve_store_link(payload.get("store_id"), store_id)
    existing_name = frappe.db.get_value(
        "Salla Product Quantities",
        {"external_id": external_id, "store_id": target_store},
        "name",
    )
    created = existing_name is None
    if created:
        doc = frappe.get_doc({"doctype": "Salla Product Quantities"})
    else:
        doc = frappe.get_doc("Salla Product Quantities", existing_name)

    doc.store_id = target_store
    doc.external_id = external_id
    doc.sku = payload.get("sku")
    doc.sku_id = payload.get("sku_id")
    doc.item = _resolve_item_by_sku(doc.sku)
    doc.product_name = payload.get("name")
    doc.variant = payload.get("variant")
    doc.image = payload.get("image")
    doc.quantity = payload.get("quantity")
    doc.sold_quantity = payload.get("sold_quantity")
    doc.price = payload.get("price")
    doc.unlimited_quantity = 1 if payload.get("unlimited_quantity") else 0

    raw = payload.get("raw")
    if isinstance(raw, (dict, list)):
        raw = json.dumps(raw, ensure_ascii=False)
    doc.raw = raw

    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    result = ClientApplyResult(status="applied", erp_doctype="Salla Product Quantities")
    result.erp_doc = doc.name
    result.message = "Created" if created else "Updated"
    return result.as_dict()
