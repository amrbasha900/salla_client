from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import json

import frappe

from .common import finalize_result, resolve_store_link
from .result import ClientApplyResult


def _ensure_values(table) -> List[dict]:
    out: List[dict] = []
    for val in table or []:
        if not isinstance(val, dict):
            continue
        # normalize inbound naming from Manager/Salla
        value_id = val.get("value_id") or val.get("id")
        label = (
            val.get("label")
            or val.get("name")
            or val.get("display_value")
            or val.get("value_label")
        )
        out.append(
            {
                "value_id": value_id,
                "label": label,
                "display_value": val.get("display_value"),
                "hashed_display_value": val.get("hashed_display_value"),
                "is_default": 1 if val.get("is_default") else 0,
            }
        )
    return out


def _compose_attribute_name(option_name: str, option_id: Optional[str], product_sku: Optional[str]) -> str:
    """
    Mirror old integration naming to avoid duplicate attributes:
    "<product_sku> - <option_id> - <option_name>"
    """
    base_name = option_name or (option_id and f"Salla Option {option_id}") or "Salla Option"
    if product_sku and option_id:
        return f"{product_sku} - {option_id} - {base_name}"
    if product_sku:
        return f"{product_sku} - {base_name}"
    if option_id:
        return f"{option_id} - {base_name}"
    return base_name


def _add_attribute_custom_fields():
    """Ensure custom fields for Item Attribute/Value exist (idempotent)."""
    # If fields already exist, skip creation to avoid permission errors
    try:
        meta_attr = frappe.get_meta("Item Attribute")
        meta_val = frappe.get_meta("Item Attribute Value")
        if meta_attr.has_field("salla_option_id") and meta_attr.has_field("salla_store") and meta_attr.has_field("product_sku") and meta_val.has_field("salla_option_value_id"):
            return
    except Exception:
        pass

    try:
        from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

        create_custom_fields(
            {
                "Item Attribute": [
                    {
                        "fieldname": "salla_option_id",
                        "label": "Salla Option ID",
                        "fieldtype": "Data",
                        "insert_after": "numeric_values",
                        "read_only": 1,
                    },
                    {
                        "fieldname": "salla_store",
                        "label": "Salla Store",
                        "fieldtype": "Link",
                        "options": "Salla Store",
                        "insert_after": "salla_option_id",
                        "read_only": 1,
                    },
                    {
                        "fieldname": "product_sku",
                        "label": "Product SKU",
                        "fieldtype": "Data",
                        "insert_after": "salla_store",
                        "read_only": 1,
                    },
                ],
                "Item Attribute Value": [
                    {
                        "fieldname": "salla_option_value_id",
                        "label": "Salla Option Value ID",
                        "fieldtype": "Data",
                        "insert_after": "abbr",
                        "read_only": 1,
                    }
                ],
            },
            update=True,
        )
    except frappe.PermissionError:
        # Best effort: log and continue without failing option upsert
        frappe.log_error("Insufficient permission to create Item Attribute custom fields; proceeding without creation", "Salla Client: add attribute custom fields skipped")
    except Exception:
        # best-effort; don't block command processing
        frappe.log_error(frappe.get_traceback(), "Salla Client: add attribute custom fields failed")


def ensure_item_attribute_for_option(
    store_id: str, option: Dict[str, Any], product_sku: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    Create/update Item Attribute and values based on a Salla option payload.
    Returns (attribute_name, selected_value_name).
    """
    option_id = str(option.get("option_id") or option.get("id") or "").strip()
    option_name = (option.get("option_name") or option.get("name") or option_id).strip()
    product_sku = (product_sku or option.get("product_sku") or "").strip() or None
    if not option_name and not option_id:
        return None, None

    attr_name = _compose_attribute_name(option_name, option_id, product_sku)
    _add_attribute_custom_fields()

    # Find or create Item Attribute
    attr_doc = None
    existing = frappe.db.get_value("Item Attribute", {"attribute_name": attr_name}, "name")
    if existing:
        attr_doc = frappe.get_doc("Item Attribute", existing)
    else:
        attr_doc = frappe.get_doc(
            {
                "doctype": "Item Attribute",
                "attribute_name": attr_name,
                "from_range": 0,
                "numeric_values": 0,
            }
        )
        attr_doc.insert(ignore_permissions=True)

    # Set custom mappings if fields exist
    if attr_doc.meta.has_field("salla_option_id"):
        attr_doc.salla_option_id = option_id
    if attr_doc.meta.has_field("salla_store") and store_id and frappe.db.exists("Salla Store", store_id):
        attr_doc.salla_store = store_id
    if attr_doc.meta.has_field("product_sku"):
        attr_doc.product_sku = product_sku

    # Ensure values
    existing_values = {row.attribute_value: row for row in (attr_doc.item_attribute_values or [])}
    option_values = option.get("values") or []
    selected_value = (
        option.get("value_label")
        or option.get("value")
        or option.get("label")
        or option.get("display_value")
        or option.get("name")
    )
    # If selected value present but not in values list, append it to list for creation
    if selected_value and not option_values:
        option_values = [{"name": selected_value, "id": option.get("value_id")}]

    for val in option_values:
        if not isinstance(val, dict):
            continue
        value_name = (
            val.get("name")
            or val.get("display_value")
            or val.get("value_label")
            or val.get("label")
            or val.get("hashed_display_value")
            or str(val.get("id") or "")
        )
        if not value_name:
            continue
        if value_name not in existing_values:
            attr_doc.append(
                "item_attribute_values",
                {
                    "attribute_value": value_name,
                    "abbr": value_name[:140],
                },
            )
        # set custom value id if present
        for row in attr_doc.item_attribute_values or []:
            if row.attribute_value == value_name and val.get("id") and row.meta.has_field(
                "salla_option_value_id"
            ):
                row.salla_option_value_id = str(val.get("id"))

    attr_doc.save(ignore_permissions=True)
    return attr_name, selected_value or None


def upsert_product_option(store_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    option_id = payload.get("option_id") or payload.get("id")
    product_id = payload.get("product_id") or payload.get("product_external_id")
    if not option_id or not product_id:
        result = ClientApplyResult(status="failed")
        result.add_error("missing_ids", "option_id and product_id are required.")
        return result.as_dict()

    target_store = resolve_store_link(payload.get("store_id"), store_id)
    product_sku = payload.get("product_sku")

    # Prefer match by store+product+option; fallback to product+option to avoid duplicates from missing store link.
    existing = frappe.db.get_value(
        "Salla Product Option",
        {"store_id": target_store or store_id, "product_id": product_id, "option_id": option_id},
        "name",
    )
    if not existing:
        existing = frappe.db.get_value(
            "Salla Product Option",
            {"product_id": product_id, "option_id": option_id},
            "name",
        )
    created = existing is None
    if created:
        doc = frappe.get_doc({"doctype": "Salla Product Option"})
    else:
        doc = frappe.get_doc("Salla Product Option", existing)

    doc.store_id = target_store or store_id
    doc.product_id = product_id
    doc.option_id = option_id
    doc.option_name = payload.get("option_name") or payload.get("name") or option_id
    doc.position = payload.get("position")
    doc.raw = payload.get("raw") or payload

    # Merge values (preserve existing rows, append/update)
    incoming_values = _ensure_values(payload.get("values"))
    # Merge by value_id first, then label as fallback to avoid duplicates
    existing_rows_by_id = {row.value_id: row for row in (doc.get("values") or []) if getattr(row, "value_id", None)}
    existing_rows_by_label = {row.label: row for row in (doc.get("values") or []) if getattr(row, "label", None)}
    new_table = []
    for inc in incoming_values:
        vid = inc.get("value_id")
        lbl = inc.get("label")
        row = None
        if vid and vid in existing_rows_by_id:
            row = existing_rows_by_id[vid]
        elif lbl and lbl in existing_rows_by_label:
            row = existing_rows_by_label[lbl]
        if row:
            row.value_id = row.value_id or inc.get("value_id")
            row.display_value = row.display_value or inc.get("display_value")
            row.hashed_display_value = row.hashed_display_value or inc.get("hashed_display_value")
            row.is_default = row.is_default or inc.get("is_default")
            if row not in new_table:
                new_table.append(row)
        else:
            new_table.append(inc)
    # preserve any existing rows that had no label match
    for row in doc.get("values") or []:
        if getattr(row, "value_id", None) and row.value_id in {r.get("value_id") for r in incoming_values}:
            continue
        if getattr(row, "label", None) and row.label in {r.get("label") for r in incoming_values}:
            continue
        if row not in new_table:
            new_table.append(row)
    doc.set("values", new_table)

    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    # Also ensure ERPNext Item Attribute/Value exists for this option
    try:
        ensure_item_attribute_for_option(target_store, payload, product_sku)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Salla Client: ensure item attribute for option failed")

    result = ClientApplyResult(status="applied", erp_doctype="Salla Product Option")
    return finalize_result(result, doc, created).as_dict()

