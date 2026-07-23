import frappe


def execute():
	"""Add a composite index on Mpesa C2B Payment Register (businessshortcode, docstatus).

	The Quick Pay - Mpesa listing filters the register by these two columns on every
	call. Without an index that is a full-table scan, which is slow for companies with
	large pending registers. `frappe.db.add_index` is idempotent (it checks for an
	existing index and uses ADD INDEX IF NOT EXISTS), so this patch is safe to re-run.

	Guarded: the doctype ships with the optional `frappe_mpsa_payments` app and may not
	be installed on every site.
	"""
	if not frappe.db.table_exists("Mpesa C2B Payment Register"):
		return

	frappe.db.add_index("Mpesa C2B Payment Register", ["businessshortcode", "docstatus"])
