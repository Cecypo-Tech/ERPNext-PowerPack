// Quick Pay - Mpesa Client Script
// For Phone type Mode of Payment (Mpesa) payments only
// Cash, Bank, Card payments are handled by the separate "Quick Pay" button
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
        CecypoPowerPack.Settings.isEnabled('enable_quick_pay_mpesa', function (enabled) {
            if (!enabled) return;
            const outstanding = flt(frm.doc.grand_total) - flt(frm.doc.advance_paid);
            const is_submitted = frm.doc.docstatus === 1;
            const not_completed = frm.doc.status !== 'Completed' && frm.doc.status !== 'Closed';
            const no_invoice = flt(frm.doc.per_billed) === 0;
            
            // Check if Mpesa is available for this company/user before showing button
            if (is_submitted && not_completed && no_invoice && outstanding > 0) {
                frappe.call({
                    method: 'cecypo_powerpack.quick_pay.api.check_mpesa_available',
                    args: { company: frm.doc.company },
                    callback(r) {
                        if (r.message && r.message.available) {
                            frm.add_custom_button(__('Quick Pay - Mpesa'), () => {
                                show_mpesa_pay_dialog(frm);
                            }, __('Actions'));
                        }
                    }
                });
            }
        });
    }
});

function show_mpesa_pay_dialog(frm) {
    const outstanding = flt(frm.doc.grand_total) - flt(frm.doc.advance_paid);
    
    if (outstanding <= 0) {
        frappe.msgprint(__('No outstanding amount to pay'));
        return;
    }
    
    const dialog = new frappe.ui.Dialog({
        title: __('Quick Pay - Mpesa'),
        size: 'large',
        fields: [
            { fieldtype: 'HTML', fieldname: 'payment_summary', options: get_mpesa_summary_html(frm, outstanding) },
            { fieldtype: 'Section Break', label: __('Select Mpesa Payments') },
            { fieldtype: 'HTML', fieldname: 'mpesa_list' },
            { fieldtype: 'Section Break' },
            { fieldtype: 'HTML', fieldname: 'mpesa_totals' },
            { fieldtype: 'Section Break', fieldname: 'invoice_section', label: __('Invoice Options'), hidden: 1 },
            { fieldtype: 'HTML', fieldname: 'invoice_options_html' }
        ],
        primary_action_label: __('Process Payments'),
        primary_action() {
            process_mpesa_payments(frm, dialog, outstanding);
        },
        secondary_action_label: __('Request Payment'),
        secondary_action() {
            show_request_payment_dialog(frm, dialog);
        }
    });
    
    dialog.selected_mpesa = [];
    dialog.outstanding = outstanding;
    dialog.currency = frm.doc.currency;
    dialog.company = frm.doc.company;
    dialog.create_invoice = false;
    dialog.submit_invoice = false;
    dialog.search_term = '';
    dialog.mpesa_data = {count: 0, payments: []};
    dialog.idempotency_token = (window.crypto && crypto.randomUUID)
        ? crypto.randomUUID()
        : 'qpm-' + Date.now() + '-' + Math.random().toString(36).slice(2);
    with_settings(function (s) {
        dialog.create_invoice = !!s.qp_auto_create_invoice;
        dialog.submit_invoice = !!s.qp_auto_submit_invoice;
    });
    
    dialog.$wrapper.find('.modal-dialog').css('max-width', '800px');
    dialog.show();
    
    // Load initial count
    dialog.fields_dict.mpesa_list.$wrapper.html(
        `<div class="text-center text-muted p-4"><i class="fa fa-spinner fa-spin"></i> ${__('Loading...')}</div>`
    );
    
    frappe.call({
        method: 'cecypo_powerpack.quick_pay.api.list_pending_mpesa_payments',
        args: { company: frm.doc.company, search: '' },
        callback(r) {
            dialog.mpesa_data = r.message || {count: 0, payments: []};
            render_mpesa_list(dialog);
            update_mpesa_totals(dialog);
        }
    });
}

function get_mpesa_summary_html(frm, outstanding) {
    const paid = flt(frm.doc.advance_paid);
    const total = flt(frm.doc.grand_total);
    const percent = total > 0 ? Math.round((paid / total) * 100) : 0;
    
    return `
        <div class="mpesa-pay-header">
            <div class="mpesa-header-icon">
                <i class="fa fa-mobile"></i>
            </div>
            <div class="mpesa-header-info">
                <div class="mpesa-row">
                    <span>${__('Customer')}</span>
                    <strong>${frm.doc.customer_name || frm.doc.customer}</strong>
                </div>
                <div class="mpesa-row">
                    <span>${__('Grand Total')}</span>
                    <strong>${format_currency(total, frm.doc.currency)}</strong>
                </div>
                <div class="mpesa-row">
                    <span>${__('Already Paid')}</span>
                    <strong class="text-success">${format_currency(paid, frm.doc.currency)} <small>(${percent}%)</small></strong>
                </div>
                <div class="mpesa-row mpesa-outstanding">
                    <span>${__('Outstanding')}</span>
                    <strong>${format_currency(outstanding, frm.doc.currency)}</strong>
                </div>
            </div>
        </div>
    `;
}

function render_mpesa_list(dialog) {
    const wrapper = dialog.fields_dict.mpesa_list.$wrapper;
    const data = dialog.mpesa_data || {};
    const count = data.count || 0;
    const payments = data.payments || [];
    
    if (count === 0) {
        wrapper.html(`
            <div class="mpesa-empty-state">
                <i class="fa fa-inbox fa-3x text-muted"></i>
                <p class="mt-3">${__('No pending Mpesa payments found')}</p>
                <small class="text-muted">${__('Mpesa payments will appear here once received')}</small>
            </div>
        `);
        return;
    }
    
    let html = `
        <div class="mpesa-search-section">
            <div class="mpesa-search-box">
                <i class="fa fa-search mpesa-search-icon"></i>
                <input type="text" class="form-control" id="mpesa-search" 
                       placeholder="${__('Search name, phone, transaction ID, reference (min 3 chars)...')}"
                       value="${dialog.search_term || ''}">
            </div>
            <div class="mpesa-count-badge">
                <i class="fa fa-mobile"></i>
                <span><strong>${count}</strong> ${__('pending')}</span>
            </div>
        </div>
        <div class="mpesa-payments-list" id="mpesa-payments-list">
    `;
    
    if (payments.length === 0 && dialog.search_term && dialog.search_term.length >= 3) {
        html += `
            <div class="mpesa-no-results">
                <i class="fa fa-search text-muted"></i>
                <p>${__('No payments match your search')}</p>
            </div>
        `;
    } else if (payments.length === 0) {
        html += `
            <div class="mpesa-search-prompt">
                <i class="fa fa-hand-o-up text-muted"></i>
                <p>${__('Enter a search term above to find payments')}</p>
            </div>
        `;
    } else {
        html += `
            <div class="mpesa-results-header">
                <label class="mpesa-checkbox-label mpesa-select-all-label">
                    <input type="checkbox" id="mpesa-select-all">
                    <span>${__('Select All')} (${payments.length} ${__('results')})</span>
                </label>
            </div>
        `;
        
        const today = frappe.datetime.get_today();
        
        for (const p of payments) {
            const amount = flt(p.transamount || 0);
            const phone = p.msisdn || '';
            const name = p.full_name || '';
            const ref = p.billrefnumber || '';
            const trans_id = p.transid || p.name;
            const posting_date = p.posting_date || p.creation || '';
            
            // Calculate age styling
            const age_style = get_age_style(posting_date, today);
            const age_days = get_age_days(posting_date, today);
            const age_label = get_age_label(age_days);
            
            const is_selected = dialog.selected_mpesa.some(x => x.name === p.name);
            const is_overpayment = amount > dialog.outstanding;
            const is_exact_match = Math.abs(amount - dialog.outstanding) < 0.01;
            
            let item_class = is_selected ? 'selected' : '';
            if (is_exact_match) {
                item_class += ' exact-match';
            } else if (is_overpayment) {
                item_class += ' overpayment-warning';
            }
            
            html += `
                <div class="mpesa-payment-item ${item_class}" data-name="${p.name}" data-amount="${amount}">
                    <div class="mpesa-item-checkbox">
                        <input type="checkbox" class="mpesa-item-check" data-name="${p.name}" data-amount="${amount}" ${is_selected ? 'checked' : ''}>
                    </div>
                    <div class="mpesa-item-info">
                        <div class="mpesa-item-primary">
                            <span class="mpesa-sender-name">${name || __('Unknown')}</span>
                            <span class="mpesa-amount ${is_overpayment && !is_exact_match ? 'text-warning' : ''}">${format_currency(amount, dialog.currency)}${is_exact_match ? '<span class="mpesa-exact-badge">' + __('EXACT') + '</span>' : ''}${is_overpayment && !is_exact_match ? ' <i class="fa fa-exclamation-triangle" title="' + __('Exceeds outstanding amount') + '"></i>' : ''}</span>
                        </div>
                        <div class="mpesa-item-secondary">
                            <span class="mpesa-phone"><i class="fa fa-phone"></i> ${phone}</span>
                            ${ref ? `<span class="mpesa-ref"><i class="fa fa-hashtag"></i> ${ref}</span>` : ''}
                            <span class="mpesa-trans-id"><i class="fa fa-exchange"></i> ${trans_id}</span>
                        </div>
                    </div>
                    <div class="mpesa-age-indicator" style="${age_style}" title="${posting_date}">
                        ${age_label}
                    </div>
                </div>
            `;
        }
    }
    
    html += '</div>';
    wrapper.html(html);
    
    // Search handler with debounce
    let search_timeout;
    wrapper.find('#mpesa-search').on('input', function() {
        const search = $(this).val().trim();
        clearTimeout(search_timeout);
        
        if (search.length >= 3 || search.length === 0) {
            search_timeout = setTimeout(() => {
                dialog.search_term = search;
                load_mpesa_payments(dialog, search);
            }, 300);
        }
    });
    
    // Select all handler
    wrapper.find('#mpesa-select-all').on('change', function() {
        const checked = $(this).is(':checked');
        wrapper.find('.mpesa-item-check').prop('checked', checked).trigger('change');
    });
    
    // Individual item handler
    wrapper.find('.mpesa-item-check').on('change', function() {
        const name = $(this).data('name');
        const amount = flt($(this).data('amount'));
        const checked = $(this).is(':checked');
        
        if (checked) {
            if (!dialog.selected_mpesa.find(x => x.name === name)) {
                dialog.selected_mpesa.push({ name, amount });
            }
        } else {
            dialog.selected_mpesa = dialog.selected_mpesa.filter(x => x.name !== name);
        }
        
        $(this).closest('.mpesa-payment-item').toggleClass('selected', checked);
        update_mpesa_totals(dialog);
    });
}

function get_age_days(posting_date, today) {
    if (!posting_date) return 0;
    const post = frappe.datetime.str_to_obj(posting_date);
    const now = frappe.datetime.str_to_obj(today);
    const diff = Math.floor((now - post) / (1000 * 60 * 60 * 24));
    return Math.max(0, diff);
}

function get_age_style(posting_date, today) {
    const days = get_age_days(posting_date, today);
    
    // Color gradient: green (0 days) -> yellow (3 days) -> orange (7 days) -> red (14+ days)
    let bg_color, text_color;
    
    if (days === 0) {
        bg_color = 'rgba(34, 197, 94, 0.15)';
        text_color = '#16a34a';
    } else if (days <= 3) {
        bg_color = 'rgba(234, 179, 8, 0.15)';
        text_color = '#ca8a04';
    } else if (days <= 7) {
        bg_color = 'rgba(249, 115, 22, 0.15)';
        text_color = '#ea580c';
    } else if (days <= 14) {
        bg_color = 'rgba(239, 68, 68, 0.15)';
        text_color = '#dc2626';
    } else {
        bg_color = 'rgba(185, 28, 28, 0.2)';
        text_color = '#b91c1c';
    }
    
    return `background: ${bg_color}; color: ${text_color};`;
}

function get_age_label(days) {
    if (days === 0) return __('Today');
    if (days === 1) return __('1 day');
    if (days < 7) return days + ' ' + __('days');
    if (days < 14) return __('1 week+');
    if (days < 30) return Math.floor(days / 7) + ' ' + __('weeks');
    return Math.floor(days / 30) + ' ' + __('month(s)');
}

function load_mpesa_payments(dialog, search) {
    const wrapper = dialog.fields_dict.mpesa_list.$wrapper;
    wrapper.find('#mpesa-payments-list').html(
        `<div class="text-center text-muted p-3"><i class="fa fa-spinner fa-spin"></i> ${__('Searching...')}</div>`
    );
    
    frappe.call({
        method: 'cecypo_powerpack.quick_pay.api.list_pending_mpesa_payments',
        args: { company: dialog.company, search: search || '' },
        callback(r) {
            dialog.mpesa_data = r.message || {count: 0, payments: []};
            render_mpesa_list(dialog);
            update_mpesa_totals(dialog);
        }
    });
}

function update_mpesa_totals(dialog) {
    const wrapper = dialog.fields_dict.mpesa_totals.$wrapper;
    const total_selected = dialog.selected_mpesa.reduce((sum, p) => sum + flt(p.amount), 0);
    const remaining = dialog.outstanding - total_selected;
    const fully_paid = remaining <= 0;
    const overpayment = total_selected > dialog.outstanding;
    const excess_amount = overpayment ? total_selected - dialog.outstanding : 0;
    
    // Check if any individual payment exceeds outstanding
    const has_single_overpayment = dialog.selected_mpesa.some(p => flt(p.amount) > dialog.outstanding);
    
    // Show/hide invoice options
    if (dialog.create_invoice && fully_paid) {
        dialog.set_df_property('invoice_section', 'hidden', 0);
        render_mpesa_invoice_options(dialog);
    } else {
        dialog.set_df_property('invoice_section', 'hidden', 1);
    }
    
    wrapper.html(`
        <div class="mpesa-totals-bar ${overpayment ? 'mpesa-overpayment' : ''}">
            <div class="mpesa-total-item">
                <span>${__('Selected')}</span>
                <strong>${dialog.selected_mpesa.length} ${__('payment(s)')}</strong>
            </div>
            <div class="mpesa-total-item">
                <span>${__('Total Amount')}</span>
                <strong class="${total_selected >= dialog.outstanding ? 'text-success' : ''}">${format_currency(total_selected, dialog.currency)}</strong>
            </div>
            <div class="mpesa-total-item">
                <span>${__('Remaining')}</span>
                <strong class="${remaining > 0 ? 'text-warning' : 'text-success'}">${format_currency(Math.max(0, remaining), dialog.currency)}</strong>
            </div>
            ${overpayment ? `
                <div class="mpesa-total-item mpesa-excess-warning">
                    <span>${__('Excess (unallocated)')}</span>
                    <strong class="text-warning">${format_currency(excess_amount, dialog.currency)}</strong>
                </div>
                <div class="mpesa-total-item mpesa-overpay-note">
                    <span class="text-warning"><i class="fa fa-exclamation-triangle"></i> ${__('Only')} ${format_currency(dialog.outstanding, dialog.currency)} ${__('will be allocated to this order. Excess remains unallocated.')}</span>
                </div>
            ` : ''}
        </div>
    `);
}

function render_mpesa_invoice_options(dialog) {
    const wrapper = dialog.fields_dict.invoice_options_html.$wrapper;
    
    wrapper.html(`
        <div class="mpesa-invoice-options">
            <div class="mpesa-invoice-check">
                <label class="mpesa-checkbox-label">
                    <input type="checkbox" id="mpesa-create-invoice" ${dialog.create_invoice ? 'checked' : ''} disabled>
                    <span>${__('Create Sales Invoice')}</span>
                </label>
            </div>
            <div class="mpesa-invoice-check">
                <label class="mpesa-checkbox-label">
                    <input type="checkbox" id="mpesa-submit-invoice" ${dialog.submit_invoice ? 'checked' : ''} disabled>
                    <span>${__('Submit immediately')}</span>
                </label>
            </div>
        </div>
    `);
}

function process_mpesa_payments(frm, dialog, outstanding) {
    if (!dialog.selected_mpesa.length) {
        frappe.msgprint(__('Please select at least one Mpesa payment'));
        return;
    }
    
    const mpesa_names = dialog.selected_mpesa.map(p => p.name).join(',');
    
    frappe.call({
        method: 'cecypo_powerpack.quick_pay.api.process_mpesa_quick_pay',
        args: {
            sales_order: frm.doc.name,
            customer: frm.doc.customer,
            mpesa_payments: mpesa_names,
            outstanding_amount: outstanding,
            create_invoice: dialog.create_invoice ? 1 : 0,
            submit_invoice: dialog.submit_invoice ? 1 : 0,
            idempotency_token: dialog.idempotency_token,
        },
        freeze: true,
        freeze_message: __('Processing Mpesa Payments...'),
        callback(r) {
            if (r.message && r.message.success) {
                dialog.hide();
                
                let msg = `<p><strong>${__('Mpesa Payments Processed Successfully')}</strong></p>`;
                
                if (r.message.payment_entries && r.message.payment_entries.length) {
                    msg += '<ul>';
                    for (const pe of r.message.payment_entries) {
                        const display_amt = pe.full_amount || pe.amount;
                        msg += `<li>Mpesa: ${format_currency(display_amt, frm.doc.currency)} - <a href="/app/payment-entry/${pe.name}" target="_blank">${pe.name}</a></li>`;
                    }
                    msg += '</ul>';
                }
                
                if (r.message.mpesa_payments && r.message.mpesa_payments.length) {
                    msg += `<p class="text-muted"><small>${__('Mpesa entries processed')}: ${r.message.mpesa_payments.map(m => m.name).join(', ')}</small></p>`;
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
        },
        error(r) {
            frappe.msgprint({
                title: __('Error'),
                message: r.message || __('Failed to process Mpesa payments'),
                indicator: 'red'
            });
        }
    });
}

function show_request_payment_dialog(frm, parent_dialog) {
    const outstanding = flt(frm.doc.grand_total) - flt(frm.doc.advance_paid);
    
    // Get customer phone from contact
    frappe.call({
        method: 'cecypo_powerpack.quick_pay.api.get_customer_phone',
        args: { customer: frm.doc.customer },
        callback(r) {
            const phone = r.message || '';
            
            const req_dialog = new frappe.ui.Dialog({
                title: __('Request Mpesa Payment'),
                fields: [
                    {
                        fieldtype: 'HTML',
                        fieldname: 'request_info',
                        options: `
                            <div class="mpesa-request-info">
                                <div class="mpesa-req-row">
                                    <span>${__('Customer')}</span>
                                    <strong>${frm.doc.customer_name || frm.doc.customer}</strong>
                                </div>
                                <div class="mpesa-req-row">
                                    <span>${__('Amount to Request')}</span>
                                    <strong class="text-success">${format_currency(outstanding, frm.doc.currency)}</strong>
                                </div>
                            </div>
                        `
                    },
                    {
                        fieldtype: 'Data',
                        fieldname: 'phone_number',
                        label: __('Phone Number'),
                        reqd: 1,
                        default: phone,
                        description: __('Enter phone number with or without country code (e.g., 0727870777 or 254727870777)')
                    }
                ],
                primary_action_label: __('Send Request'),
                primary_action(values) {
                    if (!values.phone_number) {
                        frappe.msgprint(__('Please enter a phone number'));
                        return;
                    }
                    
                    frappe.call({
                        method: 'cecypo_powerpack.quick_pay.api.create_mpesa_payment_request',
                        args: {
                            sales_order: frm.doc.name,
                            customer: frm.doc.customer,
                            phone_number: values.phone_number,
                            amount: outstanding,
                        },
                        freeze: true,
                        freeze_message: __('Sending Payment Request...'),
                        callback(r) {
                            if (r.message && r.message.success) {
                                req_dialog.hide();
                                
                                frappe.msgprint({
                                    title: __('Payment Request Sent'),
                                    message: `
                                        <p>${__('Payment request has been sent to')} <strong>${values.phone_number}</strong></p>
                                        <p><a href="/app/payment-request/${r.message.payment_request}" target="_blank" class="btn btn-sm btn-primary">
                                            <i class="fa fa-external-link"></i> ${r.message.payment_request}
                                        </a></p>
                                    `,
                                    indicator: 'green'
                                });
                                
                                frm.reload_doc();
                            }
                        },
                        error(r) {
                            frappe.msgprint({
                                title: __('Error'),
                                message: r.message || __('Failed to create payment request'),
                                indicator: 'red'
                            });
                        }
                    });
                }
            });
            
            req_dialog.show();
        }
    });
}



})();
