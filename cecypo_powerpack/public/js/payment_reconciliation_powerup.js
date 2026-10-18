/**
 * Payment Reconciliation PowerUp
 *
 * All features are gated by enable_payment_reconciliation_powerup in PowerPack Settings:
 *   - Zero Allocate  : creates zero-amount allocation rows for manual distribution
 *   - Zero Reconcile : reconciles allocations, filtering zero-amount entries
 *   - 2% Allocate    : sets allocations to 2% of invoice net total (Supplier only)
 *   - Load Additional Doc Info : injects ETR / Bill No / VAT Withholding info inline
 *
 * Performance: uses batch queries (1 API call per table, never 1 per row).
 */

(function () {

// ─── Constants ────────────────────────────────────────────────────────────────

const DISPLAY_CLASSES = [
	'.etr-invoice-display',
	'.vat-withholding-display',
	'.bill-no-display',
	'.payment-credit-note-display',
	'.allocation-bill-no-display',
].join(',');

const PALETTE = [
	'#10b981', '#3b82f6', '#8b5cf6', '#ec4899',
	'#f59e0b', '#ef4444', '#06b6d4', '#6366f1',
	'#14b8a6', '#f97316',
];

// ─── Colour helpers ───────────────────────────────────────────────────────────

function color_for(key) {
	if (!key) return '#94a3b8';
	let h = 0;
	for (let i = 0; i < key.length; i++) h = key.charCodeAt(i) + ((h << 5) - h);
	return PALETTE[Math.abs(h) % PALETTE.length];
}

function hex_to_rgba(hex, alpha) {
	if (!hex || !hex.startsWith('#') || hex.length < 7) return `rgba(148,163,184,${alpha})`;
	const r = parseInt(hex.slice(1, 3), 16);
	const g = parseInt(hex.slice(3, 5), 16);
	const b = parseInt(hex.slice(5, 7), 16);
	return `rgba(${r},${g},${b},${alpha})`;
}

// ─── DOM helpers ──────────────────────────────────────────────────────────────

function remove_all_displays() {
	$(DISPLAY_CLASSES).remove();
}

function lbl(text) {
	return `<span style="font-weight:600;color:var(--heading-color);">${text}</span>`;
}

function badge(text, color) {
	return `<span style="
		display:inline-block;padding:1px 7px;
		background:${hex_to_rgba(color, 0.15)};
		border:1px solid ${hex_to_rgba(color, 0.35)};
		border-radius:4px;font-size:10px;font-weight:700;
		color:${color};letter-spacing:.3px;vertical-align:middle;
	">${text}</span>`;
}

function inject_display(cls, grid, docname, border_color, html_content) {
	// Find row by data-name — avoids stale jQuery refs after grid rebuilds
	const $row_el = $(grid.wrapper).find(`.grid-row[data-name="${docname}"]`);
	if (!$row_el.length || !$row_el.is(':visible')) return;

	// Deduplicate: check by class + data-rowname
	const esc = docname.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
	if ($(`.${cls}[data-rowname="${esc}"]`).length) return;

	const $el = $(`<div
		class="${cls} recon-info-row"
		data-rowname="${frappe.utils.escape_html(docname)}"
		style="
			display:flex;align-items:center;flex-wrap:wrap;gap:6px;
			padding:4px 10px 4px 11px;margin:-6px 0 4px 0;
			font-size:11.5px;line-height:1.5;color:var(--text-muted);
			background-color:${hex_to_rgba(border_color, 0.06)};
			border-left:3px solid ${border_color};border-radius:0 4px 4px 0;
		">${html_content}</div>`);
	$row_el.after($el);
}

// ─── Feature gate ─────────────────────────────────────────────────────────────

function is_powerpack_enabled() {
	return new Promise(resolve =>
		CecypoPowerPack.Settings.isEnabled('enable_payment_reconciliation_powerup', resolve)
	);
}

// ═══════════════════════════════════════════════════════════════════════════════
// FORM EVENTS
// ═══════════════════════════════════════════════════════════════════════════════

frappe.ui.form.on('Payment Reconciliation', {
	refresh(frm) {
		remove_all_displays();
		is_powerpack_enabled().then(enabled => {
			if (!enabled) return;
			setup_zero_allocate_button(frm);
			setup_zero_allocate_paste_button(frm);
			setup_load_doc_info_button(frm);
			setup_allocate_2pct_button(frm);
		});
	},
	party_type(frm) {
		remove_all_displays();
		is_powerpack_enabled().then(enabled => {
			if (!enabled) return;
			setup_zero_allocate_paste_button(frm);
			setup_allocate_2pct_button(frm);
		});
	},
	get_unreconciled_entries(frm) {
		remove_all_displays();
		is_powerpack_enabled().then(enabled => {
			if (enabled) setup_zero_allocate_paste_button(frm);
		});
	},
	allocate(frm) {
		remove_all_displays();
		is_powerpack_enabled().then(enabled => {
			if (enabled) setup_allocate_2pct_button(frm);
		});
	},
});

frappe.ui.form.on('Payment Reconciliation Allocation', {
	allocation_add(frm)    { setup_zero_reconcile_button(frm); },
	allocated_amount(frm)  { setup_zero_reconcile_button(frm); },
	allocation_remove(frm) { remove_all_displays(); },
});
frappe.ui.form.on('Payment Reconciliation Invoice', { invoices_remove(frm)  { remove_all_displays(); } });
frappe.ui.form.on('Payment Reconciliation Payment', { payments_remove(frm)  { remove_all_displays(); } });

// ═══════════════════════════════════════════════════════════════════════════════
// ZERO ALLOCATE
// ═══════════════════════════════════════════════════════════════════════════════

function setup_zero_allocate_button(frm) {
	try { frm.page.remove_inner_button(__('Zero Allocate'), __('Powerup')); } catch (_) {}
	if (!frm.doc.payments?.length || !frm.doc.invoices?.length) return;
	frm.page.add_inner_button(__('Zero Allocate'), () => zero_allocate(frm), __('Powerup'));
}

function setup_zero_reconcile_button(frm) {
	if (!frm.doc?.allocation?.length) return;

	try { frm.page.remove_inner_button(__('Zero Reconcile'), __('Powerup')); } catch (_) {}

	frm.page.add_inner_button(__('Zero Reconcile'), function () {
		// counted on click: amounts are typed after the button is built
		const non_zero   = frm.doc.allocation.filter(a => (a.allocated_amount || 0) > 0).length;
		const zero_count = frm.doc.allocation.length - non_zero;
		const msg = zero_count > 0
			? __('Reconcile {0} non-zero allocation(s)? ({1} zero allocation(s) will be filtered out)', [non_zero, zero_count])
			: __('Reconcile {0} allocation(s)?', [non_zero]);

		frappe.confirm(msg, function () {
			frm.call({
				doc: frm.doc,
				method: 'zero_reconcile',
				freeze: true,
				freeze_message: __('Reconciling...'),
				callback(r) {
					if (!r.exc) {
						frm.clear_table('allocation');
						frm.clear_table('payments');
						frm.clear_table('invoices');
						frm.refresh_fields();
						frappe.show_alert({ message: __('Successfully reconciled'), indicator: 'green' });
						try { frm.page.remove_inner_button(__('Zero Reconcile'), __('Powerup')); } catch (_) {}
					}
				},
			});
		});
	}, __('Powerup'));
}

function zero_allocate(frm) {
	let selected_payments, selected_invoices;
	try {
		selected_payments = frm.fields_dict.payments.grid.get_selected_children();
		selected_invoices = frm.fields_dict.invoices.grid.get_selected_children();
	} catch (_) {
		frappe.msgprint({ title: __('Error'), message: __('Unable to get selected items. Please try again.'), indicator: 'red' });
		return;
	}

	if (!selected_payments?.length) {
		frappe.msgprint({ title: __('Selection Required'), message: __('Please select at least one payment'), indicator: 'orange' });
		return;
	}
	if (!selected_invoices?.length) {
		frappe.msgprint({ title: __('Selection Required'), message: __('Please select at least one invoice'), indicator: 'orange' });
		return;
	}

	const total_rows  = selected_payments.length * selected_invoices.length;
	const has_existing = frm.doc.allocation?.length > 0;
	const proceed = () => has_existing
		? show_replace_append_dialog(frm, selected_payments, selected_invoices, total_rows)
		: show_confirmation_dialog(frm, selected_payments, selected_invoices, total_rows);

	if (total_rows > 500) {
		frappe.confirm(
			__('This will create {0} rows which may impact performance. Continue?', [total_rows]),
			proceed
		);
	} else {
		proceed();
	}
}

function show_replace_append_dialog(frm, payments, invoices, total_rows) {
	const d = new frappe.ui.Dialog({
		title: __('Existing Allocations Found'),
		fields: [
			{
				fieldtype: 'HTML',
				options: `<p>There are ${frm.doc.allocation.length} existing allocation rows.</p>
				          <p>This will create ${total_rows} new rows. What would you like to do?</p>`,
			},
			{
				fieldname: 'action',
				fieldtype: 'Select',
				label: 'Action',
				options: ['Replace existing allocations', 'Append to existing allocations'],
				default: 'Append to existing allocations',
				reqd: 1,
			},
		],
		primary_action_label: __('Continue'),
		primary_action(values) {
			d.hide();
			execute_zero_allocate(frm, payments, invoices, values.action === 'Replace existing allocations');
		},
	});
	d.show();
}

function show_confirmation_dialog(frm, payments, invoices, total_rows) {
	frappe.confirm(
		__('This will create {0} allocation rows with zero amounts. Continue?', [total_rows]),
		() => execute_zero_allocate(frm, payments, invoices, false)
	);
}

function execute_zero_allocate(frm, payments, invoices, replace) {
	frappe.show_alert({ message: __('Creating zero allocations...'), indicator: 'blue' });
	frappe.call({
		method: 'cecypo_powerpack.api.zero_allocate_entries',
		args: { doc: frm.doc, payments, invoices },
		freeze: true,
		freeze_message: __('Creating allocation entries...'),
		callback(r) {
			if (r.message?.length) {
				if (replace) frm.clear_table('allocation');
				r.message.forEach(a => Object.assign(frm.add_child('allocation'), a));
				frm.refresh_field('allocation');
				setTimeout(() => setup_zero_reconcile_button(frm), 100);
				frappe.show_alert({
					message: __('Created {0} allocation rows. Fill in amounts and click Zero Reconcile.', [r.message.length]),
					indicator: 'green',
				});
				frm.fields_dict.payments.grid.grid_rows.forEach(gr => { gr.doc.__checked = 0; });
				frm.fields_dict.invoices.grid.grid_rows.forEach(gr => { gr.doc.__checked = 0; });
				frm.refresh_field('payments');
				frm.refresh_field('invoices');
			} else {
				frappe.msgprint({ title: __('No Allocations Created'), message: __('No allocation entries were created.'), indicator: 'orange' });
			}
		},
	});
}

// ═══════════════════════════════════════════════════════════════════════════════
// LOAD ADDITIONAL DOC INFO
// ═══════════════════════════════════════════════════════════════════════════════

function setup_load_doc_info_button(frm) {
	const BTN_LABEL = __('Load Additional Doc Info');
	const $btn = frm.add_custom_button(BTN_LABEL, async function () {
		$btn.prop('disabled', true).text(__('Loading\u2026'));
		remove_all_displays();
		try {
			if (frm.doc.party_type === 'Customer') {
				await add_etr_display(frm);
				await add_vat_display(frm);
			} else if (frm.doc.party_type === 'Supplier') {
				await add_bill_no_display(frm);
				await add_payment_credit_note_display(frm);
				await add_allocation_bill_no_display(frm);
			} else {
				frappe.show_alert({ message: __('Select a Party Type first'), indicator: 'orange' });
			}
		} catch (err) {
			frappe.msgprint({
				title: __('Error loading additional info'),
				message: String(err?.message ?? err),
				indicator: 'red',
			});
		} finally {
			$btn.prop('disabled', false).text(BTN_LABEL);
		}
	}, __('Powerup'));
}

// ── Customer: ETR Invoice Numbers (Invoices table) ────────────────────────────

async function add_etr_display(frm) {
	const invoices = (frm.doc.invoices || []).filter(r => r.invoice_type === 'Sales Invoice' && r.invoice_number);
	if (!invoices.length) return;

	const grid = frm.fields_dict.invoices?.grid;
	if (!grid?.wrapper.is(':visible')) return;

	const si_names = [...new Set(invoices.map(r => r.invoice_number))];
	const si_rows = await frappe.db.get_list('Sales Invoice', {
		filters: [['name', 'in', si_names]],
		fields: ['name', 'etr_invoice_number'],
		limit: Math.min(si_names.length, 500),
	});
	const etr_map = Object.fromEntries(
		si_rows.filter(r => r.etr_invoice_number).map(r => [r.name, r.etr_invoice_number])
	);

	// BATCH: VAT withholding invoice numbers (for match highlighting)
	const je_names = [...new Set(
		(frm.doc.payments || []).filter(r => r.reference_type === 'Journal Entry' && r.reference_name).map(r => r.reference_name)
	)];
	const vat_invoice_nos = new Set();
	if (je_names.length) {
		const vat_rows = await frappe.db.get_list('VAT Withholding', {
			filters: [['journal_entry', 'in', je_names]],
			fields: ['invoice_no'],
			limit: Math.min(je_names.length * 5, 500),
		});
		vat_rows.forEach(r => { if (r.invoice_no) vat_invoice_nos.add(r.invoice_no); });
	}

	for (const row of invoices) {
		const etr_no = etr_map[row.invoice_number];
		if (!etr_no) continue;
		const matched = vat_invoice_nos.has(etr_no) || vat_invoice_nos.has(row.invoice_number);
		const clr = matched ? color_for(etr_no) : '#94a3b8';
		inject_display('etr-invoice-display', grid, row.name, clr,
			`${lbl('ETR:')} <span>${frappe.utils.escape_html(etr_no)}</span> ${badge(matched ? 'MATCHED' : 'UNMATCHED', clr)}`
		);
	}
}

// ── Customer: VAT Withholding (Payments table — Journal Entry rows) ───────────

async function add_vat_display(frm) {
	const payments = (frm.doc.payments || []).filter(r => r.reference_type === 'Journal Entry' && r.reference_name);
	if (!payments.length) return;

	const grid = frm.fields_dict.payments?.grid;
	if (!grid?.wrapper.is(':visible')) return;

	// BATCH: ETR numbers from invoices table (for match highlighting)
	const si_names = [...new Set(
		(frm.doc.invoices || []).filter(r => r.invoice_type === 'Sales Invoice' && r.invoice_number).map(r => r.invoice_number)
	)];
	const etr_set    = new Set();
	const si_name_set = new Set(si_names);
	if (si_names.length) {
		const si_rows = await frappe.db.get_list('Sales Invoice', {
			filters: [['name', 'in', si_names]],
			fields: ['name', 'etr_invoice_number'],
			limit: Math.min(si_names.length, 500),
		});
		si_rows.forEach(r => { if (r.etr_invoice_number) etr_set.add(r.etr_invoice_number); });
	}

	// BATCH: all VAT withholding for all JEs in one query
	const je_names = [...new Set(payments.map(r => r.reference_name))];
	const vat_rows = await frappe.db.get_list('VAT Withholding', {
		filters: [['journal_entry', 'in', je_names]],
		fields: ['journal_entry', 'voucher_no', 'invoice_no'],
		limit: Math.min(je_names.length * 5, 500),
	});
	// Index by journal_entry — first match per JE wins
	const vat_map = {};
	for (const r of vat_rows) {
		if (!vat_map[r.journal_entry]) vat_map[r.journal_entry] = r;
	}

	for (const row of payments) {
		const vat = vat_map[row.reference_name];
		if (!vat || (!vat.voucher_no && !vat.invoice_no)) continue;
		const matched = etr_set.has(vat.invoice_no) || si_name_set.has(vat.invoice_no);
		const clr = matched ? color_for(vat.invoice_no) : '#94a3b8';
		const parts = [];
		if (vat.voucher_no) parts.push(`${lbl('Voucher:')} ${frappe.utils.escape_html(vat.voucher_no)}`);
		if (vat.invoice_no)  parts.push(`${lbl('Invoice:')} ${frappe.utils.escape_html(vat.invoice_no)}`);
		const sep = '<span style="color:var(--gray-400);margin:0 2px;">&bull;</span>';
		inject_display('vat-withholding-display', grid, row.name, clr,
			parts.join(sep) + ' ' + badge(matched ? 'MATCHED' : 'UNMATCHED', clr)
		);
	}
}

// ── Supplier: Bill No (Invoices table) ────────────────────────────────────────

async function add_bill_no_display(frm) {
	const invoices = (frm.doc.invoices || []).filter(r => r.invoice_type === 'Purchase Invoice' && r.invoice_number);
	if (!invoices.length) return;

	const grid = frm.fields_dict.invoices?.grid;
	if (!grid?.wrapper.is(':visible')) return;

	const pi_names = [...new Set(invoices.map(r => r.invoice_number))];
	const pi_rows = await frappe.db.get_list('Purchase Invoice', {
		filters: [['name', 'in', pi_names]],
		fields: ['name', 'bill_no', 'etr_invoice_number'],
		limit: Math.min(pi_names.length, 500),
	});
	const pi_map = Object.fromEntries(pi_rows.map(r => [r.name, r]));

	const allocated_set = new Set(
		(frm.doc.allocation || []).filter(r => r.invoice_type === 'Purchase Invoice').map(r => r.invoice_number)
	);

	for (const row of invoices) {
		const pi = pi_map[row.invoice_number];
		if (!pi?.bill_no && !pi?.etr_invoice_number) continue;
		const clr = allocated_set.has(row.invoice_number) ? color_for(pi.bill_no || pi.etr_invoice_number) : '#94a3b8';
		const sep = '<span style="color:var(--gray-400);margin:0 4px;">&bull;</span>';
		const parts = [];
		if (pi.bill_no)           parts.push(`${lbl('Supplier Invoice #:')} <span>${frappe.utils.escape_html(pi.bill_no)}</span>`);
		if (pi.etr_invoice_number) parts.push(`${lbl('ETR:')} <span>${frappe.utils.escape_html(pi.etr_invoice_number)}</span>`);
		inject_display('bill-no-display', grid, row.name, clr, parts.join(sep));
	}
}

// ── Supplier: Credit Notes / Debit Notes (Payments table — PI rows) ───────────
//
// The payments table lists both Payment Entries AND credit notes (Purchase Invoices
// with is_return=1). This function handles the PI rows that the other display
// functions would otherwise skip entirely.

async function add_payment_credit_note_display(frm) {
	const payments = (frm.doc.payments || []).filter(r => r.reference_type === 'Purchase Invoice' && r.reference_name);
	if (!payments.length) return;

	const grid = frm.fields_dict.payments?.grid;
	if (!grid?.wrapper.is(':visible')) return;

	const pi_names = [...new Set(payments.map(r => r.reference_name))];
	const pi_rows = await frappe.db.get_list('Purchase Invoice', {
		filters: [['name', 'in', pi_names]],
		fields: ['name', 'bill_no', 'etr_invoice_number', 'grand_total'],
		limit: Math.min(pi_names.length, 500),
	});
	const pi_map = Object.fromEntries(pi_rows.map(r => [r.name, r]));

	for (const row of payments) {
		const pi = pi_map[row.reference_name];
		if (!pi) continue;
		const clr   = '#8b5cf6';
		const sep   = '<span style="color:var(--gray-400);margin:0 4px;">&bull;</span>';
		const parts = [badge(__('Debit Note / Credit'), clr)];
		if (pi.bill_no)            parts.push(`${lbl('Supplier Invoice #:')} <span>${frappe.utils.escape_html(pi.bill_no)}</span>`);
		if (pi.etr_invoice_number) parts.push(`${lbl('ETR:')} <span>${frappe.utils.escape_html(pi.etr_invoice_number)}</span>`);
		inject_display('payment-credit-note-display', grid, row.name, clr, parts.join(sep));
	}
}

// ── Supplier: Bill No + Outstanding (Allocation table) ────────────────────────

async function add_allocation_bill_no_display(frm) {
	const alloc_rows = (frm.doc.allocation || []).filter(r => r.invoice_type === 'Purchase Invoice' && r.invoice_number);
	if (!alloc_rows.length) return;

	const grid = frm.fields_dict.allocation?.grid;
	if (!grid?.wrapper.is(':visible')) return;

	const pi_names = [...new Set(alloc_rows.map(r => r.invoice_number))];
	const pi_rows = await frappe.db.get_list('Purchase Invoice', {
		filters: [['name', 'in', pi_names]],
		fields: ['name', 'bill_no', 'etr_invoice_number', 'outstanding_amount'],
		limit: Math.min(pi_names.length, 500),
	});
	const pi_map = Object.fromEntries(pi_rows.map(r => [r.name, r]));

	const invoiced_set = new Set(
		(frm.doc.invoices || []).filter(r => r.invoice_type === 'Purchase Invoice').map(r => r.invoice_number)
	);

	for (const row of alloc_rows) {
		const pi = pi_map[row.invoice_number];
		if (!pi) continue;
		const parts = [];
		if (pi.bill_no) {
			parts.push(`${lbl('Supplier Invoice #:')} <span>${frappe.utils.escape_html(pi.bill_no)}</span>`);
		}
		if (pi.etr_invoice_number) {
			parts.push(`${lbl('ETR:')} <span>${frappe.utils.escape_html(pi.etr_invoice_number)}</span>`);
		}
		if (pi.outstanding_amount != null) {
			const amt     = format_currency(pi.outstanding_amount, frm.doc.company_currency);
			const amt_clr = pi.outstanding_amount > 0 ? '#ef4444'
				: pi.outstanding_amount < 0             ? '#10b981'
				:                                         'var(--text-muted)';
			parts.push(`${lbl('Outstanding:')} <span style="font-weight:600;color:${amt_clr};">${amt}</span>`);
		}
		if (!parts.length) continue;
		const clr = invoiced_set.has(row.invoice_number) && pi.bill_no ? color_for(pi.bill_no) : '#94a3b8';
		const sep = '<span style="color:var(--gray-400);margin:0 4px;">&bull;</span>';
		inject_display('allocation-bill-no-display', grid, row.name, clr, parts.join(sep));
	}
}

// ═══════════════════════════════════════════════════════════════════════════════
// 2% ALLOCATE (Supplier only)
// ═══════════════════════════════════════════════════════════════════════════════

function setup_allocate_2pct_button(frm) {
	const grid = frm.fields_dict.allocation?.grid;
	if (!grid) return;

	if (frm.doc.party_type !== 'Supplier') {
		const $existing = grid.custom_buttons?.[__('Allocate 2%')];
		if ($existing) $existing.addClass('hidden');
		return;
	}

	// Don't add duplicate button
	if (grid.custom_buttons?.[__('Allocate 2%')]) {
		grid.custom_buttons[__('Allocate 2%')].removeClass('hidden');
		return;
	}

	const $btn = grid.add_custom_button(__('Allocate 2%'), async function () {
		$btn.prop('disabled', true).text(__('Calculating\u2026'));
		try {
			await apply_2pct_allocation(frm);
		} finally {
			$btn.prop('disabled', false).text(__('Allocate 2%'));
		}
	}, 'top');
	$btn.css({ 'font-size': '11px', 'padding': '2px 9px', 'margin-top': '4px' });
}

async function apply_2pct_allocation(frm) {
	const alloc_rows = (frm.doc.allocation || []).filter(r => r.invoice_type === 'Purchase Invoice' && r.invoice_number);
	if (!alloc_rows.length) {
		frappe.show_alert({ message: __('No Purchase Invoice rows in the Allocation table'), indicator: 'orange' });
		return;
	}

	// BATCH: fetch net_total for all unique invoices
	const pi_names = [...new Set(alloc_rows.map(r => r.invoice_number))];
	const pi_rows = await frappe.db.get_list('Purchase Invoice', {
		filters: [['name', 'in', pi_names]],
		fields: ['name', 'net_total'],
		limit: Math.min(pi_names.length, 500),
	});
	const net_total_map = Object.fromEntries(pi_rows.map(r => [r.name, r.net_total]));

	const payment_summary = {};
	for (const row of alloc_rows) {
		const net_total = net_total_map[row.invoice_number];
		if (net_total == null) continue;
		// 2% of taxable amount, rounded up to nearest whole number
		const allocated = Math.ceil(net_total * 0.02);
		frappe.model.set_value(row.doctype, row.name, 'allocated_amount', allocated);
		const ref = row.reference_name;
		if (ref) {
			if (!payment_summary[ref]) payment_summary[ref] = { unreconciled: row.unreconciled_amount || 0, allocated_2pct: 0 };
			payment_summary[ref].allocated_2pct += allocated;
		}
	}

	// Remove stale display rows before grid re-renders from set_value calls
	$('.allocation-bill-no-display').remove();
	frm.refresh_field('allocation');
	await add_allocation_bill_no_display(frm);

	// Show payment remaining summary
	const currency = frm.doc.company_currency;
	const summary_rows = Object.entries(payment_summary).map(([ref, d]) => {
		const remaining  = d.unreconciled - d.allocated_2pct;
		const rem_color  = remaining >= 0 ? '#10b981' : '#ef4444';
		return `<tr>
			<td style="font-family:monospace;">${frappe.utils.escape_html(ref)}</td>
			<td style="text-align:right;">${format_currency(d.unreconciled, currency)}</td>
			<td style="text-align:right;">${format_currency(d.allocated_2pct, currency)}</td>
			<td style="text-align:right;font-weight:700;color:${rem_color};">${format_currency(remaining, currency)}</td>
		</tr>`;
	}).join('');

	if (summary_rows) {
		frappe.msgprint({
			title: __('2% Allocation Applied'),
			message: `
				<table class="table table-bordered table-sm" style="margin:0;font-size:12px;">
					<thead style="background:var(--control-bg);">
						<tr>
							<th>${__('Payment')}</th>
							<th style="text-align:right;">${__('Available')}</th>
							<th style="text-align:right;">${__('2% Applied')}</th>
							<th style="text-align:right;">${__('Remaining')}</th>
						</tr>
					</thead>
					<tbody>${summary_rows}</tbody>
				</table>`,
			indicator: 'green',
		});
	}
}

// ═══════════════════════════════════════════════════════════════════════════════
// ZERO ALLOCATE WITH PASTE (Supplier only)
// ═══════════════════════════════════════════════════════════════════════════════

function setup_zero_allocate_paste_button(frm) {
	try { frm.page.remove_inner_button(__('Zero Allocate with Paste'), __('Powerup')); } catch (_) {}
	if (frm.doc.party_type !== 'Supplier') return;
	const has_credit = (frm.doc.payments || []).some(p => (p.amount || 0) > 0);
	if (!has_credit) return;
	frm.page.add_inner_button(
		__('Zero Allocate with Paste'),
		() => zero_allocate_with_paste(frm),
		__('Powerup'),
	);
}

// ─── Paste parser ─────────────────────────────────────────────────────────────

const _CURRENCY_SYMBOL_RE = /^(KES|USD|EUR|GBP|INR|\$|€|£|₹)\s*/i;

function _normalize_amount(raw) {
	if (raw == null) return NaN;
	let s = String(raw).trim();
	if (!s) return NaN;
	s = s.replace(_CURRENCY_SYMBOL_RE, '').trim();
	// Strip thousands commas only if a dot is also present OR there are no commas acting as decimals.
	// For Excel/KE locale we expect '.' decimal and ',' thousands.
	s = s.replace(/,/g, '');
	if (!/^-?\d+(\.\d+)?$/.test(s)) return NaN;
	return parseFloat(s);
}

function _split_line(line) {
	// First delimiter wins: tab > multi-space > comma.
	if (line.includes('\t')) return line.split('\t');
	if (/\s{2,}/.test(line)) return line.split(/\s{2,}/);
	if (line.includes(',')) return line.split(',');
	return [line];
}

function parse_paste(text) {
	const rows = [];
	const skipped = [];
	if (!text) return { rows, skipped };

	const raw_lines = text.split(/\r?\n/);
	let first_content_line_seen = false;

	for (let i = 0; i < raw_lines.length; i++) {
		const raw = raw_lines[i];
		const line = raw.trim();
		if (!line) continue;

		const parts = _split_line(line).map(p => p.trim());
		if (parts.length < 2) {
			skipped.push({ line: raw, reason: 'Invalid amount' });
			continue;
		}
		const bill_no = parts[0];
		const amount = _normalize_amount(parts[1]);

		if (!first_content_line_seen) {
			first_content_line_seen = true;
			if (isNaN(amount)) {
				// Auto-detect header row — skip silently
				continue;
			}
		}

		if (!bill_no || isNaN(amount)) {
			skipped.push({ line: raw, reason: 'Invalid amount' });
			continue;
		}
		rows.push({ bill_no, amount });
	}
	return { rows, skipped };
}

function _credit_options_from_payments(payments) {
	return (payments || []).filter(p => (p.amount || 0) > 0).map(p => {
		const currency = p.currency || frappe.defaults.get_global_default('currency');
		const label = `${p.reference_name} — ${p.reference_type} — ${format_currency(p.amount, currency)}`;
		const value = `${p.reference_type}|${p.reference_name}`;
		return { label, value };
	});
}

function _lookup_credit(frm, composite_key) {
	if (!composite_key) return null;
	const [ref_type, ref_name] = composite_key.split('|');
	return (frm.doc.payments || []).find(
		p => p.reference_type === ref_type && p.reference_name === ref_name && (p.amount || 0) > 0,
	) || null;
}

function _credit_available(frm, payment) {
	if (!payment) return 0;
	const gross = payment.amount || 0;
	const already = (frm.doc.allocation || [])
		.filter(a => a.reference_type === payment.reference_type && a.reference_name === payment.reference_name)
		.reduce((acc, a) => acc + (a.allocated_amount || 0), 0);
	return flt(gross - already, 2);
}

function run_auto_distribute(rows, credit_available) {
	// 1. Cap each row to [0, outstanding]
	rows.forEach(r => {
		r.amount = Math.max(0, Math.min(flt(r.amount || 0), flt(r.outstanding_amount || 0)));
	});
	// 2. Compute total
	let total = rows.reduce((s, r) => s + r.amount, 0);
	// 3. If over credit, absorb from the tail
	if (total > credit_available) {
		let overflow = total - credit_available;
		for (let i = rows.length - 1; i >= 0 && overflow > 0; i--) {
			const take = Math.min(rows[i].amount, overflow);
			rows[i].amount -= take;
			overflow -= take;
		}
	}
	// 4. Round to 2 decimals, nudge last non-zero by residual
	rows.forEach(r => { r.amount = flt(r.amount, 2); });
	const rounded_total = rows.reduce((s, r) => s + r.amount, 0);
	const target = Math.min(total, credit_available);
	const residual = flt(target - rounded_total, 2);
	if (residual !== 0) {
		for (let i = rows.length - 1; i >= 0; i--) {
			if (rows[i].amount > 0) {
				rows[i].amount = flt(rows[i].amount + residual, 2);
				break;
			}
		}
	}
}

function render_review_section(dialog, state) {
	const currency = state.credit.currency || dialog.get_value('_currency') || frappe.defaults.get_global_default('currency');
	const rows_html = state.matched.map((r, idx) => {
		const diff = flt((r.amount || 0) - r.outstanding_amount, 2);
		const diff_color = diff === 0 ? 'var(--text-muted)' : (diff > 0 ? '#ef4444' : '#10b981');
		return `
			<tr data-idx="${idx}">
				<td style="font-family:monospace;">${frappe.utils.escape_html(r.bill_no)}</td>
				<td style="font-family:monospace;">${frappe.utils.escape_html(r.pi_name)}</td>
				<td style="text-align:right;">${format_currency(r.outstanding_amount, currency)}</td>
				<td style="text-align:right;">
					<input type="number" step="0.01" min="0" class="form-control input-xs zap-amount"
					       data-idx="${idx}" value="${flt(r.amount || 0, 2)}"
					       style="text-align:right;max-width:140px;display:inline-block;">
				</td>
				<td style="text-align:right;color:${diff_color};" class="zap-diff" data-idx="${idx}">
					${format_currency(diff, currency)}
				</td>
				<td style="text-align:center;white-space:nowrap;">
					<button class="btn btn-xs btn-default zap-match-out" data-idx="${idx}" title="${__('Set to outstanding')}">↔</button>
					<button class="btn btn-xs btn-default zap-remove" data-idx="${idx}" title="${__('Remove')}">×</button>
				</td>
			</tr>`;
	}).join('');

	const skipped_rows = [
		...state.ambiguous.map(a => `<tr>
			<td style="font-family:monospace;">${frappe.utils.escape_html(a.bill_no)}</td>
			<td>${__('Ambiguous: {0} candidates', [a.candidates.length])}</td>
		</tr>`),
		...state.not_found.map(b => `<tr>
			<td style="font-family:monospace;">${frappe.utils.escape_html(b)}</td>
			<td>${__('Not found')}</td>
		</tr>`),
		...state.invalid.map(s => `<tr>
			<td style="font-family:monospace;">${frappe.utils.escape_html(s.line)}</td>
			<td>${frappe.utils.escape_html(s.reason)}</td>
		</tr>`),
	].join('');

	const total_skipped = state.ambiguous.length + state.not_found.length + state.invalid.length;
	const skipped_collapsed = total_skipped === 0 ? ' hidden' : '';

	const html = `
		<div class="zap-review">
			<div class="zap-summary" style="display:flex;gap:16px;flex-wrap:wrap;padding:8px 0 12px;font-size:12px;">
				<div><strong>${__('Credit Available')}:</strong> <span class="zap-credit">${format_currency(state.credit_available, currency)}</span></div>
				<div><strong>${__('Total Allocated')}:</strong> <span class="zap-total">${format_currency(0, currency)}</span></div>
				<div><strong>${__('Remaining')}:</strong> <span class="zap-remaining" style="font-weight:700;">${format_currency(state.credit_available, currency)}</span></div>
				<div><strong>${__('Matched')}:</strong> ${state.matched.length}</div>
				<div><strong>${__('Skipped')}:</strong> ${total_skipped}</div>
			</div>
			<div class="zap-overalloc-warning" style="display:none;color:#ef4444;font-weight:600;padding:4px 0;"></div>
			<table class="table table-bordered table-sm" style="font-size:12px;">
				<thead style="background:var(--control-bg);">
					<tr>
						<th>${__('Bill No')}</th>
						<th>${__('PI Name')}</th>
						<th style="text-align:right;">${__('Outstanding')}</th>
						<th style="text-align:right;">${__('Amount')}</th>
						<th style="text-align:right;">${__('Diff')}</th>
						<th style="text-align:center;">${__('Actions')}</th>
					</tr>
				</thead>
				<tbody class="zap-matched">${rows_html || `<tr><td colspan="6" style="text-align:center;color:var(--text-muted);">${__('No matched rows')}</td></tr>`}</tbody>
			</table>
			<details${total_skipped === 0 ? '' : ' open'}${skipped_collapsed}>
				<summary style="cursor:pointer;font-weight:600;">${__('Skipped / Unmatched')} (${total_skipped})</summary>
				<table class="table table-bordered table-sm" style="font-size:12px;margin-top:6px;">
					<thead><tr><th>${__('Input')}</th><th>${__('Reason')}</th></tr></thead>
					<tbody>${skipped_rows}</tbody>
				</table>
			</details>
			<div style="display:flex;gap:8px;padding-top:8px;">
				<button class="btn btn-default btn-sm zap-auto">${__('Auto Distribute')}</button>
				<button class="btn btn-default btn-sm zap-reset">${__('Reset')}</button>
			</div>
		</div>
	`;

	dialog.fields_dict.review.$wrapper.html(html);
	_wire_review_handlers(dialog, state);
	_recompute_summary(dialog, state);
}

function _wire_review_handlers(dialog, state) {
	const $w = dialog.fields_dict.review.$wrapper;

	$w.off('input', '.zap-amount').on('input', '.zap-amount', function () {
		const idx = parseInt($(this).data('idx'), 10);
		state.matched[idx].amount = flt($(this).val());
		_recompute_summary(dialog, state);
	});

	$w.off('click', '.zap-match-out').on('click', '.zap-match-out', function () {
		const idx = parseInt($(this).data('idx'), 10);
		state.matched[idx].amount = flt(state.matched[idx].outstanding_amount, 2);
		render_review_section(dialog, state);
	});

	$w.off('click', '.zap-remove').on('click', '.zap-remove', function () {
		const idx = parseInt($(this).data('idx'), 10);
		state.matched.splice(idx, 1);
		render_review_section(dialog, state);
	});

	$w.off('click', '.zap-auto').on('click', '.zap-auto', function () {
		run_auto_distribute(state.matched, state.credit_available);
		render_review_section(dialog, state);
	});

	$w.off('click', '.zap-reset').on('click', '.zap-reset', function () {
		state.matched.forEach(r => { r.amount = r._pasted_amount; });
		render_review_section(dialog, state);
	});
}

function _recompute_summary(dialog, state) {
	const $w = dialog.fields_dict.review.$wrapper;
	const currency = state.credit.currency || frappe.defaults.get_global_default('currency');
	const total = state.matched.reduce((s, r) => s + flt(r.amount || 0), 0);
	const remaining = flt(state.credit_available - total, 2);
	$w.find('.zap-total').text(format_currency(total, currency));
	$w.find('.zap-remaining').text(format_currency(remaining, currency)).css(
		'color', remaining < 0 ? '#ef4444' : '#10b981',
	);
	const $warn = $w.find('.zap-overalloc-warning');
	if (remaining < 0) {
		$warn.text(__('Over-allocated by {0}', [format_currency(-remaining, currency)])).show();
	} else {
		$warn.hide();
	}
	// Disable primary when over-allocated or nothing to allocate
	const has_amount = state.matched.some(r => flt(r.amount || 0) > 0);
	dialog.get_primary_btn().prop('disabled', remaining < 0 || !has_amount);
}

function zero_allocate_with_paste(frm) {
	const credit_options = _credit_options_from_payments(frm.doc.payments);
	if (!credit_options.length) {
		frappe.msgprint({
			title: __('No Credits Available'),
			message: __('Run "Get Unreconciled Entries" first — no payments with amount > 0 were found.'),
			indicator: 'orange',
		});
		return;
	}

	const state = {
		credit: null,
		credit_available: 0,
		matched: [],
		ambiguous: [],
		not_found: [],
		invalid: [],
	};

	const dialog = new frappe.ui.Dialog({
		title: __('Zero Allocate with Paste'),
		size: 'large',
		fields: [
			{
				fieldname: 'credit', fieldtype: 'Select', label: __('Credit'), reqd: 1,
				options: [''].concat(credit_options.map(o => o.value)).join('\n'),
				description: __("Shown: credits loaded from this document. Run 'Get Unreconciled Entries' first if the credit you want is missing."),
			},
			{
				fieldname: 'paste', fieldtype: 'Small Text', label: __('Paste (bill_no, amount)'),
				description: __('Tab-, comma-, or multi-space-separated. First row treated as header if amount column is non-numeric.'),
			},
			{ fieldname: 'parse_btn', fieldtype: 'Button', label: __('Parse & Match') },
			{ fieldname: 'review', fieldtype: 'HTML' },
		],
		primary_action_label: __('Proceed'),
		primary_action() { proceed_zero_allocate_paste(frm, dialog, state); },
	});

	// Relabel the Select options to human-readable via DOM once rendered.
	// Frappe Select only accepts string options; we post-decorate.
	dialog.$wrapper.on('shown.bs.modal', function () {
		const $sel = dialog.fields_dict.credit.$input;
		$sel.find('option').each(function () {
			const val = $(this).val();
			const opt = credit_options.find(o => o.value === val);
			if (opt) $(this).text(opt.label);
		});
	});

	dialog.fields_dict.credit.$input.on('change', function () {
		state.credit = _lookup_credit(frm, dialog.get_value('credit'));
		state.credit_available = _credit_available(frm, state.credit);
		dialog.fields_dict.parse_btn.$input.prop('disabled', !state.credit);
		dialog.fields_dict.paste.$input.prop('disabled', !state.credit);
	});
	dialog.fields_dict.parse_btn.$input.prop('disabled', true);
	dialog.fields_dict.paste.$input.prop('disabled', true);

	dialog.fields_dict.parse_btn.$input.on('click', function () {
		const text = dialog.get_value('paste') || '';
		const { rows, skipped } = parse_paste(text);
		if (!rows.length) {
			frappe.msgprint({ title: __('Nothing to match'),
				message: __('Paste at least one row with a parseable amount.'), indicator: 'orange' });
			return;
		}
		const bill_nos = rows.map(r => r.bill_no);
		frappe.call({
			method: 'cecypo_powerpack.api.resolve_bill_numbers_for_credit',
			args: {
				company: frm.doc.company,
				supplier: frm.doc.party,
				bill_numbers: JSON.stringify(bill_nos),
			},
			freeze: true,
			freeze_message: __('Resolving bill numbers…'),
			callback(r) {
				if (!r.message) return;
				const pasted_map = Object.fromEntries(rows.map(x => [x.bill_no, x.amount]));
				state.matched = (r.message.matched || []).map(m => ({
					...m,
					amount: flt(pasted_map[m.bill_no] || 0, 2),
					_pasted_amount: flt(pasted_map[m.bill_no] || 0, 2),
				}));
				state.ambiguous = r.message.ambiguous || [];
				state.not_found = r.message.not_found || [];
				state.invalid = skipped;
				render_review_section(dialog, state);
			},
		});
	});

	dialog.show();
}

function proceed_zero_allocate_paste(frm, dialog, state) {
	// Guards
	if (!state.credit) {
		frappe.msgprint({ title: __('Error'), message: __('Pick a credit first.'), indicator: 'red' }); return;
	}
	const fresh = _lookup_credit(frm, `${state.credit.reference_type}|${state.credit.reference_name}`);
	if (!fresh) {
		frappe.msgprint({
			title: __('Credit no longer available'),
			message: __('The selected credit is no longer available — please reopen the dialog.'),
			indicator: 'red',
		});
		return;
	}
	const rows = state.matched.filter(r => flt(r.amount || 0) > 0);
	if (!rows.length) {
		frappe.msgprint({ title: __('Nothing to allocate'),
			message: __('Set an amount > 0 on at least one row.'), indicator: 'orange' });
		return;
	}
	const total = rows.reduce((s, r) => s + flt(r.amount), 0);
	if (total - state.credit_available > 0.005) {
		frappe.msgprint({ title: __('Over-allocated'),
			message: __('Reduce amounts so total ≤ Credit Available.'), indicator: 'red' });
		return;
	}

	const do_populate = (replace) => {
		const payments_payload = [fresh];
		const invoices_payload = rows.map(r => ({
			invoice_type: 'Purchase Invoice',
			invoice_number: r.pi_name,
			outstanding_amount: r.outstanding_amount,
			currency: r.currency,
		}));
		frappe.call({
			method: 'cecypo_powerpack.api.zero_allocate_entries',
			args: { doc: frm.doc, payments: payments_payload, invoices: invoices_payload },
			freeze: true,
			freeze_message: __('Building allocation rows…'),
			callback(r) {
				if (!r.message?.length) {
					frappe.msgprint({ title: __('No Allocations Created'),
						message: __('Nothing was produced.'), indicator: 'orange' });
					return;
				}
				if (replace) frm.clear_table('allocation');
				const amount_map = Object.fromEntries(rows.map(x => [x.pi_name, flt(x.amount, 2)]));
				r.message.forEach(a => {
					a.allocated_amount = amount_map[a.invoice_number] ?? 0;
					Object.assign(frm.add_child('allocation'), a);
				});
				frm.refresh_field('allocation');
				dialog.hide();
				frappe.show_alert({
					message: __('Added {0} allocation rows. Click Zero Reconcile to commit.', [r.message.length]),
					indicator: 'green',
				});
				setTimeout(() => setup_zero_reconcile_button(frm), 100);
			},
		});
	};

	if ((frm.doc.allocation || []).length > 0) {
		const picker = new frappe.ui.Dialog({
			title: __('Existing Allocations Found'),
			fields: [
				{ fieldtype: 'HTML', options:
					`<p>${__('There are {0} existing allocation rows.', [frm.doc.allocation.length])}</p>
					 <p>${__('This will add {0} new rows. What would you like to do?', [rows.length])}</p>` },
				{ fieldname: 'action', fieldtype: 'Select', label: 'Action',
				  options: ['Replace existing allocations', 'Append to existing allocations'],
				  default: 'Append to existing allocations', reqd: 1 },
			],
			primary_action_label: __('Continue'),
			primary_action(v) { picker.hide(); do_populate(v.action === 'Replace existing allocations'); },
		});
		picker.show();
	} else {
		do_populate(false);
	}
}

})();
