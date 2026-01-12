from __future__ import annotations

from typing import Any

import frappe

from .common import finalize_result, set_if_field
from .result import ClientApplyResult


def upsert_category(store_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    category_id = payload.get("external_id") or payload.get("category_id")
    if not category_id:
        result = ClientApplyResult(status="failed")
        result.add_error("missing_category_id", "Category external_id/category_id is required.")
        return result.as_dict()

    existing = frappe.db.get_value(
        "Salla Category", {"store_id": store_id, "category_id": category_id}, "name"
    )
    created = existing is None
    if created:
        doc = frappe.get_doc({"doctype": "Salla Category"})
    else:
        doc = frappe.get_doc("Salla Category", existing)

    doc.store_id = store_id
    doc.category_id = category_id
    doc.category_name = payload.get("category_name") or payload.get("name") or category_id
    doc.parent_category_id = payload.get("parent_category_id")
    doc.level = payload.get("level")
    doc.sort_order = payload.get("sort_order")
    doc.is_active = 1 if payload.get("is_active", True) else 0
    doc.path = payload.get("path")
    set_if_field(doc, "raw", payload.get("raw"))

    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    result = ClientApplyResult(status="applied", erp_doctype="Salla Category")
    return finalize_result(result, doc, created).as_dict()

