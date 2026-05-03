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
		`<div class="text-center text-muted p-3"><i class="fa fa-spinner fa-spin"></i> ${__('Loading payment methods...')}</div>`
	);

	frappe.call({
		method: 'cecypo_powerpack.quick_pay.api.get_payment_modes',
		args: { company: frm.doc.company },
		callback(r) {
			dialog.available_modes = r.message || {};
			render_payments_container(dialog, frm);
			update_payment_totals(dialog);
		}
	});
}

function get_summary_html(frm, outstanding) {
	const paid = flt(frm.doc.advance_paid);
	const total = flt(frm.doc.grand_total);
	const percent = total > 0 ? Math.round((paid / total) * 100) : 0;

	return `
		<div class="quick-pay-header">
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
	const total_allocated = dialog.payments.reduce((sum, p) => sum + flt(p.amount), 0);
	const remaining = dialog.outstanding - total_allocated;

	const cash_payment = dialog.payments.find(p => p.type === 'Cash');
	const non_cash_total = dialog.payments.filter(p => p.type !== 'Cash').reduce((sum, p) => sum + flt(p.amount), 0);
	const cash_needed = dialog.outstanding - non_cash_total;
	const change = cash_payment ? Math.max(0, flt(cash_payment.amount) - cash_needed) : 0;

	const overpayment = total_allocated > dialog.outstanding && !cash_payment;
	const fully_paid = remaining <= 0;

	if (dialog.create_invoice && fully_paid) {
		dialog.set_df_property('invoice_section', 'hidden', 0);
		render_invoice_options(dialog);
	} else {
		dialog.set_df_property('invoice_section', 'hidden', 1);
	}

	wrapper.html(`
		<div class="qp-totals-bar ${overpayment ? 'qp-overpayment' : ''}">
			<div class="qp-total-item">
				<span>${__('Total Allocated')}</span>
				<strong class="${total_allocated >= dialog.outstanding ? 'text-success' : ''}">${format_currency(Math.min(total_allocated, dialog.outstanding), dialog.currency)}</strong>
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
	wrapper.html(`
		<div class="qp-invoice-options">
			<div class="qp-invoice-check">
				<label class="qp-checkbox-label">
					<input type="checkbox" id="qp-create-invoice" ${dialog.create_invoice ? 'checked' : ''}>
					<span>${__('Create Sales Invoice after payment')}</span>
				</label>
			</div>
			<div class="qp-invoice-check qp-submit-check" ${dialog.create_invoice ? '' : 'style="display:none"'}>
				<label class="qp-checkbox-label">
					<input type="checkbox" id="qp-submit-invoice" ${dialog.submit_invoice ? 'checked' : ''}>
					<span>${__('Submit invoice immediately')}</span>
				</label>
			</div>
		</div>
	`);

	wrapper.find('#qp-create-invoice').on('change', function() {
		dialog.create_invoice = $(this).is(':checked');
		wrapper.find('.qp-submit-check').toggle(dialog.create_invoice);
	});
	wrapper.find('#qp-submit-invoice').on('change', function() {
		dialog.submit_invoice = $(this).is(':checked');
	});
}

function get_remaining_balance(dialog) {
	return Math.max(0, dialog.outstanding - dialog.payments.reduce((sum, p) => sum + flt(p.amount), 0));
}

function process_all_payments(frm, dialog, outstanding) {
	if (!dialog.payments.length) {
		frappe.msgprint(__('Please add at least one payment'));
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

				let msg = `<p><strong>${__('Payments Processed Successfully')}</strong></p><ul>`;
				for (const pe of (r.message.payment_entries || [])) {
					msg += `<li>${pe.type}: ${format_currency(pe.amount, frm.doc.currency)} - <a href="/app/payment-entry/${pe.name}" target="_blank">${pe.name}</a></li>`;
				}
				msg += `</ul>`;

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
