// Copyright (c) 2026, Cecypo.Tech and contributors
// For license information, please see license.txt

frappe.ui.form.on('PowerPack Settings', {
	refresh: function(frm) {
		// Add custom buttons or actions here if needed
		frm.set_intro(__('Configure PowerPack features and settings'));
	},

	enable_pos_powerup: function(frm) {
		// Handle POS powerup toggle
		if (frm.doc.enable_pos_powerup) {
			frappe.show_alert({
				message: __('Point of Sale Powerup has been enabled'),
				indicator: 'green'
			});
		}
	},

	enable_quotation_powerup: function(frm) {
		// Handle Quotation powerup toggle
		if (frm.doc.enable_quotation_powerup) {
			frappe.show_alert({
				message: __('Quotation Powerup has been enabled'),
				indicator: 'green'
			});
		}
	}
});
