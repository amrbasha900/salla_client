from __future__ import annotations

from typing import Any

import frappe

from .common import (
    ensure_item_group,
    finalize_result,
    get_existing_doc_name,
    set_external_id,
    set_if_field,
    sku_missing_result,
)
from .result import ClientApplyResult

INACTIVE_STATUSES = {"inactive", "hidden", "draft", "deleted"}


def upsert_product(store_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    external_id = payload.get("external_id")
    sku = payload.get("sku")
    if not sku:
        return sku_missing_result(store_id, "product", external_id).as_dict()

    existing_name = get_existing_doc_name("Item", external_id)
    created = existing_name is None
    if created:
        doc = frappe.get_doc({"doctype": "Item"})
    else:
        doc = frappe.get_doc("Item", existing_name)

    doc.item_code = sku
    doc.item_name = payload.get("name") or sku
    doc.description = payload.get("description") or doc.description
    doc.item_group = ensure_item_group(payload)
    doc.disabled = 1 if payload.get("status") in INACTIVE_STATUSES else 0

    set_external_id(doc, external_id)
    set_if_field(doc, "salla_url", payload.get("url"))
    set_if_field(doc, "salla_brand_id", payload.get("brand_id"))
    set_if_field(doc, "salla_category_ids", payload.get("category_ids"))
    set_if_field(doc, "salla_images", payload.get("images"))

    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    result = ClientApplyResult(status="applied", erp_doctype="Item")
    return finalize_result(result, doc, created).as_dict()
