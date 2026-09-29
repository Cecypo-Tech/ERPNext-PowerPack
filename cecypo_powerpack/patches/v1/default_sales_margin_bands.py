import frappe

DEFAULTS = {
	"sales_margin_low_below": 10,
	"sales_margin_medium_below": 20,
	"sales_margin_good_below": 30,
}


def execute():
	# A never-saved Percent reads back as 0, and bands of 0/0/0 would show every
	# positive margin as Excellent. Seed only fields absent from tabSingles, so a
	# value someone already chose stays.
	for field, value in DEFAULTS.items():
		row_exists = frappe.db.sql(
			"""select 1 from `tabSingles` where doctype='PowerPack Settings' and field=%s""", field
		)
		if not row_exists:
			frappe.db.set_single_value("PowerPack Settings", field, value)
