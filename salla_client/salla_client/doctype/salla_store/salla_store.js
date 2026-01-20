frappe.ui.form.on("Salla Store", {
	refresh(frm) {
		frm.add_custom_button(
			__("Request Pull from Manager"),
			() => {
				frappe.prompt(
					[
						{
							fieldname: "force_new",
							label: __("Force new commands (bypass idempotency)"),
							fieldtype: "Check",
							default: 0,
						},
						{
							fieldname: "since",
							label: __("Since (optional)"),
							fieldtype: "Datetime",
						},
						{
							fieldname: "limit",
							label: __("Limit"),
							fieldtype: "Int",
							default: 50,
						},
					],
					(values) => {
						frappe.call({
							method: "salla_client.api.request_pull_from_manager",
							args: {
								payload: {
									store_id: frm.doc.store_id || frm.doc.name,
									force_new: values.force_new ? 1 : 0,
									entity_types: [
										"products",
										"variants",
										"product_options",
										"categories",
										"order_statuses",
										"customer_groups",
										"brands",
										"customers",
										"orders",
									],
									since: values.since || null,
									limit: values.limit || 50,
								},
							},
							callback: (r) => {
								if (r.message && r.message.ok) {
									frappe.show_alert({ message: __("Pull requested via Manager"), indicator: "green" });
								} else {
									frappe.msgprint({
										title: __("Pull request failed"),
										indicator: "red",
										message: `<pre>${JSON.stringify(r.message || {}, null, 2)}</pre>`,
									});
								}
							},
						});
					},
					__("Request Pull"),
					__("Submit")
				);
			},
			__("Actions")
		);
		frm.add_custom_button(
			__("Sync Quantity Audit"),
			() => {
				frappe.prompt(
					[
						{
							fieldname: "force_new",
							label: __("Force new commands (bypass idempotency)"),
							fieldtype: "Check",
							default: 0,
						},
						{
							fieldname: "limit",
							label: __("Limit"),
							fieldtype: "Int",
							default: 50,
						},
					],
					(values) => {
						frappe.call({
							method: "salla_client.api.request_pull_from_manager",
							args: {
								payload: {
									store_id: frm.doc.store_id || frm.doc.name,
									force_new: values.force_new ? 1 : 0,
									entity_types: ["product_quantity_transactions"],
									limit: values.limit || 50,
								},
							},
							callback: (r) => {
								if (r.message && r.message.ok) {
									frappe.show_alert({
										message: __("Quantity audit sync requested via Manager"),
										indicator: "green",
									});
								} else {
									frappe.msgprint({
										title: __("Quantity audit sync failed"),
										indicator: "red",
										message: `<pre>${JSON.stringify(r.message || {}, null, 2)}</pre>`,
									});
								}
							},
						});
					},
					__("Sync Quantity Audit"),
					__("Submit")
				);
			},
			__("Actions")
		);
		frm.add_custom_button(
			__("Sync Product Quantities"),
			() => {
				frappe.prompt(
					[
						{
							fieldname: "force_new",
							label: __("Force new commands (bypass idempotency)"),
							fieldtype: "Check",
							default: 0,
						},
						{
							fieldname: "limit",
							label: __("Limit"),
							fieldtype: "Int",
							default: 50,
						},
						{
							fieldname: "branch_id",
							label: __("Branch ID (optional)"),
							fieldtype: "Data",
						},
					],
					(values) => {
						frappe.call({
							method: "salla_client.api.request_pull_from_manager",
							args: {
								payload: {
									store_id: frm.doc.store_id || frm.doc.name,
									force_new: values.force_new ? 1 : 0,
									entity_types: ["product_quantities"],
									limit: values.limit || 50,
									branch_id: values.branch_id || null,
								},
							},
							callback: (r) => {
								if (r.message && r.message.ok) {
									frappe.show_alert({
										message: __("Product quantities sync requested via Manager"),
										indicator: "green",
									});
								} else {
									frappe.msgprint({
										title: __("Product quantities sync failed"),
										indicator: "red",
										message: `<pre>${JSON.stringify(r.message || {}, null, 2)}</pre>`,
									});
								}
							},
						});
					},
					__("Sync Product Quantities"),
					__("Submit")
				);
			},
			__("Actions")
		);
	},
});








