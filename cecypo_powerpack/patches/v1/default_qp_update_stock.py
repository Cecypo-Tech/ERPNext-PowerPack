import frappe


def execute():
	# Check fields read back as 0 once cast, even when never saved — query the
	# Singles table directly to tell "never set" apart from "explicitly off".
	row_exists = frappe.db.sql(
		"""select 1 from `tabSingles` where doctype='PowerPack Settings' and field='qp_update_stock'"""
	)
	if not row_exists:
		frappe.db.set_single_value("PowerPack Settings", "qp_update_stock", 1)
