# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from cecypo_powerpack.api import PARTY_STATEMENT_SCRIPT, get_party_statement_script


class TestPartyStatementScript(FrappeTestCase):
	"""Customer Info formats Copy/Email/Image with the site's statement script, which
	Cecypo Frappe Reports seeds. PowerPack only reads it; it never creates it."""

	def setUp(self):
		frappe.db.delete("Client Script", {"name": PARTY_STATEMENT_SCRIPT})

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _script(self, enabled=1):
		frappe.get_doc(
			{
				"doctype": "Client Script",
				"name": PARTY_STATEMENT_SCRIPT,
				"dt": "Customer",
				"view": "Form",
				"enabled": enabled,
				"script": "// statement",
			}
		).insert(ignore_permissions=True, set_name=PARTY_STATEMENT_SCRIPT)

	def test_returns_source_when_enabled(self):
		self._script()
		self.assertEqual(get_party_statement_script(), "// statement")

	def test_none_when_disabled_or_missing(self):
		self.assertIsNone(get_party_statement_script())
		self._script(enabled=0)
		self.assertIsNone(get_party_statement_script())

	def test_requires_sales_invoice_read(self):
		self._script()
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			get_party_statement_script()
