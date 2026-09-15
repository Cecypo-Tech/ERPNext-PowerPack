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


class TestPriceApprovalSettings(FrappeTestCase):
	def tearDown(self):
		frappe.clear_cache(doctype="PowerPack Settings")

	def _settings(self, **values):
		s = frappe.get_single("PowerPack Settings")
		s.enable_min_selling_price = 1
		s.min_selling_price_default_percent = 4
		s.min_selling_price_override_role = None
		for dt_field in ("msp_approval_quotation", "msp_approval_sales_order", "msp_approval_sales_invoice", "msp_approval_delivery_note"):
			s.set(dt_field, 0)
		for key, value in values.items():
			s.set(key, value)
		return s

	def test_fields_exist_after_the_diagram(self):
		meta = frappe.get_meta("PowerPack Settings")
		order = [f.fieldname for f in meta.fields]
		for i, fieldname in enumerate(("msp_approval_quotation", "msp_approval_sales_order", "msp_approval_sales_invoice", "msp_approval_delivery_note")):
			df = meta.get_field(fieldname)
			self.assertTrue(df, fieldname)
			self.assertEqual(df.fieldtype, "Check")
			self.assertEqual(order.index(fieldname), order.index("min_selling_price_whole_sale_diagram") + 1 + i)

	def test_routing_needs_an_override_role(self):
		s = self._settings(msp_approval_sales_order=1)
		with self.assertRaisesRegex(frappe.ValidationError, "Role Allowed to Override"):
			s.save()

	def test_routing_refuses_a_foreign_active_workflow(self):
		if not frappe.db.exists("Role", "_MSP Override Role"):
			frappe.get_doc({"doctype": "Role", "role_name": "_MSP Override Role"}).insert()
		if frappe.db.exists("Workflow", "_MSP Foreign SO Workflow"):
			frappe.delete_doc("Workflow", "_MSP Foreign SO Workflow", force=True)
		had_state_field = bool(frappe.db.exists("Custom Field", "Sales Order-workflow_state"))
		foreign = frappe.get_doc({
			"doctype": "Workflow", "workflow_name": "_MSP Foreign SO Workflow", "document_type": "Sales Order",
			"workflow_state_field": "workflow_state", "is_active": 1,
			"states": [{"state": "Draft", "doc_status": "0", "allow_edit": "All"}],
		}).insert()
		try:
			s = self._settings(msp_approval_sales_order=1, min_selling_price_override_role="_MSP Override Role")
			with self.assertRaisesRegex(frappe.ValidationError, "_MSP Foreign SO Workflow"):
				s.save()
		finally:
			# Workflow.on_update creates the workflow_state Custom Field, whose ALTER TABLE
			# implicitly commits — so this workflow outlives the test rollback. Left behind it
			# would be an *active* workflow on every Sales Order on the site.
			frappe.delete_doc("Workflow", foreign.name, force=True)
			if not had_state_field:
				frappe.delete_doc("Custom Field", "Sales Order-workflow_state", force=True)
			frappe.db.commit()
			frappe.clear_cache(doctype="Sales Order")

	def test_routing_off_needs_nothing(self):
		s = self._settings()
		s.save()  # must not raise
