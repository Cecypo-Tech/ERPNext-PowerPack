/**
 * Shared Profit Calculator
 *
 * Pure functions over plain doc/row objects (a form's `frm` is accepted wherever a doc
 * is), so they can be unit-tested outside the desk: tests/js/profit_calculator.test.mjs.
 *
 * One basis for every number: company currency, net of tax, and the cost of the row's
 * own UOM. Costs arrive per *stock* UOM in company currency (see sales_insights.py), so
 * a row's cost is `valuation_rate × conversion_factor` and its price is `base_net_rate`.
 * Margin is profit ÷ net sale, whatever the document's tax setting: dividing by a
 * tax-inclusive price understated a 23.9% margin as 20.6% at 16% VAT and made the same
 * sale land in different colour bands depending only on the tax template.
 */

frappe.provide('cecypo_powerpack.profit_calculator');

(function () {
	const flt = (v) => {
		const n = parseFloat(v);
		return isNaN(n) ? 0 : n;
	};
	const doc_of = (frm_or_doc) => (frm_or_doc && frm_or_doc.doc) ? frm_or_doc.doc : frm_or_doc;

	const DEFAULT_BANDS = { low: 10, medium: 20, good: 30 };

	cecypo_powerpack.profit_calculator = {
		/**
		 * Whether item rates on this document include tax.
		 * @param {Object} frm_or_doc
		 */
		is_tax_inclusive: function (frm_or_doc) {
			const doc = doc_of(frm_or_doc);
			return !!(doc && doc.taxes && doc.taxes.some(tax => tax.included_in_print_rate === 1));
		},

		/**
		 * Document-level effective tax rate as a decimal (0.16 for 16%), transaction currency.
		 * @param {Object} frm_or_doc
		 */
		calculate_doc_tax_rate: function (frm_or_doc) {
			const doc = doc_of(frm_or_doc);
			if (!doc) return 0;
			const net_total = flt(doc.net_total) || flt(doc.base_net_total);
			return net_total > 0 ? flt(doc.total_taxes_and_charges) / net_total : 0;
		},

		/**
		 * Multiplier from a row's ex-tax price to the price it is quoted at: 1 unless the
		 * document's rates include tax. rate/net_rate is exact per row (item tax templates
		 * can differ by row) but also absorbs a document-level discount, so fall back to the
		 * document's tax rate when there is one.
		 */
		display_tax_factor: function (row, frm_or_doc) {
			const doc = doc_of(frm_or_doc);
			if (!this.is_tax_inclusive(doc)) return 1;
			if (!flt(doc.discount_amount) && flt(row.rate) > 0 && flt(row.net_rate) > 0) {
				return flt(row.rate) / flt(row.net_rate);
			}
			return 1 + this.calculate_doc_tax_rate(doc);
		},

		/**
		 * The row's net-of-tax, after-all-discounts selling rate in company currency, per
		 * row UOM. ERPNext keeps base_net_rate current on every recalculation; the fallbacks
		 * cover a row added a moment ago.
		 */
		row_net_rate_base: function (row, frm_or_doc) {
			const doc = doc_of(frm_or_doc);
			const conversion_rate = flt(doc.conversion_rate) || 1;
			if (flt(row.base_net_rate)) return flt(row.base_net_rate);
			if (flt(row.net_rate)) return flt(row.net_rate) * conversion_rate;
			return flt(row.rate) * conversion_rate / this.display_tax_factor(row, doc);
		},

		/**
		 * Per-unit profit for one row.
		 * @param {Object} row - item row
		 * @param {Object} frm_or_doc
		 * @param {number|null} valuation_rate - company currency per stock UOM
		 * @returns {{net, cost, profit, margin, markup}} company currency per row UOM;
		 *   cost/profit/margin/markup are null when the item has no cost, margin is null on
		 *   a zero price.
		 */
		row_profit: function (row, frm_or_doc, valuation_rate) {
			const net = this.row_net_rate_base(row, frm_or_doc);
			if (!(flt(valuation_rate) > 0)) {
				return { net, cost: null, profit: null, margin: null, markup: null };
			}
			const cost = flt(valuation_rate) * (flt(row.conversion_factor) || 1);
			const profit = net - cost;
			return {
				net,
				cost,
				profit,
				margin: net > 0 ? profit / net * 100 : null,
				markup: profit / cost * 100,
			};
		},

		/**
		 * Document profit over the rows that have a cost. Rows without one are left out of
		 * both sides and listed in `uncosted`: counting their revenue against zero cost
		 * reported it all as profit.
		 * @param {Object} frm_or_doc
		 * @param {Object} valuation_by_row - row.name → company-currency cost per stock UOM
		 */
		doc_profit: function (frm_or_doc, valuation_by_row) {
			const doc = doc_of(frm_or_doc);
			let revenue = 0, cost = 0, costed = 0, total = 0;
			const uncosted = [];
			(doc.items || []).forEach(row => {
				if (!row.item_code) return;
				total++;
				const valuation = flt(valuation_by_row[row.name]);
				if (!(valuation > 0)) {
					if (!uncosted.includes(row.item_code)) uncosted.push(row.item_code);
					return;
				}
				costed++;
				const qty = flt(row.qty);
				revenue += flt(row.base_net_amount) || this.row_net_rate_base(row, doc) * qty;
				// qty × conversion_factor is the stock qty, which is what valuation is per.
				cost += valuation * (flt(row.conversion_factor) || 1) * qty;
			});
			const profit = revenue - cost;
			return {
				revenue,
				cost,
				profit,
				margin: revenue > 0 ? profit / revenue * 100 : null,
				markup: cost > 0 ? profit / cost * 100 : null,
				costed,
				total,
				uncosted,
			};
		},

		/**
		 * A company-currency, per-stock-UOM, ex-tax value (cost, last purchase, last sale)
		 * restated the way this row's price is quoted: the row's UOM, the document's
		 * currency and, with `with_tax` on a tax-inclusive document, including tax.
		 */
		to_row_display: function (value, row, frm_or_doc, with_tax) {
			if (value === null || value === undefined) return null;
			const doc = doc_of(frm_or_doc);
			let v = flt(value) * (flt(row.conversion_factor) || 1) / (flt(doc.conversion_rate) || 1);
			if (with_tax) v *= this.display_tax_factor(row, doc);
			return v;
		},

		/**
		 * Margin band for the badge. Bands come from PowerPack Settings; an unset value
		 * (null / '') takes the default, a deliberate 0 is kept.
		 * @returns {{cls: string, label: string}}
		 */
		band: function (margin, settings) {
			const pick = (field, fallback) => {
				const v = settings && settings[field];
				return (v === null || v === undefined || v === '') ? fallback : flt(v);
			};
			const low = pick('sales_margin_low_below', DEFAULT_BANDS.low);
			const medium = pick('sales_margin_medium_below', DEFAULT_BANDS.medium);
			const good = pick('sales_margin_good_below', DEFAULT_BANDS.good);
			if (margin < 0) return { cls: 'profit-loss', label: 'Loss' };
			if (margin < low) return { cls: 'profit-low', label: 'Low' };
			if (margin < medium) return { cls: 'profit-medium', label: 'Medium' };
			if (margin < good) return { cls: 'profit-good', label: 'Good' };
			return { cls: 'profit-excellent', label: 'Excellent' };
		},
	};
})();
