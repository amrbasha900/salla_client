from __future__ import annotations

from typing import Any
import json

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


def _resolve_store_company(store_id: str | None, fallback: str | None = None) -> str | None:
    """Pick company from linked Salla Store if available, else fallback/default."""
    if store_id:
        try:
            store_doc = frappe.get_doc("Salla Store", store_id)
            if getattr(store_doc, "company", None):
                return store_doc.company
        except Exception:
            pass
    return fallback or _get_default_company()


def _get_company_currency(company: str | None) -> str | None:
    """Return company currency; fallback to system default currency."""
    if not company:
        return frappe.db.get_default("currency")
    try:
        currency = frappe.db.get_value("Company", company, "default_currency")
        return currency or frappe.db.get_default("currency")
    except Exception:
        return frappe.db.get_default("currency")


def _get_store_warehouse(store_id: str | None) -> str | None:
    """Return default warehouse configured on Salla Store, if any."""
    if not store_id:
        return None
    try:
        return frappe.db.get_value("Salla Store", store_id, "warehouse")
    except Exception:
        return None


def _extract_amount(value: Any) -> float:
    """Safely pull numeric amount from nested structures."""
    if value in (None, ""):
        return 0.0
    if isinstance(value, dict):
        if "amount" in value:
            return _extract_amount(value.get("amount"))
        if "value" in value:
            return _extract_amount(value.get("value"))
        return 0.0
    try:
        return float(value) or 0.0
    except Exception:
        return 0.0


def resolve_customer(store_id: str, payload: dict[str, Any], result: ClientApplyResult) -> str | None:
    customer_payload = payload.get("customer") or {}
    raw_customer = {}
    raw_obj = payload.get("raw")
    if isinstance(raw_obj, dict):
        raw_customer = raw_obj.get("customer") or {}

    if not customer_payload and isinstance(raw_customer, dict):
        customer_payload = dict(raw_customer)  # copy

    # Normalize identifiers and contact info from raw if missing
    if isinstance(raw_customer, dict):
        for k_src, k_dst in [("id", "external_id"), ("name", "name"), ("mobile", "phone"), ("email", "email")]:
            if not customer_payload.get(k_dst) and raw_customer.get(k_src):
                customer_payload[k_dst] = raw_customer.get(k_src)

    external_id = customer_payload.get("external_id") or customer_payload.get("id")
    if not external_id:
        external_id = f"guest-{store_id}-{payload.get('external_id') or frappe.generate_hash(length=8)}"
        customer_payload["external_id"] = external_id

    if not customer_payload.get("name"):
        customer_payload["name"] = "Salla Customer"

    if not customer_payload.get("phone") and customer_payload.get("mobile"):
        customer_payload["phone"] = customer_payload.get("mobile")

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


def build_items(payload_items: list[dict[str, Any]], result: ClientApplyResult, default_warehouse: str | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in payload_items:
        sku = entry.get("sku") or entry.get("item_code")
        if not sku:
            result.add_warning("missing_sku", "Order item missing SKU; skipped.", item=entry)
            continue

        item_code: str | None = None
        # Prefer direct item_code match
        if frappe.db.exists("Item", {"item_code": sku}):
            item_code = sku
        # Then match on salla_sku (old app’s unique key)
        if not item_code and frappe.db.exists("Item", {"salla_sku": sku}):
            item_code = frappe.db.get_value("Item", {"salla_sku": sku}, "name")

        if not item_code:
            result.add_warning(
                "missing_item",
                "Item not found in ERP for SKU; skipped.",
                item_code=sku,
            )
            continue
        # Prefer explicit price, else fall back to amounts block
        rate = entry.get("price") or entry.get("rate")
        if rate in (None, ""):
            rate = _extract_amount(((entry.get("amounts") or {}).get("price_without_tax") or {}).get("amount"))
        if rate in (None, ""):
            rate = _extract_amount(((entry.get("amounts") or {}).get("total") or {}).get("amount"))
        items.append(
            {
                "item_code": item_code,
                "item_name": entry.get("name") or item_code,
                "qty": entry.get("quantity") or entry.get("qty") or 1,
                "rate": rate or 0,
                "warehouse": default_warehouse,
                # legacy per-line metadata (if custom fields exist)
                "salla_is_from_salla": 1,
                "salla_product_id": entry.get("product_id") or entry.get("external_id"),
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
    doc.delivery_date = getattr(frappe.utils, "nowdate")()
    target_store = resolve_store_link(payload.get("store_id"), store_id)
    doc.company = payload.get("company") or _resolve_store_company(target_store, None)
    if not doc.company:
        result.status = "failed"
        result.add_error("missing_company", "No company configured for order creation.")
        return result.as_dict()
    doc.transaction_date = getdate(payload.get("created_at")) if payload.get("created_at") else nowdate()
    # Always align currency to company currency to avoid exchange rate issues
    doc.currency = _get_company_currency(doc.company)

    set_external_id(doc, external_id)
    status_val = payload.get("status")
    if isinstance(status_val, dict):
        status_val = status_val.get("name") or status_val.get("slug") or status_val.get("status") or json.dumps(
            status_val, ensure_ascii=False
        )
    set_if_field(doc, "salla_status", status_val)

    raw_payload = payload.get("raw")
    if isinstance(raw_payload, dict):
        raw_payload = json.dumps(raw_payload, ensure_ascii=False)
    set_if_field(doc, "salla_raw", raw_payload)
    # legacy Sales Order fields (old salla_integration schema)
    set_if_field(doc, "salla_is_from_salla", 1)
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

    raw_obj = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
    payload_items = (
        payload.get("items")
        or (raw_obj.get("items") if isinstance(raw_obj, dict) else [])
        or ((raw_obj.get("order") or {}).get("items") if isinstance(raw_obj, dict) else [])
        or []
    )
    default_wh = _get_store_warehouse(target_store)
    built_items = build_items(payload_items, result, default_warehouse=default_wh)

    # Append shipping cost and COD fee as separate lines if configured on store
    try:
        store_doc = frappe.get_doc("Salla Store", target_store) if target_store else None
    except Exception:
        store_doc = None

    amounts_obj = (raw_obj.get("order") or {}).get("amounts") if isinstance(raw_obj, dict) else {}
    if not isinstance(amounts_obj, dict):
        amounts_obj = {}

    shipping_amount = _extract_amount((amounts_obj.get("shipping_cost") or {}).get("amount") or amounts_obj.get("shipping_cost"))
    cod_amount = _extract_amount((amounts_obj.get("cash_on_delivery") or {}).get("amount") or amounts_obj.get("cash_on_delivery"))

    if shipping_amount > 0 and store_doc and getattr(store_doc, "shipping_cost_item", None):
        built_items.append(
            {
                "item_code": store_doc.shipping_cost_item,
                "item_name": "Shipping Cost",
                "qty": 1,
                "rate": shipping_amount,
                "warehouse": default_wh,
                "salla_is_from_salla": 1,
            }
        )

    if cod_amount > 0 and store_doc and getattr(store_doc, "cash_on_delivery_fee_item", None):
        built_items.append(
            {
                "item_code": store_doc.cash_on_delivery_fee_item,
                "item_name": "Cash on Delivery Fee",
                "qty": 1,
                "rate": cod_amount,
                "warehouse": default_wh,
                "salla_is_from_salla": 1,
            }
        )

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
