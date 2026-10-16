import frappe
from frappe.tests import IntegrationTestCase

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
