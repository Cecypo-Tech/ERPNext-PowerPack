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

	def test_report_rejected_when_if_owner_is_set(self):
		"""I-3: frappe enforces this invariant only in its own page endpoint
		(frappe/core/page/permission_manager/permission_manager.py:147), not in
		validate_permissions(), so committing straight to Custom DocPerm never inherits
		it. We must enforce it ourselves."""
		from cecypo_powerpack.permission_manager import preview_changes

		dt = new_doctype(permissions=[{**perm("Sales User", read=1), "if_owner": 1}])
		dt.insert()
		rule = {"doctype": dt.name, "role": "Sales User", "permlevel": 0, "if_owner": 1}
		with self.assertRaises(frappe.ValidationError):
			preview_changes([{**rule, "changes": {"report": 1}}])


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
		self.assertEqual(out, {"doctypes": 0, "rules": 0, "added": 0, "removed": 0, "detached": []})
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

	def test_validate_permissions_corrections_are_persisted(self):
		"""I-2: validate_permissions() zeroes create/submit/cancel/amend at permlevel > 0
		in place, but never saves the change itself; stock frappe persists it via
		db_update() in validate_permissions_for_doctype() and we must do the same, or
		the correction to Custom DocPerm is silently dropped.

		DocType.validate() already runs validate_permissions() on its own standard
		DocPerm rows before insert, so a permlevel-1 "create": 1 row built through
		new_doctype() directly would already arrive zeroed — that codepath cannot
		produce the dirty fixture this test needs. Detach with setup_custom_perms()
		first (copying the level-0 row across untouched) and insert the level-1
		Custom DocPerm row directly: Custom DocPerm has no validate() hook of its own,
		so its `create` reaches us still dirty."""
		from frappe.permissions import setup_custom_perms

		from cecypo_powerpack.permission_manager import commit_changes

		dt = new_doctype(permissions=[perm("Sales User", read=1)])
		dt.insert()
		setup_custom_perms(dt.name)
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": dt.name,
				"parenttype": "DocType",
				"parentfield": "permissions",
				**perm("Sales User", create=1),
				"permlevel": 1,
			}
		).insert(ignore_permissions=True)
		self.assertEqual(custom_flag(dt.name, "Sales User", "create", permlevel=1), 1)

		commit_changes(
			[{"doctype": dt.name, "role": "Sales User", "permlevel": 1, "if_owner": 0, "changes": {"read": 1}}]
		)
		self.assertEqual(custom_flag(dt.name, "Sales User", "read", permlevel=1), 1)
		self.assertEqual(custom_flag(dt.name, "Sales User", "create", permlevel=1), 0)

	def test_if_owner_disambiguates_identical_role_and_permlevel(self):
		"""I-5: a doctype can carry both an if_owner=0 and an if_owner=1 rule for the
		same role and permlevel; committing to one must not touch the other."""
		from cecypo_powerpack.permission_manager import commit_changes

		dt = new_doctype(
			permissions=[
				perm("Sales User", read=1),
				{**perm("Sales User", read=1), "if_owner": 1},
			]
		)
		dt.insert()
		commit_changes(
			[{"doctype": dt.name, "role": "Sales User", "permlevel": 0, "if_owner": 1, "changes": {"write": 1}}]
		)
		self.assertEqual(custom_flag(dt.name, "Sales User", "write", if_owner=0), 0)
		self.assertEqual(custom_flag(dt.name, "Sales User", "write", if_owner=1), 1)


class TestParseOps(FrappeTestCase):
	def setUp(self):
		frappe.set_user(SM)
		self.dt = new_doctype(permissions=[perm("Sales User", read=1), perm("Stock User", read=1)])
		self.dt.insert()

	def tearDown(self):
		frappe.set_user(SM)

	def op(self, op, role, **extra):
		return {"op": op, "doctype": self.dt.name, "role": role, "permlevel": 0, "if_owner": 0, **extra}

	def test_missing_op_still_means_update(self):
		"""The existing client sends no op at all; that contract must not break."""
		from cecypo_powerpack.permission_manager import _parse_changes

		out = _parse_changes(
			[{"doctype": self.dt.name, "role": "Sales User", "permlevel": 0, "if_owner": 0, "changes": {"write": 1}}]
		)
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["op"], "update")

	def test_unknown_op_rejected(self):
		from cecypo_powerpack.permission_manager import _parse_changes

		with self.assertRaises(frappe.ValidationError):
			_parse_changes([self.op("obliterate", "Sales User")])

	def test_add_is_parsed(self):
		from cecypo_powerpack.permission_manager import _parse_changes

		out = _parse_changes([self.op("add", "Accounts User")])
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["op"], "add")
		self.assertEqual(out[0]["role"], "Accounts User")

	def test_add_of_an_existing_rule_rejected(self):
		from cecypo_powerpack.permission_manager import _parse_changes

		with self.assertRaises(frappe.ValidationError):
			_parse_changes([self.op("add", "Sales User")])

	def test_remove_of_a_missing_rule_rejected(self):
		from cecypo_powerpack.permission_manager import _parse_changes

		with self.assertRaises(frappe.ValidationError):
			_parse_changes([self.op("remove", "Accounts User")])

	def test_add_and_remove_of_the_same_identity_rejected(self):
		from cecypo_powerpack.permission_manager import _parse_changes

		with self.assertRaises(frappe.ValidationError):
			_parse_changes([self.op("add", "Accounts User"), self.op("remove", "Accounts User")])

	def test_removing_every_rule_of_a_doctype_rejected(self):
		"""Evaluated across the whole payload: two removes for a two-rule doctype must
		fail, even though each one alone would leave a rule behind."""
		from cecypo_powerpack.permission_manager import _parse_changes

		with self.assertRaises(frappe.ValidationError):
			_parse_changes([self.op("remove", "Sales User"), self.op("remove", "Stock User")])

	def test_removing_all_but_one_is_allowed(self):
		from cecypo_powerpack.permission_manager import _parse_changes

		out = _parse_changes([self.op("remove", "Sales User")])
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["op"], "remove")

	def test_update_may_target_a_rule_added_in_the_same_payload(self):
		"""Parsing runs before the transaction, so the added row is not in the DB yet.
		commit_changes orders removals, additions, updates for exactly this case."""
		from cecypo_powerpack.permission_manager import _parse_changes

		out = _parse_changes(
			[
				self.op("add", "Accounts User"),
				self.op("update", "Accounts User", changes={"write": 1}),
			]
		)
		self.assertEqual(sorted(r["op"] for r in out), ["add", "update"])

	def test_preview_reports_adds_and_removes_and_detachment(self):
		from cecypo_powerpack.permission_manager import preview_changes

		out = preview_changes([self.op("add", "Accounts User"), self.op("remove", "Sales User")])
		ops = sorted(r["op"] for r in out["rules"])
		self.assertEqual(ops, ["add", "remove"])
		self.assertEqual(out["detaching"], [{"doctype": self.dt.name, "standard_rules": 2}])


class TestBasicRightsGuard(FrappeTestCase):
	"""frappe rejects a rule with none of BASIC_RIGHTS set, but only from inside
	validate_permissions() — after the rows are written, so the whole commit rolls back
	with a message naming neither the rule nor the flag. _parse_changes catches it first.
	"""

	def setUp(self):
		frappe.set_user(SM)
		self.dt = new_doctype(permissions=[perm("Sales User", read=1), perm("Stock User", read=1)])
		self.dt.insert()

	def tearDown(self):
		frappe.set_user(SM)

	def op(self, op, role, **extra):
		return {"op": op, "doctype": self.dt.name, "role": role, "permlevel": 0, "if_owner": 0, **extra}

	def test_unticking_read_on_a_rule_added_in_the_same_payload_rejected(self):
		"""The commonest way in: a new rule starts with Read and nothing else, so
		unticking Read leaves it with no basic rights at all."""
		from cecypo_powerpack.permission_manager import _parse_changes

		with self.assertRaises(frappe.ValidationError) as caught:
			_parse_changes(
				[
					self.op("add", "Accounts User"),
					self.op("update", "Accounts User", changes={"read": 0}),
				]
			)
		message = str(caught.exception)
		self.assertIn("Accounts User", message)
		self.assertIn("no basic rights", message)

	def test_unticking_the_last_basic_right_of_an_existing_rule_rejected(self):
		from cecypo_powerpack.permission_manager import _parse_changes

		with self.assertRaises(frappe.ValidationError) as caught:
			_parse_changes([self.op("update", "Sales User", changes={"read": 0})])
		self.assertIn("no basic rights", str(caught.exception))

	def test_adding_a_rule_and_swapping_read_for_write_is_allowed(self):
		"""Read goes off and Write comes on in one payload: the resulting rule still has
		a basic right, so it must pass. Checking the delta alone would wrongly reject."""
		from cecypo_powerpack.permission_manager import _parse_changes

		out = _parse_changes(
			[
				self.op("add", "Accounts User"),
				self.op("update", "Accounts User", changes={"read": 0, "write": 1}),
			]
		)
		self.assertEqual(sorted(r["op"] for r in out), ["add", "update"])

	def test_unticking_read_is_allowed_when_another_basic_right_stays_set(self):
		from cecypo_powerpack.permission_manager import _parse_changes

		dt = new_doctype(permissions=[perm("Sales User", read=1, write=1), perm("Stock User", read=1)])
		dt.insert()
		out = _parse_changes(
			[{"doctype": dt.name, "role": "Sales User", "permlevel": 0, "if_owner": 0, "changes": {"read": 0}}]
		)
		self.assertEqual(len(out), 1)

	def test_clearing_a_non_basic_right_is_never_blocked(self):
		"""delete, print and export are not basic rights: frappe is happy for a rule to
		have none of them, so clearing one must not trip the guard (nor query for it)."""
		from cecypo_powerpack.permission_manager import _parse_changes

		out = _parse_changes([self.op("update", "Sales User", changes={"export": 0, "delete": 0})])
		self.assertEqual(len(out), 1)

	def test_the_guard_matches_frappe_own_predicate(self):
		"""If frappe ever changes which rights count as basic, this test fails rather
		than letting our message and its enforcement drift apart."""
		import inspect

		from frappe.core.doctype.doctype.doctype import validate_permissions

		from cecypo_powerpack.permission_manager import BASIC_RIGHTS

		source = inspect.getsource(validate_permissions)
		checker = source[source.index("def check_atleast_one_set") :]
		checker = checker[: checker.index("def check_double")]
		for right in BASIC_RIGHTS:
			self.assertIn(f"d.{right}", checker)
		# and nothing else is consulted there
		self.assertEqual(checker.count("not d."), len(BASIC_RIGHTS))


class TestCommitOps(FrappeTestCase):
	def setUp(self):
		frappe.set_user(SM)
		self.a = new_doctype(permissions=[perm("Sales User", read=1), perm("Stock User", read=1)])
		self.a.insert()
		self.b = new_doctype(permissions=[perm("Sales User", read=1)])
		self.b.insert()

	def tearDown(self):
		frappe.set_user(SM)

	def op(self, op, dt, role, permlevel=0, if_owner=0, **extra):
		return {
			"op": op, "doctype": dt.name, "role": role,
			"permlevel": permlevel, "if_owner": if_owner, **extra,
		}

	def test_add_creates_the_row_seeded_read_and_detaches(self):
		from cecypo_powerpack.permission_manager import commit_changes

		out = commit_changes([self.op("add", self.a, "Accounts User")])
		self.assertEqual((out["added"], out["removed"]), (1, 0))
		self.assertEqual(out["detached"], [self.a.name])
		self.assertEqual(custom_flag(self.a.name, "Accounts User", "read"), 1)
		self.assertEqual(custom_flag(self.a.name, "Accounts User", "write"), 0)
		self.assertEqual(custom_flag(self.a.name, "Accounts User", "delete"), 0)
		# Custom DocPerm defaults export to '1' as well as read, so this one is the guard
		# that a new rule really is Read-only rather than Read plus whatever frappe defaults.
		self.assertEqual(custom_flag(self.a.name, "Accounts User", "export"), 0)

	def test_add_with_if_owner(self):
		"""frappe's own add_permission hardcodes if_owner=0 and cannot express this."""
		from cecypo_powerpack.permission_manager import commit_changes

		commit_changes([self.op("add", self.a, "Accounts User", if_owner=1)])
		self.assertEqual(custom_flag(self.a.name, "Accounts User", "read", if_owner=1), 1)
		self.assertFalse(
			frappe.db.exists(
				"Custom DocPerm",
				{"parent": self.a.name, "role": "Accounts User", "permlevel": 0, "if_owner": 0},
			)
		)

	def test_remove_deletes_only_its_own_row(self):
		from cecypo_powerpack.permission_manager import commit_changes

		out = commit_changes([self.op("remove", self.a, "Stock User")])
		self.assertEqual((out["added"], out["removed"]), (0, 1))
		self.assertFalse(
			frappe.db.exists("Custom DocPerm", {"parent": self.a.name, "role": "Stock User"})
		)
		self.assertEqual(custom_flag(self.a.name, "Sales User", "read"), 1)

	def test_mixed_payload_across_doctypes_is_atomic(self):
		"""b's update breaks a frappe rule (cancel without submit), so a's add and remove
		must both roll back — and a must not even be left detached."""
		from cecypo_powerpack.permission_manager import commit_changes

		with self.assertRaises(frappe.ValidationError):
			commit_changes(
				[
					self.op("add", self.a, "Accounts User"),
					self.op("remove", self.a, "Stock User"),
					self.op("update", self.b, "Sales User", changes={"cancel": 1}),
				]
			)
		self.assertFalse(frappe.db.exists("Custom DocPerm", {"parent": self.a.name}))
		self.assertFalse(frappe.db.exists("Custom DocPerm", {"parent": self.b.name}))

	def test_add_then_update_in_one_payload(self):
		"""Removals and additions run before updates, so a rule added in this payload can
		be edited by it too."""
		from cecypo_powerpack.permission_manager import commit_changes

		commit_changes(
			[
				self.op("add", self.a, "Accounts User"),
				self.op("update", self.a, "Accounts User", changes={"write": 1}),
			]
		)
		self.assertEqual(custom_flag(self.a.name, "Accounts User", "write"), 1)

	def test_report_with_if_owner_rejected_for_a_new_rule(self):
		from cecypo_powerpack.permission_manager import commit_changes

		with self.assertRaises(frappe.ValidationError):
			commit_changes(
				[
					self.op("add", self.a, "Accounts User", if_owner=1),
					self.op("update", self.a, "Accounts User", if_owner=1, changes={"report": 1}),
				]
			)
		self.assertFalse(frappe.db.exists("Custom DocPerm", {"parent": self.a.name}))

	def test_grid_reflects_an_add(self):
		from cecypo_powerpack.permission_manager import commit_changes, get_permission_rules

		commit_changes([self.op("add", self.a, "Accounts User")])
		row = next(
			r
			for r in get_permission_rules()["rows"]
			if r["doctype"] == self.a.name and r["role"] == "Accounts User"
		)
		self.assertEqual((row["is_custom"], row["read"], row["write"]), (1, 1, 0))

	def test_ops_require_system_manager(self):
		from cecypo_powerpack.permission_manager import commit_changes

		editor = make_user(
			"pp-perm-editor@example.com",
			[make_role("PP Perm Editor", gate_read=True, gate_write=True)],
		)
		frappe.set_user(editor)
		with self.assertRaises(frappe.PermissionError):
			commit_changes([self.op("add", self.a, "Accounts User")])

	def test_removing_every_rule_but_adding_one_is_allowed(self):
		"""The PERMITTING branch of the delete guard: 2 - 2 + 1 = 1 rule survives."""
		from cecypo_powerpack.permission_manager import commit_changes

		out = commit_changes(
			[
				self.op("remove", self.a, "Sales User"),
				self.op("remove", self.a, "Stock User"),
				self.op("add", self.a, "Accounts User"),
			]
		)
		self.assertEqual((out["added"], out["removed"]), (1, 2))
		self.assertEqual(frappe.db.count("Custom DocPerm", {"parent": self.a.name}), 1)
		self.assertEqual(custom_flag(self.a.name, "Accounts User", "read"), 1)

	def test_doctype_name_is_canonicalised_so_the_delete_guard_cannot_be_split(self):
		from cecypo_powerpack.permission_manager import _parse_changes

		with self.assertRaises(frappe.ValidationError):
			_parse_changes(
				[
					self.op("remove", self.a, "Sales User"),
					{**self.op("remove", self.a, "Stock User"), "doctype": self.a.name.lower()},
				]
			)

	def test_unknown_doctype_rejected(self):
		from cecypo_powerpack.permission_manager import _parse_changes

		with self.assertRaises(frappe.ValidationError):
			_parse_changes([self.op("add", self.a, "Sales User") | {"doctype": "No Such Doctype ZZZ"}])

	def test_add_on_a_child_table_rejected(self):
		from cecypo_powerpack.permission_manager import _parse_changes

		child = new_doctype(istable=1)
		child.insert()
		with self.assertRaises(frappe.ValidationError):
			_parse_changes([{**self.op("add", self.a, "Sales User"), "doctype": child.name}])
