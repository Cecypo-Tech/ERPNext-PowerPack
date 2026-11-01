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
PLACEHOLDERS = ("CO", "CO/", "CO-", "CO_", "BR", "BR/", "BR-", "BR_", "SET", "SET/", "SET-", "SET_", "PAYDIR", "RET", "RET/", "RET-", "RET_", "ST", "ST/", "ST-", "ST_")


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

	def test_blank_company_code_is_left_out(self):
		# A single-company site leaves the code blank: no company part at all, not the Abbr.
		_code("Company", CO, None)
		self.assertEqual(parse_variable(self._sale(), "CO"), "")
		self.assertEqual(parse_variable(self._sale(), "CO/"), "")

	def test_company_code_with_separator(self):
		self.assertEqual(parse_variable(self._sale(), "CO/"), "TC1/")
		self.assertEqual(parse_variable(self._sale(), "CO-"), "TC1-")

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

	def test_branch_falls_back_to_item_warehouse(self):
		# A POS profile with no warehouse leaves the header blank and sets each row's warehouse.
		items = [frappe._dict(warehouse=None), frappe._dict(warehouse=WH2), frappe._dict(warehouse=WH)]
		self.assertEqual(parse_variable(self._sale(set_warehouse=None, items=items), "BR/"), "MI/")
		self.assertEqual(parse_variable(self._sale(set_warehouse=WH, items=items), "BR/"), "HQ/")
		self.assertEqual(parse_variable(self._sale(set_warehouse=None, items=[]), "BR/"), "")

	def test_return_takes_the_original_item_warehouse(self):
		row = frappe.db.get_value("Sales Invoice Item", {"parenttype": "Sales Invoice"}, ["name", "parent", "warehouse"], as_dict=True)
		if not row:
			self.skipTest("no Sales Invoice on this site")
		header = frappe.db.get_value("Sales Invoice", row.parent, "set_warehouse")
		frappe.db.set_value("Sales Invoice", row.parent, "set_warehouse", None, update_modified=False)
		self.addCleanup(frappe.db.set_value, "Sales Invoice", row.parent, "set_warehouse", header, update_modified=False)
		# Other rows of the original must not outrank its first row.
		first = frappe.db.get_value("Sales Invoice Item", {"parent": row.parent, "parenttype": "Sales Invoice"}, ["name", "warehouse"], order_by="idx asc", as_dict=True)
		frappe.db.set_value("Sales Invoice Item", first.name, "warehouse", WH2, update_modified=False)
		self.addCleanup(frappe.db.set_value, "Sales Invoice Item", first.name, "warehouse", first.warehouse, update_modified=False)
		doc = self._sale(is_return=1, return_against=row.parent, items=[frappe._dict(warehouse=WH)])
		self.assertEqual(parse_variable(doc, "BR/"), "MI/")

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

	def test_return_and_debit_note(self):
		for doctype in ("Sales Invoice", "Delivery Note", "Purchase Receipt", "Purchase Invoice"):
			self.assertEqual(parse_variable(frappe._dict(doctype=doctype, is_return=1), "RET/"), "RET/", doctype)
			self.assertEqual(parse_variable(frappe._dict(doctype=doctype), "RET/"), "", doctype)
		self.assertEqual(parse_variable(self._sale(is_debit_note=1), "RET/"), "DR/")
		self.assertEqual(parse_variable(self._sale(is_debit_note=1), "RET"), "DR")
		self.assertEqual(parse_variable(frappe._dict(doctype="Purchase Invoice", is_debit_note=1), "RET/"), "")

	def test_every_placeholder_is_registered(self):
		from cecypo_powerpack import hooks

		self.assertEqual(set(hooks.naming_series_variables), set(PLACEHOLDERS))

	def test_sale_type(self):
		# klik fills custom_sale_type before insert: Cash -> POS, Credit -> INV.
		self.assertEqual(parse_variable(self._sale(custom_sale_type="Cash"), "ST/"), "POS/")
		self.assertEqual(parse_variable(self._sale(custom_sale_type="Credit"), "ST/"), "INV/")
		self.assertEqual(parse_variable(self._sale(custom_sale_type="Credit"), "ST"), "INV")
		self.assertEqual(parse_variable(self._sale(), "ST/"), "")
		self.assertEqual(parse_variable(self._sale(custom_sale_type="Barter"), "ST/"), "")
		self.assertEqual(parse_variable(frappe._dict(doctype="Delivery Note", custom_sale_type="Cash"), "ST/"), "")

	def test_return_takes_the_original_branch(self):
		original = frappe.db.get_value("Sales Invoice", {}, "name")
		if not original:
			self.skipTest("no Sales Invoice on this site")
		before = frappe.db.get_value("Sales Invoice", original, "set_warehouse")
		frappe.db.set_value("Sales Invoice", original, "set_warehouse", WH2, update_modified=False)
		self.addCleanup(frappe.db.set_value, "Sales Invoice", original, "set_warehouse", before, update_modified=False)
		self.assertEqual(parse_variable(self._sale(is_return=1, return_against=original), "BR/"), "MI/")
		# A Delivery Note return carries the company's sales-return warehouse; the original still wins.
		self.assertEqual(parse_variable(self._sale(is_return=1, return_against=original, set_warehouse=WH), "BR/"), "MI/")
		self.assertEqual(parse_variable(self._sale(return_against=original), "BR/"), "")
		frappe.db.set_value("Sales Invoice", original, "set_warehouse", None, update_modified=False)
		self.assertEqual(parse_variable(self._sale(is_return=1, return_against=original, set_warehouse=WH), "BR/"), "HQ/")

	def test_disabled_keeps_the_text(self):
		# A site with the setting off keeps its existing series, e.g. BR-.YYYY.-.####.
		frappe.db.set_single_value("PowerPack Settings", "enable_branch_naming_codes", 0)
		doc = frappe._dict(doctype="Payment Entry", company=CO, set_warehouse=WH, payment_type="Pay")
		for variable in PLACEHOLDERS:
			self.assertEqual(parse_variable(doc, variable), variable, variable)
		self.assertEqual(parse_naming_series("BR-.#", doc=doc, number_generator=lambda prefix, digits: "1"), "BR-1")

	def test_no_doc(self):
		# The Naming Series preview: no branch, type or direction; the default company's code.
		for variable in ("BR", "BR/", "SET/", "PAYDIR", "RET/", "ST/"):
			self.assertEqual(parse_variable(None, variable), "", variable)
		default = frappe.db.get_default("company")
		if default:
			expected = frappe.db.get_value("Company", default, FIELD) or ""
			self.assertEqual(parse_variable(None, "CO"), expected)

	def test_series_end_to_end(self):
		prefixes = []

		def counter(prefix, digits):
			prefixes.append(prefix)
			return "1".zfill(digits)

		series = ".CO./.BR/.SI/.#####"
		self.assertEqual(parse_naming_series(series, doc=self._sale(set_warehouse=WH), number_generator=counter), "TC1/HQ/SI/00001")
		self.assertEqual(parse_naming_series(series, doc=self._sale(set_warehouse=None), number_generator=counter), "TC1/SI/00001")
		self.assertEqual(prefixes, ["TC1/HQ/SI/", "TC1/SI/"])

		series = ".CO./.BR/.SI/.RET/.#####"
		self.assertEqual(parse_naming_series(series, doc=self._sale(set_warehouse=WH, is_return=1), number_generator=counter), "TC1/HQ/SI/RET/00001")
		self.assertEqual(parse_naming_series(series, doc=self._sale(set_warehouse=WH, is_debit_note=1), number_generator=counter), "TC1/HQ/SI/DR/00001")
		self.assertEqual(parse_naming_series(series, doc=self._sale(set_warehouse=WH), number_generator=counter), "TC1/HQ/SI/00001")

		series = ".CO/.BR/.SI/.#####"
		self.assertEqual(parse_naming_series(series, doc=self._sale(set_warehouse=WH), number_generator=counter), "TC1/HQ/SI/00001")
		_code("Company", CO, None)
		self.assertEqual(parse_naming_series(series, doc=self._sale(set_warehouse=WH), number_generator=counter), "HQ/SI/00001")

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


class TestApplySuggestedSeries(IntegrationTestCase):
	"""PowerPack Settings > Apply suggested naming: writes each doctype's series as the default."""

	DT = "Quotation"
	SERIES = ".CO/.BR/.QT/.#####"

	def setUp(self):
		from unittest.mock import patch

		self._enabled = frappe.db.get_single_value("PowerPack Settings", "enable_branch_naming_codes")
		frappe.db.set_single_value("PowerPack Settings", "enable_branch_naming_codes", 1)
		patcher = patch.dict("cecypo_powerpack.branch_naming.SUGGESTED_SERIES", {self.DT: self.SERIES}, clear=True)
		patcher.start()
		self.addCleanup(patcher.stop)
		self._options = self._series_options()
		self.addCleanup(self._restore)

	def _series_options(self):
		return [o for o in frappe.get_meta(self.DT).get_naming_series_options() if o.strip()]

	def _restore(self):
		dns = frappe.get_doc("Document Naming Settings")
		dns.user_must_always_select = 0
		dns.set_series_options_in_meta(self.DT, "\n".join(self._options))
		frappe.db.set_single_value("PowerPack Settings", "enable_branch_naming_codes", self._enabled or 0)

	def test_replaces_the_series_list(self):
		from cecypo_powerpack.branch_naming import apply_suggested_series

		self.assertEqual(apply_suggested_series(CO), [self.DT])
		self.assertEqual(self._series_options(), [self.SERIES])
		self.assertEqual(frappe.get_meta(self.DT).get_field("naming_series").default, self.SERIES)
		# A second run changes nothing.
		self.assertEqual(apply_suggested_series(CO), [])

	def test_a_list_that_only_starts_with_the_series_is_cleaned(self):
		from cecypo_powerpack.branch_naming import apply_suggested_series

		dns = frappe.get_doc("Document Naming Settings")
		dns.user_must_always_select = 0
		dns.set_series_options_in_meta(self.DT, "\n".join([self.SERIES, *self._options]))
		self.assertEqual(apply_suggested_series(CO), [self.DT])
		self.assertEqual(self._series_options(), [self.SERIES])

	def test_refuses_a_misspelt_company(self):
		from cecypo_powerpack.branch_naming import apply_suggested_series

		for wrong in (CO.lower(), CO + " ", "", None):
			self.assertRaises(frappe.ValidationError, apply_suggested_series, wrong)
		self.assertEqual(self._series_options(), self._options)

	def test_refuses_while_the_feature_is_off(self):
		from cecypo_powerpack.branch_naming import apply_suggested_series

		frappe.db.set_single_value("PowerPack Settings", "enable_branch_naming_codes", 0)
		self.assertRaises(frappe.ValidationError, apply_suggested_series, CO)
		self.assertEqual(self._series_options(), self._options)

	def test_suggestions_preview_the_series(self):
		from cecypo_powerpack.branch_naming import get_suggested_series

		rows = get_suggested_series()["rows"]
		self.assertEqual([(r["doctype"], r["series"]) for r in rows], [(self.DT, self.SERIES)])
		self.assertTrue(rows[0]["preview"].endswith("QT/00001"), rows[0]["preview"])
