from __future__ import annotations

from typing import Any

import frappe

from .result import ClientApplyResult

EXTERNAL_ID_FIELD = "salla_external_id"


def get_existing_doc_name(doctype: str, external_id: str | None) -> str | None:
    if not external_id:
        return None
    return frappe.db.get_value(doctype, {EXTERNAL_ID_FIELD: external_id})


def ensure_item_group(payload: dict[str, Any]) -> str:
    return payload.get("item_group") or "All Item Groups"


def ensure_customer_group(payload: dict[str, Any]) -> str:
    return payload.get("group_id") or "All Customer Groups"


def log_sku_skip(store_id: str, entity_type: str, external_id: str | None, reason: str) -> str:
    doc = frappe.get_doc(
        {
            "doctype": "SKU Skip Log",
            "store_id": store_id,
            "entity_type": entity_type,
            "external_id": external_id,
            "reason": reason,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc.name


def sku_missing_result(store_id: str, entity_type: str, external_id: str | None) -> ClientApplyResult:
    log_sku_skip(
        store_id=store_id,
        entity_type=entity_type,
        external_id=external_id,
        reason="Missing SKU",
    )
    result = ClientApplyResult(status="skipped", message="Missing SKU; entry skipped.")
    result.add_warning(
        "sku_missing",
        "SKU is mandatory and missing; entity skipped.",
        store_id=store_id,
        entity_type=entity_type,
        external_id=external_id,
    )
    return result


def set_external_id(doc: Any, external_id: str | None) -> None:
    if external_id:
        doc.set(EXTERNAL_ID_FIELD, external_id)


def set_if_field(doc: Any, fieldname: str, value: Any) -> None:
    if value is None:
        return
    if doc.meta.has_field(fieldname):
        doc.set(fieldname, value)


def finalize_result(result: ClientApplyResult, doc: Any, created: bool) -> ClientApplyResult:
    result.erp_doc = doc.name
    result.message = "Created" if created else "Updated"
    return result
