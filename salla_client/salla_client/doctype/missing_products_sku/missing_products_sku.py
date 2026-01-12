import frappe
from frappe.model.document import Document
from frappe.utils import now


class MissingProductsSKU(Document):
    pass


def log_missing_sku(
    store_name: str,
    product_id: str,
    product_name: str,
    missing_type: str,
    remarks: str = "",
) -> None:
    """Compatibility helper copied from the old app (client-side only)."""
    try:
        doc = frappe.get_doc(
            {
                "doctype": "Missing Products SKU",
                "salla_store": store_name or "",
                "product_id": str(product_id or ""),
                "product_name": product_name or "",
                "missing_type": "Variant" if (missing_type or "").lower() == "variant" else "Product",
                "occurred_at": now(),
                "remarks": remarks or "",
            }
        )
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(
            title="Missing Products SKU",
            message=f"Failed to log missing SKU ({missing_type}) for product {product_id}: {e}",
        )

