# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from cecypo_powerpack import copy_as_message
from cecypo_powerpack.copy_as_message import LEGACY_SCRIPTS, SCRIPTS, script_source, seed_client_scripts


class TestSeedCopyAsMessage(FrappeTestCase):
	"""The Copy as Message Client Scripts are created once and then belong to the site.

	They are deliberately not fixtures: sync_fixtures runs with force=True on every
	migrate, which would put back the app's copy over a site's edits (bank details)
	and re-enable a script the site switched off.
	"""

	def setUp(self):
		# Start from a site that has never had any of them.
		for name in (*SCRIPTS, *LEGACY_SCRIPTS):
			frappe.db.delete("Client Script", {"name": name})

	def tearDown(self):
		frappe.db.rollback()

	def test_creates_one_enabled_form_script_per_doctype(self):
		seed_client_scripts()

		for name, (doctype, _) in SCRIPTS.items():
			cs = frappe.get_doc("Client Script", name)
			self.assertEqual(cs.dt, doctype)
			self.assertEqual(cs.view, "Form")
			self.assertEqual(cs.enabled, 1)
			self.assertEqual(cs.script, script_source(name))
		self.assertEqual({d for d, _ in SCRIPTS.values()}, {"Quotation", "Sales Order", "Sales Invoice"})

	def test_scripts_are_not_picked_up_by_the_client_script_fixture_filter(self):
		# hooks.py exports Client Scripts with module "Cecypo PowerPack" as fixtures.
		seed_client_scripts()

		for name in SCRIPTS:
			self.assertNotEqual(frappe.db.get_value("Client Script", name, "module"), "Cecypo PowerPack")

	def test_never_overwrites_a_script_the_site_has_edited_or_disabled(self):
		seed_client_scripts()
		name = next(iter(SCRIPTS))
		frappe.db.set_value("Client Script", name, {"script": "// site's own version", "enabled": 0})

		seed_client_scripts()

		cs = frappe.get_doc("Client Script", name)
		self.assertEqual(cs.script, "// site's own version")
		self.assertEqual(cs.enabled, 0)

	def test_disables_but_keeps_the_legacy_sales_invoice_script(self):
		legacy = next(iter(LEGACY_SCRIPTS))
		frappe.get_doc(
			{
				"doctype": "Client Script",
				"name": legacy,
				"dt": "Sales Invoice",
				"view": "Form",
				"enabled": 1,
				"script": "// old bank details",
			}
		).insert(set_name=legacy)

		seed_client_scripts()

		self.assertEqual(frappe.db.get_value("Client Script", legacy, "enabled"), 0)
		self.assertEqual(frappe.db.get_value("Client Script", legacy, "script"), "// old bank details")

	def test_every_script_starts_with_an_empty_payment_details_block(self):
		# The app ships no bank details; the site fills in its own.
		for name in SCRIPTS:
			src = script_source(name)
			self.assertIn("const PAYMENT_DETAILS = {\n\t};", src)
			self.assertIn("__('Copy as Message')", src)
			self.assertIn("__('Powerup')", src)

	def test_a_deleted_script_comes_back_as_the_shipped_version(self):
		# Deleting is how a site resets a script to the latest shipped version.
		seed_client_scripts()
		name = next(iter(SCRIPTS))
		frappe.delete_doc("Client Script", name)

		seed_client_scripts()

		self.assertEqual(frappe.db.get_value("Client Script", name, "script"), script_source(name))

	def test_a_legacy_script_turned_back_on_stays_on(self):
		# The legacy script is disabled once, when its replacement is created - not on
		# every migrate, which would fight a site that deliberately re-enabled it.
		seed_client_scripts()
		legacy = next(iter(LEGACY_SCRIPTS))
		frappe.get_doc(
			{"doctype": "Client Script", "name": legacy, "dt": "Sales Invoice", "view": "Form", "enabled": 1}
		).insert(set_name=legacy)

		seed_client_scripts()

		self.assertEqual(frappe.db.get_value("Client Script", legacy, "enabled"), 1)

	def test_seeded_on_install_and_on_every_migrate(self):
		from cecypo_powerpack import hooks

		self.assertIn("cecypo_powerpack.copy_as_message.seed_client_scripts", hooks.after_install)
		self.assertIn("cecypo_powerpack.copy_as_message.seed_client_scripts", hooks.after_migrate)
		self.assertTrue(callable(copy_as_message.seed_client_scripts))
