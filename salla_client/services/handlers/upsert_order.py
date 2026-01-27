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
from erpnext.controllers.accounts_controller import get_taxes_and_charges
from erpnext.selling.doctype.sales_order.sales_order import (
    make_delivery_note,
    make_sales_invoice,
)


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


def _extract_percent(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        if "percent" in value:
            return _extract_percent(value.get("percent"))
        if "amount" in value:
            return None
    try:
        return float(value)
    except Exception:
        try:
            return float(str(value).replace("%", "").strip())
        except Exception:
            return None


def _get_default_sales_taxes_template(company: str | None) -> str | None:
    if not company:
        return None
    return frappe.db.get_value(
        "Sales Taxes and Charges Template",
        {"company": company, "is_default": 1},
        "name",
    )


def resolve_customer(store_id: str, payload: dict[str, Any], result: ClientApplyResult) -> str | None:
    customer_payload = payload.get("customer") or {}
    raw_customer = {}
    raw_obj = payload.get("raw")
    if isinstance(raw_obj, dict):
        raw_customer = raw_obj.get("customer") or {}
        if not raw_customer and isinstance(raw_obj.get("order"), dict):
            raw_customer = (raw_obj.get("order") or {}).get("customer") or {}
        if not raw_customer and isinstance(raw_obj.get("order"), dict):
            raw_customer = (raw_obj.get("order") or {}).get("customer") or {}

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
    raw_obj = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
    if isinstance(raw_obj.get("order"), dict):
        raw_order_id = (raw_obj.get("order") or {}).get("id")
        if raw_order_id:
            external_id = raw_order_id
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
    event_type = payload.get("event_type") or (raw_payload.get("event") if isinstance(raw_payload, dict) else None)
    if isinstance(raw_payload, dict):
        raw_payload = json.dumps(raw_payload, ensure_ascii=False)
    set_if_field(doc, "salla_raw", raw_payload)
    # legacy Sales Order fields (old salla_integration schema)
    set_if_field(doc, "salla_is_from_salla", 1)
    set_if_field(doc, "salla_store", target_store)
    set_if_field(doc, "salla_order_reference_id", raw_obj.get("reference_id"))
    set_if_field(doc, "salla_order_id", external_id)
    set_if_field(doc, "salla_sync_status", "Synced")
    set_if_field(doc, "salla_last_synced", now_datetime())
    if event_type == "order.cancelled":
        set_if_field(doc, "salla_cancelled", 1)
    if event_type == "order.deleted":
        set_if_field(doc, "salla_deleted", 1)

    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
    raw_order = raw.get("order") if isinstance(raw.get("order"), dict) else {}
    if raw:
        # best-effort mappings from typical Salla order payloads
        set_if_field(doc, "salla_reference_id", raw.get("reference_id") or payload.get("reference_id"))
        status_obj = raw_order.get("status") if isinstance(raw_order.get("status"), dict) else {}
        if not status_obj:
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
    raw_order = raw_obj.get("order") if isinstance(raw_obj.get("order"), dict) else {}
    payload_items = (
        payload.get("items")
        or (raw_obj.get("items") if isinstance(raw_obj, dict) else [])
        or (raw_order.get("items") if isinstance(raw_order, dict) else [])
        or []
    )
    is_status_update = event_type == "order.status.updated"
    default_wh = _get_store_warehouse(target_store)
    built_items = (
        (doc.get("items") or [])
        if (is_status_update and not created)
        else build_items(payload_items, result, default_warehouse=default_wh)
    )

    # Append shipping cost and COD fee as separate lines if configured on store
    try:
        store_doc = frappe.get_doc("Salla Store", target_store) if target_store else None
    except Exception:
        store_doc = None

    amounts_obj = (raw_order.get("amounts") if isinstance(raw_order, dict) else {}) or {}
    if not amounts_obj and isinstance(raw_obj, dict):
        amounts_obj = raw_obj.get("amounts") or {}
    if not isinstance(amounts_obj, dict):
        amounts_obj = {}

    shipping_amount = _extract_amount((amounts_obj.get("shipping_cost") or {}).get("amount") or amounts_obj.get("shipping_cost"))
    cod_amount = _extract_amount((amounts_obj.get("cash_on_delivery") or {}).get("amount") or amounts_obj.get("cash_on_delivery"))

    if not (is_status_update and not created) and shipping_amount > 0 and store_doc and getattr(store_doc, "shipping_cost_item", None):
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

    if not (is_status_update and not created) and cod_amount > 0 and store_doc and getattr(store_doc, "cash_on_delivery_fee_item", None):
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

    # Apply discount from raw.amounts.discounts (sum discount values)
    raw_amounts = raw_obj.get("amounts") if isinstance(raw_obj, dict) else {}
    if not isinstance(raw_amounts, dict):
        raw_amounts = {}
    discounts = raw_amounts.get("discounts") or amounts_obj.get("discounts") or []
    discount_total = 0.0
    if isinstance(discounts, list):
        for entry in discounts:
            if isinstance(entry, dict) and "discount" in entry:
                discount_total += _extract_amount(entry.get("discount"))
    if not (is_status_update and not created) and discount_total > 0:
        if doc.meta.has_field("apply_discount_on"):
            doc.apply_discount_on = "Net Total"
        if doc.meta.has_field("discount_amount"):
            doc.discount_amount = discount_total
        if doc.meta.has_field("disable_rounded_total"):
            doc.disable_rounded_total = 1

    # Map taxes template from store tax table based on raw.order.amounts.tax.percent
    tax_percent = _extract_percent((amounts_obj.get("tax") or {}).get("percent"))
    if not (is_status_update and not created) and tax_percent is not None:
        chosen_template = None
        if store_doc:
            for row in store_doc.get("salla_store_tax") or []:
                row_percent = _extract_percent(getattr(row, "tax", None))
                if row_percent is None:
                    continue
                if abs(row_percent - tax_percent) < 0.0001:
                    tmpl = getattr(row, "sales_taxes_and_charges_template", None)
                    if tmpl:
                        tmpl_company = frappe.db.get_value(
                            "Sales Taxes and Charges Template", tmpl, "company"
                        )
                        if tmpl_company == doc.company:
                            chosen_template = tmpl
                            break
        if not chosen_template:
            chosen_template = _get_default_sales_taxes_template(doc.company)
        if chosen_template:
            doc.taxes_and_charges = chosen_template
            if not doc.get("taxes"):
                taxes = get_taxes_and_charges("Sales Taxes and Charges Template", chosen_template)
                if taxes:
                    doc.set("taxes", taxes)

    if not (is_status_update and not created):
        doc.set("items", built_items)

    # Ensure payment schedule doesn't violate posting/transaction date constraints
    try:
        if doc.meta.has_field("payment_terms_template"):
            doc.payment_terms_template = None
        if doc.meta.has_field("payment_schedule"):
            schedule = doc.get("payment_schedule") or []
            for row in schedule:
                try:
                    if not row.due_date or row.due_date < doc.transaction_date:
                        row.due_date = doc.transaction_date
                except Exception:
                    row.due_date = doc.transaction_date
            doc.set("payment_schedule", schedule)
    except Exception:
        pass

    if not built_items:
        result.status = "failed"
        result.add_error("no_items", "No valid order items with SKU were found.")
        return result.as_dict()

    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    status_doc = _resolve_status_doc(payload.get("store_id") or target_store or store_id, status_obj)
    if status_doc:
        _apply_status_actions(doc, status_doc)

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


def _resolve_status_doc(store_id: str | None, status_obj: dict[str, Any] | None) -> frappe.model.document.Document | None:
    if not store_id or not isinstance(status_obj, dict):
        return None
    status_id = status_obj.get("id")
    slug = status_obj.get("slug") or status_obj.get("type")
    name = status_obj.get("name")

    if status_id:
        docname = frappe.db.get_value(
            "Salla Order Status",
            {"store_id": str(store_id), "salla_status_id": str(status_id)},
            "name",
        )
        if docname:
            return frappe.get_doc("Salla Order Status", docname)
    if slug:
        docname = frappe.db.get_value(
            "Salla Order Status",
            {"store_id": str(store_id), "slug": str(slug)},
            "name",
        )
        if docname:
            return frappe.get_doc("Salla Order Status", docname)
    if name:
        docname = frappe.db.get_value(
            "Salla Order Status",
            {"store_id": str(store_id), "status_name": str(name)},
            "name",
        )
        if docname:
            return frappe.get_doc("Salla Order Status", docname)
    return None


def _apply_status_actions(sales_order, status_doc) -> None:
    if not status_doc:
        return

    if status_doc.submit_sales_order and sales_order.docstatus == 0:
        sales_order.submit()
        frappe.db.commit()
    if status_doc.cancel_sales_order and sales_order.docstatus == 1:
        sales_order.cancel()
        frappe.db.commit()
        return

    if status_doc.create_sales_invoice:
        existing_parents = {
            row["parent"]
            for row in frappe.db.get_all(
                "Sales Invoice Item",
                filters={"sales_order": sales_order.name},
                fields=["parent"],
            )
        }
        invoices = (
            [frappe.get_doc("Sales Invoice", name) for name in existing_parents]
            if existing_parents
            else []
        )
        if not invoices:
            inv = make_sales_invoice(sales_order.name, ignore_permissions=True)
            inv.flags.ignore_permissions = True
            inv.insert(ignore_permissions=True)
            invoices = [inv]
        for inv in invoices:
            if status_doc.cancel_sales_invoice and inv.docstatus == 1:
                inv.cancel()
                frappe.db.commit()
                continue
            if status_doc.submit_sales_invoice and inv.docstatus == 0:
                inv.submit()
                frappe.db.commit()

    if status_doc.create_delivery_note:
        existing_parents = {
            row["parent"]
            for row in frappe.db.get_all(
                "Delivery Note Item",
                filters={"against_sales_order": sales_order.name},
                fields=["parent"],
            )
        }
        notes = (
            [frappe.get_doc("Delivery Note", name) for name in existing_parents]
            if existing_parents
            else []
        )
        if not notes:
            if sales_order.docstatus == 0:
                sales_order.flags.ignore_permissions = True
                sales_order.submit()
                frappe.db.commit()
            prev_ignore = getattr(frappe.flags, "ignore_permissions", False)
            prev_user = frappe.session.user
            frappe.flags.ignore_permissions = True
            frappe.set_user("Administrator")
            try:
                dn = make_delivery_note(source_name=sales_order.name)
                if dn:
                    dn.flags.ignore_permissions = True
                    dn.insert(ignore_permissions=True)
                    notes = [dn]
            finally:
                frappe.flags.ignore_permissions = prev_ignore
                frappe.set_user(prev_user)
        for dn in notes:
            if status_doc.cancel_delivery_note and dn.docstatus == 1:
                dn.cancel()
                frappe.db.commit()
                continue
            if status_doc.submit_sales_delivery_note and dn.docstatus == 0:
                dn.submit()
                frappe.db.commit()
