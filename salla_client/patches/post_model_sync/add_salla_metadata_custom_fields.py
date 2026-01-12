from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    """
    Port the key metadata custom fields from the old `salla_integration` app that the
    new `salla_client` handlers already write (set_if_field / set_external_id).

    This avoids runtime errors and keeps ERP docs observable/debuggable like the old app.
    """

    custom_fields = {
        # Item metadata used by upsert_product / upsert_variant
        "Item": [
            {
                "fieldname": "salla_url",
                "label": "Salla URL",
                "fieldtype": "Data",
                "insert_after": "salla_external_id",
                "read_only": 1,
            },
            {
                "fieldname": "salla_brand_id",
                "label": "Salla Brand ID",
                "fieldtype": "Data",
                "insert_after": "salla_url",
                "read_only": 1,
            },
            {
                "fieldname": "salla_category_ids",
                "label": "Salla Category IDs",
                "fieldtype": "Code",
                "options": "JSON",
                "insert_after": "salla_brand_id",
                "read_only": 1,
            },
            {
                "fieldname": "salla_images",
                "label": "Salla Images",
                "fieldtype": "Code",
                "options": "JSON",
                "insert_after": "salla_category_ids",
                "read_only": 1,
            },
            {
                "fieldname": "salla_options",
                "label": "Salla Options",
                "fieldtype": "Code",
                "options": "JSON",
                "insert_after": "salla_images",
                "read_only": 1,
            },
        ],
        # Customer metadata used by upsert_customer
        "Customer": [
            {
                "fieldname": "salla_addresses",
                "label": "Salla Addresses",
                "fieldtype": "Code",
                "options": "JSON",
                "insert_after": "salla_external_id",
                "read_only": 1,
            }
        ],
        # Sales Order metadata used by upsert_order
        "Sales Order": [
            {
                "fieldname": "salla_status",
                "label": "Salla Status",
                "fieldtype": "Data",
                "insert_after": "salla_external_id",
                "read_only": 1,
            },
            {
                "fieldname": "salla_raw",
                "label": "Salla Raw",
                "fieldtype": "Code",
                "options": "JSON",
                "insert_after": "salla_status",
                "read_only": 1,
            },
        ],
    }

    create_custom_fields(custom_fields, update=True)
    frappe.db.commit()

