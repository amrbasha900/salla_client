from __future__ import annotations

from typing import Any, Optional

import frappe

from .common import finalize_result, set_if_field
from .result import ClientApplyResult

STORE_CUSTOMER_GROUP_PARENT = "All Customer Groups"


def _ensure_store_root(store_id: str) -> str:
    """Ensure a top-level Customer Group exists for this store (is_group=1)."""
    existing = frappe.db.exists("Customer Group", store_id) or frappe.db.get_value(
        "Customer Group", {"customer_group_name": store_id}, "name"
    )
    if existing:
        doc = frappe.get_doc("Customer Group", existing)
        changed = False
        if not getattr(doc, "is_group", 0):
            doc.is_group = 1
            changed = True
        if getattr(doc, "parent_customer_group", None) != STORE_CUSTOMER_GROUP_PARENT:
            doc.parent_customer_group = STORE_CUSTOMER_GROUP_PARENT
            changed = True
        if changed:
            doc.save(ignore_permissions=True)
        return doc.name

    doc = frappe.get_doc(
        {
            "doctype": "Customer Group",
            "customer_group_name": store_id,
            "parent_customer_group": STORE_CUSTOMER_GROUP_PARENT,
            "is_group": 1,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc.name


def _find_existing_customer_group(salla_id: str, parent_name: str) -> Optional[str]:
    """Locate an ERPNext Customer Group by Salla ID (custom field)."""
    if not salla_id:
        return None
    if frappe.model.meta.get_meta("Customer Group").has_field("salla_customer_id"):
        return frappe.db.get_value(
            "Customer Group", {"salla_customer_id": salla_id, "parent_customer_group": parent_name}, "name"
        )
    return None


def _upsert_erp_customer_group(store_id: str, salla_id: str, name: str, description: str) -> str:
    """Create/update the ERPNext Customer Group node mirroring the Salla group."""
    parent = _ensure_store_root(store_id)
    existing = _find_existing_customer_group(salla_id, parent) or frappe.db.get_value(
        "Customer Group", {"customer_group_name": name, "parent_customer_group": parent}, "name"
    )

    fields = {
        "customer_group_name": name,
        "parent_customer_group": parent,
        "is_group": 0,
        "description": description or "",
    }

    if existing:
        doc = frappe.get_doc("Customer Group", existing)
        changed = False
        for fname, val in fields.items():
            if doc.get(fname) != val:
                doc.set(fname, val)
                changed = True
        if doc.meta.has_field("salla_customer_id") and doc.get("salla_customer_id") != salla_id:
            doc.salla_customer_id = salla_id
            changed = True
        if changed:
            doc.save(ignore_permissions=True)
        return doc.name

    doc = frappe.get_doc({"doctype": "Customer Group", **fields})
    if doc.meta.has_field("salla_customer_id"):
        doc.salla_customer_id = salla_id
    doc.insert(ignore_permissions=True)
    return doc.name


def upsert_customer_group(store_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    group_id = payload.get("external_id") or payload.get("group_id") or payload.get("id")
    if not group_id:
        result = ClientApplyResult(status="failed")
        result.add_error("missing_group_id", "group_id/external_id is required.")
        return result.as_dict()

    group_name = payload.get("group_name") or payload.get("name") or str(group_id)
    description = payload.get("description") or payload.get("note") or ""

    # Persist to Salla Customer Group DocType for observability
    existing = frappe.db.get_value(
        "Salla Customer Group", {"store_id": store_id, "group_id": group_id}, "name"
    )
    created = existing is None
    if created:
        doc = frappe.get_doc({"doctype": "Salla Customer Group"})
    else:
        doc = frappe.get_doc("Salla Customer Group", existing)

    doc.store_id = store_id
    doc.group_id = group_id
    doc.group_name = group_name
    set_if_field(doc, "status", payload.get("status"))
    set_if_field(doc, "description", description)
    set_if_field(doc, "raw", payload.get("raw") or payload)

    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    # Mirror into ERPNext Customer Group tree (legacy behavior)
    erp_group_name = _upsert_erp_customer_group(store_id, str(group_id), group_name, description)

    result = ClientApplyResult(status="applied", erp_doctype="Customer Group")
    return finalize_result(result, frappe.get_doc("Customer Group", erp_group_name), created).as_dict()

