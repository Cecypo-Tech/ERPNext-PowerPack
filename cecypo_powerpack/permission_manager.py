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
from frappe.permissions import std_rights

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
