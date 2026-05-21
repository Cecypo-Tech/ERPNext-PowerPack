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
			cecypo_powerpack.lens.inject_all(frm);
		});
	},

	inject_all: function(frm) {
		if (!frm.doc.items || !frm.doc.items.length) return;
		frm.doc.items.forEach(function(item) {
			if (item.item_code) {
				cecypo_powerpack.lens.inject_row(frm, item);
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

		// Insert before the delete button; fall back to appending to data-row
		var del_btn = grid_row.wrapper.find('.grid-delete-row').first();
		if (del_btn.length) {
			btn.insertBefore(del_btn);
		} else {
			var data_row = grid_row.wrapper.find('.data-row').first();
			if (data_row.length) {
				data_row.append(btn);
			}
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
			title: __('Lens') + ' — ' + (item_doc.item_name || item_doc.item_code),
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
					cecypo_powerpack.lens.render(d, r.message, doctype, customer, item_doc);
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
		return '<span class="lens-badge ' + cls + '">' + __(status) + '</span>';
	},

	_doc_link: function(name, doctype) {
		// Build /app/<slug>/<name> directly — more reliable than frappe.utils helpers across versions
		var slug = doctype.toLowerCase().replace(/ /g, '-');
		var url = '/app/' + slug + '/' + encodeURIComponent(name);
		return '<a class="lens-doc-link" href="' + url + '" target="_blank">' + frappe.utils.escape_html(name) + '</a>';
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
