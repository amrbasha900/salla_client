from __future__ import annotations

from typing import Any
import json

from salla_client.services.handlers.upsert_product_option import (
    _compose_attribute_name,
    ensure_item_attribute_for_option,
)

import frappe
from frappe.utils import now_datetime

from .common import (
    finalize_result,
    get_existing_doc_name,
    resolve_store_link,
    set_external_id,
    set_if_field,
    sku_missing_result,
)
from .result import ClientApplyResult

INACTIVE_STATUSES = {"inactive", "hidden", "draft", "deleted"}


def _ensure_attribute_value(attribute_name: str | None, value: str | None):
    """Create Item Attribute and value if missing."""
    if not attribute_name or not value:
        return

    attr_name = attribute_name.strip()
    if not attr_name:
        return

    if not frappe.db.exists("Item Attribute", attr_name):
        attr_doc = frappe.get_doc(
            {
                "doctype": "Item Attribute",
                "attribute_name": attr_name,
                "item_attribute_values": [
                    {"attribute_value": value, "abbr": value[:140]},
                ],
            }
        )
        attr_doc.insert(ignore_permissions=True)
        return

    attr_doc = frappe.get_doc("Item Attribute", attr_name)
    existing_values = {row.attribute_value for row in attr_doc.item_attribute_values}
    if value not in existing_values:
        attr_doc.append(
            "item_attribute_values", {"attribute_value": value, "abbr": value[:140]}
        )
        attr_doc.save(ignore_permissions=True)


def upsert_variant(store_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    external_id = payload.get("external_id")
    sku = payload.get("sku")
    if not sku:
        return sku_missing_result(store_id, "variant", external_id, sku=sku).as_dict()

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
    doc.stock_uom = payload.get("uom") or template_doc.get("stock_uom") or "Nos"
    doc.is_stock_item = template_doc.get("is_stock_item", 1)
    doc.disabled = 1 if str(payload.get("status")).lower() in INACTIVE_STATUSES else 0

    if hasattr(template_doc, "has_variants"):
        try:
            template_doc.has_variants = 1
            template_doc.save(ignore_permissions=True)
        except Exception:
            pass

    set_external_id(doc, external_id)
    # legacy fields (old salla_integration schema)
    set_if_field(doc, "salla_is_from_salla", 1)
    target_store = resolve_store_link(payload.get("store_id"), store_id)
    set_if_field(doc, "salla_store", target_store)
    # old app stored product_id on the variant too; keep parity
    set_if_field(doc, "salla_product_id", payload.get("product_id"))
    set_if_field(doc, "salla_sku", sku)
    set_if_field(doc, "salla_last_synced", now_datetime())
    # Store raw options as JSON for parity with old schema
    set_if_field(doc, "salla_options", json.dumps(payload.get("options") or [], ensure_ascii=False))
    set_if_field(doc, "default_warehouse", payload.get("warehouse"))
    set_if_field(doc, "barcode", payload.get("barcode"))

    # Build attribute rows so ERPNext variant validation passes
    attributes: list[dict[str, str]] = []
    parent_sku = template_doc.get("item_code")
    for opt in payload.get("options") or []:
        # Ensure Item Attribute + values exist (mirrors product option handler)
        try:
            attr_name, ensured_value = ensure_item_attribute_for_option(
                target_store,
                opt,
                product_sku=parent_sku,
            )
        except Exception:
            attr_name = None
            ensured_value = None

        if not attr_name:
            attr_name = _compose_attribute_name(
                opt.get("name") or opt.get("option_name"), opt.get("id") or opt.get("option_id"), parent_sku
            )

        value_label = (
            opt.get("value_label")
            or opt.get("value")
            or opt.get("label")
            or opt.get("display_value")
            or ensured_value
        )
        if not value_label:
            continue
        _ensure_attribute_value(attr_name, value_label)
        attributes.append(
            {
                "attribute": attr_name,
                "attribute_value": value_label,
                "abbr": value_label[:140],
            }
        )

    if attributes:
        doc.variant_based_on = "Item Attribute"
        doc.set("attributes", attributes)

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
