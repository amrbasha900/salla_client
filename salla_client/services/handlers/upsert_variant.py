from __future__ import annotations

from typing import Any

import frappe

from .common import (
    finalize_result,
    get_existing_doc_name,
    set_external_id,
    set_if_field,
    sku_missing_result,
)
from .result import ClientApplyResult

INACTIVE_STATUSES = {"inactive", "hidden", "draft", "deleted"}


def upsert_variant(store_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    external_id = payload.get("external_id")
    sku = payload.get("sku")
    if not sku:
        return sku_missing_result(store_id, "variant", external_id).as_dict()

    product_external_id = payload.get("product_id")
    template_name = get_existing_doc_name("Item", product_external_id)
    if not template_name:
        result = ClientApplyResult(status="failed")
        result.add_error(
            "missing_template",
            "Variant template item not found for product.",
            product_id=product_external_id,
        )
        return result.as_dict()

    existing_name = get_existing_doc_name("Item", external_id)
    created = existing_name is None
    if created:
        doc = frappe.get_doc({"doctype": "Item"})
    else:
        doc = frappe.get_doc("Item", existing_name)

    template_doc = frappe.get_doc("Item", template_name)
    doc.item_code = sku
    doc.item_name = payload.get("name") or sku
    doc.variant_of = template_doc.name
    doc.item_group = template_doc.item_group
    doc.disabled = 1 if payload.get("status") in INACTIVE_STATUSES else 0

    set_external_id(doc, external_id)
    set_if_field(doc, "salla_options", payload.get("options"))

    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    result = ClientApplyResult(status="applied", erp_doctype="Item")
    return finalize_result(result, doc, created).as_dict()
