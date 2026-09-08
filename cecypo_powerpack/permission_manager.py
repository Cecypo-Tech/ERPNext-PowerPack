# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""PowerPack Permission Manager — server side.

Frappe's Role Permissions Manager saves on every checkbox, and each save runs
setup_custom_perms -> write -> validate_permissions_for_doctype -> a GLOBAL user
cache clear. This module lets the client send every edit in one payload and pays
those fixed costs once per doctype (validation) and once per commit (cache).

Row identity is the tuple (doctype, role, permlevel, if_owner). Frappe's own
update_permission_property() looks a rule up by the first three only, which picks
the wrong row when a doctype has both an "if owner" and a plain rule for the same
role; we always include if_owner.
"""

import frappe
from frappe import _
from frappe.core.doctype.doctype.doctype import validate_permissions
from frappe.desk.notifications import delete_notification_count_for
from frappe.permissions import setup_custom_perms, std_rights

# The 14 std_rights plus mask, which is a Custom DocPerm field but deliberately not a
# std right. if_owner is NOT here: it is part of a rule's identity, not a flag on it.
FLAGS = tuple(std_rights) + ("mask",)

# Only meaningful on submittable doctypes; the client blanks them out elsewhere.
SUBMIT_FLAGS = ("submit", "cancel", "amend")

# Reading the grid reuses an existing doctype permission instead of a new role field:
# to let another role view the grid, grant it Read on this doctype in frappe's Role
# Permission Manager. It is NOT Custom DocPerm, although that is the data shown:
# frappe never honours Custom DocPerm overrides on DocType / DocField / DocPerm /
# Custom DocPerm themselves (frappe/model/meta.py:645), so Read on User Permission
# can never be granted to anyone but System Manager. User Permission is ordinary
# permission configuration and can. One constant so it can be changed in one place.
READ_GATE_DOCTYPE = "User Permission"

_ROW_FIELDS = ["parent", "role", "permlevel", "if_owner", *FLAGS]


def _check_can_view():
	if frappe.session.user == "Administrator":
		return
	if not frappe.has_permission(READ_GATE_DOCTYPE, "read"):
		frappe.throw(
			_("You need read access to {0} to view permission rules").format(_(READ_GATE_DOCTYPE)),
			frappe.PermissionError,
		)


def _check_can_edit():
	frappe.only_for("System Manager")


def _can_edit() -> bool:
	return frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles()


def _rule_key(row) -> tuple:
	return (row["doctype"], row["role"], int(row["permlevel"] or 0), int(row["if_owner"] or 0))


@frappe.whitelist()
def get_permission_rules() -> dict:
	"""Every rule in force, one row per (doctype, role, permlevel, if_owner).

	Frappe semantics (frappe/model/meta.py:641): if a doctype has ANY Custom DocPerm
	rows, those rows replace its standard DocPerm rows entirely. The grid mirrors that:
	custom rows for detached doctypes, standard rows for everything else.
	"""
	_check_can_view()

	doctypes = {
		d.name: d
		for d in frappe.get_all(
			"DocType", fields=["name", "module", "is_submittable"], filters={"istable": 0}
		)
	}

	custom = frappe.get_all("Custom DocPerm", fields=_ROW_FIELDS)
	detached = {r.parent for r in custom}
	standard = [
		r
		for r in frappe.get_all("DocPerm", fields=_ROW_FIELDS)
		if r.parent not in detached
	]

	rows = []
	for src, is_custom in ((custom, 1), (standard, 0)):
		for r in src:
			dt = doctypes.get(r.parent)
			if not dt:
				continue  # child table, or a rule whose doctype no longer exists
			row = {
				"doctype": r.parent,
				"module": dt.module,
				"role": r.role,
				"permlevel": int(r.permlevel or 0),
				"if_owner": int(r.if_owner or 0),
				"is_custom": is_custom,
				"is_submittable": int(dt.is_submittable or 0),
			}
			for flag in FLAGS:
				row[flag] = int(r.get(flag) or 0)
			rows.append(row)

	rows.sort(key=lambda r: (r["doctype"], r["role"], r["permlevel"], r["if_owner"]))
	return {"rows": rows, "can_edit": _can_edit()}


def _parse_changes(changes) -> list[dict]:
	"""Normalise the client payload. Rejects anything that is not a known flag on a
	rule that exists, so nothing downstream has to defend against the payload."""
	if isinstance(changes, str):
		changes = frappe.parse_json(changes)
	if not isinstance(changes, list):
		frappe.throw(_("changes must be a list"), frappe.ValidationError)

	merged: dict[tuple, dict] = {}
	for item in changes:
		for required in ("doctype", "role"):
			if not item.get(required):
				frappe.throw(_("Each change needs a doctype and a role"), frappe.ValidationError)
		key = _rule_key(item)
		flags = item.get("changes") or {}
		for flag, value in flags.items():
			if flag not in FLAGS:
				frappe.throw(_("{0} is not an editable permission").format(flag), frappe.ValidationError)
			merged.setdefault(key, {})[flag] = 1 if int(value) else 0

	out = []
	for (doctype, role, permlevel, if_owner), flags in merged.items():
		if not flags:
			continue
		if not _rule_exists(doctype, role, permlevel, if_owner):
			frappe.throw(
				_("No permission rule for {0} on {1} at level {2}").format(role, doctype, permlevel),
				frappe.ValidationError,
			)
		out.append(
			{"doctype": doctype, "role": role, "permlevel": permlevel, "if_owner": if_owner, "changes": flags}
		)
	return out


def _rule_exists(doctype, role, permlevel, if_owner) -> bool:
	"""A rule exists if it is in force: custom if the doctype is detached, else standard."""
	filters = {"parent": doctype, "role": role, "permlevel": permlevel, "if_owner": if_owner}
	if frappe.db.exists("Custom DocPerm", {"parent": doctype}):
		return bool(frappe.db.exists("Custom DocPerm", filters))
	return bool(frappe.db.exists("DocPerm", filters))


def _detaching_doctypes(parsed: list[dict]) -> list[dict]:
	"""Doctypes in the payload that have no Custom DocPerm yet. Committing will copy
	every one of their standard rules into Custom DocPerm (setup_custom_perms), after
	which permission changes shipped by apps on bench migrate no longer reach them."""
	out = []
	for doctype in sorted({c["doctype"] for c in parsed}):
		if frappe.db.exists("Custom DocPerm", {"parent": doctype}):
			continue
		out.append(
			{"doctype": doctype, "standard_rules": frappe.db.count("DocPerm", {"parent": doctype})}
		)
	return out


@frappe.whitelist()
def preview_changes(changes) -> dict:
	_check_can_edit()
	parsed = _parse_changes(changes)
	return {"rules": parsed, "detaching": _detaching_doctypes(parsed)}


_SAVEPOINT = "pp_permission_commit"


@frappe.whitelist()
def commit_changes(changes) -> dict:
	"""Apply a whole change set in one transaction.

	Per doctype: detach once (setup_custom_perms), write each changed row, validate
	that doctype's custom rules once. Then clear caches once for the whole commit.
	Any failure rolls the entire payload back — never a partial application.
	"""
	_check_can_edit()
	parsed = _drop_noops(_parse_changes(changes))
	if not parsed:
		return {"doctypes": 0, "rules": 0, "detached": []}

	by_doctype: dict[str, list[dict]] = {}
	for rule in parsed:
		by_doctype.setdefault(rule["doctype"], []).append(rule)

	detached = []
	frappe.db.savepoint(_SAVEPOINT)
	try:
		for doctype, rules in by_doctype.items():
			if setup_custom_perms(doctype):
				detached.append(doctype)
			_apply_to_doctype(doctype, rules)
			_validate_custom_rules(doctype)
	except Exception:
		frappe.db.rollback(save_point=_SAVEPOINT)
		raise

	# Once per commit, not once per checkbox. CustomDocPerm.on_update already cleared
	# each doctype's own cache on save; this is the site-wide part frappe's page
	# repeats for every single tick.
	from frappe.cache_manager import clear_user_cache

	for doctype in by_doctype:
		delete_notification_count_for(doctype)
	clear_user_cache()

	return {"doctypes": len(by_doctype), "rules": len(parsed), "detached": detached}


def _drop_noops(parsed: list[dict]) -> list[dict]:
	"""Remove flags that already hold the requested value, then rules left empty.
	Keeps a no-op commit from detaching a doctype for nothing."""
	out = []
	for rule in parsed:
		table = "Custom DocPerm" if frappe.db.exists("Custom DocPerm", {"parent": rule["doctype"]}) else "DocPerm"
		current = frappe.db.get_value(
			table,
			{
				"parent": rule["doctype"],
				"role": rule["role"],
				"permlevel": rule["permlevel"],
				"if_owner": rule["if_owner"],
			},
			list(rule["changes"]),
			as_dict=True,
		)
		real = {f: v for f, v in rule["changes"].items() if int(current.get(f) or 0) != v}
		if real:
			out.append({**rule, "changes": real})
	return out


def _apply_to_doctype(doctype: str, rules: list[dict]):
	for rule in rules:
		name = frappe.db.get_value(
			"Custom DocPerm",
			{
				"parent": doctype,
				"role": rule["role"],
				"permlevel": rule["permlevel"],
				"if_owner": rule["if_owner"],
			},
			"name",
		)
		if not name:
			frappe.throw(
				_("No permission rule for {0} on {1} at level {2}").format(
					rule["role"], doctype, rule["permlevel"]
				),
				frappe.ValidationError,
			)
		doc = frappe.get_doc("Custom DocPerm", name)
		doc.update(rule["changes"])
		doc.save(ignore_permissions=True)


def _validate_custom_rules(doctype: str):
	"""Run frappe's own permission rules over the rows that are actually in force.

	frappe.get_doc("DocType") loads the STANDARD DocPerm rows; only get_meta merges
	Custom DocPerm (frappe/model/meta.py:641). So validate_permissions_for_doctype()
	would validate the wrong rows. We hand validate_permissions() the DocType doc
	with its permissions swapped for the custom rows, which is all it reads.
	"""
	dt = frappe.get_doc("DocType", doctype)
	names = frappe.get_all("Custom DocPerm", filters={"parent": doctype}, pluck="name", order_by="idx")
	dt.permissions = [frappe.get_doc("Custom DocPerm", n) for n in names]
	validate_permissions(dt)
