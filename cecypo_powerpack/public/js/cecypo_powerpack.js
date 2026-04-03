/**
 * Cecypo PowerPack - Global Client Scripts
 * 
 * Include in hooks.py:
 * app_include_js = "/assets/cecypo_powerpack/js/cecypo_powerpack.js"
 */

window.CecypoPowerPack = window.CecypoPowerPack || {};

$(document).ready(function () {
    // Apply compact theme if enabled
    CecypoPowerPack.Settings.isEnabled('enable_compact_theme', function (enabled) {
        $('body').toggleClass('compact-theme', enabled);
    });
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
            method: 'frappe.client.get',
            args: {
                doctype: 'PowerPack Settings',
                name: 'PowerPack Settings'
            },
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

// Clear cache when PowerPack Settings form is saved
frappe.ui.form.on('PowerPack Settings', {
    after_save: function(frm) {
        CecypoPowerPack.Settings.clearCache();
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

    /**
     * Check if the selected customer has overdue invoices and show a dialog if so.
     * @param {Object} frm - The form object
     * @param {String} customer - Customer docname
     */
    checkCustomerOverdue: function(frm, customer) {
        let enabled = false;
        CecypoPowerPack.Settings.get(function(settings) {
            enabled = settings.enable_warnings === 1;
        });
        if (!enabled || !customer) return;

        frappe.call({
            method: 'cecypo_powerpack.api.get_customer_overdue_invoices',
            args: { customer: customer, company: frm.doc.company || '' },
            callback: function(r) {
                if (r.message && r.message.has_overdue) {
                    CecypoPowerPack.Warnings.showOverdueDialog(r.message);
                }
            }
        });
    },

    /**
     * Show a red-bordered dialog listing overdue invoices for the selected customer.
     * @param {Object} data - Response from get_customer_overdue_invoices
     */
    showOverdueDialog: function(data) {
        const invoices = data.invoices || [];
        const customer_name = data.customer_name || '';

        // Calculate total outstanding
        let total_outstanding = 0;
        const currency = invoices.length ? (invoices[0].currency || '') : '';
        invoices.forEach(function(inv) {
            total_outstanding += flt(inv.outstanding_amount);
        });

        let rows = '';
        invoices.forEach(function(inv) {
            const due = frappe.datetime.str_to_user(inv.due_date);
            const amount = format_currency(inv.grand_total, inv.currency);
            const outstanding = format_currency(inv.outstanding_amount, inv.currency);
            rows += `
                <tr>
                    <td style="padding:6px;">
                        <a href="/app/sales-invoice/${inv.name}" target="_blank">${inv.name}</a>
                    </td>
                    <td style="padding:6px; color: var(--red-500); font-weight:500;">${due}</td>
                    <td style="padding:6px; text-align:right;">${amount}</td>
                    <td style="padding:6px; text-align:right; font-weight:500;">${outstanding}</td>
                </tr>`;
        });

        const total_fmt = format_currency(total_outstanding, currency);

        const html = `
            <div style="margin-bottom:12px; padding:10px; background:var(--alert-bg,var(--bg-color)); border-left:3px solid var(--red-500); border-radius:4px;">
                <strong style="color:var(--red-500);">&#9888; ${invoices.length} overdue invoice${invoices.length !== 1 ? 's' : ''} found</strong>
            </div>
            <div style="max-height:280px; overflow-y:auto; border:1px solid var(--border-color); border-radius:4px;">
                <table class="table table-sm" style="margin-bottom:0; font-size:12px; color:var(--text-color);">
                    <thead style="position:sticky; top:0; background:var(--fg-color); z-index:1;">
                        <tr>
                            <th style="padding:8px;">Invoice</th>
                            <th style="padding:8px;">Due Date</th>
                            <th style="padding:8px; text-align:right;">Amount</th>
                            <th style="padding:8px; text-align:right;">Outstanding</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                    <tfoot>
                        <tr style="background:var(--fg-color);">
                            <td colspan="3" style="padding:8px; font-weight:600; text-align:right;">Total Outstanding:</td>
                            <td style="padding:8px; font-weight:600; text-align:right; color:var(--red-500);">${total_fmt}</td>
                        </tr>
                    </tfoot>
                </table>
            </div>`;

        const d = new frappe.ui.Dialog({
            title: __('Overdue Invoices \u2014 {0}', [customer_name]),
            indicator: 'red',
            fields: [{ fieldtype: 'HTML', options: html }],
            primary_action_label: __('Copy Reminder'),
            primary_action: function() {
                CecypoPowerPack.Warnings.copyReminderText(customer_name, invoices, total_outstanding, currency);
            },
            secondary_action_label: __('Close'),
            secondary_action: function() { d.hide(); }
        });

        d.show();

        d.$wrapper.find('.modal-content').css({
            'border': '2px solid var(--red-500)',
            'box-shadow': '0 4px 20px rgba(220, 53, 69, 0.3)'
        });
    },

    /**
     * Build a plain-text payment reminder and copy it to the clipboard.
     * @param {String} customer_name
     * @param {Array}  invoices
     * @param {Number} total_outstanding
     * @param {String} currency
     */
    copyReminderText: function(customer_name, invoices, total_outstanding, currency) {
        const pad = function(str, len) {
            str = String(str);
            return str + ' '.repeat(Math.max(0, len - str.length));
        };

        const sep = '-'.repeat(72);
        let lines = [
            'Dear ' + customer_name + ',',
            'Please note that the following invoices are overdue:',
            pad('Invoice', 22) + pad('Due Date', 16) + pad('Amount', 20) + 'Outstanding',
            sep
        ];

        invoices.forEach(function(inv) {
            const due = frappe.datetime.str_to_user(inv.due_date);
            const amount = format_currency(inv.grand_total, inv.currency);
            const outstanding = format_currency(inv.outstanding_amount, inv.currency);
            lines.push(pad(inv.name, 22) + pad(due, 16) + pad(amount, 20) + outstanding);
        });

        const total_fmt = format_currency(total_outstanding, currency);
        lines.push(sep);
        lines.push('Total Outstanding: ' + total_fmt);
        lines.push('');
        lines.push('Kindly arrange for payment at your earliest convenience.');
        lines.push('Thank you.');

        const text = lines.join('\n');

        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(function() {
                frappe.show_alert({ message: __('Reminder copied to clipboard'), indicator: 'green' }, 4);
            }).catch(function() {
                CecypoPowerPack.Warnings._fallbackCopy(text);
            });
        } else {
            CecypoPowerPack.Warnings._fallbackCopy(text);
        }
    },

    _fallbackCopy: function(text) {
        const el = document.createElement('textarea');
        el.value = text;
        el.style.position = 'fixed';
        el.style.opacity = '0';
        document.body.appendChild(el);
        el.focus();
        el.select();
        try {
            document.execCommand('copy');
            frappe.show_alert({ message: __('Reminder copied to clipboard'), indicator: 'green' }, 4);
        } catch (e) {
            frappe.show_alert({ message: __('Could not copy to clipboard'), indicator: 'red' }, 4);
        }
        document.body.removeChild(el);
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

// Overdue invoice checks for sales documents
frappe.ui.form.on('Sales Order', {
    customer: function(frm) {
        CecypoPowerPack.Warnings.checkCustomerOverdue(frm, frm.doc.customer);
    }
});

frappe.ui.form.on('Sales Invoice', {
    customer: function(frm) {
        CecypoPowerPack.Warnings.checkCustomerOverdue(frm, frm.doc.customer);
    }
});

frappe.ui.form.on('Quotation', {
    party_name: function(frm) {
        if (frm.doc.quotation_to === 'Customer') {
            CecypoPowerPack.Warnings.checkCustomerOverdue(frm, frm.doc.party_name);
        }
    }
});
