import frappe

REMOVED_FIELDS = (
	"enable_pos_powerup",
	"pos_default_view",
	"pos_enable_custom_search",
	"pos_show_cost_price",
)


def execute():
	# The Point of Sale Powerup (Frappe POS) is gone. Its Print Format "Powerpack POS
	# Template" is site data and is deliberately left alone.
	for name in ("POS Profile-enable_powerpack_by_cecypo", "POS Profile-powerpack_column_config"):
		frappe.delete_doc("Custom Field", name, ignore_missing=True, force=True)

	frappe.db.delete("Singles", {"doctype": "PowerPack Settings", "field": ("in", REMOVED_FIELDS)})
