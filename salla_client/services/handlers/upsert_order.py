from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import getdate, nowdate
from frappe.utils import now_datetime

from .common import (
    finalize_result,
    get_existing_doc_name,
    resolve_store_link,
    set_external_id,
    set_if_field,
)
from .result import ClientApplyResult
from .upsert_customer import upsert_customer


def resolve_customer(store_id: str, payload: dict[str, Any], result: ClientApplyResult) -> str | None:
    customer_payload = payload.get("customer") or {}
    external_id = customer_payload.get("external_id")
    existing_name = get_existing_doc_name("Customer", external_id)
    if existing_name:
        return existing_name

    if customer_payload:
        customer_result = upsert_customer(store_id, customer_payload)
        if customer_result.get("status") == "applied":
            return customer_result.get("erp_doc")
        result.add_warning(
            "customer_not_applied",
            "Customer payload provided but could not be applied.",
            customer=customer_payload,
        )
    return None


def build_items(payload_items: list[dict[str, Any]], result: ClientApplyResult) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in payload_items:
        sku = entry.get("sku") or entry.get("item_code")
        external_id = entry.get("external_id")
        item_code = get_existing_doc_name("Item", external_id) or sku
        if not item_code:
            result.add_warning("missing_sku", "Order item missing SKU; skipped.", item=entry)
            continue
        if not frappe.db.exists("Item", item_code):
            result.add_warning("missing_item", "Item not found in ERP; skipped.", item_code=item_code)
            continue
        items.append(
            {
                "item_code": item_code,
                "item_name": entry.get("name") or item_code,
                "qty": entry.get("quantity") or entry.get("qty") or 1,
                "rate": entry.get("price") or entry.get("rate") or 0,
                # legacy per-line metadata (if custom fields exist)
                "salla_is_from_salla": 1,
                "salla_product_id": external_id,
                "salla_item_sku": sku,
            }
        )
    return items


def upsert_order(store_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    external_id = payload.get("external_id")
    existing_name = get_existing_doc_name("Sales Order", external_id)
    created = existing_name is None
    if created:
        doc = frappe.get_doc({"doctype": "Sales Order"})
    else:
        doc = frappe.get_doc("Sales Order", existing_name)

    result = ClientApplyResult(status="applied", erp_doctype="Sales Order")
    customer_name = resolve_customer(store_id, payload, result)
    if not customer_name:
        result.status = "failed"
        result.add_error("missing_customer", "Customer not resolved for order.")
        return result.as_dict()

    doc.customer = customer_name
    doc.company = payload.get("company") or _get_default_company()
    if not doc.company:
        result.status = "failed"
        result.add_error("missing_company", "No company configured for order creation.")
        return result.as_dict()
    doc.transaction_date = getdate(payload.get("created_at")) if payload.get("created_at") else nowdate()
    doc.currency = payload.get("currency") or doc.currency

    set_external_id(doc, external_id)
    set_if_field(doc, "salla_status", payload.get("status"))
    set_if_field(doc, "salla_raw", payload.get("raw"))
    # legacy Sales Order fields (old salla_integration schema)
    set_if_field(doc, "salla_is_from_salla", 1)
    target_store = resolve_store_link(payload.get("store_id"), store_id)
    set_if_field(doc, "salla_store", target_store)
    set_if_field(doc, "salla_order_id", external_id)
    set_if_field(doc, "salla_sync_status", "Synced")
    set_if_field(doc, "salla_last_synced", now_datetime())

    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
    if raw:
        # best-effort mappings from typical Salla order payloads
        set_if_field(doc, "salla_reference_id", raw.get("reference_id") or payload.get("reference_id"))
        status_obj = raw.get("status") if isinstance(raw.get("status"), dict) else {}
        if status_obj:
            set_if_field(doc, "salla_status_id", status_obj.get("id"))
            set_if_field(doc, "salla_status_slug", status_obj.get("slug") or status_obj.get("type"))
            set_if_field(doc, "salla_status_name", status_obj.get("name"))
        payment_obj = raw.get("payment") if isinstance(raw.get("payment"), dict) else {}
        if payment_obj:
            set_if_field(doc, "salla_payment_status", payment_obj.get("status"))
            set_if_field(doc, "salla_payment_method", payment_obj.get("method"))
        shipping_obj = raw.get("shipping") if isinstance(raw.get("shipping"), dict) else {}
        if shipping_obj:
            set_if_field(doc, "salla_delivery_method", shipping_obj.get("method") or shipping_obj.get("type"))

    payload_items = payload.get("items") or []
    built_items = build_items(payload_items, result)
    doc.set("items", built_items)

    if not built_items:
        result.status = "failed"
        result.add_error("no_items", "No valid order items with SKU were found.")
        return result.as_dict()

    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    return finalize_result(result, doc, created).as_dict()


def _get_default_company() -> str | None:
    try:
        default_company = frappe.defaults.get_default("company")
        if default_company:
            return default_company
        company = frappe.db.get_value("Company", {}, "name")
        return company
    except Exception:
        return None
