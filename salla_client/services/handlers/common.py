from __future__ import annotations

from typing import Any

import frappe

from .result import ClientApplyResult

EXTERNAL_ID_FIELD = "salla_external_id"
STORE_LINK_DOCTYPE = "Salla Store"


def get_existing_doc_name(doctype: str, external_id: str | None) -> str | None:
    if not external_id:
        return None
    # Avoid hard failure if custom field isn't installed yet.
    try:
        meta = frappe.get_meta(doctype)
        if not meta.has_field(EXTERNAL_ID_FIELD):
            return None
    except Exception:
        return None
    return frappe.db.get_value(doctype, {EXTERNAL_ID_FIELD: external_id})


def ensure_item_group(payload: dict[str, Any]) -> str:
    return payload.get("item_group") or "All Item Groups"


def ensure_customer_group(payload: dict[str, Any]) -> str:
    return payload.get("group_id") or "All Customer Groups"


def log_sku_skip(
    store_id: str, entity_type: str, external_id: str | None, reason: str, sku: str | None = None
) -> str:
    store_value = store_id or "unknown"
    external_value = external_id or "unknown"
    doc = frappe.get_doc(
        {
            "doctype": "SKU Skip Log",
            "store_id": store_value,
            "entity_type": entity_type,
            "external_id": external_value,
            "sku": sku,
            "reason": reason,
        }
    )
    doc.insert(ignore_permissions=True)
    # Back-compat: also log to the old "Missing Products SKU" DocType if installed.
    try:
        if frappe.db.exists("DocType", "Missing Products SKU"):
            from salla_client.salla_client.doctype.missing_products_sku.missing_products_sku import (
                log_missing_sku,
            )

            log_missing_sku(
                store_name=store_id,
                product_id=str(external_value),
                product_name="",
                missing_type="Variant" if entity_type == "variant" else "Product",
                remarks=reason,
            )
    except Exception:
        pass
    return doc.name


def sku_missing_result(
    store_id: str, entity_type: str, external_id: str | None, sku: str | None = None
) -> ClientApplyResult:
    log_sku_skip(
        store_id=store_id,
        entity_type=entity_type,
        external_id=external_id,
        reason="missing_sku",
        sku=sku,
    )
    result = ClientApplyResult(status="skipped", message="Missing SKU; entry skipped.")
    result.add_warning(
        "sku_missing",
        "SKU is mandatory and missing; entity skipped.",
        store_id=store_id,
        entity_type=entity_type,
        external_id=external_id,
        sku=sku,
    )
    return result


def set_external_id(doc: Any, external_id: str | None) -> None:
    if external_id and doc.meta.has_field(EXTERNAL_ID_FIELD):
        doc.set(EXTERNAL_ID_FIELD, external_id)


def resolve_store_link(store_id_from_payload: str | None, fallback_store_id: str | None) -> str | None:
    """
    Return a store_id that actually exists in `Salla Store`.
    Prefer the `store_id` from the payload (numeric Salla store id), else fallback.
    If no matching Salla Store doc exists, return None so we don't fail link validation.
    """
    candidates = [store_id_from_payload, fallback_store_id]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            # First try store_id field (numeric Salla ID)
            if frappe.db.exists(STORE_LINK_DOCTYPE, {"store_id": candidate}):
                return candidate
            # Then try by document name (in case name already equals store_id)
            if frappe.db.exists(STORE_LINK_DOCTYPE, candidate):
                return candidate
        except Exception:
            continue
    return None


def set_if_field(doc: Any, fieldname: str, value: Any) -> None:
    if value is None:
        return
    if doc.meta.has_field(fieldname):
        doc.set(fieldname, value)


def set_store_if_exists(doc: Any, store_id: str | None) -> None:
    """Set salla_store link only if the target Salla Store exists to avoid LinkValidationError."""
    if not store_id:
        return
    if not doc.meta.has_field("salla_store"):
        return
    if frappe.db.exists("Salla Store", store_id):
        doc.set("salla_store", store_id)


def finalize_result(result: ClientApplyResult, doc: Any, created: bool) -> ClientApplyResult:
    result.erp_doc = doc.name
    result.message = "Created" if created else "Updated"
    return result
