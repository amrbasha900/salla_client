from __future__ import annotations

from typing import Any

import frappe
import json
from frappe.utils import now_datetime

from .common import (
    ensure_item_group,
    finalize_result,
    get_existing_doc_name,
    resolve_store_link,
    set_external_id,
    set_if_field,
    sku_missing_result,
)
from .result import ClientApplyResult

INACTIVE_STATUSES = {"inactive", "hidden", "draft", "deleted"}


def _extract_amount(value: Any) -> Any:
    """If value is a dict with amount, return that; otherwise return value."""
    if isinstance(value, dict) and "amount" in value:
        return value.get("amount")
    return value


def upsert_product(store_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    external_id = payload.get("external_id")
    sku = payload.get("sku")
    if not sku:
        return sku_missing_result(store_id, "product", external_id, sku=sku).as_dict()

    existing_name = get_existing_doc_name("Item", external_id)
    created = existing_name is None
    if created:
        doc = frappe.get_doc({"doctype": "Item"})
    else:
        doc = frappe.get_doc("Item", existing_name)

    doc.item_code = sku
    doc.item_name = payload.get("name") or sku
    doc.description = payload.get("description") or doc.get("description")
    doc.item_group = ensure_item_group(payload)
    doc.disabled = 1 if str(payload.get("status")).lower() in INACTIVE_STATUSES else 0
    doc.stock_uom = payload.get("uom") or doc.get("stock_uom") or "Nos"
    doc.is_stock_item = 0 if payload.get("is_stock_item") is False else 1

    set_external_id(doc, external_id)
    # legacy fields (old salla_integration schema)
    set_if_field(doc, "salla_is_from_salla", 1)
    target_store = resolve_store_link(payload.get("store_id"), store_id)
    set_if_field(doc, "salla_store", target_store)
    set_if_field(doc, "salla_product_id", external_id)
    set_if_field(doc, "salla_sku", sku)
    set_if_field(doc, "salla_last_synced", now_datetime())
    set_if_field(doc, "standard_rate", _extract_amount(payload.get("price")))
    set_if_field(doc, "salla_url", payload.get("url"))
    set_if_field(doc, "salla_brand_id", payload.get("brand_id"))
    # Normalize lists to JSON strings for Code/Data fields
    category_ids = payload.get("category_ids")
    if isinstance(category_ids, list):
        category_ids = json.dumps(category_ids, ensure_ascii=False)
    set_if_field(doc, "salla_category_ids", category_ids)

    images = payload.get("images")
    if isinstance(images, list):
        images = json.dumps(images, ensure_ascii=False)
    set_if_field(doc, "salla_images", images)
    set_if_field(doc, "default_warehouse", payload.get("warehouse"))
    set_if_field(doc, "barcode", payload.get("barcode"))

    if created:
        _prev_in_patch = getattr(frappe.flags, "in_patch", False)
        _prev_ignore_perms = getattr(frappe.flags, "ignore_permissions", False)
        try:
            frappe.flags.in_patch = True  # bypass Item after_insert price permission
            frappe.flags.ignore_permissions = True
            doc.insert(ignore_permissions=True)
        finally:
            frappe.flags.in_patch = _prev_in_patch
            frappe.flags.ignore_permissions = _prev_ignore_perms
    else:
        doc.save(ignore_permissions=True)

    result = ClientApplyResult(status="applied", erp_doctype="Item")
    return finalize_result(result, doc, created).as_dict()
