import frappe

from salla_client.utils import get_default_customer_group, get_default_territory


def upsert_customer(payload):
	external_id = payload.get("external_id")
	name = payload.get("name") or external_id
	if not name:
		frappe.throw("Customer name is required")

	customer_name = name
	existing = frappe.db.exists("Customer", {"customer_name": customer_name})
	if existing:
		doc = frappe.get_doc("Customer", existing)
	else:
		doc = frappe.get_doc({
			"doctype": "Customer",
			"customer_name": customer_name,
			"customer_group": get_default_customer_group(),
			"territory": get_default_territory(),
		})

	doc.customer_type = "Individual"
	if payload.get("email"):
		doc.email_id = payload.get("email")
	if payload.get("phone"):
		doc.mobile_no = payload.get("phone")

	if existing:
		doc.save(ignore_permissions=True)
		return doc.name, "updated"

	doc.insert(ignore_permissions=True)
	return doc.name, "created"
