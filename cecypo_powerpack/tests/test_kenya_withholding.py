import unittest
from datetime import date

import frappe
from frappe.tests import IntegrationTestCase

from cecypo_powerpack.kenya_withholding import (
	income_tax_due_date,
	invoice_withholding,
	vat_due_date,
	withheld,
)

CHILDREN = {
	"Withholding Rule": ["item", "supplier", "rate", "account"],
	"Withholding VAT Account": ["account"],
	"Withholding VAT Exemption": ["supplier", "certificate_no", "valid_until"],
	"Payment Entry Withholding": [
		"purchase_invoice", "bill_no", "bill_date", "base_amount", "rate",
		"account", "amount", "is_vat", "due_date", "kra_journal_entry",
	],
}
SETTINGS = [
	"withholding_tab", "kenya_withholding_section", "enable_kenya_withholding",
	"withholding_vat_accounts", "withholding_rules", "withholding_exemptions",
]


class TestScaffold(IntegrationTestCase):
	def test_child_doctypes(self):
		for name, fields in CHILDREN.items():
			meta = frappe.get_meta(name)
			self.assertTrue(meta.istable, name)
			names = [f.fieldname for f in meta.fields]
			self.assertEqual(sorted(names), sorted(fields), name)

	def test_settings_fields(self):
		meta = frappe.get_meta("PowerPack Settings")
		for fieldname in SETTINGS:
			self.assertTrue(meta.get_field(fieldname), fieldname)

	def test_payment_entry_field(self):
		field = frappe.get_meta("Payment Entry").get_field("cecypo_withholding")
		self.assertEqual(field.options, "Payment Entry Withholding")

	def test_settings_child_links_ignore_user_permissions(self):
		for name in ("Withholding Rule", "Withholding VAT Account", "Withholding VAT Exemption"):
			for f in frappe.get_meta(name).fields:
				if f.fieldtype == "Link":
					self.assertEqual(f.ignore_user_permissions, 1, f"{name}.{f.fieldname}")


INV = {
	"name": "INV60515", "bill_no": "B1", "bill_date": "2026-01-01", "total": 315752,
	"items": [
		{"item_code": "RENT", "base_net_amount": 266200},
		{"item_code": "OTHER", "base_net_amount": 6000},
	],
}
VAT_RULE = {"item": None, "supplier": None, "rate": 2, "account": "VAT"}
RENT_RULE = {"item": "RENT", "supplier": None, "rate": 7.5, "account": "RENT"}


class TestCalculation(unittest.TestCase):
	def test_withheld_rounds_up_like_itax(self):
		for base, rate, want in [
			(126316.58, 2, 2527), (251195.14, 2, 5024), (4310.34, 2, 87),
			(266200, 7.5, 19965), (6000, 2, 120),
		]:
			self.assertEqual(withheld(base, rate), want)

	def _rows(self, allocated=315752, exempt=False, rules=None, supplier="S1"):
		rows = invoice_withholding(
			INV, allocated, supplier, rules or [VAT_RULE, RENT_RULE], {"VAT"}, exempt
		)
		return {r["account"]: r for r in rows}

	def test_inv60515_full_payment(self):
		rows = self._rows()
		self.assertEqual(rows["VAT"]["base_amount"], 272200)
		self.assertEqual(rows["VAT"]["amount"], 5444)
		self.assertEqual(rows["VAT"]["is_vat"], 1)
		self.assertEqual(rows["VAT"]["purchase_invoice"], "INV60515")
		self.assertEqual(rows["RENT"]["base_amount"], 266200)
		self.assertEqual(rows["RENT"]["amount"], 19965)
		self.assertEqual(rows["RENT"]["is_vat"], 0)

	def test_partial_payment_scales_base(self):
		rows = self._rows(allocated=157876)
		self.assertEqual(rows["VAT"]["base_amount"], 136100.00)
		self.assertEqual(rows["VAT"]["amount"], 2722)

	def test_exempt_skips_vat_only(self):
		self.assertEqual(list(self._rows(exempt=True)), ["RENT"])

	def test_supplier_and_item_matching(self):
		x = {"item": "RENT", "supplier": "S1", "rate": 1, "account": "A"}
		self.assertIn("A", self._rows(rules=[x], supplier="S1"))
		self.assertNotIn("A", self._rows(rules=[x], supplier="S2"))
		s1 = {"item": "", "supplier": "S1", "rate": 1, "account": "B"}
		self.assertEqual(self._rows(rules=[s1])["B"]["base_amount"], 272200)
		self.assertNotIn("B", self._rows(rules=[s1], supplier="S2"))
		rows = invoice_withholding(INV, 315752, "S1", [x, x], set(), False)
		self.assertEqual(len(rows), 2)

	def test_due_dates(self):
		self.assertEqual(vat_due_date(date(2026, 1, 22), set()), date(2026, 1, 29))
		self.assertEqual(vat_due_date(date(2026, 1, 22), {date(2026, 1, 26)}), date(2026, 1, 30))
		self.assertEqual(income_tax_due_date(date(2026, 10, 5)), date(2026, 11, 20))
		self.assertEqual(income_tax_due_date(date(2026, 12, 31)), date(2027, 1, 20))
