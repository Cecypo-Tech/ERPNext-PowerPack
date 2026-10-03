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
		self.assertEqual(
			{d for d, _ in SCRIPTS.values()}, {"Quotation", "Sales Order", "Sales Invoice", "Purchase Order"}
		)

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

	def test_every_script_adds_copy_as_message_under_powerup(self):
		for name in SCRIPTS:
			src = script_source(name)
			self.assertIn("__('Copy as Message')", src)
			self.assertIn("__('Powerup')", src)

	def test_sales_scripts_start_with_an_empty_payment_details_block(self):
		# The app ships no bank details; the site fills in its own. (Purchase Order has
		# NOTES instead: see the test below.)
		for name, (doctype, _) in SCRIPTS.items():
			if doctype != "Purchase Order":
				self.assertIn("const PAYMENT_DETAILS = {\n\t};", script_source(name))

	def test_purchase_order_message_is_for_the_supplier(self):
		# We pay the supplier, so no payment details; a per-company NOTES block carries
		# delivery instructions instead, shipped empty like PAYMENT_DETAILS.
		src = script_source("PowerPack - Copy as Message (Purchase Order)")
		self.assertIn("frappe.ui.form.on('Purchase Order'", src)
		self.assertIn("doc.supplier_name", src)
		self.assertIn("const NOTES = {\n\t};", src)
		self.assertNotIn("PAYMENT_DETAILS", src)
		self.assertNotIn("doc.customer", src)
		# internal fulfilment statuses mean nothing to a supplier
		self.assertIn("['On Hold', 'Closed'].includes(doc.status)", src)

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


MATCHING = "frm.add_custom_button(__('Copy as Message'), () => do_copy(frm), __('Powerup'));"


class TestGetCopyMessageScript(FrappeTestCase):
	"""get_copy_message_script hands the print preview the same script source the desk
	form runs, found the way klik_pos finds it: an enabled Form Client Script whose
	source adds a 'Copy as Message' button, the seeded name first."""

	DOCTYPE = "Sales Invoice"

	def setUp(self):
		# Start from a site with no Client Scripts on the doctype at all.
		frappe.db.delete("Client Script", {"dt": self.DOCTYPE})

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _script(self, name, script=MATCHING, enabled=1, view="Form"):
		frappe.get_doc(
			{
				"doctype": "Client Script",
				"name": name,
				"dt": self.DOCTYPE,
				"view": view,
				"enabled": enabled,
				"script": script,
			}
		).insert(set_name=name)

	def get(self):
		return copy_as_message.get_copy_message_script(self.DOCTYPE)

	def test_none_when_the_doctype_has_no_scripts(self):
		self.assertIsNone(self.get())

	def test_finds_an_enabled_form_script_that_adds_the_button(self):
		self._script("Site copy message")
		self.assertEqual(self.get(), MATCHING)

	def test_matches_the_unwrapped_label_too(self):
		# A site edit may drop __(): add_custom_button("Copy as Message", ...)
		self._script("Site copy message", script='frm.add_custom_button("Copy as Message", fn);')
		self.assertIsNotNone(self.get())

	def test_prefers_the_seeded_name_over_an_alphabetically_earlier_match(self):
		self._script("AAA copy message", script=MATCHING + " // site copy")
		self._script(f"PowerPack - Copy as Message ({self.DOCTYPE})", script=MATCHING + " // seeded")
		self.assertTrue(self.get().endswith("// seeded"))

	def test_falls_back_to_another_matching_script_when_the_seeded_one_is_disabled(self):
		self._script(f"PowerPack - Copy as Message ({self.DOCTYPE})", enabled=0)
		self._script("Site copy message", script=MATCHING + " // site copy")
		self.assertTrue(self.get().endswith("// site copy"))

	def test_ignores_disabled_list_view_and_non_matching_scripts(self):
		self._script("Disabled", enabled=0)
		self._script("List view", view="List")
		self._script("No button", script="frm.add_custom_button(__('Something Else'), fn);")
		self.assertIsNone(self.get())

	def test_none_without_read_permission_on_the_doctype(self):
		self._script("Site copy message")
		frappe.set_user("Guest")
		self.assertIsNone(self.get())
