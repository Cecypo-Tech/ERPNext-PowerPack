"""Naming-series placeholders for company, branch (warehouse) and Stock Entry Type codes, and the
Payment Entry direction: `.CO./.BR/.SI/.#####` names a Paint Matt invoice `OJ/PM/SI/00001`."""

import frappe
from frappe.model.naming import parse_naming_series
from frappe.tests import IntegrationTestCase

from cecypo_powerpack.branch_naming import parse_variable, setup_custom_fields

CO = "_Test Company"
WH = "_Test Warehouse - _TC"
WH2 = "_Test Warehouse 1 - _TC"
SET = "Material Transfer"
FIELD = "cecypo_naming_code"
PLACEHOLDERS = ("CO", "BR", "BR/", "BR-", "BR_", "SET", "SET/", "SET-", "SET_", "PAYDIR")


def _code(doctype, name, code):
	frappe.db.set_value(doctype, name, FIELD, code, update_modified=False)


class TestBranchNaming(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		setup_custom_fields()

	def setUp(self):
		self._enabled = frappe.db.get_single_value("PowerPack Settings", "enable_branch_naming_codes")
		frappe.db.set_single_value("PowerPack Settings", "enable_branch_naming_codes", 1)
		_code("Company", CO, "TC1")
		_code("Warehouse", WH, "HQ")
		_code("Warehouse", WH2, "MI")
		_code("Stock Entry Type", SET, "MT")

	def tearDown(self):
		frappe.db.set_single_value("PowerPack Settings", "enable_branch_naming_codes", self._enabled or 0)
		for doctype, name in (("Company", CO), ("Warehouse", WH), ("Warehouse", WH2), ("Stock Entry Type", SET)):
			_code(doctype, name, None)

	def _sale(self, **kw):
		return frappe._dict(doctype="Sales Invoice", company=CO, **kw)

	def test_company_code(self):
		self.assertEqual(parse_variable(self._sale(), "CO"), "TC1")

	def test_company_code_falls_back_to_abbr(self):
		_code("Company", CO, None)
		self.assertEqual(parse_variable(self._sale(), "CO"), frappe.db.get_value("Company", CO, "abbr"))

	def test_branch_code_with_separator(self):
		doc = self._sale(set_warehouse=WH)
		self.assertEqual(parse_variable(doc, "BR"), "HQ")
		self.assertEqual(parse_variable(doc, "BR/"), "HQ/")
		self.assertEqual(parse_variable(doc, "BR-"), "HQ-")

	def test_no_branch_drops_separator(self):
		self.assertEqual(parse_variable(self._sale(set_warehouse=None), "BR/"), "")
		_code("Warehouse", WH, None)
		self.assertEqual(parse_variable(self._sale(set_warehouse=WH), "BR/"), "")
		self.assertEqual(parse_variable(self._sale(set_warehouse="No Such Warehouse"), "BR/"), "")

	def test_stock_entry_branches(self):
		def entry(src, tgt):
			return frappe._dict(doctype="Stock Entry", company=CO, from_warehouse=src, to_warehouse=tgt)

		self.assertEqual(parse_variable(entry(WH, WH2), "BR/"), "HQ-MI/")
		self.assertEqual(parse_variable(entry(None, WH2), "BR/"), "MI/")
		self.assertEqual(parse_variable(entry(WH, None), "BR/"), "HQ/")
		self.assertEqual(parse_variable(entry(WH, WH), "BR/"), "HQ/")
		self.assertEqual(parse_variable(entry(None, None), "BR/"), "")

	def test_stock_entry_type_code(self):
		entry = frappe._dict(doctype="Stock Entry", company=CO, stock_entry_type=SET)
		self.assertEqual(parse_variable(entry, "SET/"), "MT/")
		_code("Stock Entry Type", SET, None)
		self.assertEqual(parse_variable(entry, "SET/"), "")
		self.assertEqual(parse_variable(self._sale(stock_entry_type=SET), "SET/"), "")

	def test_payment_direction(self):
		for payment_type, expected in (("Receive", "IN"), ("Pay", "OUT"), ("Internal Transfer", "TRF")):
			doc = frappe._dict(doctype="Payment Entry", company=CO, payment_type=payment_type)
			self.assertEqual(parse_variable(doc, "PAYDIR"), expected)
		self.assertEqual(parse_variable(self._sale(payment_type="Receive"), "PAYDIR"), "")

	def test_disabled_returns_empty(self):
		frappe.db.set_single_value("PowerPack Settings", "enable_branch_naming_codes", 0)
		doc = frappe._dict(doctype="Payment Entry", company=CO, set_warehouse=WH, payment_type="Pay")
		for variable in PLACEHOLDERS:
			self.assertEqual(parse_variable(doc, variable), "", variable)

	def test_no_doc(self):
		for variable in PLACEHOLDERS:
			self.assertEqual(parse_variable(None, variable), "", variable)

	def test_series_end_to_end(self):
		prefixes = []

		def counter(prefix, digits):
			prefixes.append(prefix)
			return "1".zfill(digits)

		series = ".CO./.BR/.SI/.#####"
		self.assertEqual(parse_naming_series(series, doc=self._sale(set_warehouse=WH), number_generator=counter), "TC1/HQ/SI/00001")
		self.assertEqual(parse_naming_series(series, doc=self._sale(set_warehouse=None), number_generator=counter), "TC1/SI/00001")
		self.assertEqual(prefixes, ["TC1/HQ/SI/", "TC1/SI/"])

	def test_enabling_creates_code_fields(self):
		names = [f"{dt}-{FIELD}" for dt in ("Company", "Warehouse", "Stock Entry Type")]
		for name in names:
			frappe.delete_doc("Custom Field", name, ignore_missing=True, force=True)
		self.addCleanup(setup_custom_fields)
		settings = frappe.get_single("PowerPack Settings")
		settings.enable_branch_naming_codes = 1
		settings.save()
		for name in names:
			self.assertTrue(frappe.db.exists("Custom Field", name), name)
