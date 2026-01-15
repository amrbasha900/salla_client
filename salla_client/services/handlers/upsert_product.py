from __future__ import annotations

from typing import Any

import frappe
import json
from frappe.utils import now_datetime

from .common import (
    ensure_item_group,
    finalize_result,
    get_existing_doc_name,
    resolve_store_link,
    set_external_id,
    set_if_field,
    sku_missing_result,
)
from salla_client.services.handlers.upsert_product_option import (
    ensure_item_attribute_for_option,
    _compose_attribute_name,
)
from .result import ClientApplyResult

INACTIVE_STATUSES = {"inactive", "hidden", "draft", "deleted"}


def _extract_amount(value: Any) -> Any:
    """If value is a dict with amount, return that; otherwise return value."""
    if isinstance(value, dict) and "amount" in value:
        return value.get("amount")
    return value


def _normalize_price(value: Any) -> float | None:
    value = _extract_amount(value)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _upsert_item_price(item_code: str, price_list: str, price: float) -> None:
    if not item_code or not price_list:
        return
    existing = frappe.db.exists(
        "Item Price",
        {"item_code": item_code, "price_list": price_list},
    )
    if existing:
        frappe.db.set_value(
            "Item Price",
            {"item_code": item_code, "price_list": price_list},
            "price_list_rate",
            price,
        )
        return
    item_price = frappe.get_doc(
        {
            "doctype": "Item Price",
            "item_code": item_code,
            "price_list": price_list,
            "price_list_rate": price,
        }
    )
    item_price.insert(ignore_permissions=True)


def _get_store_doc(*candidates: str | None) -> Any | None:
    for candidate in candidates:
        if not candidate:
            continue
        if frappe.db.exists("Salla Store", candidate):
            return frappe.get_doc("Salla Store", candidate)
        store_name = frappe.db.get_value("Salla Store", {"store_id": candidate}, "name")
        if store_name:
            return frappe.get_doc("Salla Store", store_name)
    return None


def _get_bundle_components(product_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract component products from a Salla group_products payload."""
    if isinstance(product_data.get("consisted_products"), list) and product_data.get("consisted_products"):
        return product_data.get("consisted_products") or []

    raw_payload = product_data.get("raw")
    if isinstance(raw_payload, str):
        try:
            raw_payload = json.loads(raw_payload)
        except Exception:
            raw_payload = None

    if isinstance(raw_payload, dict):
        raw_components = raw_payload.get("consisted_products")
        if isinstance(raw_components, list) and raw_components:
            return raw_components

    bundle_products: list[dict[str, Any]] = []
    bundle_data = product_data.get("bundle")
    if isinstance(bundle_data, dict):
        bundle_products = bundle_data.get("products") or []
    elif isinstance(raw_payload, dict) and isinstance(raw_payload.get("bundle"), dict):
        bundle_products = raw_payload.get("bundle").get("products") or []

    normalized: list[dict[str, Any]] = []
    for product in bundle_products:
        if not isinstance(product, dict):
            continue
        normalized.append(
            {
                "id": product.get("id"),
                "sku": product.get("sku"),
                "name": product.get("name"),
                "price": product.get("price"),
                "type": product.get("type") or "product",
                "quantity": product.get("qty") or product.get("quantity") or product.get("quantity_in_group"),
                "quantity_in_group": product.get("quantity_in_group") or product.get("qty") or 1,
            }
        )
    return normalized


def _ensure_bundle_components(store_id: str, product_data: dict[str, Any]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    for component in _get_bundle_components(product_data):
        if str(component.get("type") or "").strip().lower() == "group_products":
            frappe.log_error(
                "Salla Bundle Component Sync",
                f"Nested bundle detected for product {product_data.get('id')} -> {component.get('id')}",
            )
            continue

        sku = component.get("sku") or component.get("item_code")
        if not sku:
            continue

        item_code: str | None = None
        if frappe.db.exists("Item", {"item_code": sku}):
            item_code = sku
        elif frappe.db.exists("Item", {"salla_sku": sku}):
            item_code = frappe.db.get_value("Item", {"salla_sku": sku}, "name")

        if not item_code:
            try:
                upsert_product(store_id, component, allow_bundle=False)
            except Exception:
                frappe.log_error(
                    "Salla Bundle Component Sync",
                    f"Failed to sync component {component.get('id')} (sku: {sku})",
                )
            if frappe.db.exists("Item", {"item_code": sku}):
                item_code = sku
            elif frappe.db.exists("Item", {"salla_sku": sku}):
                item_code = frappe.db.get_value("Item", {"salla_sku": sku}, "name")

        if not item_code:
            frappe.log_error(
                "Salla Bundle Component Sync",
                f"Component item missing for Salla product {component.get('id')} (sku: {sku})",
            )
            continue

        qty = component.get("quantity_in_group") or component.get("qty") or component.get("quantity") or 1
        try:
            qty = float(qty or 1)
        except Exception:
            qty = 1

        components.append({"item_code": item_code, "qty": qty})
    return components


def _create_or_update_product_bundle(parent_item_code: str | None, components: list[dict[str, Any]]) -> str | None:
    if not parent_item_code or not components:
        return None
    if not frappe.db.exists("DocType", "Product Bundle"):
        return None

    existing_bundle = frappe.db.exists("Product Bundle", {"new_item_code": parent_item_code})
    if existing_bundle:
        bundle_doc = frappe.get_doc("Product Bundle", existing_bundle)
        bundle_doc.items = []
    else:
        bundle_doc = frappe.get_doc({"doctype": "Product Bundle", "new_item_code": parent_item_code, "items": []})

    for component in components:
        item_code = component.get("item_code")
        if not item_code:
            continue
        qty = component.get("qty") or 1
        bundle_doc.append("items", {"item_code": item_code, "qty": qty})

    bundle_doc.save(ignore_permissions=True)
    return bundle_doc.name


def upsert_product(store_id: str, payload: dict[str, Any], allow_bundle: bool = True) -> dict[str, Any]:
    external_id = payload.get("external_id")
    sku = payload.get("sku")
    # Old app allowed products without SKU by falling back to Salla ID; mirror that to allow variants flow.
    if not sku:
        sku = external_id or payload.get("product_id") or f"SALLA-{external_id}" if external_id else None
    if not sku:
        return sku_missing_result(store_id, "product", external_id, sku=sku).as_dict()

    existing_name = get_existing_doc_name("Item", external_id)
    created = existing_name is None
    if created:
        doc = frappe.get_doc({"doctype": "Item"})
    else:
        doc = frappe.get_doc("Item", existing_name)

    doc.item_code = sku
    doc.item_name = payload.get("name") or sku
    doc.description = payload.get("description") or doc.get("description")
    doc.item_group = ensure_item_group(payload)
    doc.disabled = 1 if str(payload.get("status")).lower() in INACTIVE_STATUSES else 0
    doc.stock_uom = payload.get("uom") or doc.get("stock_uom") or "Nos"
    raw_type = ""
    raw_payload = payload.get("raw")
    if isinstance(raw_payload, str):
        try:
            raw_payload = json.loads(raw_payload)
        except Exception:
            raw_payload = None
    if isinstance(raw_payload, dict):
        raw_type = raw_payload.get("type") or ""
    product_type = str(payload.get("type") or raw_type or "").strip().lower()
    is_group_product = product_type == "group_products"
    is_service = product_type == "service"
    frappe.log_error(title=f"is_group_product: {is_group_product}, is_service: {is_service}"+"Salla Client: upsert_product", message=str({"payload": payload}))
    doc.is_stock_item = 0 if is_group_product or is_service or payload.get("is_stock_item") is False else 1
    # If options/variants exist, mark as template and attach Item Attribute rows (old flow behavior).
    target_store = resolve_store_link(payload.get("store_id"), store_id)
    options = payload.get("options") or []
    has_options = bool(options)
    has_variants = bool(payload.get("variants"))
    frappe.log_error(title=f"has_options: {has_options}, has_variants: {has_variants}"+"Salla Client: upsert_product", message=str({"options": options}))
    if hasattr(doc, "has_variants") and (has_options or has_variants):

        doc.has_variants = 1
        if doc.meta.has_field("variant_based_on") and not doc.get("variant_based_on"):
            doc.variant_based_on = "Item Attribute"
        # Build attribute rows from options to let variants attach later
        new_attrs: list[dict[str, str]] = []
        seen = set()
        for opt in options:
            attr_name, _ = ensure_item_attribute_for_option(
                target_store or store_id,
                opt,
                product_sku=sku,
            )
            if not attr_name:
                attr_name = _compose_attribute_name(
                    opt.get("name") or opt.get("option_name"),
                    opt.get("id") or opt.get("option_id"),
                    sku,
                )
            if not attr_name or attr_name in seen:
                continue
            seen.add(attr_name)
            new_attrs.append({"attribute": attr_name})
        if new_attrs:
            existing_attrs = doc.get("attributes") or []
            existing_names = {row.get("attribute") for row in existing_attrs if row.get("attribute")}
            merged = list(existing_attrs)
            for attr in new_attrs:
                if attr["attribute"] not in existing_names:
                    merged.append(attr)
            doc.set("attributes", merged)
    set_external_id(doc, external_id)
    # legacy fields (old salla_integration schema)
    set_if_field(doc, "salla_is_from_salla", 1)
    set_if_field(doc, "salla_store", target_store)
    set_if_field(doc, "salla_product_id", external_id)
    set_if_field(doc, "salla_sku", sku)
    set_if_field(doc, "salla_last_synced", now_datetime())
    # For template items (has_variants), skip setting standard_rate to avoid Item Price creation on template
    if not getattr(doc, "has_variants", 0):
        set_if_field(doc, "standard_rate", _extract_amount(payload.get("price")))
    set_if_field(doc, "salla_url", payload.get("url"))
    set_if_field(doc, "salla_brand_id", payload.get("brand_id"))
    # Normalize lists to JSON strings for Code/Data fields
    category_ids = payload.get("category_ids")
    if isinstance(category_ids, list):
        category_ids = json.dumps(category_ids, ensure_ascii=False)
    set_if_field(doc, "salla_category_ids", category_ids)

    images = payload.get("images")
    if isinstance(images, list):
        images = json.dumps(images, ensure_ascii=False)
    set_if_field(doc, "salla_images", images)
    set_if_field(doc, "default_warehouse", payload.get("warehouse"))
    set_if_field(doc, "barcode", payload.get("barcode"))

    if created:
        _prev_in_patch = getattr(frappe.flags, "in_patch", False)
        _prev_ignore_perms = getattr(frappe.flags, "ignore_permissions", False)
        prev_user = frappe.session.user if hasattr(frappe, "session") else None
        try:
            frappe.flags.in_patch = True  # bypass Item after_insert price permission
            frappe.flags.ignore_permissions = True
            doc.flags.ignore_after_insert = True  # skip default price creation that needs perms
            # elevate to Administrator to allow Item Price insert inside Item.after_insert
            if prev_user and prev_user != "Administrator":
                frappe.set_user("Administrator")
            doc.insert(ignore_permissions=True)
        finally:
            if prev_user and prev_user != "Administrator":
                frappe.set_user(prev_user)
            frappe.flags.in_patch = _prev_in_patch
            frappe.flags.ignore_permissions = _prev_ignore_perms
    else:
        doc.save(ignore_permissions=True)

    store_doc = _get_store_doc(target_store, payload.get("store_id"), store_id)
    if store_doc:
        raw_payload = payload.get("raw")
        if isinstance(raw_payload, str):
            try:
                raw_payload = json.loads(raw_payload)
            except Exception:
                raw_payload = None
        if not isinstance(raw_payload, dict):
            raw_payload = {}

        sale_price = payload.get("sale_price")
        if sale_price in (None, ""):
            sale_price = raw_payload.get("sale_price")
        price_fallback = payload.get("price")
        if price_fallback in (None, ""):
            price_fallback = raw_payload.get("price")
        if sale_price in (None, ""):
            sale_price = price_fallback
        elif _extract_amount(sale_price) in (None, "", 0) and _extract_amount(price_fallback) not in (None, ""):
            sale_price = price_fallback
        cost_price = payload.get("cost_price")
        if cost_price in (None, ""):
            cost_price = raw_payload.get("cost_price")

        selling_price_list = store_doc.get("selling_price_list")
        buying_price_list = store_doc.get("buying_price_list")
        selling_rate = _normalize_price(sale_price)
        buying_rate = _normalize_price(cost_price)
        item_code = doc.item_code
        if selling_price_list and selling_rate is not None:
            try:
                _upsert_item_price(item_code, selling_price_list, selling_rate)
            except Exception:
                frappe.log_error(
                    "Salla Item Price",
                    f"Failed to upsert selling price for {item_code} ({selling_price_list}): {selling_rate}",
                )
        elif sale_price is not None and not selling_price_list:
            frappe.log_error(
                "Salla Item Price",
                f"Selling price list missing for store {store_doc.name}; item {item_code} sale_price={sale_price}",
            )
        if buying_price_list and buying_rate is not None:
            try:
                _upsert_item_price(item_code, buying_price_list, buying_rate)
            except Exception:
                frappe.log_error(
                    "Salla Item Price",
                    f"Failed to upsert buying price for {item_code} ({buying_price_list}): {buying_rate}",
                )
        elif cost_price is not None and not buying_price_list:
            frappe.log_error(
                "Salla Item Price",
                f"Buying price list missing for store {store_doc.name}; item {item_code} cost_price={cost_price}",
            )
    else:
        frappe.log_error(
            "Salla Item Price",
            f"Store not found for item {doc.item_code}. target_store={target_store} payload_store_id={payload.get('store_id')} store_id={store_id}",
        )

    if allow_bundle and is_group_product:
        components = _ensure_bundle_components(target_store or store_id, payload)
        _create_or_update_product_bundle(doc.name, components)

    result = ClientApplyResult(status="applied", erp_doctype="Item")
    return finalize_result(result, doc, created).as_dict()
