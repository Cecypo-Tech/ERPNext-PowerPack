/**
 * Cecypo PowerPack - Global Client Scripts
 * 
 * Include in hooks.py:
 * app_include_js = "/assets/cecypo_powerpack/js/cecypo_powerpack.js"
 */

window.CecypoPowerPack = window.CecypoPowerPack || {};

$(document).ready(function () {
    // PowerPack initialized
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
        // Check for duplicates and block save if found
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
        // Check for duplicates and block save if found
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
