# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""PowerPack Settings must stay readable for users scoped by User Permissions.

PowerPack Settings is a singleton whose child tables hold *configuration*: which
item groups get a selling-price floor, which companies get an accent border. Those
rows legitimately name records the reader is not scoped to — "All Item Groups" in a
floor rule, another company in a border rule.

frappe.permissions.has_user_permission() walks every Link field of a document AND of
all its child rows, so without ignore_user_permissions on those two fields a single
User Permission on Item Group (or Company) makes the whole singleton unreadable. As
frappe.has_permission() resolves a Single to its doc even when no doc is passed, that
takes down every read path — frappe.client.get, get_single_value, the desk form load
— and with them every PowerPack feature gated behind Settings.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

SETTINGS = "PowerPack Settings"


def _make_user(email, role):
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "PowerPack Perm Test",
				"send_welcome_email": 0,
			}
		)
		user.append("roles", {"role": role})
		user.insert(ignore_permissions=True)
	return email


def _restrict(user, allow, for_value):
	if not frappe.db.exists(
		"User Permission", {"user": user, "allow": allow, "for_value": for_value}
	):
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user,
				"allow": allow,
				"for_value": for_value,
			}
		).insert(ignore_permissions=True)


class TestSettingsIgnoresUserPermissions(FrappeTestCase):
	"""The two config link fields must be flagged so the checker skips them."""

	def test_min_selling_price_rule_item_group_ignores_user_permissions(self):
		field = frappe.get_meta("Minimum Selling Price Rule").get_field("item_group")
		self.assertTrue(
			field.ignore_user_permissions,
			"Minimum Selling Price Rule.item_group must set ignore_user_permissions, "
			"or any User Permission on Item Group makes PowerPack Settings unreadable",
		)

	def test_company_border_company_ignores_user_permissions(self):
		field = frappe.get_meta("Powerpack Company Border").get_field("company")
		self.assertTrue(
			field.ignore_user_permissions,
			"Powerpack Company Border.company must set ignore_user_permissions, "
			"or any User Permission on Company makes PowerPack Settings unreadable",
		)


class TestSettingsReadableUnderUserPermissions(FrappeTestCase):
	"""End-to-end: the permission check itself must pass for a scoped user."""

	def setUp(self):
		self.settings = frappe.get_single(SETTINGS)
		self.item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		if not self.item_group:
			self.skipTest("no leaf Item Group on this site")

		# A rule pointing at a group the user is NOT scoped to is the trigger.
		self.settings.set("min_selling_price_rules", [])
		self.settings.append(
			"min_selling_price_rules",
			{"item_group": "All Item Groups", "basis": "Valuation Rate", "floor_percent": 10},
		)
		self.settings.save(ignore_permissions=True)
		frappe.clear_cache(doctype=SETTINGS)

		self.user = _make_user("powerpack-perm-test@example.com", "Sales User")
		_restrict(self.user, "Item Group", self.item_group)
		frappe.clear_cache(user=self.user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_scoped_user_can_read_settings(self):
		frappe.set_user(self.user)
		self.assertTrue(
			frappe.has_permission(SETTINGS, "read"),
			"a user restricted to one Item Group must still be able to read "
			"PowerPack Settings",
		)

	def test_scoped_user_passes_user_permission_check_on_the_doc(self):
		from frappe.permissions import has_user_permission

		frappe.set_user(self.user)
		doc = frappe.get_doc(SETTINGS)
		self.assertTrue(
			has_user_permission(doc, self.user, ptype="read"),
			"the child-row Item Group link must not fail the User Permission check",
		)

	def test_client_get_single_value_succeeds_for_scoped_user(self):
		"""The POS reads the feature flag through this exact whitelisted path."""
		from frappe.client import get_single_value

		frappe.set_user(self.user)
		# Raises frappe.PermissionError("No permission for PowerPack Settings") on regression.
		get_single_value(SETTINGS, "enable_pos_powerup")
