// Copyright (c) 2026, Cecypo.Tech and contributors
// For license information, please see license.txt

frappe.provide('cecypo_powerpack.lens');

cecypo_powerpack.lens = {

	SALES_DOCTYPES: ['Quotation', 'Sales Order', 'Sales Invoice'],
	PURCHASE_DOCTYPES: ['Purchase Order', 'Purchase Receipt', 'Purchase Invoice'],

	SVG: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6.5" cy="6.5" r="4"/><line x1="10" y1="10" x2="14" y2="14"/></svg>',

	WH_SVG: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="12" height="7" rx="1"/><polyline points="1 7 8 2 15 7"/></svg>',

	init: function(frm) {
		CecypoPowerPack.Settings.isEnabled('enable_lens', function(enabled) {
			if (!enabled) return;
			var grid = frm.fields_dict.items && frm.fields_dict.items.grid;
			if (!grid) return;

			// Patch grid.refresh once so icons survive every subsequent grid re-render
			// (Frappe calls grid.refresh() after the initial form load for existing docs,
			// which wipes any buttons injected by a one-shot setTimeout)
			if (!grid._lens_patched) {
				grid._lens_patched = true;
				var _orig_refresh = grid.refresh.bind(grid);
				grid.refresh = function() {
					_orig_refresh.apply(this, arguments);
					cecypo_powerpack.lens.inject_all(frm);
				};
			}

			// Also inject for the current render pass
			setTimeout(function() {
				cecypo_powerpack.lens.inject_all(frm);
			}, 200);
		});
	},

	inject_all: function(frm) {
		var grid = frm.fields_dict.items && frm.fields_dict.items.grid;
		if (!grid) return;
		(grid.grid_rows || []).forEach(function(grid_row) {
			var item_doc = grid_row.doc;
			if (item_doc && item_doc.item_code) {
				cecypo_powerpack.lens.inject_row(frm, item_doc);
			}
		});
	},

	inject_row: function(frm, item_doc) {
		var grid = frm.fields_dict.items && frm.fields_dict.items.grid;
		if (!grid) return;
		var grid_row = grid.grid_rows_by_docname[item_doc.name];
		if (!grid_row || !grid_row.wrapper) return;

		// Remove stale icon from this row
		grid_row.wrapper.find('.lens-icon-btn').remove();

		var btn = $('<button class="lens-icon-btn" title="' + __('Lens — item insights') + '">' + cecypo_powerpack.lens.SVG + '</button>');

		btn.on('click', function(e) {
			e.stopPropagation();
			cecypo_powerpack.lens.open(frm, item_doc);
		});

		// Sit next to Frappe's .link-btn inside the item_name/item_code cell
		var data_row = grid_row.wrapper.find('.data-row').first();
		var target = data_row.find('[data-fieldname="item_name"]').first();
		if (!target.length) target = data_row.find('[data-fieldname="item_code"]').first();
		if (target.length) {
			var link_btn = target.find('.link-btn').first();
			if (link_btn.length) {
				btn.insertBefore(link_btn);
			} else {
				target.css('position', 'relative');
				target.append(btn);
			}
		} else {
			// Fallback: after edit button
			var open_btn = grid_row.wrapper.find('.btn-open-row').first();
			if (open_btn.length) btn.insertAfter(open_btn);
		}
	},

	open: function(frm, item_doc) {
		var doctype = frm.doctype;
		var customer = frm.doc.customer || null;

		// Quotation uses party_name; skip if party is a Lead
		if (!customer && frm.doc.party_name) {
			if (frm.doc.party_type !== 'Lead') {
				customer = frm.doc.party_name;
			}
		}

		var d = new frappe.ui.Dialog({
			title: __('Lens') + ' — ' + frappe.utils.escape_html(item_doc.item_name || item_doc.item_code),
			size: 'large',
		});
		d.$body.html('<div style="padding:20px;text-align:center;color:var(--text-muted)">' + __('Loading...') + '</div>');
		d.show();

		frappe.call({
			method: 'cecypo_powerpack.api.get_lens_data',
			args: {
				item_code: item_doc.item_code,
				customer: customer || '',
				doctype: doctype,
			},
			callback: function(r) {
				if (r.message) {
					if (typeof cecypo_powerpack.lens.render === 'function') {
						cecypo_powerpack.lens.render(d, r.message, doctype, customer, item_doc);
					} else {
						d.$body.html('<div style="padding:20px;text-align:center;color:var(--text-muted)">Render not yet implemented.</div>');
					}
				} else {
					d.$body.html('<div style="padding:20px;text-align:center;color:var(--text-muted)">No data found.</div>');
				}
			},
			error: function() {
				d.$body.html('<div style="padding:20px;text-align:center;color:var(--red)">Failed to load data.</div>');
			}
		});
	},

	// ── Rendering helpers ────────────────────────────────────────────

	_fmt_date: function(d) {
		return d ? moment(d).format('DD-MMM-YY') : '—';
	},

	_fmt_num: function(n) {
		if (n === null || n === undefined) return '—';
		return frappe.format(n, {fieldtype: 'Float', precision: 2});
	},

	_status_badge: function(status) {
		if (!status) return '';
		var s = (status || '').toLowerCase();
		var cls = 'lens-badge-default';
		if (s === 'paid') cls = 'lens-badge-paid';
		else if (s.indexOf('partly') !== -1 || s.indexOf('partial') !== -1) cls = 'lens-badge-partly';
		else if (s === 'unpaid') cls = 'lens-badge-unpaid';
		else if (s === 'overdue') cls = 'lens-badge-overdue';
		else if (s === 'draft') cls = 'lens-badge-draft';
		return '<span class="lens-badge ' + cls + '">' + frappe.utils.escape_html(__(status)) + '</span>';
	},

	_doc_link: function(name, doctype) {
		// Build /app/<slug>/<name> directly — more reliable than frappe.utils helpers across versions
		var slug = doctype.toLowerCase().replace(/ /g, '-');
		var url = '/app/' + slug + '/' + encodeURIComponent(name);
		return '<a class="lens-doc-link" href="' + url + '" target="_blank">' + frappe.utils.escape_html(name) + '</a>';
	},

	render: function(d, data, doctype, customer, item_doc) {
		var self = cecypo_powerpack.lens;
		var html = '';

		html += self._render_header(data);

		var is_sales = self.SALES_DOCTYPES.indexOf(doctype) !== -1;
		var is_purchase = self.PURCHASE_DOCTYPES.indexOf(doctype) !== -1;

		if (is_sales) {
			if (customer) {
				html += self._render_sales_to_customer(data.sales_to_customer || [], customer);
			}
			html += self._render_sales_to_others(data.sales_to_others || [], customer);
		}

		if (is_purchase) {
			html += self._render_purchase_history(data.purchase_history || []);
		}

		// New Rate editing only on PR and PI (not sales docs or PO)
		var show_new_rate = frappe.model.can_write('Item Price') &&
			(doctype === 'Purchase Receipt' || doctype === 'Purchase Invoice');
		html += self._render_price_lists(data.price_lists || [], data.valuation_rate || 0, show_new_rate);

		// Save Prices footer (only if show_new_rate)
		if (show_new_rate) {
			html += '<div class="lens-dialog-footer">';
			html += '<button class="btn btn-sm btn-primary lens-save-prices-btn">' + __('Save Prices') + '</button>';
			html += '</div>';
		}

		d.$body.html('<div class="lens-dialog-body">' + html + '</div>');

		self._wire_stock_popover(d, data.stock_by_warehouse);
		self._wire_price_editing(d, data.price_lists || [], data.valuation_rate || 0);

		if (show_new_rate) {
			d.$body.find('.lens-save-prices-btn').on('click', function() {
				self._save_prices(d, data.price_lists || []);
			});
		}
	},

	_render_header: function(data) {
		var wh_icon = cecypo_powerpack.lens.WH_SVG;
		var html = '<div class="lens-item-header">';
		html += '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">';
		html += '<span class="lens-item-name">' + frappe.utils.escape_html(data.item_name || '') + '</span>';
		if (data.item_group) {
			html += '<span class="lens-item-group-badge">' + frappe.utils.escape_html(data.item_group) + '</span>';
		}
		html += '</div>';

		// Stock chip
		var total = cecypo_powerpack.lens._fmt_num(data.total_stock || 0);
		html += '<div class="lens-stock-chip" data-has-popover="' + (data.stock_by_warehouse ? '1' : '0') + '">';
		html += '<div class="lens-stock-chip-label">' + wh_icon + ' ' + total + ' ' + __('units') + '</div>';
		if (data.stock_by_warehouse && data.stock_by_warehouse.length) {
			html += '<div class="lens-stock-popover">';
			html += '<div class="lens-popover-title">' + __('Stock by warehouse') + '</div>';
			data.stock_by_warehouse.forEach(function(row) {
				var low = row.qty <= 5 ? ' low-stock' : '';
				html += '<div class="lens-popover-row">';
				html += '<span class="lens-popover-wh">' + frappe.utils.escape_html(row.warehouse) + '</span>';
				html += '<span class="lens-popover-qty' + low + '">' + cecypo_powerpack.lens._fmt_num(row.qty) + '</span>';
				html += '</div>';
			});
			html += '<div class="lens-popover-total">';
			html += '<span>' + __('Total') + '</span><span>' + total + '</span>';
			html += '</div>';
			html += '</div>'; // .lens-stock-popover
		}
		html += '</div>'; // .lens-stock-chip
		html += '</div>'; // .lens-item-header
		return html;
	},

	_render_sales_to_customer: function(rows, customer) {
		var self = cecypo_powerpack.lens;
		var html = '<div class="lens-section-header">' + __('Sales to') + ' ' + frappe.utils.escape_html(customer) + ' — ' + __('this item') + '</div>';
		html += '<table class="lens-table"><thead><tr>';
		html += '<th>' + __('Doc') + '</th><th>' + __('Date') + '</th>';
		html += '<th class="right">' + __('Qty') + '</th><th class="right">' + __('Rate') + '</th>';
		html += '<th>' + __('Status') + '</th></tr></thead><tbody>';
		if (!rows.length) {
			html += '<tr class="lens-empty-row"><td colspan="5">' + __('No previous sales to this customer') + '</td></tr>';
		} else {
			rows.forEach(function(r) {
				html += '<tr>';
				html += '<td>' + self._doc_link(r.name, r.source_doctype || 'Sales Invoice') + '</td>';
				html += '<td>' + self._fmt_date(r.posting_date) + '</td>';
				html += '<td class="right">' + self._fmt_num(r.qty) + '</td>';
				html += '<td class="right">' + self._fmt_num(r.rate) + '</td>';
				html += '<td>' + self._status_badge(r.status) + '</td>';
				html += '</tr>';
			});
		}
		html += '</tbody></table>';
		return html;
	},

	_render_sales_to_others: function(rows, current_customer) {
		var self = cecypo_powerpack.lens;
		var label = current_customer ? __('Sales to other customers — this item') : __('Sales history — this item');
		var html = '<div class="lens-section-header">' + label + '</div>';
		html += '<table class="lens-table"><thead><tr>';
		html += '<th>' + __('Doc') + '</th><th>' + __('Customer') + '</th><th>' + __('Date') + '</th>';
		html += '<th class="right">' + __('Qty') + '</th><th class="right">' + __('Rate') + '</th>';
		html += '</tr></thead><tbody>';
		if (!rows.length) {
			html += '<tr class="lens-empty-row"><td colspan="5">' + __('No sales to other customers found') + '</td></tr>';
		} else {
			rows.forEach(function(r) {
				html += '<tr>';
				html += '<td>' + self._doc_link(r.name, 'Sales Invoice') + '</td>';
				html += '<td>' + frappe.utils.escape_html(r.customer || '') + '</td>';
				html += '<td>' + self._fmt_date(r.posting_date) + '</td>';
				html += '<td class="right">' + self._fmt_num(r.qty) + '</td>';
				html += '<td class="right">' + self._fmt_num(r.rate) + '</td>';
				html += '</tr>';
			});
		}
		html += '</tbody></table>';
		return html;
	},

	_render_purchase_history: function(rows) {
		var self = cecypo_powerpack.lens;
		var html = '<div class="lens-section-header">' + __('Purchase history — this item') + '</div>';
		html += '<table class="lens-table"><thead><tr>';
		html += '<th>' + __('Doc') + '</th><th>' + __('Supplier') + '</th><th>' + __('Date') + '</th>';
		html += '<th class="right">' + __('Qty') + '</th><th class="right">' + __('Rate') + '</th>';
		html += '</tr></thead><tbody>';
		if (!rows.length) {
			html += '<tr class="lens-empty-row"><td colspan="5">' + __('No purchase history found') + '</td></tr>';
		} else {
			rows.forEach(function(r) {
				html += '<tr>';
				html += '<td>' + self._doc_link(r.name, r.source_doctype || 'Purchase Invoice') + '</td>';
				html += '<td>' + frappe.utils.escape_html(r.supplier || '') + '</td>';
				html += '<td>' + self._fmt_date(r.posting_date) + '</td>';
				html += '<td class="right">' + self._fmt_num(r.qty) + '</td>';
				html += '<td class="right">' + self._fmt_num(r.rate) + '</td>';
				html += '</tr>';
			});
		}
		html += '</tbody></table>';
		return html;
	},

	_render_price_lists: function(rows, valuation_rate, show_new_rate) {
		var self = cecypo_powerpack.lens;
		var show_margin = valuation_rate > 0;
		var col_count = 2 + (show_margin ? 1 : 0) + (show_new_rate ? 1 : 0) + (show_new_rate && show_margin ? 1 : 0);
		var html = '<div class="lens-section-header">' + __('Price Lists') + '</div>';
		html += '<table class="lens-table"><thead><tr>';
		html += '<th>' + __('List') + '</th><th class="right">' + __('Rate') + '</th>';
		if (show_margin) html += '<th class="right">' + __('Margin') + '</th>';
		if (show_new_rate) {
			html += '<th class="right">' + __('New Rate') + '</th>';
			if (show_margin) html += '<th class="right">' + __('New Margin') + '</th>';
		}
		html += '</tr></thead><tbody>';
		if (!rows.length) {
			html += '<tr class="lens-empty-row"><td colspan="' + col_count + '">' + __('No price list entries found') + '</td></tr>';
		} else {
			rows.forEach(function(r) {
				var margin = (show_margin && r.rate) ? ((r.rate - valuation_rate) / r.rate * 100) : null;
				var margin_str = (margin !== null) ? margin.toFixed(1) + '%' : '—';
				html += '<tr>';
				html += '<td>' + frappe.utils.escape_html(r.price_list) + '</td>';
				html += '<td class="right">' + self._fmt_num(r.rate) + '</td>';
				if (show_margin) html += '<td class="right">' + margin_str + '</td>';
				if (show_new_rate) {
					html += '<td class="right"><input class="lens-new-rate" type="number" step="any"';
					html += ' data-item-price-name="' + frappe.utils.escape_html(r.item_price_name) + '"';
					html += ' data-current-rate="' + (r.rate || 0) + '"';
					html += ' value="' + (r.rate || '') + '"></td>';
					if (show_margin) {
						html += '<td class="right"><span class="lens-new-margin" data-valuation="' + valuation_rate + '">' + margin_str + '</span></td>';
					}
				}
				html += '</tr>';
			});
		}
		html += '</tbody></table>';
		return html;
	},

	_wire_stock_popover: function(d, warehouse_data) {
		// CSS :hover handles the popover display — no JS wiring needed.
	},

	_wire_price_editing: function(d, price_lists, valuation_rate) {
		d.$body.find('.lens-new-rate').on('input', function() {
			var new_rate = parseFloat($(this).val()) || 0;
			var margin_el = $(this).closest('tr').find('.lens-new-margin');
			if (valuation_rate && new_rate) {
				var new_margin = (new_rate - valuation_rate) / new_rate * 100;
				margin_el.text(new_margin.toFixed(1) + '%');
				margin_el.toggleClass('negative', new_margin < 0);
			} else {
				margin_el.text('—');
			}
		});
	},

	_save_prices: function(d, price_lists) {
		var updates = [];
		d.$body.find('.lens-new-rate').each(function() {
			var new_rate = parseFloat($(this).val());
			var current_rate = parseFloat($(this).data('current-rate'));
			var name = $(this).data('item-price-name');
			if (name && !isNaN(new_rate) && new_rate !== current_rate) {
				updates.push({item_price_name: name, new_rate: new_rate});
			}
		});

		if (!updates.length) {
			frappe.show_alert({message: __('No prices changed'), indicator: 'blue'});
			return;
		}

		frappe.call({
			method: 'cecypo_powerpack.api.update_item_prices',
			args: {updates: JSON.stringify(updates)},
			callback: function(r) {
				if (r.message && r.message.count) {
					frappe.show_alert({
						message: __('Updated {0} price(s)', [r.message.count]),
						indicator: 'green'
					});
					// Refresh current-rate data attributes so next save is accurate
					d.$body.find('.lens-new-rate').each(function() {
						$(this).data('current-rate', $(this).val());
					});
				}
			},
			error: function() {
				frappe.show_alert({message: __('Failed to save prices'), indicator: 'red'});
			}
		});
	},

};

// ── Register on all target doctypes ──────────────────────────────────────

var _LENS_DOCTYPES = cecypo_powerpack.lens.SALES_DOCTYPES.concat(cecypo_powerpack.lens.PURCHASE_DOCTYPES);

_LENS_DOCTYPES.forEach(function(dt) {
	frappe.ui.form.on(dt, {
		refresh: function(frm) {
			cecypo_powerpack.lens.init(frm);
		},
		form_render: function(frm, cdt, cdn) {
			CecypoPowerPack.Settings.isEnabled('enable_lens', function(enabled) {
				if (!enabled) return;
				var item = frappe.get_doc(cdt, cdn);
				if (item && item.item_code) {
					cecypo_powerpack.lens.inject_row(frm, item);
				}
			});
		},
		items_add: function(frm, cdt, cdn) {
			// Icon injected later when item_code is set, via items_item_code
		},
	});

	// Inject icon when item_code is set on a row
	frappe.ui.form.on(dt + ' Item', {
		item_code: function(frm, cdt, cdn) {
			CecypoPowerPack.Settings.isEnabled('enable_lens', function(enabled) {
				if (!enabled) return;
				var item = frappe.get_doc(cdt, cdn);
				if (item && item.item_code) {
					cecypo_powerpack.lens.inject_row(frm, item);
				}
			});
		},
	});
});
