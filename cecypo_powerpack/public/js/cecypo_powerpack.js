/**
 * Cecypo PowerPack - Global Client Scripts
 *
 * Bundled via cecypo_powerpack.bundle.js (see hooks.py app_include_js).
 */

window.CecypoPowerPack = window.CecypoPowerPack || {};

/**
 * PowerPack's own compact number formatter.
 *
 * Lives here because bulk_selection.js and point_of_sale_powerpack.js both need it.
 * It used to be a bare top-level `function format_number()` in bulk_selection.js,
 * which in a classic script overwrote frappe's core `window.format_number`
 * (number_format.js:90) for EVERY desk page -- frappe's and erpnext's own rendering
 * included. That version ignores the site number format, hardcodes en-US, defaults
 * to 2 decimals instead of float_precision, and returns an em dash for null, so the
 * clobber quietly changed numbers well outside PowerPack.
 *
 * Deliberately unchanged in behaviour: both callers render exactly as they did
 * before. The only difference is that frappe's global is no longer replaced.
 */
CecypoPowerPack.formatNumber = function (value, format, decimals) {
    if (value === null || value === undefined) return '—';
    // toFixed-style formatting, deliberately independent of frappe's formatter system
    const precision = decimals || 2;
    return parseFloat(value).toLocaleString('en-US', {
        minimumFractionDigits: precision,
        maximumFractionDigits: precision
    });
};

$(document).ready(function () {
    // Apply compact theme if enabled
    CecypoPowerPack.Settings.isEnabled('enable_compact_theme', function (enabled) {
        $('body').toggleClass('compact-theme', enabled);
    });
});

/**
 * Company Border Indicator
 * Renders fixed top/bottom colored bars based on the company of the document
 * currently open in a form view. Hidden on lists, reports, the workspace, and
 * doctypes that have no company field.
 */
CecypoPowerPack.CompanyBorder = {
    _TOP_ID: 'pp-border-top',
    _BOT_ID: 'pp-border-bottom',

    // Resolve the accent from a form: use its document's company, if any.
    applyFromForm: function (frm) {
        var company = (frm && frm.doc) ? frm.doc.company : null;
        CecypoPowerPack.CompanyBorder.applyForCompany(company);
    },

    // Render the accent for a given company, or remove it if none/unconfigured.
    applyForCompany: function (company) {
        var self = CecypoPowerPack.CompanyBorder;
        if (!company) {
            self._remove();
            return;
        }
        CecypoPowerPack.Settings.get(function (settings) {
            var rows = settings.company_borders || [];
            var row = rows.find(function (r) { return r.company === company; });
            if (!row || !row.color) {
                self._remove();
                return;
            }
            self._render(row.color, row.top_border || 0, row.bottom_border || 0);
        });
    },

    _render: function (color, topPx, botPx) {
        this._setBar(this._TOP_ID, color, topPx, 'top');
        this._setBar(this._BOT_ID, color, botPx, 'bottom');
    },

    _setBar: function (id, color, px, edge) {
        var $el = $('#' + id);
        if (px <= 0) {
            $el.remove();
            return;
        }
        if (!$el.length) {
            $el = $('<div>').attr('id', id).css('pointer-events', 'none');
            $('body').append($el);
        }
        $el.css({
            position: 'fixed',
            left: 0,
            right: 0,
            height: px + 'px',
            background: color,
            zIndex: 9999,
            top: edge === 'top' ? 0 : 'auto',
            bottom: edge === 'bottom' ? 0 : 'auto'
        });
    },

    _remove: function () {
        $('#' + this._TOP_ID + ', #' + this._BOT_ID).remove();
    }
};

// React to the document's company on every doctype's form, live on field change.
frappe.ui.form.on('*', {
    refresh: function (frm) { CecypoPowerPack.CompanyBorder.applyFromForm(frm); },
    company: function (frm) { CecypoPowerPack.CompanyBorder.applyFromForm(frm); }
});

// Clear the accent when navigating to a non-form route. Form destinations are
// handled by the wildcard refresh above (which always sets the correct state for
// the new form, including removal), so only non-form routes need clearing here.
frappe.router.on('change', function () {
    if ((frappe.get_route() || [])[0] !== 'Form') {
        CecypoPowerPack.CompanyBorder._remove();
    }
});

/**
 * Show system health status
 */
CecypoPowerPack.checkHealth = function () {
    frappe.call({
        method: "cecypo_powerpack.api.get_system_health",
        callback: function (r) {
            if (r.message) {
                frappe.msgprint({
                    title: __("System Health"),
                    indicator: r.message.status === "healthy" ? "green" : "red",
                    message: `Status: ${r.message.status}<br>Time: ${r.message.timestamp}`
                });
            }
        }
    });
};

/**
 * PowerPack Settings Utilities with Caching
 */
CecypoPowerPack.Settings = {
    _cache: {},

    /**
     * Get PowerPack Settings (cached)
     * @param {Function} callback - Callback function receiving the settings object
     */
    get: function(callback) {
        // Return cached settings if available
        if (this._cache.settings) {
            callback(this._cache.settings);
            return;
        }

        // Fetch settings from server
        frappe.call({
            method: 'cecypo_powerpack.api.get_settings_for_client',
            callback: function(r) {
                if (r.message) {
                    CecypoPowerPack.Settings._cache.settings = r.message;
                    callback(r.message);
                } else {
                    callback({});
                }
            }
        });
    },

    /**
     * Check if a specific feature is enabled
     * @param {String} feature_name - Name of the feature field (e.g., 'enable_item_list_powerup')
     * @param {Function} callback - Callback function receiving boolean (true/false)
     */
    isEnabled: function(feature_name, callback) {
        this.get(function(settings) {
            const enabled = settings[feature_name] === 1;
            callback(enabled);
        });
    },

    /**
     * Clear the settings cache (call this when settings are updated)
     */
    clearCache: function() {
        this._cache = {};
    }
};

/**
 * Item List Powerup Utilities
 */
CecypoPowerPack.ItemListPowerup = {
    /**
     * Check if Item List Powerup is enabled
     * @param {Function} callback - Callback function receiving boolean
     */
    isEnabled: function(callback) {
        CecypoPowerPack.Settings.isEnabled('enable_item_list_powerup', callback);
    },

    /**
     * Add button only if Item List Powerup is enabled
     * @param {Object} frm - The form object
     * @param {String} label - Button label
     * @param {Function} action - Button click handler
     * @param {String} group - Optional button group
     */
    addButton: function(frm, label, action, group) {
        this.isEnabled(function(enabled) {
            if (!enabled) return;

            if (group) {
                frm.add_custom_button(__(label), action, __(group));
            } else {
                frm.add_custom_button(__(label), action);
            }
        });
    }
};

// Clear cache when PowerPack Settings form is saved and re-apply border
frappe.ui.form.on('PowerPack Settings', {
    after_save: function(frm) {
        CecypoPowerPack.Settings.clearCache();
        CecypoPowerPack.CompanyBorder.applyFromForm(frm);
        frappe.show_alert({
            message: __('PowerPack Settings cache cleared'),
            indicator: 'green'
        }, 3);
    }
});

/**
 * Tax ID Duplicate Checker
 */
CecypoPowerPack.TaxIDChecker = {
    /**
     * Check if feature is enabled
     * @param {Function} callback - Callback receiving boolean
     */
    isEnabled: function(callback) {
        CecypoPowerPack.Settings.isEnabled('enable_duplicate_tax_id_check', callback);
    },

    /**
     * Check for duplicate tax IDs and block save if found
     * @param {Object} frm - The form object
     * @param {String} doctype - 'Customer' or 'Supplier'
     * @returns {Boolean} - Returns true to allow save, false to block
     */
    checkAndShowDialog: function(frm, doctype) {
        const tax_id = frm.doc.tax_id;

        // If no tax_id or user already confirmed, allow save
        if (!tax_id || frm._tax_id_confirmed) {
            return true;
        }

        // Check if feature is enabled (synchronous check from cache)
        let feature_enabled = false;
        CecypoPowerPack.Settings.get(function(settings) {
            feature_enabled = settings.enable_duplicate_tax_id_check === 1;
        });

        // If feature disabled, allow save
        if (!feature_enabled) {
            return true;
        }

        // Check for duplicates synchronously
        let has_duplicates = false;
        let duplicates_data = null;

        frappe.call({
            method: 'cecypo_powerpack.api.check_duplicate_tax_id',
            args: {
                doctype: doctype,
                tax_id: tax_id,
                current_name: frm.doc.name
            },
            async: false,  // Synchronous call to block save
            callback: function(r) {
                if (r.message && r.message.has_duplicates) {
                    has_duplicates = true;
                    duplicates_data = r.message.duplicates;
                }
            }
        });

        // If duplicates found, show dialog and block save
        if (has_duplicates) {
            CecypoPowerPack.TaxIDChecker.showConfirmationDialog(
                frm,
                duplicates_data,
                doctype,
                tax_id
            );
            return false;  // Block save
        }

        return true;  // Allow save
    },

    /**
     * Show confirmation dialog with list of duplicates
     * @param {Object} frm - The form object
     * @param {Array} duplicates - List of duplicate records
     * @param {String} doctype - 'Customer' or 'Supplier'
     * @param {String} tax_id - The tax ID
     */
    showConfirmationDialog: function(frm, duplicates, doctype, tax_id) {
        const title = doctype === 'Customer' ? __('Duplicate Customer Tax IDs') : __('Duplicate Supplier Tax IDs');
        const name_label = doctype === 'Customer' ? __('Customer Name') : __('Supplier Name');

        let html = `
            <div style="margin-bottom: 15px;">
                <p style="color: var(--text-muted); margin-bottom: 10px;">
                    <strong style="color: var(--orange-500);">⚠ Warning:</strong>
                    The Tax ID <strong>${tax_id}</strong> is already used by the following ${doctype.toLowerCase()}s:
                </p>
            </div>
            <div style="max-height: 300px; overflow-y: auto; border: 1px solid var(--border-color); border-radius: 4px;">
                <table class="table table-sm" style="margin-bottom: 0; font-size: 12px;">
                    <thead style="position: sticky; top: 0; background: var(--subtle-fg); z-index: 1;">
                        <tr>
                            <th style="padding: 8px;">${doctype} ID</th>
                            <th style="padding: 8px;">${name_label}</th>
                            <th style="padding: 8px;">Date Created</th>
                        </tr>
                    </thead>
                    <tbody>
        `;

        duplicates.forEach(dup => {
            const date = frappe.datetime.str_to_user(dup.creation);
            html += `
                <tr>
                    <td style="padding: 6px;">
                        <a href="/app/${doctype.toLowerCase()}/${dup.name}" target="_blank" style="color: var(--text-color); font-weight: 500;">
                            ${dup.name}
                        </a>
                    </td>
                    <td style="padding: 6px;">${dup.display_name || ''}</td>
                    <td style="padding: 6px; color: var(--text-muted);">${date}</td>
                </tr>
            `;
        });

        html += `
                    </tbody>
                </table>
            </div>
            <div style="margin-top: 15px; padding: 10px; background: var(--yellow-highlight-bg); border-left: 3px solid var(--yellow-500); border-radius: 4px;">
                <p style="margin: 0; font-size: 12px; color: var(--text-color);">
                    <strong>Note:</strong> Having multiple records with the same Tax ID may indicate duplicate entries.
                </p>
            </div>
        `;

        // Use confirm dialog with custom buttons
        const d = new frappe.ui.Dialog({
            title: title,
            indicator: 'orange',
            fields: [
                {
                    fieldtype: 'HTML',
                    options: html
                }
            ],
            primary_action_label: __('Save Anyway'),
            primary_action: function() {
                // Set flag to bypass check and save
                frm._tax_id_confirmed = true;
                d.hide();
                frm.save();
            },
            secondary_action_label: __('Cancel'),
            secondary_action: function() {
                // Reset flag and close dialog
                frm._tax_id_confirmed = false;
                d.hide();
            }
        });

        d.show();

        // Add custom styling to make it stand out
        d.$wrapper.find('.modal-content').css({
            'border': '2px solid var(--orange-500)',
            'box-shadow': '0 4px 20px rgba(255, 152, 0, 0.3)'
        });
    }
};

// Hook into Customer form
frappe.ui.form.on('Customer', {
    validate: function(frm) {
        CecypoPowerPack.Warnings.checkEmptyTaxId(frm, 'Customer');
        const allow_save = CecypoPowerPack.TaxIDChecker.checkAndShowDialog(frm, 'Customer');
        if (!allow_save) {
            frappe.validated = false;  // Block the save
        }
    },
    after_save: function(frm) {
        // Reset confirmation flag after successful save
        frm._tax_id_confirmed = false;
    }
});

// Hook into Supplier form
frappe.ui.form.on('Supplier', {
    validate: function(frm) {
        CecypoPowerPack.Warnings.checkEmptyTaxId(frm, 'Supplier');
        const allow_save = CecypoPowerPack.TaxIDChecker.checkAndShowDialog(frm, 'Supplier');
        if (!allow_save) {
            frappe.validated = false;  // Block the save
        }
    },
    after_save: function(frm) {
        // Reset confirmation flag after successful save
        frm._tax_id_confirmed = false;
    }
});

/**
 * Warnings — Empty Tax ID and Customer Overdue Invoices
 */
CecypoPowerPack.Warnings = {
    /**
     * Show orange toast if Customer/Supplier is being saved with no Tax ID.
     * Non-blocking — does not prevent the save.
     * @param {Object} frm - The form object
     * @param {String} doctype - 'Customer' or 'Supplier'
     */
    checkEmptyTaxId: function(frm, doctype) {
        let enabled = false;
        CecypoPowerPack.Settings.get(function(settings) {
            enabled = settings.enable_warnings === 1;
        });
        if (!enabled) return;

        if (!frm.doc.tax_id) {
            frappe.show_alert({
                message: __('Warning: {0} has no Tax ID set.', [frm.doc[doctype === 'Customer' ? 'customer_name' : 'supplier_name'] || frm.doc.name]),
                indicator: 'orange'
            }, 8);
        }
    },

};

/**
 * Customer snapshot: an (i) icon next to Customer that opens a dialog with the
 * customer's outstanding invoices, open payments, credit limit and contact.
 * Red when overdue, amber when anything is pending, neutral when clean.
 */
CecypoPowerPack.CustomerInfo = {
    ICON: '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',

    /**
     * Put (or refresh) the icon next to a customer field and fetch the snapshot.
     * @param {Object} frm
     * @param {String} fieldname - 'customer' or 'party_name'
     * @param {String} customer
     * @param {Object} opts - { auto_open: Boolean } open the dialog by itself when overdue
     */
    attach: function(frm, fieldname, customer, opts) {
        opts = opts || {};
        const field = frm.get_field(fieldname);
        if (!field || !field.$wrapper) return;
        const $label = field.$wrapper.find('.control-label').first();
        $label.find('.pp-customer-info').remove();
        if (!customer) return;

        CecypoPowerPack.Settings.isEnabled('enable_warnings', function(enabled) {
            if (!enabled) return;
            const $icon = $('<span class="pp-customer-info" title="' + __('Customer snapshot') + '"></span>').html(CecypoPowerPack.CustomerInfo.ICON);
            $label.append($icon);
            $icon.on('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                CecypoPowerPack.CustomerInfo.open(customer, frm.doc.company || '');
            });
            CecypoPowerPack.CustomerInfo.fetch(customer, frm.doc.company || '', function(snap) {
                if (!snap) return;
                $icon.removeClass('is-red is-amber');
                if (snap.highlight) $icon.addClass('is-' + snap.highlight);
                $icon.attr('title', snap.overdue_count
                    ? __('{0} overdue invoice(s) \u2014 click for details', [snap.overdue_count])
                    : snap.highlight ? __('Outstanding or advances pending \u2014 click for details') : __('Customer snapshot'));
                if (opts.auto_open && snap.overdue_count > 0 && frm.doc.docstatus === 0) {
                    CecypoPowerPack.CustomerInfo.render(snap);
                }
            });
        });
    },

    fetch: function(customer, company, callback) {
        frappe.call({
            method: 'cecypo_powerpack.api.get_customer_snapshot',
            args: { customer: customer, company: company },
            callback: function(r) { callback(r.message && r.message.customer ? r.message : null); }
        });
    },

    open: function(customer, company) {
        CecypoPowerPack.CustomerInfo.fetch(customer, company, function(snap) {
            if (snap) CecypoPowerPack.CustomerInfo.render(snap);
            else frappe.show_alert({ message: __('Customer snapshot is not available'), indicator: 'orange' }, 4);
        });
    },

    render: function(snap) {
        const cur = snap.currency;
        const money = function(v) { return format_currency(v || 0, cur); };
        const date = function(d) { return d ? frappe.datetime.str_to_user(d) : '\u2014'; };
        const card = function(label, value, color) {
            return '<div class="pp-snap-card"><div class="pp-snap-label">' + label + '</div>' +
                '<div class="pp-snap-value"' + (color ? ' style="color:' + color + '"' : '') + '>' + value + '</div></div>';
        };

        const cards =
            card(__('Total Outstanding'), money(snap.outstanding_total), snap.outstanding_total > 0 ? 'var(--red)' : 'var(--green)') +
            card(__('Overdue'), (snap.overdue_count || 0) + ' \u00b7 ' + money(snap.overdue_total), snap.overdue_count ? 'var(--red)' : '') +
            card(__('Unallocated Advances'), money(snap.advances_total), snap.advances_total > 0 ? 'var(--green)' : '') +
            card(__('Credit Limit'), snap.credit_limit != null ? money(snap.credit_limit) : '\u2014');

        const inv_rows = (snap.invoices || []).map(function(r) {
            return '<tr>' +
                '<td><a href="/app/sales-invoice/' + r.name + '" target="_blank">' + r.name + '</a></td>' +
                '<td>' + date(r.posting_date) + '</td>' +
                '<td>' + date(r.due_date) + '</td>' +
                '<td class="r' + (r.days_overdue > 0 ? ' pp-overdue' : '') + '">' + (r.days_overdue || 0) + '</td>' +
                '<td class="r">' + money(r.grand_total) + '</td>' +
                '<td class="r">' + money(r.paid) + '</td>' +
                '<td class="r pp-strong">' + money(r.outstanding_amount) + '</td></tr>';
        }).join('');
        const invoices = inv_rows
            ? '<table class="pp-snap-table"><thead><tr><th>' + __('Invoice') + '</th><th>' + __('Date') + '</th><th>' + __('Due') + '</th><th class="r">' + __('Days overdue') + '</th><th class="r">' + __('Amount') + '</th><th class="r">' + __('Paid') + '</th><th class="r">' + __('Outstanding') + '</th></tr></thead><tbody>' + inv_rows + '</tbody></table>'
            : '<div class="text-muted">' + __('No outstanding invoices') + '</div>';

        const adv_rows = (snap.advances || []).map(function(a) {
            return '<tr><td><a href="/app/payment-entry/' + a.name + '" target="_blank">' + a.name + '</a></td>' +
                '<td>' + date(a.posting_date) + '</td><td class="r">' + money(a.paid_amount) + '</td>' +
                '<td class="r pp-strong" style="color:var(--green)">' + money(a.unallocated_amount) + '</td></tr>';
        }).join('');
        const advances = adv_rows
            ? '<table class="pp-snap-table"><thead><tr><th>' + __('Payment Entry') + '</th><th>' + __('Date') + '</th><th class="r">' + __('Paid') + '</th><th class="r">' + __('Unallocated') + '</th></tr></thead><tbody>' + adv_rows + '</tbody></table>'
            : '<div class="text-muted">' + __('No open payments') + '</div>';

        const c = snap.primary_contact;
        let contact = '<span class="text-muted">' + __('No contact on file') + '</span>';
        if (c) {
            contact = '<strong>' + frappe.utils.escape_html(c.name || '') + '</strong>' +
                (c.email ? ' \u00b7 <a href="mailto:' + c.email + '">' + c.email + '</a>' : '') +
                (c.phone ? ' \u00b7 <a href="tel:' + c.phone + '">' + c.phone + '</a>' : '');
        }
        if (snap.payment_terms) contact += '<div class="text-muted">' + __('Payment Terms') + ': ' + snap.payment_terms + '</div>';

        const html =
            '<div class="pp-snap">' +
            '<div class="pp-snap-cards">' + cards + '</div>' +
            '<div class="pp-snap-section">' + __('Outstanding invoices') + '</div>' + invoices +
            '<div class="pp-snap-section">' + __('Open payments') + '</div>' + advances +
            '<div class="pp-snap-section">' + __('Contact') + '</div><div class="pp-snap-contact">' + contact + '</div>' +
            '</div>';

        const d = new frappe.ui.Dialog({
            title: snap.customer_name || snap.customer,
            indicator: snap.overdue_count ? 'red' : 'blue',
            size: 'large',
            fields: [{ fieldtype: 'HTML', fieldname: 'body', options: html }],
            primary_action_label: __('Email Customer'),
            primary_action: function() { CecypoPowerPack.CustomerInfo.email(snap); },
            secondary_action_label: __('Copy to Clipboard'),
            secondary_action: function() { CecypoPowerPack.CustomerInfo.copy(snap); }
        });
        d.add_custom_action(__('Close'), function() { d.hide(); });
        d.show();
    },

    build_text: function(snap) {
        const pad = function(s, n) { s = String(s == null ? '' : s); return s + ' '.repeat(Math.max(0, n - s.length)); };
        const money = function(v) { return format_currency(v || 0, snap.currency); };
        const sep = '-'.repeat(72);
        const lines = ['Dear ' + (snap.customer_name || snap.customer) + ',', ''];
        if ((snap.invoices || []).length) {
            lines.push('Your account currently shows the following outstanding invoices:');
            lines.push(pad('Invoice', 22) + pad('Due Date', 14) + pad('Days Overdue', 14) + 'Outstanding');
            lines.push(sep);
            snap.invoices.forEach(function(r) {
                lines.push(pad(r.name, 22) + pad(frappe.datetime.str_to_user(r.due_date), 14) + pad(r.days_overdue || 0, 14) + money(r.outstanding_amount));
            });
            lines.push(sep);
            lines.push('Total Outstanding: ' + money(snap.outstanding_total));
        } else {
            lines.push('Your account has no outstanding invoices.');
        }
        if ((snap.advances || []).length) {
            lines.push('');
            lines.push('Unallocated payments on your account:');
            snap.advances.forEach(function(a) {
                lines.push(pad(a.name, 22) + pad(frappe.datetime.str_to_user(a.posting_date), 14) + money(a.unallocated_amount));
            });
            lines.push('Net position: ' + money(snap.net_position));
        }
        lines.push('');
        lines.push(snap.overdue_count ? 'Kindly arrange for payment at your earliest convenience.' : 'Thank you for your business.');
        return lines.join('\n');
    },

    copy: function(snap) {
        const text = CecypoPowerPack.CustomerInfo.build_text(snap);
        const done = function() { frappe.show_alert({ message: __('Copied to clipboard'), indicator: 'green' }, 4); };
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(done).catch(function() { CecypoPowerPack.CustomerInfo._fallbackCopy(text, done); });
        } else {
            CecypoPowerPack.CustomerInfo._fallbackCopy(text, done);
        }
    },

    _fallbackCopy: function(text, done) {
        const el = document.createElement('textarea');
        el.value = text;
        el.style.position = 'fixed';
        el.style.opacity = '0';
        document.body.appendChild(el);
        el.focus();
        el.select();
        try { document.execCommand('copy'); done(); }
        catch (e) { frappe.show_alert({ message: __('Could not copy to clipboard'), indicator: 'red' }, 4); }
        document.body.removeChild(el);
    },

    email: function(snap) {
        const recipient = snap.primary_contact && snap.primary_contact.email ? snap.primary_contact.email : '';
        const subject = __('Account statement \u2014 {0}: {1} outstanding', [snap.customer_name || snap.customer, format_currency(snap.outstanding_total || 0, snap.currency)]);
        new frappe.views.CommunicationComposer({
            doc: { doctype: 'Customer', name: snap.customer },
            subject: subject,
            recipients: recipient,
            message: '<pre style="font-family:inherit;white-space:pre-wrap">' + frappe.utils.escape_html(CecypoPowerPack.CustomerInfo.build_text(snap)) + '</pre>'
        });
    }
};

/**
 * ETR Invoice Cancellation Prevention
 * Shows informational dialog before server-side validation blocks cancellation
 */
CecypoPowerPack.ETRCancelBlock = {
    showWarning: function(frm) {
        CecypoPowerPack.Settings.get(function(settings) {
            if (settings.prevent_etr_invoice_cancellation === 1 && frm.doc.etr_invoice_number) {
                frappe.msgprint({
                    title: __('ETR Invoice Cannot Be Cancelled'),
                    indicator: 'red',
                    message: __('This document contains an ETR Invoice Number: <strong>{0}</strong><br><br>ETR registered invoices cannot be cancelled for tax compliance reasons.<br><br>The cancellation will be blocked by the system.',
                        [frm.doc.etr_invoice_number])
                });
            }
        });
    }
};

// Hook into Sales Invoice
frappe.ui.form.on('Sales Invoice', {
    before_cancel: function(frm) {
        CecypoPowerPack.ETRCancelBlock.showWarning(frm);
    }
});

// Hook into POS Invoice
frappe.ui.form.on('POS Invoice', {
    before_cancel: function(frm) {
        CecypoPowerPack.ETRCancelBlock.showWarning(frm);
    }
});

/**
 * ETR Invoice Number helpers for Purchase Invoice
 * Gated by enable_warnings in PowerPack Settings.
 */
CecypoPowerPack.ETRInvoice = {

	// TIMS:  exactly 19 digits
	// eTIMS: KRACU + any word chars (taxpayer code) + / + digits
	_REGEX: /^\d{19}$|^KRACU\w+\/\d+$/,

	isValid(value) {
		return !value || this._REGEX.test(value);
	},

	// Determine verification URL based on format
	_verifyUrl(etr) {
		const is_tims = /^\d{19}$/.test(etr);
		if (is_tims) {
			return `https://itax.kra.go.ke/KRA-Portal/invoiceChk.htm?actionCode=loadPage&invoiceNo=${etr}`;
		}
		// eTIMS — replace all slashes with hyphens for the URL
		return `https://etims.kra.go.ke/common/link/etims/receipt/indexEtimsInvoiceData?Data=${etr.replace(/\//g, '-')}`;
	},

	setupFieldValidation(frm) {
		const fd = frm.fields_dict.etr_invoice_number;
		if (!fd || !fd.$input) return;

		// Inject validation message element once
		if (!fd.$wrapper.find('.etr-validation-msg').length) {
			fd.$wrapper.append('<div class="etr-validation-msg" style="color:var(--red-500);font-size:11px;margin-top:2px;"></div>');
		}

		fd.$input.off('input.etr').on('input.etr', function () {
			const val  = $(this).val();
			const $msg = fd.$wrapper.find('.etr-validation-msg');
			const ok   = !val || CecypoPowerPack.ETRInvoice._REGEX.test(val);
			$msg.text(ok ? '' : __('Invalid TIMS/eTIMS format ({0} chars)', [val.length]));
			$(this).toggleClass('is-invalid', !ok);
		});
	},

	setupButtons(frm) {
		const fd = frm.fields_dict.etr_invoice_number;
		if (!fd) return;

		// Dedup — remove any previously injected container on each refresh
		fd.$wrapper.find('.etr-action-buttons').remove();

		const $container = $(`
			<div class="etr-action-buttons" style="margin-top:5px;display:flex;gap:8px;">
				<button class="btn btn-xs btn-primary btn-verify">${__('Verify')}</button>
				<button class="btn btn-xs btn-default btn-last-cuin">${__('Get Last CU INV')}</button>
			</div>`);

		fd.$wrapper.find('.control-input-wrapper').after($container);
		$container.find('.btn-verify').on('click', () => CecypoPowerPack.ETRInvoice.verify(frm));
		$container.find('.btn-last-cuin').on('click', () => CecypoPowerPack.ETRInvoice.getLastCUIN(frm));
	},

	verify(frm) {
		const etr = frm.doc.etr_invoice_number;
		if (!etr) {
			frappe.show_alert({ message: __('Please fill the ETR Invoice Number first.'), indicator: 'red' });
			return;
		}
		window.open(this._verifyUrl(etr));
	},

	getLastCUIN(frm) {
		if (frm.doc.etr_invoice_number) {
			frappe.show_alert({ message: __('ETR Invoice Number already has a value.'), indicator: 'orange' });
			return;
		}
		if (!frm.doc.supplier) {
			frappe.show_alert({ message: __('Please select a Supplier first.'), indicator: 'orange' });
			return;
		}
		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Purchase Invoice',
				fields: ['etr_invoice_number'],
				filters: {
					supplier: frm.doc.supplier,
					etr_invoice_number: ['!=', ''],
				},
				order_by: 'creation desc',
				limit: 1,
			},
			callback(r) {
				if (r.message?.length && r.message[0].etr_invoice_number) {
					frm.set_value('etr_invoice_number', r.message[0].etr_invoice_number);
				} else {
					frappe.msgprint({
						title: __('Not Found'),
						indicator: 'orange',
						message: __('No ETR Invoice Number found on previous invoices for this supplier.'),
					});
				}
			},
		});
	},
};

frappe.ui.form.on('Purchase Invoice', {
	onload(frm) {
		CecypoPowerPack.Settings.isEnabled('enable_warnings', enabled => {
			if (!enabled) return;
			CecypoPowerPack.ETRInvoice.setupFieldValidation(frm);
		});
	},

	refresh(frm) {
		CecypoPowerPack.Settings.isEnabled('enable_warnings', enabled => {
			if (!enabled) return;
			CecypoPowerPack.ETRInvoice.setupButtons(frm);
		});
	},

	bill_date(frm) {
		CecypoPowerPack.Settings.isEnabled('enable_warnings', enabled => {
			if (!enabled || !frm.doc.bill_date) return;
			const today = frappe.datetime.get_today();
			if (frm.doc.bill_date > today) {
				frappe.show_alert({
					message: __('Bill Date is in the future. Please check — a Purchase Invoice cannot be dated after today.'),
					indicator: 'orange'
				}, 10);
			}
		});
	},

	before_submit(frm) {
		// Wrap in a Promise so Frappe waits for user decision before proceeding
		return new Promise((resolve, reject) => {
			CecypoPowerPack.Settings.isEnabled('enable_warnings', enabled => {
				if (!enabled || frm.doc.etr_invoice_number) {
					resolve();
					return;
				}
				frappe.confirm(
					__('The ETR Invoice Number is empty. Submit anyway?'),
					resolve,
					() => {
						frappe.show_alert({ message: __('Please fill the ETR Invoice Number.'), indicator: 'orange' });
						frm.scroll_to_field('etr_invoice_number');
						reject();
					}
				);
			});
		});
	},
});

// Customer snapshot icon on sales documents
['Sales Order', 'Sales Invoice', 'Delivery Note'].forEach(function(doctype) {
    frappe.ui.form.on(doctype, {
        refresh: function(frm) {
            CecypoPowerPack.CustomerInfo.attach(frm, 'customer', frm.doc.customer, { auto_open: false });
        },
        customer: function(frm) {
            CecypoPowerPack.CustomerInfo.attach(frm, 'customer', frm.doc.customer, { auto_open: true });
        }
    });
});

frappe.ui.form.on('Quotation', {
    refresh: function(frm) {
        const customer = frm.doc.quotation_to === 'Customer' ? frm.doc.party_name : '';
        CecypoPowerPack.CustomerInfo.attach(frm, 'party_name', customer, { auto_open: false });
    },
    party_name: function(frm) {
        const customer = frm.doc.quotation_to === 'Customer' ? frm.doc.party_name : '';
        CecypoPowerPack.CustomerInfo.attach(frm, 'party_name', customer, { auto_open: true });
    }
});
