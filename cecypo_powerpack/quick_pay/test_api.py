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
