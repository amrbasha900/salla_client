from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    """
    Ensure the standard ERPNext doctypes have `salla_external_id` so the client executor
    can upsert idempotently without relying on docnames.
    """
    custom_fields = {
        "Item": [
            {
                "fieldname": "salla_external_id",
                "label": "Salla External ID",
                "fieldtype": "Data",
                "insert_after": "item_code",
                "read_only": 1,
                "unique": 1,
                "search_index": 1,
            }
        ],
        "Customer": [
            {
                "fieldname": "salla_external_id",
                "label": "Salla External ID",
                "fieldtype": "Data",
                "insert_after": "customer_name",
                "read_only": 1,
                "unique": 1,
                "search_index": 1,
            }
        ],
        "Sales Order": [
            {
                "fieldname": "salla_external_id",
                "label": "Salla External ID",
                "fieldtype": "Data",
                "insert_after": "title",
                "read_only": 1,
                "unique": 1,
                "search_index": 1,
            }
        ],
    }

    create_custom_fields(custom_fields, update=True)
    frappe.db.commit()

