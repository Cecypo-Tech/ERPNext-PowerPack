// Copyright (c) 2024, Cecypo.Tech and contributors
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

	enable_quotation_tweaks: function(frm) {
		// Handle Quotation tweaks toggle
		if (frm.doc.enable_quotation_tweaks) {
			frappe.show_alert({
				message: __('Quotation Tweaks has been enabled'),
				indicator: 'green'
			});
		}
	}
});
