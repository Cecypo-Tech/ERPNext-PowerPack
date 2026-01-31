// Copyright (c) 2024, Cecypo.Tech and contributors
// For license information, please see license.txt

// Reuse the quotation tweaks functionality for Sales Order
frappe.provide('cecypo_powerpack.sales_order_tweaks');

// Copy the entire quotation_tweaks object for sales orders
cecypo_powerpack.sales_order_tweaks = Object.assign({}, cecypo_powerpack.quotation_tweaks);

// Hook into Sales Order form
frappe.ui.form.on('Sales Order', {
	refresh: function(frm) {
		// Add PowerUp button for System Managers
		if (frappe.user.has_role('System Manager')) {
			cecypo_powerpack.sales_order_tweaks.add_powerup_button(frm);
		}

		// Small delay to ensure grid is fully rendered
		setTimeout(function() {
			cecypo_powerpack.sales_order_tweaks.check_and_setup(frm);
		}, 500);
	},

	onload: function(frm) {
		setTimeout(function() {
			cecypo_powerpack.sales_order_tweaks.check_and_setup(frm);
		}, 500);
	},

	// Update profit metrics when taxes change
	total_taxes_and_charges: function(frm) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_order_tweaks.enabled && powerpack_enabled && frappe.user.has_role('System Manager')) {
			setTimeout(function() {
				cecypo_powerpack.sales_order_tweaks.add_profit_metrics(frm);
			}, 300);
		}
	},

	grand_total: function(frm) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_order_tweaks.enabled && powerpack_enabled && frappe.user.has_role('System Manager')) {
			setTimeout(function() {
				cecypo_powerpack.sales_order_tweaks.add_profit_metrics(frm);
			}, 300);
		}
	}
});

// Also trigger when items are added or changed
frappe.ui.form.on('Sales Order Item', {
	item_code: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_order_tweaks.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			setTimeout(function() {
				cecypo_powerpack.sales_order_tweaks.add_item_info(frm, item);
				if (frappe.user.has_role('System Manager')) {
					cecypo_powerpack.sales_order_tweaks.add_profit_metrics(frm);
				}
			}, 500);
		}
	},

	items_add: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_order_tweaks.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			setTimeout(function() {
				if (item.item_code) {
					cecypo_powerpack.sales_order_tweaks.add_item_info(frm, item);
				}
				if (frappe.user.has_role('System Manager')) {
					cecypo_powerpack.sales_order_tweaks.add_profit_metrics(frm);
				}
			}, 500);
		}
	},

	items_remove: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_order_tweaks.enabled && powerpack_enabled) {
			setTimeout(function() {
				if (frappe.user.has_role('System Manager')) {
					cecypo_powerpack.sales_order_tweaks.add_profit_metrics(frm);
				}
			}, 500);
		}
	},

	warehouse: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_order_tweaks.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			setTimeout(function() {
				if (item.item_code) {
					cecypo_powerpack.sales_order_tweaks.add_item_info(frm, item);
				}
				if (frappe.user.has_role('System Manager')) {
					cecypo_powerpack.sales_order_tweaks.add_profit_metrics(frm);
				}
			}, 500);
		}
	},

	qty: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_order_tweaks.enabled && powerpack_enabled && frappe.user.has_role('System Manager')) {
			setTimeout(function() {
				cecypo_powerpack.sales_order_tweaks.add_profit_metrics(frm);
			}, 300);
		}
	},

	rate: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_order_tweaks.enabled && powerpack_enabled && frappe.user.has_role('System Manager')) {
			setTimeout(function() {
				cecypo_powerpack.sales_order_tweaks.add_profit_metrics(frm);
			}, 300);
		}
	}
});
