from __future__ import annotations

from typing import Any
import json

from erpnext.controllers.item_variant import create_variant, make_variant_item_code
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
from .upsert_product import _extract_amount, _get_store_doc, _normalize_price, _upsert_item_price
from .result import ClientApplyResult


def _as_str(val: Any) -> str:
    """Ensure item codes/names are strings to satisfy ERPNext autoname."""
    if val is None:
        return ""
    return str(val)

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
    template_name = _ensure_template_item(store_id, payload)
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
    doc.item_code = _as_str(sku)
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

    # Helper to add attribute-value pair safely
    def _add_attr(attr_name: str | None, value_label: str | None):
        if not attr_name or not value_label:
            return
        _ensure_attribute_value(attr_name, value_label)
        attributes.append(
            {
                "attribute": attr_name,
                "attribute_value": value_label,
                "abbr": value_label[:140],
            }
        )

    # First, map from explicit option payload
    for opt in payload.get("options") or []:
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
        _add_attr(attr_name, value_label)

    # If no options came through, map related_option_values to attribute values (old flow parity)
    if not attributes:
        value_map = _build_value_map_from_item_attributes(parent_sku, target_store)
        for vid in payload.get("related_option_values") or []:
            vid_str = str(vid)
            if vid_str in value_map:
                attr_name, val_label = value_map[vid_str]
                _add_attr(attr_name, val_label)

    if attributes:
        doc.variant_based_on = "Item Attribute"
        doc.set("attributes", attributes)

    def _default_variant_name() -> str | None:
        if not attributes:
            return None
        try:
            temp = frappe.new_doc("Item")
            temp.set("attributes", attributes)
            make_variant_item_code(template_doc.item_code, template_doc.item_name, temp)
            return temp.item_name
        except Exception:
            return None

    default_variant_name = _default_variant_name()
    desired_name = payload.get("name") or _as_str(sku)
    if not created and (doc.item_name in (None, "", doc.item_code, _as_str(sku))):
        if default_variant_name:
            doc.item_name = default_variant_name
        elif payload.get("name") and not doc.item_name:
            doc.item_name = payload.get("name")

    # Use ERPNext's create_variant to mirror old flow; fall back to manual insert when needed.
    try:
        if created:
            args = {row["attribute"]: row["attribute_value"] for row in (doc.get("attributes") or []) if row.get("attribute") and row.get("attribute_value")}
            if args:
                variant = create_variant(template_doc.name, args)
                # copy custom fields
                set_external_id(variant, external_id)
                set_if_field(variant, "salla_is_from_salla", 1)
                set_if_field(variant, "salla_store", target_store)
                set_if_field(variant, "salla_product_id", payload.get("product_id"))
                set_if_field(variant, "salla_sku", sku)
                set_if_field(variant, "salla_last_synced", now_datetime())
                set_if_field(variant, "salla_options", json.dumps(payload.get("options") or [], ensure_ascii=False))
                set_if_field(variant, "default_warehouse", payload.get("warehouse"))
                set_if_field(variant, "barcode", payload.get("barcode"))
                variant.save(ignore_permissions=True)
                doc = variant
            else:
                # No attributes; fall back to insert/save with explicit name
                doc.item_name = default_variant_name or desired_name
                doc.flags.ignore_after_insert = True
                doc.insert(ignore_permissions=True)
        else:
            doc.save(ignore_permissions=True)
    except Exception:
        # Fallback path to ensure variant is created even if create_variant fails
        if created:
            _prev_in_patch = getattr(frappe.flags, "in_patch", False)
            _prev_ignore_perms = getattr(frappe.flags, "ignore_permissions", False)
            try:
                frappe.flags.in_patch = True
                frappe.flags.ignore_permissions = True
                doc.flags.ignore_after_insert = True
                if not doc.item_name:
                    doc.item_name = default_variant_name or desired_name
                doc.insert(ignore_permissions=True)
            finally:
                frappe.flags.in_patch = _prev_in_patch
                frappe.flags.ignore_permissions = _prev_ignore_perms
        else:
            doc.save(ignore_permissions=True)

    result = ClientApplyResult(status="applied", erp_doctype="Item")
    try:
        raw_payload = payload.get("raw")
        if isinstance(raw_payload, str):
            try:
                raw_payload = json.loads(raw_payload)
            except Exception:
                raw_payload = None
        if not isinstance(raw_payload, dict):
            raw_payload = {}

        store_doc = _get_store_doc(target_store, payload.get("store_id"), store_id, raw_payload.get("store_id"))
        if store_doc:
            sale_price = payload.get("sale_price")
            if sale_price in (None, ""):
                sale_price = raw_payload.get("sale_price")
            price_fallback = payload.get("price")
            if price_fallback in (None, ""):
                price_fallback = raw_payload.get("price")
            if sale_price in (None, ""):
                sale_price = price_fallback
            elif _extract_amount(sale_price) in (None, "", 0) and _extract_amount(price_fallback) not in (
                None,
                "",
            ):
                sale_price = price_fallback

            cost_price = payload.get("cost_price")
            if cost_price in (None, ""):
                cost_price = raw_payload.get("cost_price")

            selling_price_list = store_doc.get("selling_price_list")
            buying_price_list = store_doc.get("buying_price_list")
            selling_rate = _normalize_price(sale_price)
            buying_rate = _normalize_price(cost_price)
            if created:
                if selling_rate is None:
                    selling_rate = 0.0
                if buying_rate is None:
                    buying_rate = 0.0
            if created and selling_rate is None:
                selling_rate = 0.0
            if created and buying_rate is None:
                buying_rate = 0.0
            item_code = doc.item_code

            if selling_price_list and selling_rate is not None:
                _upsert_item_price(item_code, selling_price_list, selling_rate)
            if buying_price_list and buying_rate is not None:
                _upsert_item_price(item_code, buying_price_list, buying_rate)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Salla Client: variant item price upsert failed")

    return finalize_result(result, doc, created).as_dict()


def _ensure_template_item(store_id: str, payload: dict[str, Any]) -> str | None:
    """Ensure a template Item exists for the given product_id; create minimal stub if missing."""
    product_external_id = payload.get("product_id")
    template_name = get_existing_doc_name("Item", product_external_id)
    if template_name:
        return template_name

    # Attempt reuse by item_code if a non-variant item exists
    candidate_code = payload.get("product_sku") or product_external_id
    candidate_code_str = _as_str(candidate_code or product_external_id)
    def _ensure_template_attributes(doc: frappe.model.document.Document) -> bool:
        """Attach Item Attribute rows to template when possible."""
        product_sku = (payload.get("product_sku") or payload.get("sku") or candidate_code_str or "").strip()
        target_store = resolve_store_link(payload.get("store_id"), store_id)
        attr_names: list[str] = []
        seen: set[str] = set()

        for opt in payload.get("options") or []:
            try:
                attr_name, _ = ensure_item_attribute_for_option(
                    target_store or store_id,
                    opt,
                    product_sku=product_sku,
                )
            except Exception:
                attr_name = None
            if not attr_name:
                attr_name = _compose_attribute_name(
                    opt.get("name") or opt.get("option_name"),
                    opt.get("id") or opt.get("option_id"),
                    product_sku,
                )
            if attr_name and attr_name not in seen:
                seen.add(attr_name)
                attr_names.append(attr_name)

        if not attr_names:
            value_map = _build_value_map_from_item_attributes(product_sku, target_store)
            for vid in payload.get("related_option_values") or []:
                vid_str = str(vid)
                if vid_str in value_map:
                    attr_name, _ = value_map[vid_str]
                    if attr_name and attr_name not in seen:
                        seen.add(attr_name)
                        attr_names.append(attr_name)

        if not attr_names and payload.get("related_options"):
            filters = {"salla_option_id": ("in", [str(o) for o in payload.get("related_options")])}
            if target_store:
                filters["salla_store"] = target_store
            if product_sku:
                filters["product_sku"] = product_sku
            try:
                rows = frappe.get_all("Item Attribute", filters=filters, fields=["attribute_name"])
                for row in rows:
                    name = row.get("attribute_name")
                    if name and name not in seen:
                        seen.add(name)
                        attr_names.append(name)
            except Exception:
                pass

        if not attr_names:
            return False

        merged = list(doc.get("attributes") or [])
        existing_names = {row.get("attribute") for row in merged if row.get("attribute")}
        for attr_name in attr_names:
            if attr_name not in existing_names:
                merged.append({"attribute": attr_name})
        doc.set("attributes", merged)
        if hasattr(doc, "has_variants"):
            doc.has_variants = 1
        if doc.meta.has_field("variant_based_on") and not doc.get("variant_based_on"):
            doc.variant_based_on = "Item Attribute"
        return True

    if candidate_code_str and frappe.db.exists("Item", {"item_code": candidate_code_str, "variant_of": ""}):
        doc = frappe.get_doc("Item", candidate_code_str)
        set_external_id(doc, product_external_id)
        _ensure_template_attributes(doc)
        set_if_field(doc, "salla_is_from_salla", 1)
        target_store = resolve_store_link(payload.get("store_id"), store_id)
        set_if_field(doc, "salla_store", target_store or store_id)
        set_if_field(doc, "salla_product_id", product_external_id)
        doc.save(ignore_permissions=True)
        return doc.name

    # Create a minimal template
    doc = frappe.get_doc({"doctype": "Item"})
    doc.item_code = candidate_code_str or _as_str(product_external_id)
    doc.item_name = payload.get("product_name") or doc.item_code or _as_str(product_external_id)
    doc.item_group = "All Item Groups"
    doc.stock_uom = payload.get("uom") or "Nos"
    doc.is_stock_item = 1
    _ensure_template_attributes(doc)
    set_external_id(doc, product_external_id)
    set_if_field(doc, "salla_is_from_salla", 1)
    target_store = resolve_store_link(payload.get("store_id"), store_id)
    set_if_field(doc, "salla_store", target_store or store_id)
    set_if_field(doc, "salla_product_id", product_external_id)
    _prev_in_patch = getattr(frappe.flags, "in_patch", False)
    _prev_ignore_perms = getattr(frappe.flags, "ignore_permissions", False)
    try:
        frappe.flags.in_patch = True
        frappe.flags.ignore_permissions = True
        doc.flags.ignore_after_insert = True
        doc.insert(ignore_permissions=True)
    finally:
        frappe.flags.in_patch = _prev_in_patch
        frappe.flags.ignore_permissions = _prev_ignore_perms
    return doc.name


def _build_value_map_from_item_attributes(product_sku: str | None, store_id: str | None) -> dict[str, tuple[str, str]]:
    """
    Map salla_option_value_id -> (attribute_name, attribute_value) using Item Attribute data.
    """
    value_map: dict[str, tuple[str, str]] = {}
    if not product_sku:
        return value_map
    filters = {"product_sku": product_sku}
    if store_id:
        filters["salla_store"] = store_id
    try:
        attrs = frappe.get_all("Item Attribute", filters=filters, fields=["name", "attribute_name"])
        for row in attrs:
            try:
                doc = frappe.get_doc("Item Attribute", row["name"])
            except Exception:
                continue
            attr_name = doc.attribute_name
            for val in doc.item_attribute_values or []:
                vid = getattr(val, "salla_option_value_id", None)
                lbl = getattr(val, "attribute_value", None)
                if vid and lbl:
                    value_map[str(vid)] = (attr_name, lbl)
    except Exception:
        pass
    return value_map
