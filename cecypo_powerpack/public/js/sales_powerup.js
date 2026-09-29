// Copyright (c) 2024, Cecypo.Tech and contributors
// For license information, please see license.txt

/**
 * Sales Powerup: stock, cost, purchase/sale history and a margin badge under each item
 * row of Quotation / Sales Order / Sales Invoice / POS Invoice, and a profit summary by
 * the Items label. Toggled from the form's Powerup ▾ menu (Show / Hide Item Insights).
 *
 * Data for every row comes from one call, cecypo_powerpack.sales_insights
 * .get_sales_item_insights, cached for a few minutes per (company, customer, item,
 * warehouse). Cost fields arrive only for users with `sales_visible_to_role`; the
 * server enforces that, the browser just follows `can_see_cost`.
 *
 * Nothing here writes to the doc: dirtying the form flips Submit back to Save.
 * All maths is in profit_calculator.js.
 */

frappe.provide('cecypo_powerpack.sales_powerup');

(function () {
	const FEATURE_BY_DOCTYPE = {
		'Quotation': 'enable_quotation_powerup',
		'Sales Order': 'enable_sales_order_powerup',
		'Sales Invoice': 'enable_sales_invoice_powerup',
		'POS Invoice': 'enable_pos_invoice_powerup',
	};
	const CACHE_TTL_MS = 5 * 60 * 1000;
	const FETCH_DELAY_MS = 150;
	const RENDER_DELAY_MS = 100;

	const flt = (v) => {
		const n = parseFloat(v);
		return isNaN(n) ? 0 : n;
	};
	const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
	const amount = (v) => format_number(v, null, 2);
	const qty = (v) => format_number(v, null, 0);
	const short_date = (d) => moment(d).format('DD-MMM-YY');
	const pct = (v) => (v === null || v === undefined) ? '—' : `${v.toFixed(1)}%`;

	const sp = cecypo_powerpack.sales_powerup = {
		settings: {},
		can_see_cost: false,
		_cache: {},     // key → {data, at}
		_inflight: {},  // key → true while a request for it is out

		is_enabled(frm) {
			return cint(sp.settings[FEATURE_BY_DOCTYPE[frm.doctype]]) === 1;
		},

		customer_of(frm) {
			if (frm.doctype === 'Quotation') {
				// party_name holds a Lead or Prospect unless quoting to a Customer
				return frm.doc.quotation_to === 'Customer' ? frm.doc.party_name : null;
			}
			return frm.doc.customer || null;
		},

		warehouse_of(frm, row) {
			return row.warehouse || frm.doc.set_warehouse || null;
		},

		key(frm, row) {
			return [frm.doc.company, sp.customer_of(frm), row.item_code, sp.warehouse_of(frm, row)]
				.map(v => v || '').join('\u001f');
		},

		// ---- lifecycle -------------------------------------------------------------

		setup(frm) {
			CecypoPowerPack.Settings.get(function (settings) {
				if (!settings || !Object.keys(settings).length) return;
				sp.settings = settings;
				if (!sp.is_enabled(frm)) return;
				// First load in this session takes the setting; later loads keep the user's toggle.
				if (frm._powerpack_visible === undefined) {
					frm._powerpack_visible = settings.sales_powerup_shown_by_default !== 0;
				}
				sp.add_toggle(frm);
				sp.fetch(frm);
			});
		},

		add_toggle(frm) {
			const group = __('Powerup');
			const show = __('Show Item Insights');
			const hide = __('Hide Item Insights');
			frm.remove_custom_button(show, group);
			frm.remove_custom_button(hide, group);
			frm.add_custom_button(frm._powerpack_visible ? hide : show, () => sp.toggle(frm), group);
		},

		toggle(frm) {
			frm._powerpack_visible = !frm._powerpack_visible;
			if (frm._powerpack_visible) {
				sp.fetch(frm);
			} else {
				sp.clear(frm);
			}
			sp.add_toggle(frm);
		},

		clear(frm) {
			$(frm.wrapper).find('.sales-item-info, .profit-metrics-section').remove();
		},

		active(frm) {
			return sp.is_enabled(frm) && frm._powerpack_visible;
		},

		// ---- data --------------------------------------------------------------------

		schedule_fetch(frm) {
			if (!sp.active(frm)) return;
			clearTimeout(frm._pp_fetch_timer);
			frm._pp_fetch_timer = setTimeout(() => sp.fetch(frm), FETCH_DELAY_MS);
		},

		/** Request every row whose data is missing or stale, all in one call. */
		fetch(frm) {
			if (!sp.active(frm)) return;
			const now = Date.now();
			const wanted = {};
			(frm.doc.items || []).forEach(row => {
				if (!row.item_code) return;
				const k = sp.key(frm, row);
				const hit = sp._cache[k];
				if ((hit && now - hit.at < CACHE_TTL_MS) || sp._inflight[k]) return;
				wanted[k] = { item_code: row.item_code, warehouse: sp.warehouse_of(frm, row) };
			});

			const keys = Object.keys(wanted);
			if (!keys.length) {
				sp.schedule_render(frm);
				return;
			}
			keys.forEach(k => { sp._inflight[k] = true; });

			const customer = sp.customer_of(frm);
			const company = frm.doc.company;
			frappe.call({
				method: 'cecypo_powerpack.sales_insights.get_sales_item_insights',
				args: {
					doctype: frm.doctype,
					items: JSON.stringify(Object.values(wanted)),
					customer: customer,
					company: company,
				},
				callback(r) {
					const msg = r.message || {};
					sp.can_see_cost = !!msg.can_see_cost;
					(msg.items || []).forEach(d => {
						const k = [company, customer, d.item_code, d.warehouse].map(v => v || '').join('\u001f');
						sp._cache[k] = { data: d, at: Date.now() };
					});
				},
				always() {
					keys.forEach(k => { delete sp._inflight[k]; });
					sp.schedule_render(frm);
				},
			});
		},

		// ---- rendering ---------------------------------------------------------------

		/** Coalesces the burst of events one edit fires (rate, qty, taxes, totals…). */
		schedule_render(frm) {
			clearTimeout(frm._pp_render_timer);
			frm._pp_render_timer = setTimeout(() => sp.render(frm), RENDER_DELAY_MS);
		},

		render(frm) {
			if (!sp.active(frm)) {
				sp.clear(frm);
				return;
			}
			const valuations = {};
			(frm.doc.items || []).forEach(row => {
				const hit = row.item_code && sp._cache[sp.key(frm, row)];
				const data = hit ? hit.data : null;
				valuations[row.name] = data ? data.valuation_rate : null;
				sp.render_row(frm, row, data);
			});
			if (sp.can_see_cost && sp.settings.show_profit_indicator !== 0) {
				sp.render_summary(frm, valuations);
			} else {
				$(frm.wrapper).find('.profit-metrics-section').remove();
			}
		},

		render_row(frm, row, data) {
			const grid_row = frm.fields_dict.items.grid.grid_rows_by_docname[row.name];
			if (!grid_row || !grid_row.wrapper) return;
			let $info = grid_row.wrapper.find('.sales-item-info');
			const html = data ? sp.row_html(frm, row, data) : '';
			if (!html) {
				$info.remove();
				return;
			}
			if (!$info.length) {
				$info = $('<div class="sales-item-info"></div>');
				const $form = grid_row.wrapper.find('.form-in-grid');
				const $row = grid_row.wrapper.find('.grid-row').first();
				if ($form.length) $form.after($info);
				else if ($row.length) $row.after($info);
				else grid_row.wrapper.append($info);
			}
			if ($info.data('html') !== html) {
				$info.html(html).data('html', html);
			}
		},

		row_html(frm, row, data) {
			const s = sp.settings;
			const calc = cecypo_powerpack.profit_calculator;
			const doc = frm.doc;
			const tax_inclusive = calc.is_tax_inclusive(doc);
			// '+' marks a value that has tax to add, like the row's own price does.
			const plus = !tax_inclusive && (doc.taxes || []).some(t => flt(t.rate) > 0) ? '+' : '';
			const shown = (v) => amount(calc.to_row_display(v, row, doc, true)) + plus;
			const parts = [];

			if (s.show_stock_info !== 0 && data.actual_qty !== null && data.actual_qty !== undefined) {
				const scope = data.warehouse ? esc(data.warehouse) : __('all warehouses');
				const bits = [`${__('Phy')}: ${qty(data.actual_qty)}`];
				if (flt(data.reserved_qty) > 0) bits.push(`${__('Res')}: ${qty(data.reserved_qty)}`);
				bits.push(`${__('Avl')}: ${qty(data.available_qty)}`);
				const title = __('In stock / reserved / available (projected) in {0}, in stock UOM', [scope]);
				parts.push(`<span class="info-item" title="${esc(title)}"><strong>${__('Stock')}:</strong> ${bits.join('&nbsp;&bull;&nbsp;')}</span>`);
			}

			if (sp.can_see_cost && s.show_valuation_rate !== 0 && data.valuation_rate) {
				parts.push(`<span class="info-item"><strong>${__('Cost')}:</strong> ${shown(data.valuation_rate)}</span>`);
			}

			const history = [
				['last_purchase', __('Last Purchase'), sp.can_see_cost && s.show_last_purchase !== 0],
				['last_sale', __('Last Sale'), s.show_last_sale !== 0],
				['last_sale_to_customer', __('Last Sold to Customer'), s.show_last_sale_to_customer !== 0],
			];
			history.forEach(([prefix, label, visible]) => {
				const rate = data[`${prefix}_rate`];
				if (!visible || rate === null || rate === undefined) return;
				const date = data[`${prefix}_date`] ? ` (${short_date(data[`${prefix}_date`])})` : '';
				parts.push(`<span class="info-item"><strong>${label}:</strong> ${shown(rate)}${date}</span>`);
			});

			let badge = '';
			if (sp.can_see_cost && s.show_profit_indicator !== 0) {
				badge = sp.badge_html(frm, row, data);
			}
			if (!parts.length && !badge) return '';
			return `<div class="sales-item-details">${parts.join('')}${badge}</div>`;
		},

		badge_html(frm, row, data) {
			const calc = cecypo_powerpack.profit_calculator;
			const doc = frm.doc;
			const r = calc.row_profit(row, doc, data.valuation_rate);
			const uom = esc(row.uom || row.stock_uom || '');
			if (r.cost === null) {
				const why = data.actual_qty === null ? __('Not a stock item') : __('No valuation rate');
				return `<span class="item-profit-indicator profit-none" title="${esc(why)}">${__('No cost')}</span>`;
			}
			if (r.margin === null) {
				return `<span class="item-profit-indicator profit-none" title="${esc(__('No price'))}">—</span>`;
			}
			// Tooltip in the document's currency, ex tax, per row UOM so it can be checked
			// against the row; the margin itself is currency-free.
			const cr = flt(doc.conversion_rate) || 1;
			const title = __('Net {0} − Cost {1} = {2} per {3} (ex. tax)', [
				amount(r.net / cr), amount(r.cost / cr), amount(r.profit / cr), uom,
			]) + '\n' + __('Margin {0} · Markup {1}', [pct(r.margin), pct(r.markup)]);
			const band = calc.band(r.margin, sp.settings);
			return `<span class="item-profit-indicator ${band.cls}" title="${esc(title)}">`
				+ `<span class="profit-dot"></span>${pct(r.margin)}</span>`;
		},

		render_summary(frm, valuations) {
			const $wrapper = frm.fields_dict.items.$wrapper;
			const has_items = (frm.doc.items || []).some(row => row.item_code);
			if (!has_items) {
				$wrapper.find('.profit-metrics-section').remove();
				return;
			}
			const calc = cecypo_powerpack.profit_calculator;
			const m = calc.doc_profit(frm.doc, valuations);

			// Summary amounts are company currency; say so when the document is in another.
			const company_currency = window.erpnext && erpnext.get_currency
				? erpnext.get_currency(frm.doc.company) : null;
			const currency_note = company_currency && company_currency !== frm.doc.currency
				? ` <span class="tax-info">${esc(company_currency)}</span>` : '';
			const tax_note = flt(frm.doc.total_taxes_and_charges)
				? ` <span class="tax-info">${__('ex. tax')}</span>` : '';

			const cls = m.costed ? (m.profit >= 0 ? 'profit-positive-bg' : 'profit-negative-bg') : '';
			let coverage = '';
			if (m.costed < m.total) {
				const title = __('Not costed: {0}. Profit and margin cover costed items only.', [m.uncosted.join(', ')]);
				coverage = `<span class="metric-mini metric-coverage" title="${esc(title)}">`
					+ `${__('Costed {0}/{1}', [m.costed, m.total])}</span>`;
			}

			// Nothing costed: zeros everywhere would read as a break-even sale.
			const html = !m.costed ? `<div class="profit-metrics-section">${coverage}</div>` : `
				<div class="profit-metrics-section ${cls}">
					<span class="metric-mini">${__('Cost')}: ${amount(m.cost)}</span>
					<span class="metric-mini">${__('Net Sale')}: ${amount(m.revenue)}${tax_note}</span>
					<span class="metric-mini metric-highlight">${__('Profit')}: ${amount(m.profit)}${currency_note}</span>
					<span class="metric-mini">${__('Margin')}: ${pct(m.margin)}</span>
					<span class="metric-mini">${__('Markup')}: ${pct(m.markup)}</span>
					${coverage}
				</div>`;

			let $section = $wrapper.find('.profit-metrics-section');
			if ($section.length && $section.data('html') === html) return;
			$section.remove();
			$section = $(html).data('html', html);
			const $label = $wrapper.find('.clearfix').first();
			if ($label.length) $label.append($section);
			else frm.fields_dict.items.grid.wrapper.before($section);
		},
	};

	// ---- form events (same wiring for every sales doctype) ----------------------------

	const fetch_events = ['customer', 'party_name', 'quotation_to', 'company', 'set_warehouse'];
	const render_events = [
		'conversion_rate', 'currency', 'taxes_and_charges', 'total_taxes_and_charges',
		'grand_total', 'discount_amount', 'additional_discount_percentage', 'apply_discount_on',
	];
	const row_fetch_events = ['item_code', 'warehouse', 'items_add'];
	const row_render_events = [
		'qty', 'rate', 'uom', 'conversion_factor', 'discount_percentage', 'discount_amount',
		'price_list_rate', 'items_remove',
	];

	Object.keys(FEATURE_BY_DOCTYPE).forEach(doctype => {
		const parent_handlers = {
			refresh(frm) {
				sp.setup(frm);
			},
		};
		fetch_events.forEach(ev => { parent_handlers[ev] = frm => sp.schedule_fetch(frm); });
		render_events.forEach(ev => { parent_handlers[ev] = frm => sp.active(frm) && sp.schedule_render(frm); });
		frappe.ui.form.on(doctype, parent_handlers);

		const row_handlers = {};
		row_fetch_events.forEach(ev => { row_handlers[ev] = frm => sp.schedule_fetch(frm); });
		row_render_events.forEach(ev => { row_handlers[ev] = frm => sp.active(frm) && sp.schedule_render(frm); });
		frappe.ui.form.on(`${doctype} Item`, row_handlers);
	});
})();
