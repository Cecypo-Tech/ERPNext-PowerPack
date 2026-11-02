# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""POS minimum selling price = the sale's price list.

On a till whose POS Profile ticks "Enforce minimum selling price to selected pricelist",
a line may not sell below the Item Price of the list it was priced from, unless a
supervisor authorised it with a PIN at the till (pos_supervisor_pin). A till sale on an
unticked till is not judged by PowerPack at all; desk documents keep the cost floor.
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

ENFORCE_FIELD = "powerpack_enforce_list_floor"
LINE_LIST_FIELD = "powerpack_line_price_list"
PIN_FIELD = "powerpack_pos_supervisor_pin"


def custom_field_definitions():
	line_field = {
		"fieldname": LINE_LIST_FIELD,
		"label": "Priced From List",
		"fieldtype": "Data",
		"insert_after": "price_list_rate",
		"hidden": 1,
		"read_only": 1,
		"print_hide": 1,
	}
	return {
		"POS Profile": [
			{
				"fieldname": ENFORCE_FIELD,
				"label": "Enforce minimum selling price to selected pricelist",
				"fieldtype": "Check",
				"insert_after": "allow_rate_change",
				"description": "Lines may not sell below the price list they were priced from unless a supervisor authorises it with their PIN.",
			}
		],
		"Sales Invoice Item": [dict(line_field)],
		"POS Invoice Item": [dict(line_field)],
		"Sales Order Item": [dict(line_field)],
		"User": [
			{
				"fieldname": PIN_FIELD,
				"label": "POS Supervisor PIN",
				"fieldtype": "Password",
				"insert_after": "new_password",
				"description": "4 to 6 digits. Lets you authorise a sale below the minimum selling price at a till.",
			}
		],
	}


def setup_custom_fields():
	"""Idempotent. Wired to after_install and after_migrate."""
	create_custom_fields(custom_field_definitions(), ignore_validate=True, update=True)
