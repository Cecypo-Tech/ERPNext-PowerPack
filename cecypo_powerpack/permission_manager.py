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
from frappe.cache_manager import clear_user_cache
from frappe.core.doctype.doctype.doctype import validate_permissions
from frappe.desk.notifications import delete_notification_count_for
from frappe.permissions import setup_custom_perms, std_rights

# The 14 std_rights plus mask, which is a Custom DocPerm field but deliberately not a
# std right. if_owner is NOT here: it is part of a rule's identity, not a flag on it.
FLAGS = tuple(std_rights) + ("mask",)

# frappe's check_atleast_one_set (frappe/core/doctype/doctype/doctype.py:1859) rejects any
# rule with none of these six set. Mirrored here so the rejection can name the rule and the
# way out, instead of surfacing as a bare "<rule>: No basic permissions set" from inside
# validate_permissions() — which runs after the rows are already written, so the whole
# commit rolls back on it. Note this is not "any flag": delete, print or export alone does
# NOT satisfy frappe.
BASIC_RIGHTS = ("select", "read", "write", "create", "submit", "cancel")

# An entry with no `op` is an update: that is what the client sent before add/remove
# existed, and every pre-existing test relies on it.
OPS = ("update", "add", "remove")

# Frappe's own page refuses these (not_allowed_in_permission_manager) and never offers a
# child table. We must refuse them too: get_permission_rules() filters istable: 0, so a
# rule created on a child table is invisible here AND in frappe's page — unreachable
# except through the raw Custom DocPerm list.
NOT_ADDABLE_DOCTYPES = ("DocType", "Patch Log", "Module Def")

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


def _check_addable(doctype: str):
	if doctype in NOT_ADDABLE_DOCTYPES:
		frappe.throw(
			_("Permission rules for {0} cannot be managed here").format(doctype),
			frappe.ValidationError,
		)
	if frappe.get_cached_value("DocType", doctype, "istable"):
		frappe.throw(
			_("{0} is a child table and has no role permissions of its own").format(doctype),
			frappe.ValidationError,
		)


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
	"""Normalise the client payload into update / add / remove entries.

	This is the single validation gate: nothing downstream defends against the payload.
	Three of the checks here exist because frappe enforces them only in its own page
	endpoint, never in validate_permissions(), so a path that bypasses that page
	inherits nothing — the duplicate check, the "at least one rule" check, and the
	report/if_owner check. A fourth, the basic-rights check, duplicates one frappe DOES
	make in validate_permissions() — but only after every row is written, which turns a
	single stray checkbox into a full rollback with an unattributable message.
	"""
	if isinstance(changes, str):
		changes = frappe.parse_json(changes)
	if not isinstance(changes, list):
		frappe.throw(_("changes must be a list"), frappe.ValidationError)

	updates: dict[tuple, dict] = {}
	adds: dict[tuple, None] = {}
	removes: dict[tuple, None] = {}

	# MariaDB's default collation is case-insensitive, so "sales invoice" and "Sales Invoice"
	# count the same rows but hash to different keys. Canonicalise before anything buckets by
	# doctype, or a payload spelling one doctype two ways splits the "keep at least one rule"
	# arithmetic and defeats it from both sides.
	canonical: dict[str, str] = {}

	def _canonical(name):
		if name not in canonical:
			resolved = frappe.db.get_value("DocType", name, "name")
			if not resolved:
				frappe.throw(_("{0} is not a document type").format(name), frappe.ValidationError)
			canonical[name] = resolved
		return canonical[name]

	for item in changes:
		for required in ("doctype", "role"):
			if not item.get(required):
				frappe.throw(_("Each change needs a doctype and a role"), frappe.ValidationError)
		item = {**item, "doctype": _canonical(item["doctype"])}
		op = item.get("op") or "update"
		if op not in OPS:
			frappe.throw(_("{0} is not a valid operation").format(op), frappe.ValidationError)
		key = _rule_key(item)
		if op == "add":
			adds[key] = None
		elif op == "remove":
			removes[key] = None
		else:
			for flag, value in (item.get("changes") or {}).items():
				if flag not in FLAGS:
					frappe.throw(_("{0} is not an editable permission").format(flag), frappe.ValidationError)
				updates.setdefault(key, {})[flag] = 1 if int(value) else 0

	overlap = set(adds) & set(removes)
	if overlap:
		doctype, role, permlevel, _if_owner = next(iter(overlap))
		frappe.throw(
			_("Cannot add and remove the same rule in one commit: {0} on {1} at level {2}").format(
				role, doctype, permlevel
			),
			frappe.ValidationError,
		)

	out = []

	for key in adds:
		doctype, role, permlevel, if_owner = key
		_check_addable(doctype)
		if _rule_exists(doctype, role, permlevel, if_owner):
			frappe.throw(
				_("A rule for {0} on {1} at level {2} already exists").format(role, doctype, permlevel),
				frappe.ValidationError,
			)
		out.append(
			{"op": "add", "doctype": doctype, "role": role, "permlevel": permlevel, "if_owner": if_owner}
		)

	for key in removes:
		doctype, role, permlevel, if_owner = key
		if not _rule_exists(doctype, role, permlevel, if_owner):
			frappe.throw(
				_("No permission rule for {0} on {1} at level {2}").format(role, doctype, permlevel),
				frappe.ValidationError,
			)
		out.append(
			{"op": "remove", "doctype": doctype, "role": role, "permlevel": permlevel, "if_owner": if_owner}
		)

	_check_doctypes_keep_a_rule(removes, adds)

	for key, flags in updates.items():
		doctype, role, permlevel, if_owner = key
		if not flags:
			continue
		# A rule this same payload is ADDING does not exist in the database yet — parsing
		# runs before commit_changes' transaction. commit_changes applies removals, then
		# additions, then updates per doctype precisely so an update can target a rule the
		# same payload creates, so accept it here too.
		if key not in adds and not _rule_exists(doctype, role, permlevel, if_owner):
			frappe.throw(
				_("No permission rule for {0} on {1} at level {2}").format(role, doctype, permlevel),
				frappe.ValidationError,
			)
		if flags.get("report") and if_owner:
			frappe.throw(
				_("Cannot set 'Report' permission when 'Only If Creator' is set"), frappe.ValidationError
			)
		_check_keeps_a_basic_right(doctype, role, permlevel, if_owner, flags, is_add=key in adds)
		out.append(
			{
				"op": "update",
				"doctype": doctype,
				"role": role,
				"permlevel": permlevel,
				"if_owner": if_owner,
				"changes": flags,
			}
		)
	return out


def _check_doctypes_keep_a_rule(removes, adds):
	"""Reject a payload that would leave a doctype with no rules at all.

	Counted per doctype over the WHOLE payload: removing both rules of a two-rule
	doctype passes a row-by-row check and still leaves it with none. Adds in the same
	payload count towards the survivors, since they land in the same transaction.
	"""
	per_doctype: dict[str, int] = {}
	for doctype, _role, _permlevel, _if_owner in removes:
		per_doctype[doctype] = per_doctype.get(doctype, 0) + 1

	added: dict[str, int] = {}
	for doctype, _role, _permlevel, _if_owner in adds:
		added[doctype] = added.get(doctype, 0) + 1

	for doctype, removing in per_doctype.items():
		table = "Custom DocPerm" if frappe.db.exists("Custom DocPerm", {"parent": doctype}) else "DocPerm"
		existing = frappe.db.count(table, {"parent": doctype})
		if existing - removing + added.get(doctype, 0) < 1:
			# frappe's own wording, plus the doctype: in a multi-doctype payload the bare
			# sentence leaves an admin no way to tell which one blocked the commit.
			frappe.throw(
				_("There must be atleast one permission rule ({0}).").format(doctype),
				frappe.ValidationError,
				title=_("Cannot Remove"),
			)


def _rule_exists(doctype, role, permlevel, if_owner) -> bool:
	"""A rule exists if it is in force: custom if the doctype is detached, else standard."""
	filters = {"parent": doctype, "role": role, "permlevel": permlevel, "if_owner": if_owner}
	if frappe.db.exists("Custom DocPerm", {"parent": doctype}):
		return bool(frappe.db.exists("Custom DocPerm", filters))
	return bool(frappe.db.exists("DocPerm", filters))


def _rule_in_force(doctype, role, permlevel, if_owner) -> dict | None:
	"""The flags of the rule actually in force, or None if there is none.

	Custom if the doctype is detached, else standard — the same choice _rule_exists()
	makes, for the same reason (frappe/model/meta.py:641).
	"""
	source = "Custom DocPerm" if frappe.db.exists("Custom DocPerm", {"parent": doctype}) else "DocPerm"
	rows = frappe.get_all(
		source,
		filters={"parent": doctype, "role": role, "permlevel": permlevel, "if_owner": if_owner},
		fields=list(BASIC_RIGHTS),
		limit=1,
	)
	return rows[0] if rows else None


def _check_keeps_a_basic_right(doctype, role, permlevel, if_owner, flags, is_add):
	"""Reject an edit that would leave a rule with none of frappe's basic rights.

	frappe enforces this in validate_permissions(), which _apply_to_doctype() runs only
	after every row is written: the savepoint rolls back and the admin is told
	"No basic permissions set" without being told which rule, which flag, or what to do
	about it. The commonest way to trigger it is unticking Read on a rule this same
	payload is adding, since a new rule starts with Read and nothing else.
	"""
	# Only turning a basic right OFF can empty the set. Anything else grants a right or
	# leaves the count alone, so there is nothing to check and no query to run.
	if not any(flag in BASIC_RIGHTS and not value for flag, value in flags.items()):
		return
	# A rule this payload is adding does not exist yet; _add_rule seeds it read: 1.
	current = {"read": 1} if is_add else _rule_in_force(doctype, role, permlevel, if_owner)
	if current is None:
		return  # no such rule — the caller's own _rule_exists() check reports that
	if any(int(flags.get(flag, current.get(flag) or 0)) for flag in BASIC_RIGHTS):
		return
	frappe.throw(
		_(
			"{0} on {1} at level {2} would be left with no basic rights. Every rule needs at"
			" least one of {3}. Leave one of them set, or remove the rule instead."
		).format(role, doctype, permlevel, ", ".join(frappe.unscrub(f) for f in BASIC_RIGHTS)),
		frappe.ValidationError,
	)


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

	Per doctype the order is removals, then additions, then updates: an update in the
	same payload may target a rule that payload creates, so the row has to exist by then.
	"""
	_check_can_edit()
	parsed = _drop_noops(_parse_changes(changes))
	if not parsed:
		return {"doctypes": 0, "rules": 0, "added": 0, "removed": 0, "detached": []}

	by_doctype: dict[str, list[dict]] = {}
	for rule in parsed:
		by_doctype.setdefault(rule["doctype"], []).append(rule)

	detached = []
	added = removed = 0
	frappe.db.savepoint(_SAVEPOINT)
	try:
		for doctype, rules in by_doctype.items():
			if setup_custom_perms(doctype):
				detached.append(doctype)
			# Removals first, then additions, then updates: an update in the same payload
			# may target a rule this payload is adding, so the row has to exist by then.
			for rule in [r for r in rules if r["op"] == "remove"]:
				_remove_rule(doctype, rule)
				removed += 1
			for rule in [r for r in rules if r["op"] == "add"]:
				_add_rule(doctype, rule)
				added += 1
			# Checked again here, inside the transaction: _check_doctypes_keep_a_rule reads
			# counts before the savepoint opens, so two concurrent commits could each pass it
			# and still leave a doctype with nothing.
			if any(r["op"] == "remove" for r in rules) and frappe.db.count(
				"Custom DocPerm", {"parent": doctype}
			) < 1:
				frappe.throw(
					_("There must be atleast one permission rule ({0}).").format(doctype),
					frappe.ValidationError,
					title=_("Cannot Remove"),
				)
			_apply_to_doctype(doctype, [r for r in rules if r["op"] == "update"])
			_validate_custom_rules(doctype)
	except Exception:
		frappe.db.rollback(save_point=_SAVEPOINT)
		raise

	# Once per commit, not once per checkbox. CustomDocPerm.on_update already cleared
	# each doctype's own cache on save; this is the site-wide part frappe's page
	# repeats for every single tick. One global clear_user_cache() here is enough even
	# though we also saved a row per doctype above: CustomDocPerm.on_update calls
	# frappe.clear_cache(doctype=...), which self-registers an after_commit callback to
	# re-clear that doctype's cache (frappe/cache_manager.py:131-133) once this request
	# commits, so the per-doctype clears effectively repeat after commit regardless.
	for doctype in by_doctype:
		delete_notification_count_for(doctype)
	clear_user_cache()

	return {
		"doctypes": len(by_doctype),
		"rules": len(parsed),
		"added": added,
		"removed": removed,
		"detached": detached,
	}


def _drop_noops(parsed: list[dict]) -> list[dict]:
	"""Remove flags that already hold the requested value, then rules left empty.
	Keeps a no-op commit from detaching a doctype for nothing."""
	out = []
	for rule in parsed:
		if rule["op"] != "update":
			# Only an update can be a no-op; an add or a remove always changes something.
			out.append(rule)
			continue
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
		if not current:
			# The row doesn't exist yet — e.g. this same payload adds it before this
			# update runs. Nothing to compare against, so it is not a no-op.
			out.append(rule)
			continue
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


def _add_rule(doctype: str, rule: dict):
	"""Insert one Custom DocPerm row, seeded read: 1.

	Deliberately not frappe.permissions.add_permission(): that msgprints and silently
	returns on a duplicate (useless inside a transaction that has to report), and it
	hardcodes if_owner=0 so it cannot create an if-owner rule at all. The field set
	below is the same one it builds. read: 1 is its default seed and the minimum that
	satisfies check_atleast_one_set (frappe/core/doctype/doctype/doctype.py:1859).
	"""
	# Every flag is set explicitly. Custom DocPerm's own field defaults are read: '1' AND
	# export: '1' (custom_docperm.json), so passing read alone would silently grant Export
	# on every new rule — a permission the admin never asked for, and one the review
	# dialog explicitly promises they are not getting ("starts with Read only").
	flags = dict.fromkeys(FLAGS, 0)
	flags["read"] = 1
	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": doctype,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": rule["role"],
			"permlevel": rule["permlevel"],
			"if_owner": rule["if_owner"],
			**flags,
		}
	).insert(ignore_permissions=True)


def _remove_rule(doctype: str, rule: dict):
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
	frappe.delete_doc("Custom DocPerm", name, ignore_permissions=True, force=True)


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
	# validate_permissions() mutates rows in place (e.g. zeroes create/submit/cancel/amend
	# at permlevel > 0, zeroes report/import/export on Single doctypes) but never saves
	# them. Stock frappe persists via db_update() in validate_permissions_for_doctype();
	# we must do the same here or the corrections are silently dropped.
	for perm in dt.permissions:
		perm.db_update()
