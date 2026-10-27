import unittest
from datetime import date

import frappe
from frappe.tests import IntegrationTestCase

from cecypo_powerpack.kenya_withholding import (
	income_tax_due_date,
	invoice_withholding,
	merge_vat_rows,
	vat_due_date,
	withheld,
)

CHILDREN = {
	"Withholding Rule": ["item", "supplier", "rate", "account"],
	"Withholding VAT Account": ["account"],
	"Withholding VAT Exemption": ["supplier", "certificate_no", "valid_until"],
	"Payment Entry Withholding": [
		"purchase_invoice", "purchase_order", "allocated_amount", "bill_no", "bill_date", "base_amount", "rate",
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
		total = frappe.get_meta("Payment Entry").get_field("cecypo_total_withheld")
		self.assertEqual((total.fieldtype, total.read_only, total.insert_after), ("Currency", 1, "column_break_21"))

	def test_references_section_shown_before_paid_amount(self):
		# Get Outstanding Invoices lives in this section; ERPNext hides it until a paid amount is typed.
		self.assertEqual(
			frappe.get_meta("Payment Entry").get_field("section_break_14").depends_on,
			"eval:(doc.party && doc.paid_from && doc.paid_to)",
		)

	def test_withholding_grid_columns(self):
		meta = frappe.get_meta("Payment Entry Withholding")
		self.assertEqual([f.fieldname for f in meta.fields if f.in_list_view],
			["purchase_invoice", "base_amount", "rate", "amount"])

	def test_kra_journal_entry_indexed(self):
		self.assertEqual(frappe.get_meta("Payment Entry Withholding").get_field("kra_journal_entry").search_index, 1)

	def test_journal_entry_kra_marker(self):
		f = frappe.get_meta("Journal Entry").get_field("cecypo_kra_payment")
		self.assertEqual((f.fieldtype, f.hidden, f.no_copy, f.read_only), ("Check", 1, 1, 1))

	def test_money_endpoints_post_only(self):
		from cecypo_powerpack import kenya_withholding as kw

		for fn in (kw.pay_kra, kw.export_itax_csv, kw.check_itax_export):
			self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[fn], ["POST"], fn.__name__)

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

	def test_report_cards_sum_unpaid_by_account(self):
		from cecypo_powerpack.cecypo_powerpack.report.withholding_due_to_kra.withholding_due_to_kra import account_cards

		rows = [
			{"account": "VAT", "amount": 5444, "kra_journal_entry": None, "overdue": 0},
			{"account": "VAT", "amount": 120, "kra_journal_entry": None, "overdue": 1},
			{"account": "RENT", "amount": 19965, "kra_journal_entry": None, "overdue": 0},
			{"account": "RENT", "amount": 999, "kra_journal_entry": "ACC-JV-1", "overdue": 0},
		]
		cards = account_cards(rows, "KES")
		self.assertEqual([(c["label"], c["value"], c["indicator"]) for c in cards], [
			("VAT", 5564, "Red"), ("RENT", 19965, "Blue"), ("Selected", 0, "Green"),
		])
		self.assertEqual({c["currency"] for c in cards}, {"KES"})

	def test_merge_vat_rows(self):
		rows = [
			{"tax_id": "P1", "bill_no": "B1", "base_amount": 50000.25, "posting_date": date(2026, 1, 2),
				"rate": 2, "is_vat": 1, "purchase_invoice": "PI-1"},
			{"tax_id": "P1", "bill_no": "B1", "base_amount": 50000.25, "posting_date": date(2026, 1, 5),
				"rate": 2, "is_vat": 1, "purchase_invoice": "PI-1"},
			{"tax_id": "P1", "bill_no": "B2", "base_amount": 10, "posting_date": date(2026, 1, 1),
				"rate": 2, "is_vat": 1, "purchase_invoice": "PI-2"},
			{"tax_id": "P2", "bill_no": "B1", "base_amount": 20, "posting_date": date(2026, 1, 1),
				"rate": 2, "is_vat": 1, "purchase_invoice": "PI-3"},
			{"tax_id": "P1", "bill_no": "B1", "base_amount": 999, "posting_date": date(2026, 2, 1),
				"rate": 7.5, "is_vat": 0, "purchase_invoice": "PI-1"},
			{"tax_id": "P3", "bill_no": None, "base_amount": 1, "posting_date": date(2026, 1, 1),
				"rate": 2, "is_vat": 1, "purchase_invoice": "PI-4"},
			{"tax_id": "P3", "bill_no": None, "base_amount": 2, "posting_date": date(2026, 1, 1),
				"rate": 2, "is_vat": 1, "purchase_invoice": "PI-5"},
		]
		merged = merge_vat_rows(rows)
		self.assertEqual(len(merged), 5)  # income tax row dropped; blank bill_no keyed by invoice
		first = merged[0]
		self.assertEqual(first["base_amount"], 100000.5)
		self.assertEqual(first["posting_date"], date(2026, 1, 5))
		self.assertEqual(first["purchase_invoice"], "PI-1")
		self.assertEqual(withheld(first["base_amount"], first["rate"]), 2001)
		self.assertEqual(rows[0]["base_amount"], 50000.25)  # input untouched

	def test_merge_vat_rows_refuses_mixed_rates(self):
		rows = [
			{"tax_id": "P1", "bill_no": "B9", "base_amount": 10, "rate": 2, "is_vat": 1},
			{"tax_id": "P1", "bill_no": "B9", "base_amount": 10, "rate": 3, "is_vat": 1},
		]
		with self.assertRaisesRegex(frappe.ValidationError, "B9"):
			merge_vat_rows(rows)


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


class _WithholdingCase(IntegrationTestCase):
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


class TestPaymentEntry(_WithholdingCase):
	def test_full_payment_posts_withholding(self):
		pi = _make_pi()
		self.assertEqual(pi.grand_total, 272200)
		pe = _make_pe(pi)
		self.assertEqual(pe.paid_amount, 272200 - 5444 - 19965)
		self.assertEqual(_deductions(pe), {VAT_ACC: -5444, RENT_ACC: -19965})
		self.assertEqual(pe.cecypo_total_withheld, 5444 + 19965)
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

	def test_withholding_more_than_allocated_refused(self):
		# Allocated 1 shilling: 2% and 7.5% each round up to 1, which would make the paid amount -1.
		pi = _make_pi()
		with self.assertRaisesRegex(frappe.ValidationError, "leaves nothing to pay"):
			_make_pe(pi, allocated=1, submit=False)

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

	def test_skip_withholding_works_like_an_exemption(self):
		pe = _make_pe(_make_pi(), submit=False)
		self.assertEqual(_deductions(pe), {VAT_ACC: -5444, RENT_ACC: -19965})
		pe.cecypo_skip_withholding = 1
		pe.save()
		self.assertEqual([r.account for r in pe.cecypo_withholding], [RENT_ACC])
		self.assertEqual(_deductions(pe), {RENT_ACC: -19965})
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

	def test_other_deduction_keeps_entry_balanced(self):
		pe = _pe(_make_pi())
		pe.append("deductions", {"account": "Bank Charges - _TC", "cost_center": "Main - _TC", "amount": 100})
		pe.insert(ignore_permissions=True)
		self.assertEqual(pe.difference_amount, 0)
		self.assertEqual(pe.unallocated_amount, 0)
		self.assertEqual(pe.paid_amount, 272200 - 5444 - 19965 + 100)
		pe.save()  # recompute must not stack the 100 twice
		self.assertEqual(pe.paid_amount, 272200 - 5444 - 19965 + 100)
		pe.submit()
		self.assertEqual(_deductions(pe)["Bank Charges - _TC"], 100)

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

	def test_feature_off_clears_stale_rows(self):
		pe = _make_pe(_make_pi(), submit=False)
		self.assertTrue(pe.cecypo_withholding)
		self._settings(enable_kenya_withholding=0)
		pe.save()
		self.assertEqual((pe.cecypo_withholding, pe.deductions, pe.paid_amount), ([], [], 272200))
		self.assertEqual(pe.cecypo_total_withheld, 0)
		self.assertEqual(pe.difference_amount, 0)

	def test_no_rules_for_company_clears_stale_rows(self):
		pe = _make_pe(_make_pi(), submit=False)
		self._settings(withholding_rules=[])
		pe.submit()
		self.assertEqual((pe.cecypo_withholding, pe.deductions, pe.paid_amount), ([], [], 272200))

	def test_switch_to_receive_clears_rows(self):
		from cecypo_powerpack.kenya_withholding import apply_to_payment_entry

		pe = _make_pe(_make_pi(), submit=False)
		pe.payment_type = "Receive"
		apply_to_payment_entry(pe)
		self.assertEqual((pe.cecypo_withholding, pe.deductions), ([], []))

	def test_invoice_split_over_reference_rows_withheld_once(self):
		from cecypo_powerpack.kenya_withholding import apply_to_payment_entry

		pe = _pe(_make_pi())
		ref = pe.references[0]
		ref.allocated_amount = 136100
		pe.append("references", {k: v for k, v in ref.as_dict().items() if k not in ("name", "idx")})
		apply_to_payment_entry(pe)
		# Per row, rent would be ceil(133,100 x 7.5%) = 9,983 twice = 19,966.
		self.assertEqual(_deductions(pe), {VAT_ACC: -5444, RENT_ACC: -19965})
		self.assertEqual(len(pe.cecypo_withholding), 2)
		self.assertEqual(pe.paid_amount, 272200 - 5444 - 19965)

	def test_manual_deduction_on_rule_account_kept_without_invoices(self):
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		from cecypo_powerpack.kenya_withholding import apply_to_payment_entry

		po = frappe.get_doc({
			"doctype": "Purchase Order", "company": COMPANY, "supplier": WHT_SUPPLIER,
			"schedule_date": frappe.utils.nowdate(),
			"items": [{"item_code": RENT_ITEM, "qty": 1, "rate": 10000}],
		}).insert(ignore_permissions=True)
		po.submit()
		pe = get_payment_entry("Purchase Order", po.name, bank_account=BANK)
		pe.append("deductions", {"account": RENT_ACC, "cost_center": "Main - _TC", "amount": 50})
		paid = pe.paid_amount
		apply_to_payment_entry(pe)
		self.assertEqual(_deductions(pe), {RENT_ACC: 50})
		self.assertEqual(pe.paid_amount, paid)

	def test_compute_refuses_other_doctypes(self):
		from cecypo_powerpack.kenya_withholding import compute_for_payment_entry

		with self.assertRaises(frappe.ValidationError):
			compute_for_payment_entry({"doctype": "Journal Entry", "company": COMPANY})

	def test_compute_checks_invoice_read_permission(self):
		from unittest.mock import patch

		from cecypo_powerpack.kenya_withholding import compute_for_payment_entry

		pe = _pe(_make_pi())
		real = frappe.has_permission

		def deny_pi(doctype, *args, **kwargs):
			if doctype == "Purchase Invoice":
				raise frappe.PermissionError
			return real(doctype, *args, **kwargs)

		with patch("frappe.has_permission", side_effect=deny_pi):
			with self.assertRaises(frappe.PermissionError):
				compute_for_payment_entry(pe.as_json())

	def test_compute_for_unsaved_entry(self):
		from cecypo_powerpack.kenya_withholding import compute_for_payment_entry

		pe = _pe(_make_pi())
		out = compute_for_payment_entry(pe.as_json())
		self.assertEqual(out["paid_amount"], 272200 - 5444 - 19965)
		self.assertEqual({d["account"]: d["amount"] for d in out["deductions"]}, {VAT_ACC: -5444, RENT_ACC: -19965})
		self.assertEqual(len(out["cecypo_withholding"]), 2)


class TestPayKRA(_WithholdingCase):
	def _pay(self, pes, vat=1, **kw):
		"""Pays the VAT rows (vat=1), the income tax rows (vat=0) or all (vat=None) of the entries."""
		from cecypo_powerpack.kenya_withholding import pay_kra

		today = frappe.utils.nowdate()
		names = [r.name for pe in pes for r in pe.cecypo_withholding if vat is None or r.is_vat == vat]
		args = {"bank_account": BANK, "posting_date": today, "prn": "PRN-1", "reference_date": today, **kw}
		return pay_kra(names, **args)

	def _report(self, pes, **filters):
		from cecypo_powerpack.cecypo_powerpack.report.withholding_due_to_kra.withholding_due_to_kra import execute

		columns, data, _message, _chart, cards = execute(frappe._dict(company=COMPANY, **filters))
		self.assertEqual(cards[-1]["label"], "Selected")
		self.assertIn("row_name", [c["fieldname"] for c in columns])
		names = {pe.name for pe in pes}
		return [r for r in data if r["payment_entry"] in names]

	def _je_lines(self, je):
		lines = {}
		for a in frappe.get_doc("Journal Entry", je).accounts:
			lines[a.account] = lines.get(a.account, 0) + a.debit - a.credit
		return lines

	def test_report_lists_unpaid_rows(self):
		from cecypo_powerpack.kenya_withholding import _holidays

		frappe.db.set_value("Supplier", WHT_SUPPLIER, "tax_id", "P051234567X")
		pe1 = _make_pe(_make_pi())
		pe2 = _make_pe(_make_pi(lines=((OTHER_ITEM, 6000),)))
		rows = self._report([pe1, pe2])
		self.assertEqual(len(rows), 3)
		today = frappe.utils.getdate()
		for r in rows:
			self.assertEqual(r["tax_id"], "P051234567X")
			self.assertEqual(r["supplier"], WHT_SUPPLIER)
			self.assertFalse(r["kra_journal_entry"])
			self.assertEqual(r["overdue"], 0)
			want = vat_due_date(today, _holidays(COMPANY)) if r["is_vat"] else income_tax_due_date(today)
			self.assertEqual(frappe.utils.getdate(r["due_date"]), want)
		self.assertEqual(sorted(r["amount"] for r in rows), [120, 5444, 19965])
		self.assertEqual(self._report([pe1, pe2], status="Paid"), [])

	def test_report_flags_overdue(self):
		pe = _make_pe(_make_pi())
		frappe.db.set_value("Payment Entry Withholding", pe.cecypo_withholding[0].name, "due_date", "2020-01-01")
		rows = {r["row_name"]: r for r in self._report([pe])}
		self.assertEqual(rows[pe.cecypo_withholding[0].name]["overdue"], 1)
		self.assertEqual(rows[pe.cecypo_withholding[1].name]["overdue"], 0)

	def test_pay_kra_posts_and_links(self):
		pe = _make_pe(_make_pi())
		je_name = self._pay([pe])
		je = frappe.get_doc("Journal Entry", je_name)
		self.assertEqual(je.docstatus, 1)
		self.assertEqual(je.voucher_type, "Bank Entry")
		self.assertEqual(je.cheque_no, "PRN-1")
		self.assertIn(pe.name, je.user_remark)
		self.assertEqual(je.cecypo_kra_payment, 1)
		self.assertEqual(self._je_lines(je_name), {VAT_ACC: 5444, BANK: -5444})
		vat, rent = pe.cecypo_withholding
		self.assertEqual(frappe.db.get_value("Payment Entry Withholding", vat.name, "kra_journal_entry"), je_name)
		self.assertFalse(frappe.db.get_value("Payment Entry Withholding", rent.name, "kra_journal_entry"))
		self.assertEqual([r["row_name"] for r in self._report([pe])], [rent.name])
		rent_je = self._pay([pe], vat=0)
		self.assertEqual(self._je_lines(rent_je), {RENT_ACC: 19965, BANK: -19965})
		self.assertEqual(self._report([pe]), [])
		self.assertEqual(len(self._report([pe], status="Paid")), 2)
		self.assertEqual(len(self._report([pe], status="All")), 2)

	def test_pay_kra_refuses_vat_and_income_tax_together(self):
		pe = _make_pe(_make_pi())
		with self.assertRaisesRegex(frappe.ValidationError, "VAT"):
			self._pay([pe], vat=None)

	def test_amending_kra_je_refused(self):
		pe = _make_pe(_make_pi())
		je = frappe.get_doc("Journal Entry", self._pay([pe]))
		je.cancel()
		amended = frappe.copy_doc(je)
		amended.amended_from, amended.docstatus = je.name, 0
		with self.assertRaisesRegex(frappe.ValidationError, "Pay KRA"):
			amended.insert()

	def test_pay_kra_preview_shows_bank_figure(self):
		from cecypo_powerpack.kenya_withholding import pay_kra_preview

		pi = _make_pi(lines=((OTHER_ITEM, 100000.50),), disable_rounded_total=1)
		pe1 = _make_pe(pi, allocated=50000.25)
		pe2 = _make_pe(pi)
		names = [r.name for pe in (pe1, pe2) for r in pe.cecypo_withholding]
		self.assertEqual(pay_kra_preview(names), {"bank": 2001, "withheld": 2002})

	def test_pay_kra_refuses_twice(self):
		pe = _make_pe(_make_pi())
		je_name = self._pay([pe])
		with self.assertRaisesRegex(frappe.ValidationError, je_name):
			self._pay([pe])
		pe2 = _make_pe(_make_pi())
		with self.assertRaises(frappe.ValidationError):
			self._pay([pe, pe2])  # one paid row in the batch refuses the whole batch
		self.assertFalse(frappe.db.get_value(
			"Payment Entry Withholding", pe2.cecypo_withholding[0].name, "kra_journal_entry"))

	def test_pay_kra_refuses_unknown_or_draft_rows(self):
		from cecypo_powerpack.kenya_withholding import pay_kra

		today = frappe.utils.nowdate()
		draft = _make_pe(_make_pi(), submit=False)
		for names in ([], ["no-such-row"], [draft.cecypo_withholding[0].name]):
			with self.assertRaises(frappe.ValidationError):
				pay_kra(names, BANK, today, "PRN-1", today)

	def test_pay_kra_refuses_non_bank_account(self):
		pe = _make_pe(_make_pi())
		with self.assertRaisesRegex(frappe.ValidationError, "Bank or Cash"):
			self._pay([pe], bank_account=VAT_ACC)
		self.assertFalse(frappe.db.get_value(
			"Payment Entry Withholding", pe.cecypo_withholding[0].name, "kra_journal_entry"))

	def test_kra_je_form_flag(self):
		from frappe.desk.form.load import run_onload

		pe = _make_pe(_make_pi())
		je = frappe.get_doc("Journal Entry", self._pay([pe]))
		run_onload(je)
		self.assertEqual(je.get_onload().get("is_kra_payment"), 1)
		je.cancel()
		je = frappe.get_doc("Journal Entry", je.name)
		run_onload(je)
		self.assertFalse(je.get_onload().get("is_kra_payment"))

	def test_pay_kra_merges_part_payments(self):
		pi = _make_pi(lines=((OTHER_ITEM, 100000.50),), disable_rounded_total=1)
		pe1 = _make_pe(pi, allocated=50000.25)
		pe2 = _make_pe(pi)
		self.assertEqual([r.base_amount for r in pe1.cecypo_withholding + pe2.cecypo_withholding], [50000.25, 50000.25])
		self.assertEqual([r.amount for r in pe1.cecypo_withholding + pe2.cecypo_withholding], [1001, 1001])
		je_name = self._pay([pe1, pe2])
		lines = self._je_lines(je_name)
		self.assertEqual(lines, {VAT_ACC: 2002, BANK: -withheld(100000.50, 2), "Round Off - _TC": -1})
		self.assertEqual(withheld(100000.50, 2), 2001)
		je = frappe.get_doc("Journal Entry", je_name)
		self.assertEqual(je.total_debit, je.total_credit)

	def test_cancel_kra_je_unlinks(self):
		pe = _make_pe(_make_pi())
		je_name = self._pay([pe])
		frappe.get_doc("Journal Entry", je_name).cancel()
		for r in pe.cecypo_withholding:
			self.assertFalse(frappe.db.get_value("Payment Entry Withholding", r.name, "kra_journal_entry"))
		self.assertEqual(len(self._report([pe])), 2)
		pe.reload()
		pe.cancel()  # unpaid again, so the Payment Entry can be cancelled

	def test_pay_kra_works_with_feature_disabled(self):
		pe = _make_pe(_make_pi())
		self._settings(enable_kenya_withholding=0)
		self.assertEqual(len(self._report([pe])), 2)
		je_name = self._pay([pe])
		self.assertEqual(frappe.db.get_value("Journal Entry", je_name, "docstatus"), 1)
		frappe.get_doc("Journal Entry", je_name).cancel()
		self.assertFalse(frappe.db.get_value(
			"Payment Entry Withholding", pe.cecypo_withholding[0].name, "kra_journal_entry"))


def _vat(tax_id, bill_no, base, paid, billed="2026-01-19", **kw):
	return {"tax_id": tax_id, "bill_no": bill_no, "base_amount": base, "posting_date": date.fromisoformat(paid),
		"bill_date": date.fromisoformat(billed), "rate": 2, "is_vat": 1, "supplier": tax_id,
		"purchase_invoice": "PI-" + bill_no, **kw}


class TestItaxCsv(_WithholdingCase):
	def test_csv_rows_match_itax_upload(self):
		from cecypo_powerpack.kenya_withholding import itax_csv_rows

		rows = [
			_vat("P051163409Z", "LPO/26/01/012", 126316.5776, "2026-01-22"),
			_vat("P000593951A", "905186226", 251195.1435, "2026-01-22", billed="2026-01-20"),
		]
		self.assertEqual(itax_csv_rows(rows), [
			["P051163409Z", "LPO/26/01/012", "19/01/2026", "126316.58", "22/01/2026"],
			["P000593951A", "905186226", "20/01/2026", "251195.14", "22/01/2026"],
		])

	def test_csv_merges_same_invoice(self):
		from cecypo_powerpack.kenya_withholding import itax_csv_rows

		rows = [_vat("P1", "B1", 50000.25, "2026-01-22"), _vat("P1", "B1", 50000.25, "2026-01-25")]
		self.assertEqual(itax_csv_rows(rows), [["P1", "B1", "19/01/2026", "100000.50", "25/01/2026"]])

	def test_csv_skips_income_tax_rows(self):
		from cecypo_powerpack.kenya_withholding import itax_csv_rows

		self.assertEqual(itax_csv_rows([_vat("P1", "B1", 10, "2026-01-22", is_vat=0)]), [])

	def test_export_blocks_missing_pin(self):
		from cecypo_powerpack.kenya_withholding import export_itax_csv

		frappe.db.set_value("Supplier", WHT_SUPPLIER, "tax_id", "")
		pe = _make_pe(_make_pi())
		with self.assertRaisesRegex(frappe.ValidationError, WHT_SUPPLIER):
			export_itax_csv([r.name for r in pe.cecypo_withholding])

	def test_export_blocks_blank_pin(self):
		from cecypo_powerpack.kenya_withholding import export_itax_csv

		frappe.db.set_value("Supplier", WHT_SUPPLIER, "tax_id", "   ")
		pe = _make_pe(_make_pi())
		with self.assertRaisesRegex(frappe.ValidationError, WHT_SUPPLIER):
			export_itax_csv([r.name for r in pe.cecypo_withholding])

	def test_export_refuses_no_vat_rows(self):
		from cecypo_powerpack.kenya_withholding import export_itax_csv

		frappe.db.set_value("Supplier", WHT_SUPPLIER, "tax_id", "P051234567X")
		pe = _make_pe(_make_pi())
		frappe.response.pop("filecontent", None)
		with self.assertRaisesRegex(frappe.ValidationError, "No VAT withholding rows"):
			export_itax_csv([r.name for r in pe.cecypo_withholding if not r.is_vat])
		self.assertNotIn("filecontent", frappe.response)

	def test_check_refuses_what_export_refuses(self):
		from cecypo_powerpack.kenya_withholding import check_itax_export

		frappe.db.set_value("Supplier", WHT_SUPPLIER, "tax_id", "P051234567X")
		pe = _make_pe(_make_pi())
		frappe.response.pop("filecontent", None)
		with self.assertRaisesRegex(frappe.ValidationError, "No VAT withholding rows"):
			check_itax_export([r.name for r in pe.cecypo_withholding if not r.is_vat])
		check_itax_export([r.name for r in pe.cecypo_withholding])  # has a VAT row: passes
		self.assertNotIn("filecontent", frappe.response)  # a check, never the download
		frappe.db.set_value("Supplier", WHT_SUPPLIER, "tax_id", "")
		with self.assertRaisesRegex(frappe.ValidationError, WHT_SUPPLIER):
			check_itax_export([r.name for r in pe.cecypo_withholding])

	def test_export_bytes_crlf_no_header(self):
		from cecypo_powerpack.kenya_withholding import export_itax_csv

		frappe.db.set_value("Supplier", WHT_SUPPLIER, "tax_id", "P051234567X")
		pi = _make_pi()
		pe = _make_pe(pi)
		export_itax_csv([r.name for r in pe.cecypo_withholding])  # the Rent row is income tax: skipped
		today = frappe.utils.getdate()
		self.assertEqual(frappe.response["type"], "download")
		self.assertEqual(frappe.response["filename"], f"WHT-VAT-{today.strftime('%d-%m-%Y')}.csv")
		d = today.strftime("%d/%m/%Y")
		self.assertEqual(frappe.response["filecontent"], f"P051234567X,{pi.bill_no},{d},272200.00,{d}\r\n".encode())
