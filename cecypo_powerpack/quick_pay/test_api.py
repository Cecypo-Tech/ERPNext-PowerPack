import json
import uuid

import frappe
from frappe.tests import UnitTestCase


class TestGetPaymentModes(UnitTestCase):
	def test_returns_three_buckets(self):
		from cecypo_powerpack.quick_pay.api import get_payment_modes
		company = frappe.db.get_single_value("Global Defaults", "default_company") or \
				  frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest("No company configured")
		result = get_payment_modes(company=company)
		self.assertIn("cash_modes", result)
		self.assertIn("bank_modes", result)
		self.assertIn("card_modes", result)
		# No Phone-type leaked in
		for mop in result["cash_modes"] + result["bank_modes"] + result["card_modes"]:
			self.assertNotEqual(
				frappe.db.get_value("Mode of Payment", mop, "type"),
				"Phone",
			)


class TestProcessQuickPay(UnitTestCase):
	def test_full_payment_creates_pe_and_optional_invoice(self):
		from cecypo_powerpack.quick_pay.api import process_quick_pay
		so_name = frappe.db.get_value(
			"Sales Order",
			{"docstatus": 1, "per_billed": 0, "status": ["not in", ["Closed", "Cancelled"]]},
			"name",
		)
		if not so_name:
			self.skipTest("No unbilled SO available")
		so = frappe.get_doc("Sales Order", so_name)
		outstanding = float(so.grand_total) - float(so.advance_paid or 0)
		if outstanding <= 0:
			self.skipTest("SO has no outstanding")

		mop_row = frappe.db.sql("""
			SELECT parent FROM `tabMode of Payment Account`
			WHERE company = %s AND default_account IS NOT NULL LIMIT 1
		""", so.company, as_dict=True)
		if not mop_row:
			self.skipTest("No MOP available")
		mop = mop_row[0]["parent"]

		token = "test-" + uuid.uuid4().hex
		payments = json.dumps([
			{"type": "Cash", "amount": outstanding, "mode_of_payment": mop, "reference": ""},
		])

		result = process_quick_pay(
			sales_order=so.name,
			customer=so.customer,
			payments_json=payments,
			outstanding_amount=outstanding,
			create_invoice=0,
			submit_invoice=0,
			idempotency_token=token,
		)
		self.assertTrue(result["success"])
		self.assertEqual(len(result["payment_entries"]), 1)

	def test_duplicate_token_rejected(self):
		from cecypo_powerpack.quick_pay.api import process_quick_pay
		from cecypo_powerpack.quick_pay.validators import IdempotencyError, claim_idempotency_token
		token = "test-" + uuid.uuid4().hex
		# Pre-claim the token, then call should fail with IdempotencyError
		claim_idempotency_token(token)
		with self.assertRaises(IdempotencyError):
			process_quick_pay(
				sales_order="DOES-NOT-EXIST",
				customer="X",
				payments_json="[]",
				outstanding_amount=0,
				create_invoice=0,
				submit_invoice=0,
				idempotency_token=token,
			)
