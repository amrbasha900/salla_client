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
	},
});








