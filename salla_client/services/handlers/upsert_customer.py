from __future__ import annotations

from typing import Any

import frappe
import json
from frappe.utils import now_datetime

from .common import (
    ensure_customer_group,
    finalize_result,
    get_existing_doc_name,
    resolve_store_link,
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
    doc.disabled = 1 if str(payload.get("status")).lower() in {"inactive", "disabled"} else 0

    set_external_id(doc, external_id)
    # legacy fields (old salla_integration schema)
    set_if_field(doc, "salla_is_from_salla", 1)
    target_store = resolve_store_link(payload.get("store_id"), store_id)
    set_if_field(doc, "salla_store", target_store)
    set_if_field(doc, "salla_customer_id", external_id)
    set_if_field(doc, "salla_last_synced", now_datetime())
    set_if_field(doc, "email_id", payload.get("email"))
    set_if_field(doc, "mobile_no", payload.get("phone"))
    addresses = payload.get("addresses")
    if isinstance(addresses, list):
        addresses = json.dumps(addresses, ensure_ascii=False)
    set_if_field(doc, "salla_addresses", addresses)

    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    _ensure_contact(doc.name, payload)
    _ensure_address(doc.name, payload)

    result = ClientApplyResult(status="applied", erp_doctype="Customer")
    return finalize_result(result, doc, created).as_dict()


def _ensure_contact(customer_name: str, payload: dict[str, Any]) -> None:
    if not customer_name:
        return
    email = payload.get("email")
    phone = payload.get("phone")
    if not email and not phone:
        return
    existing = None
    if email:
        existing = frappe.db.get_value("Contact", {"email_id": email}, "name")
    if existing:
        return
    contact = frappe.get_doc({"doctype": "Contact", "first_name": payload.get("name") or customer_name})
    contact.append(
        "links",
        {
            "link_doctype": "Customer",
            "link_name": customer_name,
        },
    )
    if email:
        contact.append("email_ids", {"email_id": email, "is_primary": 1})
    if phone:
        contact.append("phone_nos", {"phone": phone, "is_primary_mobile_no": 1})
    try:
        contact.insert(ignore_permissions=True)
    except Exception:
        pass


def _ensure_address(customer_name: str, payload: dict[str, Any]) -> None:
    addresses = payload.get("addresses") or []
    if not customer_name or not addresses:
        return
    address_data = addresses[0]
    if not isinstance(address_data, dict):
        return
    existing = frappe.db.get_value(
        "Address",
        {
            "address_line1": address_data.get("address_line1") or address_data.get("street"),
            "city": address_data.get("city"),
            "country": address_data.get("country"),
        },
        "name",
    )
    if existing:
        return
    address = frappe.get_doc(
        {
            "doctype": "Address",
            "address_title": customer_name,
            "address_line1": address_data.get("address_line1") or address_data.get("street") or "",
            "address_line2": address_data.get("address_line2") or address_data.get("block"),
            "city": address_data.get("city") or "",
            "state": address_data.get("state") or "",
            "country": address_data.get("country") or "",
            "pincode": address_data.get("pincode") or address_data.get("postal_code") or "",
            "links": [
                {
                    "link_doctype": "Customer",
                    "link_name": customer_name,
                }
            ],
        }
    )
    try:
        address.insert(ignore_permissions=True)
    except Exception:
        pass
