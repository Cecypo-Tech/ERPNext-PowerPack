/**
 * Shared Profit Calculator
 *
 * This module provides unified profit and margin calculations across all PowerPack features.
 * It ensures consistent handling of taxes and proper profit calculations.
 */

frappe.provide('cecypo_powerpack.profit_calculator');

cecypo_powerpack.profit_calculator = {
	/**
	 * Check if taxes are included in item rates for a given form
	 * @param {Object} frm - Frappe form object
	 * @returns {boolean} True if taxes are included in print rate
	 */
	is_tax_inclusive: function(frm) {
		if (!frm || !frm.doc || !frm.doc.taxes) {
			return false;
		}
		return frm.doc.taxes.some(tax => tax.included_in_print_rate === 1);
	},

	/**
	 * Calculate item-specific tax rate from rate and net_rate
	 * @param {number} rate - Tax-inclusive rate
	 * @param {number} net_rate - Tax-exclusive rate
	 * @returns {number} Tax rate as decimal (e.g., 0.1 for 10%)
	 */
	calculate_item_tax_rate: function(rate, net_rate) {
		if (!rate || !net_rate || net_rate <= 0) {
			return 0;
		}
		return (rate - net_rate) / net_rate;
	},

	/**
	 * Calculate document-level effective tax rate
	 * @param {Object} frm - Frappe form object
	 * @returns {number} Tax rate as decimal (e.g., 0.1 for 10%)
	 */
	calculate_doc_tax_rate: function(frm) {
		if (!frm || !frm.doc) {
			return 0;
		}

		const net_total = frm.doc.net_total || frm.doc.base_net_total || 0;
		const total_taxes = frm.doc.total_taxes_and_charges || 0;

		if (net_total <= 0) {
			return 0;
		}

		return total_taxes / net_total;
	},

	/**
	 * Get the net (tax-exclusive) rate for an item
	 * @param {Object} item_doc - Item document from form
	 * @param {boolean} tax_inclusive - Whether taxes are included
	 * @returns {number} Net rate (tax-exclusive)
	 */
	get_net_rate: function(item_doc, tax_inclusive) {
		if (!item_doc) {
			return 0;
		}

		if (tax_inclusive && item_doc.net_rate !== undefined) {
			return item_doc.net_rate || 0;
		}

		return item_doc.rate || 0;
	},

	/**
	 * Calculate profit and margin for an item
	 * @param {Object} params - Calculation parameters
	 * @param {number} params.rate - Item rate (may be tax-inclusive)
	 * @param {number} params.net_rate - Item net rate (tax-exclusive)
	 * @param {number} params.valuation_rate - Item cost/valuation rate
	 * @param {number} params.qty - Quantity
	 * @param {boolean} params.tax_inclusive - Whether taxes are included in rate
	 * @returns {Object} { profit, margin, net_rate_used, display_rate }
	 */
	calculate_item_profit: function(params) {
		const {
			rate = 0,
			net_rate = 0,
			valuation_rate = 0,
			qty = 1,
			tax_inclusive = false
		} = params;

		// Determine which rate to use for profit calculation (always tax-exclusive)
		const rate_for_profit = tax_inclusive && net_rate > 0 ? net_rate : rate;

		// Display rate is what the customer sees (tax-inclusive if applicable)
		const display_rate = rate;

		// Calculate profit per unit (using tax-exclusive rate)
		const profit_per_unit = rate_for_profit - valuation_rate;
		const total_profit = profit_per_unit * qty;

		// Calculate margin based on display rate (what customer pays)
		const margin = display_rate > 0 ? (profit_per_unit / display_rate * 100) : 0;

		return {
			profit: total_profit,
			profit_per_unit: profit_per_unit,
			margin: margin,
			net_rate_used: rate_for_profit,
			display_rate: display_rate
		};
	},

	/**
	 * Calculate document-level profit metrics (for summary)
	 * @param {Object} frm - Frappe form object
	 * @param {Array} items - Array of items with valuation_rate
	 * @returns {Object} { total_cost, net_total, grand_total, profit, margin, tax_inclusive }
	 */
	calculate_doc_profit: function(frm, items) {
		if (!frm || !frm.doc || !items) {
			return {
				total_cost: 0,
				net_total: 0,
				grand_total: 0,
				profit: 0,
				margin: 0,
				tax_inclusive: false
			};
		}

		let total_cost = 0;
		let total_amount = 0;

		// Calculate total cost based on valuation rates
		items.forEach(function(item) {
			const qty = item.qty || 0;
			const amount = item.amount || 0;
			total_amount += amount;

			if (item.valuation_rate && item.valuation_rate > 0) {
				total_cost += (item.valuation_rate * qty);
			}
		});

		// Get document totals
		let net_total = frm.doc.net_total || total_amount;
		const total_taxes = frm.doc.total_taxes_and_charges || 0;
		const grand_total = frm.doc.grand_total || (net_total + total_taxes);

		// Use base_net_total if available (always tax-exclusive)
		if (frm.doc.base_net_total) {
			net_total = frm.doc.base_net_total;
		}

		// Check if prices are tax-inclusive
		const tax_inclusive = this.is_tax_inclusive(frm);

		// Profit calculation (always use net total - tax is not business profit)
		// Profit = Net Sales (before tax) - Cost of Goods Sold
		const profit = net_total - total_cost;

		// For margin: if tax-inclusive, show margin on grand total (what customer sees)
		// Otherwise show margin on net total
		const margin_base = tax_inclusive ? grand_total : net_total;
		const margin = margin_base > 0 ? (profit / margin_base * 100) : 0;

		return {
			total_cost: total_cost,
			net_total: net_total,
			grand_total: grand_total,
			total_taxes: total_taxes,
			profit: profit,
			margin: margin,
			tax_inclusive: tax_inclusive
		};
	},

	/**
	 * Add tax to a value based on tax rate
	 * @param {number} value - Base value (without tax)
	 * @param {number} tax_rate - Tax rate as decimal (e.g., 0.1 for 10%)
	 * @returns {number} Value with tax added
	 */
	add_tax_to_value: function(value, tax_rate) {
		if (!value || !tax_rate) {
			return value || 0;
		}
		return value * (1 + tax_rate);
	},

	/**
	 * Format a value with optional tax addition
	 * @param {number} value - Base value
	 * @param {boolean} add_tax - Whether to add tax
	 * @param {number} tax_rate - Tax rate as decimal
	 * @returns {number} Formatted value
	 */
	format_with_tax: function(value, add_tax, tax_rate) {
		if (add_tax && tax_rate > 0) {
			return this.add_tax_to_value(value, tax_rate);
		}
		return value || 0;
	}
};
