# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""PowerPack Permission Manager — server side.

Throwaway doctypes come from frappe's own new_doctype() helper: they are created
inside the test transaction and rolled back with it, and a fresh doctype is the
only way to be sure a doctype has standard rules and NO Custom DocPerm rows.
"""

import frappe
from frappe.core.doctype.doctype.test_doctype import new_doctype
from frappe.tests.utils import FrappeTestCase

SM = "Administrator"


def make_user(email, roles):
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "PP Perm", "send_welcome_email": 0}
		)
		for r in roles:
			user.append("roles", {"role": r})
		user.insert(ignore_permissions=True)
	return email


def perm(role, **flags):
	"""DocPerm defaults read, write, create AND delete to 1 (docperm.json), so a rule
	written as {"role": r, "read": 1} silently grants delete. Start every test rule
	from explicit zeros so a test states exactly what it grants."""
	return {"role": role, "read": 0, "write": 0, "create": 0, "delete": 0, **flags}


def make_role(name, gate_read=False, gate_write=False):
	"""A role that can (or cannot) read/write the grid's gate doctype, granted the way
	an admin would grant it: a Custom DocPerm row on READ_GATE_DOCTYPE."""
	from cecypo_powerpack.permission_manager import READ_GATE_DOCTYPE

	if not frappe.db.exists("Role", name):
		frappe.get_doc({"doctype": "Role", "role_name": name, "desk_access": 1}).insert(
			ignore_permissions=True
		)
	if gate_read or gate_write:
		from frappe.permissions import add_permission, update_permission_property

		add_permission(READ_GATE_DOCTYPE, name, 0)
		update_permission_property(READ_GATE_DOCTYPE, name, 0, "read", 1 if gate_read else 0)
		update_permission_property(READ_GATE_DOCTYPE, name, 0, "write", 1 if gate_write else 0)
	return name


class TestReadRules(FrappeTestCase):
	def setUp(self):
		frappe.set_user(SM)
		self.dt = new_doctype(permissions=[perm("Sales User", read=1, write=1)])
		self.dt.insert()

	def tearDown(self):
		frappe.set_user(SM)

	def test_row_shape(self):
		from cecypo_powerpack.permission_manager import FLAGS, get_permission_rules

		out = get_permission_rules()
		self.assertTrue(out["can_edit"])
		rows = [r for r in out["rows"] if r["doctype"] == self.dt.name]
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row["role"], "Sales User")
		self.assertEqual(row["permlevel"], 0)
		self.assertEqual(row["if_owner"], 0)
		self.assertEqual(row["module"], "Core")
		self.assertEqual(row["is_submittable"], 0)
		for flag in FLAGS:
			self.assertIn(flag, row)
		self.assertEqual(row["read"], 1)
		self.assertEqual(row["write"], 1)
		self.assertEqual(row["delete"], 0)

	def test_standard_rows_reported_as_not_custom(self):
		from cecypo_powerpack.permission_manager import get_permission_rules

		row = next(r for r in get_permission_rules()["rows"] if r["doctype"] == self.dt.name)
		self.assertEqual(row["is_custom"], 0)

	def test_custom_rows_replace_standard_rows(self):
		"""Frappe semantics: once a doctype has any Custom DocPerm, those rows ARE its
		permissions and the standard rows no longer apply. The grid must mirror that."""
		from frappe.permissions import update_permission_property

		from cecypo_powerpack.permission_manager import get_permission_rules

		update_permission_property(self.dt.name, "Sales User", 0, "delete", 1)
		rows = [r for r in get_permission_rules()["rows"] if r["doctype"] == self.dt.name]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["is_custom"], 1)
		self.assertEqual(rows[0]["delete"], 1)

	def test_child_tables_excluded(self):
		from cecypo_powerpack.permission_manager import get_permission_rules

		child = new_doctype(istable=1)
		child.insert()
		self.assertFalse(any(r["doctype"] == child.name for r in get_permission_rules()["rows"]))


class TestReadGate(FrappeTestCase):
	def setUp(self):
		frappe.set_user(SM)
		self.viewer_role = make_role("PP Perm Viewer", gate_read=True)
		self.nobody_role = make_role("PP Perm Nobody")
		self.viewer = make_user("pp-perm-viewer@example.com", [self.viewer_role])
		self.nobody = make_user("pp-perm-nobody@example.com", [self.nobody_role])
		frappe.clear_cache()

	def tearDown(self):
		frappe.set_user(SM)

	def test_role_with_gate_read_can_view_but_not_edit(self):
		from cecypo_powerpack.permission_manager import get_permission_rules

		frappe.set_user(self.viewer)
		out = get_permission_rules()
		self.assertGreater(len(out["rows"]), 0)
		self.assertFalse(out["can_edit"])

	def test_role_without_gate_read_is_rejected(self):
		from cecypo_powerpack.permission_manager import get_permission_rules

		frappe.set_user(self.nobody)
		with self.assertRaises(frappe.PermissionError):
			get_permission_rules()


class TestPreview(FrappeTestCase):
	def setUp(self):
		frappe.set_user(SM)
		self.dt = new_doctype(permissions=[perm("Sales User", read=1)])
		self.dt.insert()
		self.rule = {"doctype": self.dt.name, "role": "Sales User", "permlevel": 0, "if_owner": 0}

	def tearDown(self):
		frappe.set_user(SM)

	def test_preview_lists_rules_and_newly_detached_doctypes(self):
		from cecypo_powerpack.permission_manager import preview_changes

		out = preview_changes([{**self.rule, "changes": {"write": 1}}])
		self.assertEqual(len(out["rules"]), 1)
		self.assertEqual(out["rules"][0]["changes"], {"write": 1})
		self.assertEqual(out["detaching"], [{"doctype": self.dt.name, "standard_rules": 1}])

	def test_already_custom_doctype_is_not_listed_as_detaching(self):
		from frappe.permissions import update_permission_property

		from cecypo_powerpack.permission_manager import preview_changes

		update_permission_property(self.dt.name, "Sales User", 0, "write", 1)
		out = preview_changes([{**self.rule, "changes": {"delete": 1}}])
		self.assertEqual(out["detaching"], [])

	def test_accepts_json_string_payload(self):
		"""frappe.call sends nested args as JSON strings."""
		from cecypo_powerpack.permission_manager import preview_changes

		out = preview_changes(frappe.as_json([{**self.rule, "changes": {"write": 1}}]))
		self.assertEqual(len(out["rules"]), 1)

	def test_unknown_flag_rejected(self):
		from cecypo_powerpack.permission_manager import preview_changes

		with self.assertRaises(frappe.ValidationError):
			preview_changes([{**self.rule, "changes": {"if_owner": 1}}])
		with self.assertRaises(frappe.ValidationError):
			preview_changes([{**self.rule, "changes": {"launch_missiles": 1}}])

	def test_unknown_rule_rejected(self):
		from cecypo_powerpack.permission_manager import preview_changes

		with self.assertRaises(frappe.ValidationError):
			preview_changes([{**self.rule, "role": "Stock User", "changes": {"read": 1}}])

	def test_empty_changes_dropped(self):
		from cecypo_powerpack.permission_manager import preview_changes

		self.assertEqual(preview_changes([{**self.rule, "changes": {}}])["rules"], [])

	def test_preview_requires_system_manager(self):
		from cecypo_powerpack.permission_manager import preview_changes

		viewer = make_user("pp-perm-viewer@example.com", [make_role("PP Perm Viewer", gate_read=True)])
		frappe.set_user(viewer)
		with self.assertRaises(frappe.PermissionError):
			preview_changes([{**self.rule, "changes": {"write": 1}}])


def custom_flag(doctype, role, flag, permlevel=0, if_owner=0):
	return frappe.db.get_value(
		"Custom DocPerm",
		{"parent": doctype, "role": role, "permlevel": permlevel, "if_owner": if_owner},
		flag,
	)


class TestCommit(FrappeTestCase):
	def setUp(self):
		frappe.set_user(SM)
		self.a = new_doctype(permissions=[perm("Sales User", read=1), perm("Stock User", read=1)])
		self.a.insert()
		self.b = new_doctype(permissions=[perm("Sales User", read=1)])
		self.b.insert()

	def tearDown(self):
		frappe.set_user(SM)

	def rule(self, dt, role, **changes):
		return {"doctype": dt.name, "role": role, "permlevel": 0, "if_owner": 0, "changes": changes}

	def test_commit_applies_every_change_across_doctypes(self):
		from cecypo_powerpack.permission_manager import commit_changes

		out = commit_changes(
			[
				self.rule(self.a, "Sales User", write=1, delete=1),
				self.rule(self.a, "Stock User", write=1),
				self.rule(self.b, "Sales User", write=1),
			]
		)
		self.assertEqual(out["doctypes"], 2)
		self.assertEqual(out["rules"], 3)
		self.assertEqual(sorted(out["detached"]), sorted([self.a.name, self.b.name]))
		self.assertEqual(custom_flag(self.a.name, "Sales User", "write"), 1)
		self.assertEqual(custom_flag(self.a.name, "Sales User", "delete"), 1)
		self.assertEqual(custom_flag(self.a.name, "Stock User", "write"), 1)
		self.assertEqual(custom_flag(self.b.name, "Sales User", "write"), 1)
		# untouched rows on a detached doctype are copied verbatim, not lost
		self.assertEqual(custom_flag(self.a.name, "Stock User", "read"), 1)

	def test_commit_detaches_the_doctype_once(self):
		from cecypo_powerpack.permission_manager import commit_changes

		commit_changes([self.rule(self.a, "Sales User", write=1)])
		self.assertEqual(frappe.db.count("Custom DocPerm", {"parent": self.a.name}), 2)

	def test_failure_rolls_back_every_doctype_in_the_payload(self):
		"""Second doctype's change breaks a frappe rule (cancel without submit).
		The first doctype must come out untouched — not even detached."""
		from cecypo_powerpack.permission_manager import commit_changes

		with self.assertRaises(frappe.ValidationError):
			commit_changes(
				[
					self.rule(self.a, "Sales User", write=1),
					self.rule(self.b, "Sales User", cancel=1),
				]
			)
		self.assertFalse(frappe.db.exists("Custom DocPerm", {"parent": self.a.name}))
		self.assertFalse(frappe.db.exists("Custom DocPerm", {"parent": self.b.name}))

	def test_clearing_last_basic_right_is_rejected(self):
		from cecypo_powerpack.permission_manager import commit_changes

		with self.assertRaises(frappe.ValidationError):
			commit_changes([self.rule(self.a, "Sales User", read=0)])

	def test_noop_payload_writes_nothing(self):
		from cecypo_powerpack.permission_manager import commit_changes

		out = commit_changes([self.rule(self.a, "Sales User", read=1)])  # already 1
		self.assertEqual(out, {"doctypes": 0, "rules": 0, "detached": []})
		self.assertFalse(frappe.db.exists("Custom DocPerm", {"parent": self.a.name}))

	def test_grid_reflects_the_commit(self):
		from cecypo_powerpack.permission_manager import commit_changes, get_permission_rules

		commit_changes([self.rule(self.a, "Sales User", write=1)])
		row = next(
			r
			for r in get_permission_rules()["rows"]
			if r["doctype"] == self.a.name and r["role"] == "Sales User"
		)
		self.assertEqual((row["is_custom"], row["write"]), (1, 1))

	def test_commit_requires_system_manager_even_with_gate_write(self):
		from cecypo_powerpack.permission_manager import commit_changes

		editor = make_user(
			"pp-perm-editor@example.com",
			[make_role("PP Perm Editor", gate_read=True, gate_write=True)],
		)
		frappe.set_user(editor)
		with self.assertRaises(frappe.PermissionError):
			commit_changes([self.rule(self.a, "Sales User", write=1)])
