import frappe
from frappe.tests import UnitTestCase

from cecypo_powerpack.quick_pay.builders import build_payment_entry
from cecypo_powerpack.quick_pay.builders import build_sales_invoice


class TestBuildPaymentEntry(UnitTestCase):
	def test_pe_uses_party_receivable_account(self):
		so_name = frappe.db.get_value("Sales Order", {"docstatus": 1}, "name")
		if not so_name:
			self.skipTest("No submitted Sales Order in DB to build a PE against")
		so = frappe.get_doc("Sales Order", so_name)

		mop = frappe.db.sql("""
			SELECT parent FROM `tabMode of Payment Account`
			WHERE company = %s AND default_account IS NOT NULL LIMIT 1
		""", so.company, as_dict=True)
		if not mop:
			self.skipTest("No Mode of Payment Account for company")
		mode_of_payment = mop[0]["parent"]

		pe = build_payment_entry(
			so_doc=so,
			amount=10.00,
			mode_of_payment=mode_of_payment,
			reference_no="TEST-REF-001",
			remarks="test",
		)

		# paid_from must be the party-specific receivable, not Company default
		from erpnext.accounts.party import get_party_account
		expected_paid_from = get_party_account("Customer", so.customer, so.company)
		self.assertEqual(pe.paid_from, expected_paid_from)

		# Reference row exists with capped allocated
		self.assertEqual(len(pe.references), 1)
		self.assertEqual(pe.references[0].reference_doctype, "Sales Order")
		self.assertEqual(pe.references[0].reference_name, so.name)
		self.assertLessEqual(
			pe.references[0].allocated_amount,
			pe.references[0].outstanding_amount,
		)

		# Don't insert. Just verify the document constructed correctly.
		self.assertEqual(pe.payment_type, "Receive")
		self.assertEqual(pe.party_type, "Customer")
		self.assertEqual(pe.party, so.customer)


class TestBuildSalesInvoice(UnitTestCase):
	def test_si_built_via_official_mapper(self):
		so_name = frappe.db.get_value("Sales Order", {"docstatus": 1, "per_billed": 0}, "name")
		if not so_name:
			self.skipTest("No unbilled submitted Sales Order to invoice against")
		so = frappe.get_doc("Sales Order", so_name)

		si = build_sales_invoice(so, update_stock=1)
		# Mapper-style invariant: items inherit so_detail
		self.assertTrue(all(it.so_detail for it in si.items))
		# update_stock honored
		self.assertEqual(si.update_stock, 1)
		# Should still be unsaved
		self.assertFalse(si.get("name") and frappe.db.exists("Sales Invoice", si.name))
