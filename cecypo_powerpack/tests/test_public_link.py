# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from cecypo_powerpack.api import get_document_public_link

# Always present, and readable only by System Manager - a plain desk user cannot read it.
DOCTYPE, NAME = "Role", "System Manager"
NO_ACCESS_USER = "pp-public-link-no-access@example.com"


def _short_links():
	return frappe.db.count("PowerPack Short Link", {"reference_doctype": DOCTYPE, "reference_docname": NAME})


class TestGetDocumentPublicLink(FrappeTestCase):
	"""The whitelisted endpoint mints a guest-viewable link, so it must check read access.

	Without the check any logged-in user could call it with any doctype and name and get
	a public link to a document they cannot open themselves.
	"""

	def setUp(self):
		if not frappe.db.exists("User", NO_ACCESS_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": NO_ACCESS_USER,
					"first_name": "No Access",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		frappe.db.delete("PowerPack Short Link", {"reference_doctype": DOCTYPE, "reference_docname": NAME})

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_refuses_a_user_who_cannot_read_the_document(self):
		frappe.set_user(NO_ACCESS_USER)

		with self.assertRaises(frappe.PermissionError):
			get_document_public_link(DOCTYPE, NAME)

		frappe.set_user("Administrator")
		self.assertEqual(_short_links(), 0)

	def test_refuses_even_when_a_link_already_exists(self):
		# The reuse path returns before anything is created - it must be guarded too.
		get_document_public_link(DOCTYPE, NAME)
		frappe.set_user(NO_ACCESS_USER)

		with self.assertRaises(frappe.PermissionError):
			get_document_public_link(DOCTYPE, NAME)

	def test_returns_a_link_for_a_user_who_can_read_it(self):
		url = get_document_public_link(DOCTYPE, NAME)

		self.assertIn("/s/", url)
		self.assertEqual(_short_links(), 1)

	def test_print_formats_can_still_render_the_link_as_guest(self):
		# A share-key web view renders the print format as Guest. The Jinja method keeps
		# the name print formats already call, and must not check permission.
		from frappe.utils.jinja import get_jinja_hooks

		methods, _ = get_jinja_hooks()
		jinja_fn = methods["get_document_public_link"]
		frappe.set_user("Guest")

		self.assertIn("/s/", jinja_fn(DOCTYPE, NAME))
