from __future__ import annotations

from typing import Any, Dict, List

import frappe
from frappe.model.rename_doc import rename_doc

from .common import finalize_result
from .result import ClientApplyResult


def _build_taxes(taxes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for row in taxes or []:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "tax_id": row.get("tax_id"),
                "status": row.get("status") or "active",
                "tax": row.get("tax"),
                "country": row.get("country"),
                "sales_taxes_and_charges_template": row.get("sales_taxes_and_charges_template"),
            }
        )
    return out


def _build_branches(branches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for row in branches or []:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "salla_id": row.get("branch_id") or row.get("id"),
                "branch_name": row.get("branch_name") or row.get("name"),
                "type": row.get("type"),
                "status": row.get("status"),
                "is_default": 1 if row.get("is_default") else 0,
                "is_cod_available": 1 if row.get("is_cod_available") else 0,
                "cod_cost": row.get("cod_cost"),
                "preparation_time": row.get("preparation_time"),
                "country": row.get("country"),
                "city": row.get("city"),
                "postal_code": row.get("postal_code"),
                "address_description": row.get("address_description"),
                "street": row.get("street"),
                "local": row.get("local"),
                "location_lat": row.get("location_lat"),
                "location_lng": row.get("location_lng"),
                "phone": row.get("phone"),
                "whatsapp": row.get("whatsapp"),
                "telephone": row.get("telephone"),
                "erp_branch": row.get("erp_branch"),
                "erp_warehouse": row.get("erp_warehouse"),
            }
        )
    return out


def upsert_store(store_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    store_external_id = payload.get("store_id") or store_id
    if not store_external_id:
        result = ClientApplyResult(status="failed")
        result.add_error("missing_store_id", "store_id is required.")
        return result.as_dict()

    # Recovery: older Manager builds accidentally sent a JSON string payload, causing the handler
    # to create a Salla Store using `store_id` = store_account id (e.g. SM-STORE-00002).
    # If we now have a real numeric store_id, rename the wrong doc to the correct store_id.
    if store_id and store_external_id and store_id != store_external_id:
        try:
            if str(store_id).startswith("SM-STORE-") and str(store_external_id).isdigit():
                wrong_name = frappe.db.get_value("Salla Store", {"store_id": store_id}, "name")
                existing_correct = frappe.db.get_value("Salla Store", {"store_id": store_external_id}, "name")
                if wrong_name and not existing_correct:
                    rename_doc("Salla Store", wrong_name, store_external_id, force=True)
        except Exception:
            # Best-effort; continue with normal upsert flow.
            pass

    existing = frappe.db.get_value("Salla Store", {"store_id": store_external_id}, "name")
    created = existing is None
    if created:
        doc = frappe.get_doc({"doctype": "Salla Store"})
    else:
        doc = frappe.get_doc("Salla Store", existing)

    doc.store_id = store_external_id
    # Only overwrite fields when the payload actually provides a value.
    if payload.get("store_name"):
        doc.store_name = payload.get("store_name")
    if payload.get("store_domain") is not None:
        doc.store_domain = payload.get("store_domain")
    if payload.get("status") is not None:
        doc.status = payload.get("status")
    if payload.get("merchant_id") is not None:
        doc.merchant_id = payload.get("merchant_id")
    if "is_authorized" in payload:
        doc.is_authorized = 1 if payload.get("is_authorized") else 0
    if payload.get("plan") is not None:
        doc.plan = payload.get("plan")
    if payload.get("company") is not None:
        doc.company = payload.get("company")
    if payload.get("warehouse") is not None:
        doc.warehouse = payload.get("warehouse")
    if payload.get("price_list") is not None:
        doc.price_list = payload.get("price_list")
    if payload.get("default_customer_group") is not None:
        doc.default_customer_group = payload.get("default_customer_group")
    if payload.get("default_territory") is not None:
        doc.default_territory = payload.get("default_territory")
    if payload.get("shipping_cost_item") is not None:
        doc.shipping_cost_item = payload.get("shipping_cost_item")
    if payload.get("cash_on_delivery_fee_item") is not None:
        doc.cash_on_delivery_fee_item = payload.get("cash_on_delivery_fee_item")

    doc.set("salla_store_tax", _build_taxes(payload.get("taxes") or []))
    doc.set("warehouses_and_branches", _build_branches(payload.get("warehouses_and_branches") or []))

    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    result = ClientApplyResult(status="applied", erp_doctype="Salla Store")
    return finalize_result(result, doc, created).as_dict()

