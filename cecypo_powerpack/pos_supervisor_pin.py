# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""Supervisor PIN for authorising a below-minimum sale at a till."""

import re

import frappe
from frappe import _
from frappe.utils import cint

from cecypo_powerpack.pos_list_floor import PIN_FIELD


def validate_pin_format(doc, method=None):
	"""User.validate. A saved Password field reads back as asterisks; leave that alone."""
	pin = doc.get(PIN_FIELD)
	if not pin or set(pin) == {"*"}:
		return
	if not re.fullmatch(r"\d{4,6}", pin):
		frappe.throw(_("POS Supervisor PIN must be 4 to 6 digits."))


MAX_WRONG = 5
LOCKOUT_SECONDS = 15 * 60
TOKEN_SECONDS = 10 * 60


def _override_role():
	return frappe.get_cached_doc("PowerPack Settings").get("min_selling_price_override_role")


def _is_supervisor(user):
	role = _override_role()
	return bool(role and user and frappe.db.get_value("User", user, "enabled") and role in frappe.get_roles(user))


@frappe.whitelist()
def get_pos_supervisors():
	"""Users who can authorise at a till: enabled, holding the override role, with a PIN set."""
	role = _override_role()
	if not role:
		return []
	users = frappe.get_all("Has Role", {"role": role, "parenttype": "User"}, pluck="parent", distinct=True)
	with_pin = set(
		frappe.db.sql_list(
			"select name from `__Auth` where doctype='User' and fieldname=%s and name in %s",
			(PIN_FIELD, tuple(users) or ("",)),
		)
	)
	return [
		{"name": u.name, "full_name": u.full_name or u.name}
		for u in frappe.get_all("User", {"name": ["in", list(with_pin) or [""]], "enabled": 1}, ["name", "full_name"], order_by="full_name")
	]


def _fail_key(supervisor):
	return f"powerpack_pin_fail:{supervisor}"


def _log(supervisor, ok, doc):
	"""Every attempt: who authorised (or tried), for which cashier and till. Never the PIN."""
	subject = _("{0} PIN for {1} at till {2}").format(
		_("Accepted") if ok else _("Wrong"), frappe.session.user, doc.get("pos_profile") or "-"
	)
	frappe.get_doc(
		{
			"doctype": "Activity Log",
			"subject": subject,
			"status": "Success" if ok else "Failed",
			# timeline_*, not reference_*: Activity Log forces status "Linked" on a reference.
			"timeline_doctype": "User",
			"timeline_name": supervisor,
			"user": frappe.session.user,
			"full_name": frappe.utils.get_fullname(frappe.session.user),
			"communication_date": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)


def verify_pin(supervisor, pin, doc):
	"""True for a supervisor's own PIN. Throws while the supervisor is locked out."""
	import hmac

	from frappe.utils.password import get_decrypted_password

	failures = cint(frappe.cache.get_value(_fail_key(supervisor)))
	if failures >= MAX_WRONG:
		frappe.throw(
			_("Too many wrong PINs for {0}. Try again in 15 minutes.").format(frappe.utils.get_fullname(supervisor))
		)
	stored = get_decrypted_password("User", supervisor, PIN_FIELD, raise_exception=False) if _is_supervisor(supervisor) else None
	ok = bool(stored and pin and hmac.compare_digest(str(stored), str(pin)))
	if ok:
		frappe.cache.delete_value(_fail_key(supervisor))
	else:
		frappe.cache.set_value(_fail_key(supervisor), failures + 1, expires_in_sec=LOCKOUT_SECONDS)
	_log(supervisor, ok, doc)
	return ok


def authorise(doc, supervisor, pin):
	"""A supervisor's PIN at the till → a short-lived token covering the below-list rows as they are now.

	A wrong PIN returns ok=False instead of throwing, so the attempt's log and count stand.
	"""
	from cecypo_powerpack.pos_list_floor import below_floor_rows
	from cecypo_powerpack.price_approval import snapshot_rows

	if not verify_pin(supervisor, pin, doc):
		return {"ok": False, "token": None, "message": _("Wrong PIN, or that user may not authorise prices.")}
	by_idx = {row.idx: row for row in doc.items}
	rows = snapshot_rows(doc, items=[by_idx[b["idx"]] for b in below_floor_rows(doc)])
	token = frappe.generate_hash(length=32)
	frappe.cache.set_value(
		f"powerpack_pos_auth:{token}",
		{"supervisor": supervisor, "cashier": frappe.session.user, "rows": rows},
		expires_in_sec=TOKEN_SECONDS,
	)
	return {"ok": True, "token": token, "message": _("Authorised by {0}").format(frappe.utils.get_fullname(supervisor))}


def apply_authorisation(doc, token):
	"""Hand the validator a supervisor's authorisation for this checkout (see pos_list_floor.validate)."""
	key = f"powerpack_pos_auth:{token}"
	entry = frappe.cache.get_value(key) if token else None
	if not entry or entry.get("cashier") != frappe.session.user:
		frappe.throw(_("The supervisor's authorisation expired. Authorise again."))
	# Spent when the sale commits, not here: a retried checkout re-sends the same token.
	doc.flags.powerpack_pos_approval = {"supervisor": entry["supervisor"], "rows": entry["rows"], "token_key": key}
