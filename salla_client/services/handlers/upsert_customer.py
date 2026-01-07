from __future__ import annotations

from typing import Any

import frappe

from .common import (
    ensure_customer_group,
    finalize_result,
    get_existing_doc_name,
    set_external_id,
    set_if_field,
)
from .result import ClientApplyResult


def upsert_customer(store_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    external_id = payload.get("external_id")
    existing_name = get_existing_doc_name("Customer", external_id)
    created = existing_name is None
    if created:
        doc = frappe.get_doc({"doctype": "Customer"})
    else:
        doc = frappe.get_doc("Customer", existing_name)

    doc.customer_name = payload.get("name") or payload.get("email") or payload.get("phone")
    doc.customer_group = ensure_customer_group(payload)
    doc.territory = payload.get("territory") or "All Territories"
    doc.customer_type = payload.get("customer_type") or "Individual"
    doc.disabled = 1 if payload.get("status") in {"inactive", "disabled"} else 0

    set_external_id(doc, external_id)
    set_if_field(doc, "email_id", payload.get("email"))
    set_if_field(doc, "mobile_no", payload.get("phone"))
    set_if_field(doc, "salla_addresses", payload.get("addresses"))

    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    result = ClientApplyResult(status="applied", erp_doctype="Customer")
    return finalize_result(result, doc, created).as_dict()
