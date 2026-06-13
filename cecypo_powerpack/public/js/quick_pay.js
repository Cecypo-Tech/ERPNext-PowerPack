// Quick Pay Client Script - Cash, Bank, Card payments only
// For Mpesa payments, use the separate "Quick Pay - Mpesa" button
// Loaded per-doctype via hooks.py — do not add to app_include_js.

(function () {

let qp_settings_cache = null;

function with_settings(cb) {
	if (qp_settings_cache) return cb(qp_settings_cache);
	frappe.call({
		method: "cecypo_powerpack.api.get_settings_for_client",
		callback(r) {
			qp_settings_cache = r.message || {};
			cb(qp_settings_cache);
		},
	});
}

frappe.ui.form.on('Sales Order', {
	refresh(frm) {
		if (!window.CecypoPowerPack || !CecypoPowerPack.Settings) return;
		CecypoPowerPack.Settings.isEnabled('enable_quick_pay', function (enabled) {
			if (!enabled) return;

			const outstanding = flt(frm.doc.grand_total) - flt(frm.doc.advance_paid);
			const is_submitted = frm.doc.docstatus === 1;
			const not_completed = frm.doc.status !== 'Completed' && frm.doc.status !== 'Closed';
			const no_invoice = flt(frm.doc.per_billed) === 0;

			if (is_submitted && not_completed && no_invoice) {
				const btn = frm.add_custom_button(__('Quick Pay'), () => {
					if (outstanding <= 0) {
						frappe.msgprint(__('No outstanding amount to pay'));
						return;
					}
					show_quick_pay_dialog(frm);
				}, __('Actions'));

				if (outstanding <= 0) {
					btn.prop('disabled', true).addClass('disabled');
				}
			}

			update_payment_status_indicator(frm);
		});
	}
});

function update_payment_status_indicator(frm) {
	if (frm.doc.docstatus !== 1) return;

	const outstanding = flt(frm.doc.grand_total) - flt(frm.doc.advance_paid);
	const paid = flt(frm.doc.advance_paid);
	const total = flt(frm.doc.grand_total);

	let status_html = '';
	if (paid <= 0) {
		status_html = `<span class="indicator-pill red">${__('Unpaid')}</span><br>`;
	} else if (outstanding <= 0) {
		status_html = `<span class="indicator-pill green">${__('Paid')}</span>`;
	} else {
		const percent = Math.round((paid / total) * 100);
		status_html = `<span class="indicator-pill orange">${__('Partial')} (${percent}%)</span>`;
	}

	setTimeout(() => {
		const $title_area = frm.$wrapper.find('.title-area');
		if ($title_area.length) {
			$title_area.find('.payment-status-header').remove();
			$title_area.append(`
				<div class="payment-status-header mt-1">
					${status_html}
					<small class="text-muted ml-2">${Number(outstanding).toLocaleString()} due</small>
				</div>
			`);
		}
	}, 100);
}

function show_quick_pay_dialog(frm) {
	const outstanding = flt(frm.doc.grand_total) - flt(frm.doc.advance_paid);

	if (outstanding <= 0) {
		frappe.msgprint(__('No outstanding amount to pay'));
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __('Quick Payment'),
		size: 'large',
		fields: [
			{ fieldtype: 'HTML', fieldname: 'payment_summary', options: get_summary_html(frm, outstanding) },
			{ fieldtype: 'HTML', fieldname: 'credits_container' },
			{ fieldtype: 'Section Break', label: __('Payments') },
			{ fieldtype: 'HTML', fieldname: 'payments_container' },
			{ fieldtype: 'Section Break' },
			{ fieldtype: 'HTML', fieldname: 'payment_totals' },
			{ fieldtype: 'Section Break', fieldname: 'invoice_section', label: __('Invoice Options'), hidden: 1 },
			{ fieldtype: 'HTML', fieldname: 'invoice_options_html' }
		],
		primary_action_label: __('Process Payments'),
		primary_action() {
			process_all_payments(frm, dialog, outstanding);
		}
	});

	dialog.payments = [];
	dialog.credits = [];
	dialog.outstanding = outstanding;
	dialog.currency = frm.doc.currency;
	dialog.company = frm.doc.company;
	dialog.create_invoice = false;
	dialog.submit_invoice = false;

	dialog.idempotency_token = (window.crypto && crypto.randomUUID)
		? crypto.randomUUID()
		: 'qp-' + Date.now() + '-' + Math.random().toString(36).slice(2);

	with_settings(function (s) {
		dialog.create_invoice = !!s.qp_auto_create_invoice;
		dialog.submit_invoice = !!s.qp_auto_submit_invoice;
	});

	dialog.$wrapper.find('.modal-dialog').css('max-width', '700px');
	dialog.show();

	dialog.fields_dict.payments_container.$wrapper.html(
		`<div class="text-center text-muted p-3"><i class="fa fa-spinner fa-spin"></i> ${__('Loading...')}</div>`
	);

	// Load payment modes and unallocated credits in parallel.
	let modes_loaded = false, credits_loaded = false;
	function on_data_ready() {
		if (!modes_loaded || !credits_loaded) return;
		render_payments_container(dialog, frm);
		update_payment_totals(dialog);
	}

	frappe.call({
		method: 'cecypo_powerpack.quick_pay.api.get_payment_modes',
		args: { company: frm.doc.company },
		callback(r) {
			dialog.available_modes = r.message || {};
			modes_loaded = true;
			on_data_ready();
		}
	});

	frappe.call({
		method: 'cecypo_powerpack.quick_pay.api.get_unallocated_payments',
		args: { customer: frm.doc.customer, company: frm.doc.company },
		callback(r) {
			render_credits_container(dialog, frm, r.message || []);
			credits_loaded = true;
			on_data_ready();
		}
	});
}

function get_summary_html(frm, outstanding) {
	const paid = flt(frm.doc.advance_paid);
	const total = flt(frm.doc.grand_total);
	const percent = total > 0 ? Math.round((paid / total) * 100) : 0;

	return `
		<div class="quick-pay-header">
			<div class="qp-header-icon">
				<i class="fa fa-credit-card"></i>
			</div>
			<div class="qp-header-info">
				<div class="qp-row">
					<span>${__('Customer')}</span>
					<strong>${frm.doc.customer_name || frm.doc.customer}</strong>
				</div>
				<div class="qp-row">
					<span>${__('Grand Total')}</span>
					<strong>${format_currency(total, frm.doc.currency)}</strong>
				</div>
				<div class="qp-row">
					<span>${__('Already Paid')}</span>
					<strong class="text-success">${format_currency(paid, frm.doc.currency)} <small>(${percent}%)</small></strong>
				</div>
				<div class="qp-row qp-outstanding">
					<span>${__('Outstanding')}</span>
					<strong>${format_currency(outstanding, frm.doc.currency)}</strong>
				</div>
			</div>
		</div>
	`;
}

function render_payments_container(dialog, frm) {
	const wrapper = dialog.fields_dict.payments_container.$wrapper;

	const cash_modes = dialog.available_modes.cash_modes || [];
	const bank_modes = dialog.available_modes.bank_modes || [];
	const card_modes = dialog.available_modes.card_modes || [];

	const has_cash = cash_modes.length > 0;
	const has_bank = bank_modes.length > 0;
	const has_card = card_modes.length > 0;

	if (!has_cash && !has_bank && !has_card) {
		wrapper.html(`
			<div class="qp-empty-state">
				<i class="fa fa-exclamation-circle fa-2x text-warning"></i>
				<p>${__('No payment methods available. Please check Mode of Payment settings.')}</p>
			</div>
		`);
		return;
	}

	const html = `
		<div class="qp-payments-list" id="qp-payments-list"></div>
		<div class="qp-add-payment-btns">
			${has_cash ? `<button type="button" class="btn btn-sm btn-default qp-add-btn" data-type="Cash"><i class="fa fa-money"></i> ${__('Cash')}</button>` : ''}
			${has_bank ? `<button type="button" class="btn btn-sm btn-default qp-add-btn" data-type="Bank Transfer"><i class="fa fa-bank"></i> ${__('Bank')}</button>` : ''}
			${has_card ? `<button type="button" class="btn btn-sm btn-default qp-add-btn" data-type="Card"><i class="fa fa-credit-card"></i> ${__('Card')}</button>` : ''}
		</div>
	`;

	wrapper.html(html);
	wrapper.find('.qp-add-btn').on('click', function() {
		add_payment_row(dialog, $(this).data('type'), frm);
	});
}

function render_credits_container(dialog, frm, raw_credits) {
	const wrapper = dialog.fields_dict.credits_container.$wrapper;

	if (!raw_credits || !raw_credits.length) {
		wrapper.html('');
		return;
	}

	let remaining = dialog.outstanding;
	dialog.credits = raw_credits.map(c => {
		const avail = flt(c.unallocated_amount);
		const apply = Math.min(avail, remaining);
		const diff = avail - remaining;
		const amount_cls = Math.abs(diff) < 0.01 ? '' : (diff > 0 ? 'qp-credit-over' : 'qp-credit-partial');
		remaining = Math.max(0, remaining - apply);
		return {
			pe_name: c.name,
			posting_date: c.posting_date,
			mode_of_payment: c.mode_of_payment || '',
			reference_no: c.reference_no || '',
			available_amount: avail,
			apply_amount: apply,
			checked: apply > 0,
			amount_cls,
		};
	});

	const rows_html = dialog.credits.map(c => `
		<div class="qp-credit-row" data-credit="${c.pe_name}">
			<input type="checkbox" class="qp-credit-check" ${c.checked ? 'checked' : ''}>
			<div class="qp-credit-body">
				<div class="qp-credit-top">
					<a href="/app/payment-entry/${c.pe_name}" target="_blank" class="qp-credit-id">${c.pe_name}</a>
					<span class="qp-credit-total ${c.amount_cls}">${format_currency(c.available_amount, dialog.currency)}</span>
				</div>
				<div class="qp-credit-pills">
					<span class="qp-pill"><i class="fa fa-calendar"></i> ${frappe.datetime.str_to_user(c.posting_date)}</span>
					${c.mode_of_payment ? `<span class="qp-pill"><i class="fa fa-credit-card"></i> ${c.mode_of_payment}</span>` : ''}
					${c.reference_no ? `<span class="qp-pill"><i class="fa fa-hashtag"></i> ${c.reference_no}</span>` : ''}
				</div>
			</div>
			<div class="qp-credit-apply-col">
				<input type="number" class="form-control qp-credit-apply-input"
					value="${c.apply_amount}" min="0" max="${c.available_amount}" step="0.01"
					${c.checked ? '' : 'disabled'}>
			</div>
		</div>
	`).join('');

	wrapper.html(`
		<div class="qp-credits-section">
			<div class="qp-credit-header">
				<i class="fa fa-check-circle"></i>
				<span>${__('Credits')} (${dialog.credits.length})</span>
			</div>
			<div class="qp-credits-scroll">
				${rows_html}
			</div>
		</div>
	`);

	dialog.credits.forEach(c => {
		const $row = wrapper.find(`[data-credit="${c.pe_name}"]`);

		$row.on('click', function (e) {
			if ($(e.target).is('input, a')) return;
			$row.find('.qp-credit-check').prop('checked', function (_, v) { return !v; }).trigger('change');
		});

		$row.find('.qp-credit-check').on('change', function () {
			c.checked = $(this).is(':checked');
			$row.find('.qp-credit-apply-input').prop('disabled', !c.checked);
			update_payment_totals(dialog);
		});
		$row.find('.qp-credit-apply-input').on('input change', function () {
			c.apply_amount = Math.min(flt($(this).val()), c.available_amount);
			update_payment_totals(dialog);
		});
	});
}

function get_credits_applied_total(dialog) {
	if (!dialog.credits || !dialog.credits.length) return 0;
	return dialog.credits.filter(c => c.checked).reduce((sum, c) => sum + flt(c.apply_amount), 0);
}

function add_payment_row(dialog, type, frm) {
	const remaining = get_remaining_balance(dialog);
	if (remaining <= 0) {
		frappe.msgprint(__('Outstanding amount is fully allocated'));
		return;
	}

	const payment_id = 'payment_' + Date.now();
	let mode_options = [];

	if (type === 'Cash') {
		mode_options = dialog.available_modes.cash_modes || [];
	} else if (type === 'Bank Transfer') {
		mode_options = dialog.available_modes.bank_modes || [];
	} else if (type === 'Card') {
		mode_options = dialog.available_modes.card_modes || [];
	}

	if (!mode_options.length) {
		frappe.msgprint(__('No {0} payment method available', [type]));
		return;
	}

	const payment = {
		id: payment_id,
		type: type,
		amount: remaining,
		reference: '',
		mode_of_payment: mode_options[0],
		mode_options: mode_options
	};

	dialog.payments.push(payment);
	render_payment_row(dialog, payment);
	update_payment_totals(dialog);
}

function render_payment_row(dialog, payment) {
	const list = dialog.$wrapper.find('#qp-payments-list');
	const is_cash = payment.type === 'Cash';
	const needs_reference = ['Bank Transfer', 'Card'].includes(payment.type);
	const has_mode_options = payment.mode_options && payment.mode_options.length > 1;

	const icon_map = { 'Cash': 'fa-money', 'Bank Transfer': 'fa-bank', 'Card': 'fa-credit-card' };

	let mode_select = has_mode_options
		? `<select class="form-control qp-mode-select" data-id="${payment.id}">${payment.mode_options.map(m => `<option value="${m}" ${m === payment.mode_of_payment ? 'selected' : ''}>${m}</option>`).join('')}</select>`
		: `<span class="qp-mode-label">${payment.mode_of_payment}</span>`;

	const html = `
		<div class="qp-payment-row" data-id="${payment.id}">
			<div class="qp-payment-type">
				<i class="fa ${icon_map[payment.type] || 'fa-money'}"></i>
				<span>${payment.type}</span>
			</div>
			<div class="qp-payment-fields">
				${mode_select}
				<input type="number" class="form-control qp-amount-input" value="${payment.amount}" placeholder="${__('Amount')}" data-id="${payment.id}" step="0.01">
				${needs_reference ? `<input type="text" class="form-control qp-ref-input" value="${payment.reference}" placeholder="${__('Reference No.')}" data-id="${payment.id}">` : ''}
			</div>
			<div class="qp-payment-amount">
				<strong>${format_currency(payment.amount, dialog.currency)}</strong>
				${is_cash ? `<div class="qp-change-display" data-id="${payment.id}"></div>` : ''}
			</div>
			<button type="button" class="btn btn-xs btn-danger qp-remove-btn" data-id="${payment.id}"><i class="fa fa-times"></i></button>
		</div>
	`;

	list.append(html);
	const $row = list.find(`[data-id="${payment.id}"]`);

	$row.find('.qp-mode-select').on('change', function() {
		const p = dialog.payments.find(x => x.id === $(this).data('id'));
		if (p) p.mode_of_payment = $(this).val();
	});

	$row.find('.qp-amount-input').on('input change', function() {
		const p = dialog.payments.find(x => x.id === $(this).data('id'));
		if (p) {
			p.amount = flt($(this).val());
			$row.find('.qp-payment-amount strong').text(format_currency(p.amount, dialog.currency));
			update_payment_totals(dialog);
			if (p.type === 'Cash') update_cash_change($row, p.amount, dialog);
		}
	});

	$row.find('.qp-ref-input').on('input change', function() {
		const p = dialog.payments.find(x => x.id === $(this).data('id'));
		if (p) p.reference = $(this).val();
	});

	$row.find('.qp-remove-btn').on('click', function() {
		dialog.payments = dialog.payments.filter(x => x.id !== $(this).data('id'));
		$row.remove();
		update_payment_totals(dialog);
	});

	if (is_cash) update_cash_change($row, payment.amount, dialog);
}

function update_cash_change($row, cash_amount, dialog) {
	const total_other = dialog.payments.filter(p => p.type !== 'Cash').reduce((sum, p) => sum + flt(p.amount), 0);
	const needed_from_cash = dialog.outstanding - total_other;
	const change = Math.max(0, cash_amount - needed_from_cash);

	const $change = $row.find('.qp-change-display');
	$change.html(change > 0 ? `<span class="text-success">${__('Change')}: ${format_currency(change, dialog.currency)}</span>` : '');
}

function update_payment_totals(dialog) {
	const wrapper = dialog.fields_dict.payment_totals.$wrapper;
	const credits_total = get_credits_applied_total(dialog);
	const new_payments_total = dialog.payments.reduce((sum, p) => sum + flt(p.amount), 0);
	const total_covered = credits_total + new_payments_total;
	const remaining = dialog.outstanding - total_covered;

	const cash_payment = dialog.payments.find(p => p.type === 'Cash');
	const non_cash_total = dialog.payments.filter(p => p.type !== 'Cash').reduce((sum, p) => sum + flt(p.amount), 0);
	const cash_needed = Math.max(0, dialog.outstanding - credits_total - non_cash_total);
	const change = cash_payment ? Math.max(0, flt(cash_payment.amount) - cash_needed) : 0;

	const overpayment = new_payments_total > (dialog.outstanding - credits_total) && !cash_payment && credits_total < dialog.outstanding;
	const fully_paid = remaining <= 0;

	if (fully_paid) {
		dialog.set_df_property('invoice_section', 'hidden', 0);
		render_invoice_options(dialog);
	} else {
		dialog.set_df_property('invoice_section', 'hidden', 1);
	}

	const credits_item = credits_total > 0
		? `<div class="qp-total-item"><span>${__('Credits Applied')}</span><strong class="text-success">${format_currency(credits_total, dialog.currency)}</strong></div>`
		: '';

	wrapper.html(`
		<div class="qp-totals-bar ${overpayment ? 'qp-overpayment' : ''}">
			${credits_item}
			<div class="qp-total-item">
				<span>${__('Total Covered')}</span>
				<strong class="${total_covered >= dialog.outstanding ? 'text-success' : ''}">${format_currency(Math.min(total_covered, dialog.outstanding), dialog.currency)}</strong>
			</div>
			<div class="qp-total-item">
				<span>${__('Remaining')}</span>
				<strong class="${remaining > 0 ? 'text-warning' : 'text-success'}">${format_currency(Math.max(0, remaining), dialog.currency)}</strong>
			</div>
			${change > 0 ? `<div class="qp-total-item qp-change-total"><span>${__('Change Due')}</span><strong class="text-success">${format_currency(change, dialog.currency)}</strong></div>` : ''}
			${overpayment ? `<div class="qp-total-item qp-overpay-warning"><span class="text-warning"><i class="fa fa-exclamation-triangle"></i> ${__('Overpayment will be adjusted')}</span></div>` : ''}
		</div>
	`);
}

function render_invoice_options(dialog) {
	const wrapper = dialog.fields_dict.invoice_options_html.$wrapper;
	const c = dialog.create_invoice, s = dialog.create_invoice && dialog.submit_invoice;
	wrapper.html(`
		<div class="qp-invoice-toggles">
			<button class="qp-toggle-btn ${c ? 'qp-toggle-active' : ''}" data-action="create">
				<i class="fa fa-file-text-o"></i> ${__('Invoice')}
			</button>
			<button class="qp-toggle-btn ${s ? 'qp-toggle-active' : ''} ${!c ? 'qp-toggle-muted' : ''}" data-action="submit">
				<i class="fa fa-check"></i> ${__('Auto-submit')}
			</button>
		</div>
	`);
	wrapper.find('[data-action="create"]').on('click', function() {
		dialog.create_invoice = !dialog.create_invoice;
		if (!dialog.create_invoice) dialog.submit_invoice = false;
		render_invoice_options(dialog);
	});
	wrapper.find('[data-action="submit"]').on('click', function() {
		if (!dialog.create_invoice) return;
		dialog.submit_invoice = !dialog.submit_invoice;
		render_invoice_options(dialog);
	});
}

function get_remaining_balance(dialog) {
	const credits = get_credits_applied_total(dialog);
	return Math.max(0, dialog.outstanding - credits - dialog.payments.reduce((sum, p) => sum + flt(p.amount), 0));
}

function process_all_payments(frm, dialog, outstanding) {
	const active_credits = (dialog.credits || []).filter(c => c.checked && flt(c.apply_amount) > 0);
	const credits_total = get_credits_applied_total(dialog);
	const remaining_after_credits = Math.max(0, outstanding - credits_total);

	if (!dialog.payments.length && !active_credits.length) {
		frappe.msgprint(__('Please add at least one payment or apply a credit'));
		return;
	}

	for (const p of dialog.payments) {
		if (flt(p.amount) <= 0) {
			frappe.msgprint(__('All payment amounts must be greater than zero'));
			return;
		}
		if (['Bank Transfer', 'Card'].includes(p.type) && !p.reference) {
			frappe.msgprint(__('Please enter a reference number for {0} payment', [p.type]));
			return;
		}
	}

	frappe.call({
		method: 'cecypo_powerpack.quick_pay.api.process_quick_pay',
		args: {
			sales_order: frm.doc.name,
			customer: frm.doc.customer,
			payments_json: JSON.stringify(dialog.payments.map(p => ({
				type: p.type,
				amount: p.amount,
				mode_of_payment: p.mode_of_payment || p.type,
				reference: p.reference || ''
			}))),
			credits_json: JSON.stringify(active_credits.map(c => ({
				pe_name: c.pe_name,
				amount: c.apply_amount,
			}))),
			outstanding_amount: outstanding,
			create_invoice: dialog.create_invoice ? 1 : 0,
			submit_invoice: dialog.submit_invoice ? 1 : 0,
			idempotency_token: dialog.idempotency_token,
		},
		freeze: true,
		freeze_message: __('Processing Payments...'),
		callback(r) {
			if (r.message && r.message.success) {
				dialog.hide();

				let msg = '';

				const credits_applied = r.message.credits_applied || [];
				if (credits_applied.length) {
					msg += `<p><strong>${__('Credits Applied')}</strong></p><ul>`;
					for (const c of credits_applied) {
						msg += `<li>${format_currency(c.amount, frm.doc.currency)} — <a href="/app/payment-entry/${c.amended_pe}" target="_blank">${c.amended_pe}</a></li>`;
					}
					msg += `</ul>`;
				}

				const payment_entries = r.message.payment_entries || [];
				if (payment_entries.length) {
					msg += `<p><strong>${__('New Payments')}</strong></p><ul>`;
					for (const pe of payment_entries) {
						msg += `<li>${pe.type}: ${format_currency(pe.amount, frm.doc.currency)} — <a href="/app/payment-entry/${pe.name}" target="_blank">${pe.name}</a></li>`;
					}
					msg += `</ul>`;
				}

				if (r.message.change_amount > 0) {
					msg += `<p class="mt-3"><strong style="font-size:1.3em;color:#22c55e;">${__('Change Due')}: ${format_currency(r.message.change_amount, frm.doc.currency)}</strong></p>`;
				}

				if (r.message.sales_invoice) {
					const inv = r.message.sales_invoice;
					msg += `
						<div style="margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border-color);">
							<p style="margin-bottom: 8px;"><strong>${__('Sales Invoice')}</strong></p>
							<a href="/app/sales-invoice/${inv.name}" target="_blank" class="btn btn-sm btn-primary"><i class="fa fa-external-link"></i> ${inv.name}</a>
							<span class="indicator-pill ${inv.submitted ? 'green' : 'orange'}">${inv.submitted ? __('Submitted') : __('Draft')}</span>
						</div>
					`;
				}

				frappe.msgprint({ title: __('Payment Successful'), message: msg, indicator: 'green' });
				frm.reload_doc();
			}
		}
	});
}


})();
