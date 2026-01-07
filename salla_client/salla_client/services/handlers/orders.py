import frappe
from frappe.utils import nowdate

from salla_client.services.handlers.customers import upsert_customer


def _get_item_code(item_payload):
	sku = item_payload.get("sku")
	if sku and frappe.db.exists("Item", sku):
		return sku
	external_id = item_payload.get("external_id")
	if external_id and frappe.db.exists("Item", external_id):
		return external_id
	return None


def upsert_order(payload):
	customer_payload = payload.get("customer") or {}
	customer_name, _status = upsert_customer(customer_payload)

	items = []
	warnings = []
	for line in payload.get("items") or []:
		item_code = _get_item_code(line)
		if not item_code:
			warnings.append(f"Item not found for SKU {line.get('sku') or line.get('external_id')}")
			continue
		items.append({
			"item_code": item_code,
			"qty": line.get("quantity") or 1,
			"rate": line.get("price") or 0,
		})

	if not items:
		return None, "skipped", warnings

	sales_order = frappe.get_doc({
		"doctype": "Sales Order",
		"customer": customer_name,
		"transaction_date": nowdate(),
		"delivery_date": nowdate(),
		"currency": payload.get("currency"),
		"items": items,
	})
	sales_order.insert(ignore_permissions=True)
	return sales_order.name, "created", warnings
