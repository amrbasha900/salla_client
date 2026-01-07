import frappe

from salla_client.utils import get_default_item_group


def _get_default_uom() -> str:
	if frappe.db.exists("UOM", "Nos"):
		return "Nos"
	uom = frappe.db.get_value("UOM", {}, "name")
	return uom or "Nos"


def _upsert_item(payload, is_variant=False):
	sku = payload.get("sku")
	item_code = sku
	item_name = payload.get("name") or sku
	item_group = get_default_item_group()
	stock_uom = _get_default_uom()

	existing = frappe.db.exists("Item", item_code)
	if existing:
		doc = frappe.get_doc("Item", item_code)
	else:
		doc = frappe.get_doc({
			"doctype": "Item",
			"item_code": item_code,
		})

	doc.item_name = item_name
	doc.item_group = item_group
	doc.stock_uom = stock_uom
	doc.description = payload.get("description")
	if payload.get("status"):
		doc.disabled = 1 if payload.get("status") == "inactive" else 0

	if existing:
		doc.save(ignore_permissions=True)
		return doc.name, "updated"

	doc.insert(ignore_permissions=True)
	return doc.name, "created"


def upsert_product(payload):
	return _upsert_item(payload, is_variant=False)


def upsert_variant(payload):
	return _upsert_item(payload, is_variant=True)
