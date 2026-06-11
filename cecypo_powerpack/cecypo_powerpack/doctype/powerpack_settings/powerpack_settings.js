// Copyright (c) 2026, Cecypo.Tech and contributors
// For license information, please see license.txt

frappe.ui.form.on('PowerPack Settings', {
	refresh: function(frm) {
		frm.set_intro(__('Configure PowerPack features and settings'));
		cecypo_check_min_price_conflict(frm);
	},

	enable_min_selling_price: function(frm) {
		cecypo_check_min_price_conflict(frm);
	},

	enable_pos_powerup: function(frm) {
		if (frm.doc.enable_pos_powerup) {
			frappe.show_alert({ message: __('Point of Sale Powerup has been enabled'), indicator: 'green' });
		}
	},

	enable_quotation_powerup: function(frm) {
		if (frm.doc.enable_quotation_powerup) {
			frappe.show_alert({ message: __('Quotation Powerup has been enabled'), indicator: 'green' });
		}
	}
});

function cecypo_check_min_price_conflict(frm) {
	if (!frm.doc.enable_min_selling_price) {
		frm.dashboard.clear_comment();
		return;
	}
	frappe.db.get_single_value('Selling Settings', 'validate_selling_price').then(function (val) {
		frm.dashboard.clear_comment();
		if (cint(val)) {
			frm.dashboard.add_comment(
				__('Conflict: Selling Settings → "Validate Selling Price for Item" is ON. It hard-blocks any sale below cost and overrides negative (rebate) floors. Turn it OFF to let PowerPack be the single authority.'),
				'yellow',
				true
			);
		}
	});
}
