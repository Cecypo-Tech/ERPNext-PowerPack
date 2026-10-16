# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_custom_fields():
	"""Idempotent. Wired to after_install and after_migrate."""
	create_custom_fields(
		{
			"Payment Entry": [
				{
					"fieldname": "cecypo_withholding",
					"label": "Withholding Details",
					"fieldtype": "Table",
					"options": "Payment Entry Withholding",
					"insert_after": "deductions",
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
				}
			]
		},
		ignore_validate=True,
		update=True,
	)
