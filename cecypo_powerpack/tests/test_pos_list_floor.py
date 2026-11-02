# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""POS minimum selling price = the sale's price list (ticked tills only).

Spec: docs/superpowers/specs/2026-11-02-pos-price-list-floor-design.md
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestPosListFloorFields(FrappeTestCase):
	def test_fields_exist_after_setup(self):
		from cecypo_powerpack.pos_list_floor import ENFORCE_FIELD, LINE_LIST_FIELD, PIN_FIELD, setup_custom_fields

		setup_custom_fields()
		field = frappe.get_meta("POS Profile").get_field(ENFORCE_FIELD)
		self.assertEqual(field.label, "Enforce minimum selling price to selected pricelist")
		self.assertEqual(field.fieldtype, "Check")
		for doctype in ("Sales Invoice Item", "POS Invoice Item", "Sales Order Item"):
			self.assertTrue(frappe.get_meta(doctype).has_field(LINE_LIST_FIELD), doctype)
		self.assertEqual(frappe.get_meta("User").get_field(PIN_FIELD).fieldtype, "Password")

	def test_audit_fields_filterable_on_sales_invoice(self):
		meta = frappe.get_meta("Sales Invoice")
		self.assertTrue(meta.get_field("powerpack_price_approved_by").in_standard_filter)
		breach = meta.get_field("powerpack_price_breach")
		self.assertTrue(breach.in_standard_filter)
		self.assertFalse(breach.hidden)

	def test_pin_must_be_4_to_6_digits(self):
		from cecypo_powerpack.pos_list_floor import PIN_FIELD
		from cecypo_powerpack.pos_supervisor_pin import validate_pin_format

		for bad in ("123", "1234567", "12a4", " 1234"):
			with self.assertRaises(frappe.ValidationError, msg=bad):
				validate_pin_format(frappe._dict({PIN_FIELD: bad}))
		for good in ("1234", "123456", "", None, "*****"):
			validate_pin_format(frappe._dict({PIN_FIELD: good}))
