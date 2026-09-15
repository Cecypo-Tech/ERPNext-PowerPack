# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestPriceApprovalFields(FrappeTestCase):
	def test_custom_fields_exist_on_every_approval_doctype(self):
		from cecypo_powerpack import price_approval as pa

		pa.setup_custom_fields()
		for dt in pa.APPROVAL_DOCTYPES:
			meta = frappe.get_meta(dt)
			for fieldname in (pa.BREACH_FIELD, *pa.APPROVAL_FIELDS):
				self.assertTrue(meta.get_field(fieldname), f"{dt} lacks {fieldname}")
		self.assertTrue(frappe.get_meta("Sales Invoice").get_field(pa.SOURCE_ORDER_FIELD))
		self.assertFalse(frappe.get_meta("Sales Order").get_field(pa.SOURCE_ORDER_FIELD))

	def test_source_order_is_data_not_link(self):
		# klik_pos deletes the held Sales Order right after checkout; a Link here
		# would make that delete fail with LinkExistsError.
		from cecypo_powerpack import price_approval as pa

		df = frappe.get_meta("Sales Invoice").get_field(pa.SOURCE_ORDER_FIELD)
		self.assertEqual(df.fieldtype, "Data")

	def test_setup_is_idempotent(self):
		from cecypo_powerpack import price_approval as pa

		pa.setup_custom_fields()
		pa.setup_custom_fields()
		names = frappe.get_all(
			"Custom Field", filters={"dt": "Sales Order", "fieldname": pa.BREACH_FIELD}, pluck="name"
		)
		self.assertEqual(len(names), 1)
