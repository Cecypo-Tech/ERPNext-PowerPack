import json
import uuid

import frappe
from frappe.tests import UnitTestCase


class TestQpUpdateStockSetting(UnitTestCase):
	"""Doesn't touch any Sales Order / Payment Entry data — safe to re-run."""

	def setUp(self):
		self._original = frappe.db.sql(
			"""select value from `tabSingles` where doctype='PowerPack Settings' and field='qp_update_stock'"""
		)

	def tearDown(self):
		if self._original:
			frappe.db.set_single_value("PowerPack Settings", "qp_update_stock", self._original[0][0])
		else:
			frappe.db.sql(
				"""delete from `tabSingles` where doctype='PowerPack Settings' and field='qp_update_stock'"""
			)
		frappe.db.commit()

	def test_respects_explicit_disable(self):
		from cecypo_powerpack.utils import is_feature_enabled

		frappe.db.set_single_value("PowerPack Settings", "qp_update_stock", 0)
		self.assertFalse(is_feature_enabled("qp_update_stock"))

	def test_respects_explicit_enable(self):
		from cecypo_powerpack.utils import is_feature_enabled

		frappe.db.set_single_value("PowerPack Settings", "qp_update_stock", 1)
		self.assertTrue(is_feature_enabled("qp_update_stock"))

	def test_patch_backfills_default_when_never_saved(self):
		from cecypo_powerpack.patches.v1.default_qp_update_stock import execute
		from cecypo_powerpack.utils import is_feature_enabled

		frappe.db.sql(
			"""delete from `tabSingles` where doctype='PowerPack Settings' and field='qp_update_stock'"""
		)
		frappe.db.commit()

		execute()

		self.assertTrue(is_feature_enabled("qp_update_stock"))

	def test_patch_leaves_explicit_value_untouched(self):
		from cecypo_powerpack.patches.v1.default_qp_update_stock import execute
		from cecypo_powerpack.utils import is_feature_enabled

		frappe.db.set_single_value("PowerPack Settings", "qp_update_stock", 0)

		execute()

		self.assertFalse(is_feature_enabled("qp_update_stock"))


class TestGetPaymentModes(UnitTestCase):
	def setUp(self):
		frappe.db.set_single_value("PowerPack Settings", "enable_quick_pay", 1)

	def tearDown(self):
		frappe.db.set_single_value("PowerPack Settings", "enable_quick_pay", 0)

	def test_returns_three_buckets(self):
		from cecypo_powerpack.quick_pay.api import get_payment_modes

		company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
			"Company", {}, "name"
		)
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
	def setUp(self):
		frappe.db.set_single_value("PowerPack Settings", "enable_quick_pay", 1)

	def tearDown(self):
		frappe.db.set_single_value("PowerPack Settings", "enable_quick_pay", 0)

	def test_full_payment_creates_pe_and_optional_invoice(self):
		from cecypo_powerpack.quick_pay.api import process_quick_pay
		from cecypo_powerpack.quick_pay.validators import effective_total

		so_name = frappe.db.get_value(
			"Sales Order",
			{"docstatus": 1, "per_billed": 0, "status": ["not in", ["Closed", "Cancelled"]]},
			"name",
		)
		if not so_name:
			self.skipTest("No unbilled SO available")
		so = frappe.get_doc("Sales Order", so_name)
		# Match production: outstanding is measured against the rounded
		# ceiling Payment Entry actually enforces, not the raw grand_total.
		outstanding = effective_total(so) - float(so.advance_paid or 0)
		if outstanding <= 0:
			self.skipTest("SO has no outstanding")

		mop_row = frappe.db.sql(
			"""
			SELECT parent FROM `tabMode of Payment Account`
			WHERE company = %s AND default_account IS NOT NULL LIMIT 1
		""",
			so.company,
			as_dict=True,
		)
		if not mop_row:
			self.skipTest("No MOP available")
		mop = mop_row[0]["parent"]

		token = "test-" + uuid.uuid4().hex
		payments = json.dumps(
			[
				{"type": "Cash", "amount": outstanding, "mode_of_payment": mop, "reference": ""},
			]
		)

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
