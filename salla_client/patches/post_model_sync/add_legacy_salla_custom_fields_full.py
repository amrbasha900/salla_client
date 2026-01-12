from __future__ import annotations

from typing import Any, Dict, List

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def _fallback_insert_after(dt: str) -> str:
    meta = frappe.get_meta(dt)
    # pick last real fieldname as safe fallback
    for df in reversed(meta.fields or []):
        if getattr(df, "fieldname", None):
            return df.fieldname
    # extreme fallback
    return "modified"


def _fix_insert_after(dt: str, fields: List[Dict[str, Any]]) -> None:
    meta = frappe.get_meta(dt)
    fallback = _fallback_insert_after(dt)
    for f in fields:
        ia = f.get("insert_after")
        if ia and not meta.has_field(ia):
            f["insert_after"] = fallback


def execute():
    """
    Port *all* legacy custom fields from the old `salla_integration` app so ERPNext doctypes
    have the same metadata fields (salla_store, salla_product_id, salla_order_id, etc.).

    This does NOT re-enable Salla API calls. It only restores schema parity/observability.
    """

    custom_fields: Dict[str, List[Dict[str, Any]]] = {
        "Item": [
            {
                "fieldname": "salla_integration_section",
                "label": "Salla Integration",
                "fieldtype": "Section Break",
                "insert_after": "is_stock_item",
                "collapsible": 1,
            },
            {
                "fieldname": "salla_is_from_salla",
                "label": "From Salla",
                "fieldtype": "Check",
                "insert_after": "salla_integration_section",
                "read_only": 1,
            },
            {
                "fieldname": "salla_store",
                "label": "Salla Store",
                "fieldtype": "Link",
                "options": "Salla Store",
                "insert_after": "salla_is_from_salla",
                "in_list_view": 0,
                "in_standard_filter": 1,
            },
            {
                "fieldname": "salla_product_id",
                "label": "Salla Product ID",
                "fieldtype": "Data",
                "insert_after": "salla_store",
                "read_only": 1,
                "unique": 0,
                "search_index": 1,
            },
            {
                "fieldname": "salla_sku",
                "label": "Salla SKU",
                "fieldtype": "Data",
                "insert_after": "salla_product_id",
                "read_only": 0,
            },
            {
                "fieldname": "salla_option_ids",
                "label": "Salla Option IDs",
                "fieldtype": "Small Text",
                "insert_after": "salla_sku",
                "read_only": 1,
                "hidden": 1,
            },
            {
                "fieldname": "salla_option_value_ids",
                "label": "Salla Option Value IDs",
                "fieldtype": "Small Text",
                "insert_after": "salla_option_ids",
                "read_only": 0,
                "hidden": 0,
            },
            {
                "fieldname": "column_break_salla",
                "fieldtype": "Column Break",
                "insert_after": "salla_option_value_ids",
            },
            {
                "fieldname": "salla_sync_hash",
                "label": "Salla Sync Hash",
                "fieldtype": "Data",
                "insert_after": "column_break_salla",
                "hidden": 1,
                "read_only": 1,
            },
            {
                "fieldname": "salla_last_synced",
                "label": "Salla Last Synced",
                "fieldtype": "Datetime",
                "insert_after": "salla_sync_hash",
                "read_only": 1,
            },
        ],
        "Item Attribute": [
            {
                "fieldname": "salla_option_id",
                "label": "Salla Option ID",
                "fieldtype": "Data",
                "insert_after": "numeric_values",
                "read_only": 1,
            },
            {
                "fieldname": "salla_option_ids",
                "label": "Salla Option IDs",
                "fieldtype": "Small Text",
                "insert_after": "salla_option_id",
                "read_only": 1,
            },
            {
                "fieldname": "salla_option_value_ids",
                "label": "Salla Option Value IDs",
                "fieldtype": "Small Text",
                "insert_after": "salla_option_ids",
                "read_only": 1,
            },
            {
                "fieldname": "salla_store",
                "label": "Salla Store",
                "fieldtype": "Link",
                "options": "Salla Store",
                "insert_after": "salla_option_value_ids",
            },
            {
                "fieldname": "product_sku",
                "label": "Product SKU",
                "fieldtype": "Data",
                "insert_after": "salla_store",
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
        "Sales Order Item": [
            {
                "fieldname": "salla_is_from_salla",
                "label": "From Salla",
                "fieldtype": "Check",
                "insert_after": "description",
                "read_only": 1,
            },
            {
                "fieldname": "salla_product_id",
                "label": "Salla Product ID",
                "fieldtype": "Data",
                "insert_after": "salla_is_from_salla",
                "read_only": 1,
                "search_index": 1,
            },
            {
                "fieldname": "salla_item_sku",
                "label": "Salla Item SKU",
                "fieldtype": "Data",
                "insert_after": "salla_product_id",
                "read_only": 1,
            },
            {
                "fieldname": "salla_option_value_ids",
                "label": "Salla Option Value IDs",
                "fieldtype": "Small Text",
                "insert_after": "salla_item_sku",
                "read_only": 1,
            },
            {
                "fieldname": "salla_option_summary",
                "label": "Salla Option Summary",
                "fieldtype": "Small Text",
                "insert_after": "salla_option_value_ids",
                "read_only": 1,
            },
        ],
        "Sales Order": [
            {
                "fieldname": "salla_integration_section",
                "label": "Salla Integration",
                "fieldtype": "Section Break",
                "insert_after": "title",
                "collapsible": 1,
            },
            {
                "fieldname": "salla_is_from_salla",
                "label": "From Salla",
                "fieldtype": "Check",
                "insert_after": "salla_integration_section",
                "read_only": 1,
                "in_list_view": 0,
            },
            {
                "fieldname": "salla_store",
                "label": "Salla Store",
                "fieldtype": "Link",
                "options": "Salla Store",
                "insert_after": "salla_is_from_salla",
                "in_list_view": 0,
                "in_standard_filter": 1,
                "read_only": 1,
            },
            {
                "fieldname": "salla_order_id",
                "label": "Salla Order ID",
                "fieldtype": "Data",
                "insert_after": "salla_store",
                "read_only": 1,
                "search_index": 1,
            },
            {
                "fieldname": "salla_reference_id",
                "label": "Salla Reference ID",
                "fieldtype": "Data",
                "insert_after": "salla_order_id",
                "read_only": 1,
            },
            {
                "fieldname": "salla_status_id",
                "label": "Salla Status ID",
                "fieldtype": "Data",
                "insert_after": "salla_reference_id",
                "read_only": 1,
            },
            {
                "fieldname": "salla_status_slug",
                "label": "Salla Status Slug",
                "fieldtype": "Data",
                "insert_after": "salla_status_id",
                "read_only": 1,
            },
            {
                "fieldname": "salla_status_name",
                "label": "Salla Status Name",
                "fieldtype": "Data",
                "insert_after": "salla_status_slug",
                "read_only": 1,
            },
            {
                "fieldname": "salla_payment_status",
                "label": "Salla Payment Status",
                "fieldtype": "Data",
                "insert_after": "salla_status_name",
                "read_only": 1,
            },
            {
                "fieldname": "salla_payment_method",
                "label": "Salla Payment Method",
                "fieldtype": "Data",
                "insert_after": "salla_payment_status",
                "read_only": 1,
            },
            {
                "fieldname": "salla_delivery_method",
                "label": "Salla Delivery Method",
                "fieldtype": "Data",
                "insert_after": "salla_payment_method",
                "read_only": 1,
            },
            {"fieldname": "column_break_salla", "fieldtype": "Column Break", "insert_after": "salla_delivery_method"},
            {
                "fieldname": "salla_sync_status",
                "label": "Salla Sync Status",
                "fieldtype": "Select",
                "options": "\nNot Synced\nSynced\nFailed",
                "insert_after": "column_break_salla",
                "read_only": 1,
                "in_list_view": 1,
            },
            {
                "fieldname": "salla_last_synced",
                "label": "Salla Last Synced",
                "fieldtype": "Datetime",
                "insert_after": "salla_sync_status",
                "read_only": 1,
            },
        ],
        "Customer": [
            {
                "fieldname": "salla_integration_section",
                "label": "Salla Integration",
                "fieldtype": "Section Break",
                "insert_after": "represents_company",
                "collapsible": 1,
            },
            {
                "fieldname": "salla_is_from_salla",
                "label": "From Salla",
                "fieldtype": "Check",
                "insert_after": "salla_integration_section",
                "read_only": 1,
            },
            {
                "fieldname": "salla_store",
                "label": "Salla Store",
                "fieldtype": "Link",
                "options": "Salla Store",
                "insert_after": "salla_is_from_salla",
                "in_standard_filter": 1,
            },
            {
                "fieldname": "salla_customer_id",
                "label": "Salla Customer ID",
                "fieldtype": "Data",
                "insert_after": "salla_store",
                "read_only": 1,
                "search_index": 1,
            },
            {
                "fieldname": "salla_last_synced",
                "label": "Salla Last Synced",
                "fieldtype": "Datetime",
                "insert_after": "salla_customer_id",
                "read_only": 1,
            },
        ],
        "Customer Group": [
            {
                "fieldname": "salla_customer_id",
                "label": "Salla Customer ID",
                "fieldtype": "Data",
                "insert_after": "is_group",
                "read_only": 1,
                "search_index": 1,
            }
        ],
        "Item Group": [
            {
                "fieldname": "salla_category_id",
                "label": "Salla Category ID",
                "fieldtype": "Data",
                "insert_after": "is_group",
                "read_only": 1,
                "search_index": 1,
            },
            {
                "fieldname": "salla_is_from_salla",
                "label": "From Salla",
                "fieldtype": "Check",
                "insert_after": "salla_category_id",
                "read_only": 1,
            },
            {
                "fieldname": "salla_store",
                "label": "Salla Store",
                "fieldtype": "Link",
                "options": "Salla Store",
                "insert_after": "salla_is_from_salla",
                "in_standard_filter": 1,
            },
        ],
        "Brand": [
            {
                "fieldname": "salla_brand_id",
                "label": "Salla Brand ID",
                "fieldtype": "Data",
                "insert_after": "description",
                "read_only": 1,
                "search_index": 1,
            },
            {
                "fieldname": "salla_is_from_salla",
                "label": "From Salla",
                "fieldtype": "Check",
                "insert_after": "salla_brand_id",
                "read_only": 1,
            },
            {
                "fieldname": "salla_store",
                "label": "Salla Store",
                "fieldtype": "Link",
                "options": "Salla Store",
                "insert_after": "salla_is_from_salla",
                "in_standard_filter": 1,
            },
            {"fieldname": "salla_logo_url", "label": "Salla Logo URL", "fieldtype": "Data", "insert_after": "salla_store", "read_only": 1},
            {"fieldname": "salla_banner_url", "label": "Salla Banner URL", "fieldtype": "Data", "insert_after": "salla_logo_url", "read_only": 1},
            {"fieldname": "salla_metadata_title", "label": "Salla Meta Title", "fieldtype": "Data", "insert_after": "salla_banner_url", "read_only": 1},
            {"fieldname": "salla_metadata_description", "label": "Salla Meta Description", "fieldtype": "Small Text", "insert_after": "salla_metadata_title", "read_only": 1},
            {"fieldname": "salla_metadata_url", "label": "Salla Meta URL", "fieldtype": "Data", "insert_after": "salla_metadata_description", "read_only": 1},
            {"fieldname": "salla_ar_char", "label": "Salla Arabic Character", "fieldtype": "Data", "insert_after": "salla_metadata_url", "read_only": 1},
            {"fieldname": "salla_en_char", "label": "Salla English Character", "fieldtype": "Data", "insert_after": "salla_ar_char", "read_only": 1},
            {"fieldname": "salla_translations", "label": "Salla Translations", "fieldtype": "Code", "options": "JSON", "insert_after": "salla_en_char", "read_only": 1},
        ],
        "Address": [
            {
                "fieldname": "salla_is_from_salla",
                "label": "From Salla",
                "fieldtype": "Check",
                "insert_after": "address_type",
                "read_only": 1,
            }
        ],
        "Contact": [
            {
                "fieldname": "salla_is_from_salla",
                "label": "From Salla",
                "fieldtype": "Check",
                "insert_after": "first_name",
                "read_only": 1,
            }
        ],
        "Sales Taxes and Charges Template": [
            {
                "fieldname": "salla_tax_id",
                "label": "Salla Tax ID",
                "fieldtype": "Data",
                "insert_after": "disabled",
                "read_only": 1,
                "search_index": 1,
                "description": "Original tax identifier pulled from Salla",
            }
        ],
    }

    for dt, fields in custom_fields.items():
        _fix_insert_after(dt, fields)

    create_custom_fields(custom_fields, update=True)
    frappe.db.commit()

