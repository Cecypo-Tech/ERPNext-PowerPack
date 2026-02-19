import frappe


def execute():
	if not frappe.db.exists("Custom Field", "Quotation-custom_warehouse"):
		return  # Already renamed or not installed, skip

	# Rename the database column
	if frappe.db.has_column("Quotation", "custom_warehouse"):
		frappe.db.rename_column("Quotation", "custom_warehouse", "set_warehouse")

	# Update the Custom Field record's fieldname
	frappe.db.set_value(
		"Custom Field",
		"Quotation-custom_warehouse",
		"fieldname",
		"set_warehouse",
	)

	# Rename the Custom Field doc itself (name = "Quotation-set_warehouse")
	frappe.rename_doc(
		"Custom Field",
		"Quotation-custom_warehouse",
		"Quotation-set_warehouse",
		force=True,
	)

	frappe.db.commit()
