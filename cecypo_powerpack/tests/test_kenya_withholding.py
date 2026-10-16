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


COMPANY = "_Test Company"
VAT_ACC = "_Test VAT WHT - _TC"
RENT_ACC = "_Test Rent WHT - _TC"
RENT_ITEM = "_Test WHT Rent"
OTHER_ITEM = "_Test Non Stock Item"
WHT_SUPPLIER = "_Test WHT Supplier"
BANK = "_Test Bank - _TC"
SETTINGS_FIELDS = [
	"enable_kenya_withholding", "withholding_vat_accounts", "withholding_rules",
	"withholding_exemptions",
]


def _account(name):
	if not frappe.db.exists("Account", name):
		frappe.get_doc({
			"doctype": "Account",
			"account_name": name.rsplit(" - ", 1)[0],
			"parent_account": "Duties and Taxes - _TC",
			"company": COMPANY,
			"account_type": "Tax",
		}).insert(ignore_permissions=True)


def _supplier(name):
	if not frappe.db.exists("Supplier", name):
		frappe.get_doc({
			"doctype": "Supplier", "supplier_name": name,
			"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}),
		}).insert(ignore_permissions=True)


def _make_pi(supplier=WHT_SUPPLIER, lines=((RENT_ITEM, 266200), (OTHER_ITEM, 6000)), **extra):
	pi = frappe.get_doc({
		"doctype": "Purchase Invoice",
		"company": COMPANY,
		"supplier": supplier,
		"bill_no": frappe.generate_hash(length=8),
		"bill_date": frappe.utils.nowdate(),
		"posting_date": frappe.utils.nowdate(),
		"due_date": frappe.utils.add_days(frappe.utils.nowdate(), 30),
		"items": [{"item_code": i, "qty": 1, "rate": r} for i, r in lines],
		**extra,
	})
	pi.insert(ignore_permissions=True)
	pi.submit()
	return pi


def _make_pe(pi, allocated=None, submit=True, **extra):
	pe = _pe(pi)
	pe.update(extra)
	if allocated is not None:
		pe.references[0].allocated_amount = allocated
	pe.insert(ignore_permissions=True)
	if submit:
		pe.submit()
	return pe


def _pe(pi):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	pe = get_payment_entry("Purchase Invoice", pi.name, bank_account=BANK)
	pe.reference_no, pe.reference_date = "WHT-TEST", frappe.utils.nowdate()
	return pe


def _deductions(pe):
	return {d.account: d.amount for d in pe.deductions}


class TestPaymentEntry(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from erpnext.stock.doctype.item.test_item import make_item

		_account(VAT_ACC)
		_account(RENT_ACC)
		make_item(RENT_ITEM, {"is_stock_item": 0})
		_supplier(WHT_SUPPLIER)
		s = frappe.get_single("PowerPack Settings")
		cls.saved = {f: [r.as_dict() for r in s.get(f)] if s.meta.get_field(f).fieldtype in (
			"Table", "Table MultiSelect") else s.get(f) for f in SETTINGS_FIELDS}
		s.enable_kenya_withholding = 1
		s.set("withholding_vat_accounts", [{"account": VAT_ACC}])
		s.set("withholding_rules", [
			{"item": None, "supplier": None, "rate": 2, "account": VAT_ACC},
			{"item": RENT_ITEM, "supplier": None, "rate": 7.5, "account": RENT_ACC},
		])
		s.set("withholding_exemptions", [])
		s.save(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		s = frappe.get_single("PowerPack Settings")
		for f, v in cls.saved.items():
			if isinstance(v, list):
				s.set(f, [{k: r[k] for k in r if k not in ("name", "idx", "parent")} for r in v])
			else:
				s.set(f, v)
		s.save(ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	def tearDown(self):
		frappe.db.rollback()

	def _settings(self, **changes):
		s = frappe.get_single("PowerPack Settings")
		for k, v in changes.items():
			s.set(k, v)
		s.save(ignore_permissions=True)
		return s

	def test_full_payment_posts_withholding(self):
		pi = _make_pi()
		self.assertEqual(pi.grand_total, 272200)
		pe = _make_pe(pi)
		self.assertEqual(pe.paid_amount, 272200 - 5444 - 19965)
		self.assertEqual(_deductions(pe), {VAT_ACC: -5444, RENT_ACC: -19965})
		self.assertEqual(pe.difference_amount, 0)
		rows = {r.account: r for r in pe.cecypo_withholding}
		self.assertEqual(rows[VAT_ACC].base_amount, 272200)
		self.assertEqual(rows[VAT_ACC].is_vat, 1)
		self.assertEqual(rows[RENT_ACC].base_amount, 266200)
		self.assertEqual(rows[RENT_ACC].bill_no, pi.bill_no)
		self.assertTrue(rows[VAT_ACC].due_date and rows[RENT_ACC].due_date)
		gl = dict(frappe.get_all(
			"GL Entry", {"voucher_no": pe.name, "is_cancelled": 0, "account": ["in", [VAT_ACC, RENT_ACC]]},
			["account", "credit"], as_list=True,
		))
		self.assertEqual(gl, {VAT_ACC: 5444, RENT_ACC: 19965})
		self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount"), 0)

	def test_dispute_allocates_less(self):
		pi = _make_pi()
		pe = _make_pe(pi, allocated=100000)
		rows = {r.account: r for r in pe.cecypo_withholding}
		self.assertEqual(rows[VAT_ACC].base_amount, 100000)
		self.assertEqual(rows[RENT_ACC].base_amount, round(266200 * 100000 / 272200, 2))
		self.assertEqual(pe.paid_amount, 100000 - rows[VAT_ACC].amount - rows[RENT_ACC].amount)
		self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount"), 172200)

	def test_debit_note_reduces_base(self):
		from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note

		pi = _make_pi()
		dn = make_debit_note(pi.name)
		# Return rate may not exceed the original line's rate, so the 72,200 goes on the rent line.
		dn.items = [i for i in dn.items if i.item_code == RENT_ITEM]
		dn.items[0].qty, dn.items[0].rate = -1, 72200
		dn.update_outstanding_for_self = 0
		dn.insert(ignore_permissions=True)
		dn.submit()
		self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount"), 200000)
		pe = _make_pe(pi)
		self.assertEqual(pe.references[0].allocated_amount, 200000)
		rows = {r.account: r for r in pe.cecypo_withholding}
		self.assertEqual(rows[VAT_ACC].base_amount, round(272200 * 200000 / 272200, 2))
		self.assertEqual(rows[RENT_ACC].base_amount, round(266200 * 200000 / 272200, 2))

	def test_exemption_valid_then_expired(self):
		today = frappe.utils.getdate()
		pi = _make_pi()
		self._settings(withholding_exemptions=[
			{"supplier": WHT_SUPPLIER, "certificate_no": "X1", "valid_until": today}])
		pe = _make_pe(pi, submit=False)
		self.assertEqual([r.account for r in pe.cecypo_withholding], [RENT_ACC])
		self.assertEqual(_deductions(pe), {RENT_ACC: -19965})
		self._settings(withholding_exemptions=[
			{"supplier": WHT_SUPPLIER, "certificate_no": "X1", "valid_until": frappe.utils.add_days(today, -1)}])
		pe.save()
		self.assertEqual(_deductions(pe), {VAT_ACC: -5444, RENT_ACC: -19965})
		self.assertEqual(pe.difference_amount, 0)

	def test_nothing_left_to_withhold_restores_paid_amount(self):
		pi = _make_pi(lines=((OTHER_ITEM, 6000),))
		pe = _make_pe(pi, submit=False)
		self.assertEqual(_deductions(pe), {VAT_ACC: -120})
		self._settings(withholding_exemptions=[
			{"supplier": WHT_SUPPLIER, "certificate_no": "X1", "valid_until": frappe.utils.getdate()}])
		pe.save()
		self.assertEqual((pe.cecypo_withholding, pe.deductions, pe.paid_amount), ([], [], 6000))
		self.assertEqual(pe.difference_amount, 0)

	def test_entry_inserted_without_exchange_rates(self):
		pe = _pe(_make_pi())
		pe.source_exchange_rate = pe.target_exchange_rate = None
		pe.insert(ignore_permissions=True)
		self.assertEqual(pe.paid_amount, 272200 - 5444 - 19965)
		self.assertEqual(pe.difference_amount, 0)

	def test_feature_off_does_nothing(self):
		self._settings(enable_kenya_withholding=0)
		pi = _make_pi()
		pe = _make_pe(pi, submit=False)
		self.assertEqual(pe.cecypo_withholding, [])
		self.assertEqual(pe.deductions, [])
		self.assertEqual(pe.paid_amount, 272200)

	def test_submit_recomputes_with_current_rules(self):
		pi = _make_pi()
		pe = _make_pe(pi, submit=False)
		s = frappe.get_single("PowerPack Settings")
		s.withholding_rules[0].rate = 3
		s.save(ignore_permissions=True)
		pe.reload()
		pe.submit()
		vat = [r for r in pe.cecypo_withholding if r.account == VAT_ACC][0]
		self.assertEqual(vat.rate, 3)
		self.assertEqual(vat.amount, 8166)
		self.assertEqual(pe.paid_amount, 272200 - 8166 - 19965)

	def test_non_pi_reference_ignored(self):
		pi = _make_pi()
		po = frappe.get_doc({
			"doctype": "Purchase Order", "company": COMPANY, "supplier": WHT_SUPPLIER,
			"schedule_date": frappe.utils.nowdate(),
			"items": [{"item_code": RENT_ITEM, "qty": 1, "rate": 10000}],
		}).insert(ignore_permissions=True)
		po.submit()
		pe = _pe(pi)
		pe.append("references", {
			"reference_doctype": "Purchase Order", "reference_name": po.name, "allocated_amount": 10000})
		pe.insert(ignore_permissions=True)
		pe.submit()
		self.assertEqual({r.purchase_invoice for r in pe.cecypo_withholding}, {pi.name})
		self.assertEqual(_deductions(pe), {VAT_ACC: -5444, RENT_ACC: -19965})
		self.assertEqual(pe.paid_amount, 282200 - 5444 - 19965)
		self.assertEqual(pe.unallocated_amount, 0)

	def test_usd_invoice_kes_bank(self):
		pi = _make_pi(
			supplier="_Test Supplier USD", currency="USD", conversion_rate=100,
			credit_to="_Test Payable USD - _TC", lines=((RENT_ITEM, 2662), (OTHER_ITEM, 60)),
		)
		for rate in (100, 101.37):
			pe = _make_pe(pi, submit=False, target_exchange_rate=rate)
			rows = {r.account: r for r in pe.cecypo_withholding}
			self.assertEqual(rows[VAT_ACC].base_amount, 272200)
			self.assertEqual(rows[RENT_ACC].base_amount, 266200)
			self.assertAlmostEqual(pe.paid_amount, 2722 * rate - 5444 - 19965, places=2)
			self.assertEqual(pe.difference_amount, 0)
			self.assertEqual(pe.unallocated_amount, 0)
		pe.submit()
		self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount"), 0)

	def test_cancel_blocked_when_paid_to_kra(self):
		pe = _make_pe(_make_pi())
		frappe.db.set_value("Payment Entry Withholding", pe.cecypo_withholding[0].name, "kra_journal_entry", "ACC-JV-KRA-1")
		pe.reload()
		with self.assertRaisesRegex(frappe.ValidationError, "ACC-JV-KRA-1"):
			pe.cancel()

	def test_compute_for_unsaved_entry(self):
		from cecypo_powerpack.kenya_withholding import compute_for_payment_entry

		pe = _pe(_make_pi())
		out = compute_for_payment_entry(pe.as_json())
		self.assertEqual(out["paid_amount"], 272200 - 5444 - 19965)
		self.assertEqual({d["account"]: d["amount"] for d in out["deductions"]}, {VAT_ACC: -5444, RENT_ACC: -19965})
		self.assertEqual(len(out["cecypo_withholding"]), 2)
