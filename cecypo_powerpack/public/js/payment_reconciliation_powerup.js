/**
 * Payment Reconciliation PowerUp - Zero Allocate Feature
 *
 * Adds a "Zero Allocate" button that creates allocation rows with zero amounts
 * for selected payments and invoices, allowing manual distribution without FIFO.
 */

frappe.ui.form.on('Payment Reconciliation', {
    refresh: function(frm) {
        check_and_setup(frm);
        add_zero_reconcile_button(frm);
    },

    party: function(frm) {
        // Re-check when party changes
        check_and_setup(frm);
    }
});

// Child table event to show Zero Reconcile button when allocations are added/modified
frappe.ui.form.on('Payment Reconciliation Allocation', {
    allocation_add: function(frm) {
        add_zero_reconcile_button(frm);
    },

    allocated_amount: function(frm) {
        // When user fills in amounts, show Zero Reconcile button
        add_zero_reconcile_button(frm);
    }
});

function check_and_setup(frm) {
    // Check if feature is enabled
    frappe.call({
        method: 'cecypo_powerpack.utils.is_feature_enabled',
        args: {
            feature_name: 'enable_payment_reconciliation_zero_allocate'
        },
        callback: function(r) {
            if (r.message) {
                add_zero_allocate_button(frm);
            }
        }
    });
}

function add_zero_allocate_button(frm) {
    // Remove existing button if present
    try {
        frm.page.remove_inner_button(__('Zero Allocate'));
    } catch (e) {
        // Button doesn't exist yet, ignore
    }

    // Only show button if we have payments and invoices loaded
    if (frm.doc && frm.doc.payments && frm.doc.payments.length > 0 &&
        frm.doc.invoices && frm.doc.invoices.length > 0) {

        // Add button next to "Allocate" button
        frm.page.add_inner_button(__('Zero Allocate'), function() {
            zero_allocate(frm);
        }, __('Actions'));
    }
}

function add_zero_reconcile_button(frm) {
    // Add "Zero Reconcile" button when allocations exist
    // This is a separate button that doesn't interfere with standard Reconcile
    if (!frm.doc || !frm.doc.allocation || frm.doc.allocation.length === 0) {
        return;
    }

    // Count non-zero allocations
    const non_zero_count = frm.doc.allocation.filter(alloc => (alloc.allocated_amount || 0) > 0).length;
    const total_count = frm.doc.allocation.length;
    const zero_count = total_count - non_zero_count;

    // Only show if there are allocations (including zeros)
    if (total_count > 0) {
        // Remove existing button if present
        try {
            frm.page.remove_inner_button(__('Zero Reconcile'));
        } catch (e) {
            // Button doesn't exist yet
        }

        // Add "Zero Reconcile" button
        frm.page.add_inner_button(__('Zero Reconcile'), function() {
            // Show confirmation with allocation info
            const msg = zero_count > 0
                ? __('Reconcile {0} non-zero allocation(s)? ({1} zero allocation(s) will be filtered out)', [non_zero_count, zero_count])
                : __('Reconcile {0} allocation(s)?', [non_zero_count]);

            frappe.confirm(
                msg,
                function() {
                    // User confirmed, proceed with reconciliation
                    frm.call({
                        doc: frm.doc,
                        method: 'zero_reconcile',
                        freeze: true,
                        freeze_message: __('Reconciling...'),
                        callback: function(r) {
                            if (!r.exc) {
                                // Clear tables after successful reconciliation
                                frm.clear_table('allocation');
                                frm.clear_table('payments');
                                frm.clear_table('invoices');
                                frm.refresh_fields();

                                frappe.show_alert({
                                    message: __('Successfully reconciled'),
                                    indicator: 'green'
                                });

                                // Remove button after success
                                try {
                                    frm.page.remove_inner_button(__('Zero Reconcile'));
                                } catch (e) {
                                    // Ignore
                                }
                            }
                        }
                    });
                }
            );
        }, __('Actions'));

        console.log('Zero Reconcile button added - Total:', total_count, 'Non-zero:', non_zero_count, 'Zero:', zero_count);
    }
}

function zero_allocate(frm) {
    // Validate form and fields exist
    if (!frm || !frm.fields_dict || !frm.fields_dict.payments || !frm.fields_dict.invoices) {
        frappe.msgprint({
            title: __('Error'),
            message: __('Form is not properly initialized'),
            indicator: 'red'
        });
        return;
    }

    // Get selected payments and invoices via checkboxes
    let selected_payments, selected_invoices;

    try {
        selected_payments = frm.fields_dict.payments.grid.get_selected_children();
        selected_invoices = frm.fields_dict.invoices.grid.get_selected_children();
    } catch (e) {
        frappe.msgprint({
            title: __('Error'),
            message: __('Unable to get selected items. Please try again.'),
            indicator: 'red'
        });
        console.error('Error getting selections:', e);
        return;
    }

    // Validate selection
    if (!selected_payments || selected_payments.length === 0) {
        frappe.msgprint({
            title: __('Selection Required'),
            message: __('Please select at least one payment using the checkboxes'),
            indicator: 'orange'
        });
        return;
    }

    if (!selected_invoices || selected_invoices.length === 0) {
        frappe.msgprint({
            title: __('Selection Required'),
            message: __('Please select at least one invoice using the checkboxes'),
            indicator: 'orange'
        });
        return;
    }

    // Calculate total rows that will be created
    const total_rows = selected_payments.length * selected_invoices.length;

    // Check if allocations already exist
    const has_existing_allocations = frm.doc.allocation && frm.doc.allocation.length > 0;

    // Show row limit warning if creating many rows
    if (total_rows > 500) {
        frappe.confirm(
            __('This will create {0} rows which may impact performance. Continue?', [total_rows]),
            function() {
                // User clicked Yes
                if (has_existing_allocations) {
                    show_replace_append_dialog(frm, selected_payments, selected_invoices, total_rows);
                } else {
                    show_confirmation_dialog(frm, selected_payments, selected_invoices, total_rows);
                }
            },
            function() {
                // User clicked No - do nothing
            }
        );
        return;
    }

    // If we have existing allocations, ask to replace or append
    if (has_existing_allocations) {
        show_replace_append_dialog(frm, selected_payments, selected_invoices, total_rows);
    } else {
        // No existing allocations, show confirmation
        show_confirmation_dialog(frm, selected_payments, selected_invoices, total_rows);
    }
}

function show_replace_append_dialog(frm, payments, invoices, total_rows) {
    const dialog = new frappe.ui.Dialog({
        title: __('Existing Allocations Found'),
        fields: [
            {
                fieldtype: 'HTML',
                options: `
                    <p>There are ${frm.doc.allocation.length} existing allocation rows.</p>
                    <p>This operation will create ${total_rows} new rows.</p>
                    <p><strong>What would you like to do?</strong></p>
                `
            },
            {
                fieldname: 'action',
                fieldtype: 'Select',
                label: 'Action',
                options: ['Replace existing allocations', 'Append to existing allocations'],
                default: 'Append to existing allocations',
                reqd: 1
            }
        ],
        primary_action_label: __('Continue'),
        primary_action: function(values) {
            dialog.hide();
            const replace = values.action === 'Replace existing allocations';
            execute_zero_allocate(frm, payments, invoices, replace);
        }
    });

    dialog.show();
}

function show_confirmation_dialog(frm, payments, invoices, total_rows) {
    frappe.confirm(
        __('This will create {0} allocation rows with zero amounts. Continue?', [total_rows]),
        function() {
            // User clicked Yes
            execute_zero_allocate(frm, payments, invoices, false);
        },
        function() {
            // User clicked No - do nothing
        }
    );
}

function execute_zero_allocate(frm, payments, invoices, replace) {
    // Show loading indicator
    frappe.show_alert({
        message: __('Creating zero allocations...'),
        indicator: 'blue'
    });

    // Call API to generate allocations
    frappe.call({
        method: 'cecypo_powerpack.api.zero_allocate_entries',
        args: {
            doc: frm.doc,
            payments: payments,
            invoices: invoices
        },
        freeze: true,
        freeze_message: __('Creating allocation entries...'),
        callback: function(r) {
            if (r.message && r.message.length > 0) {
                // Replace or append allocations
                if (replace) {
                    frm.clear_table('allocation');
                }

                // Add new allocations
                r.message.forEach(function(allocation) {
                    const row = frm.add_child('allocation');
                    Object.assign(row, allocation);
                });

                // Refresh the allocation table
                frm.refresh_field('allocation');

                // Show Zero Reconcile button
                setTimeout(function() {
                    add_zero_reconcile_button(frm);
                }, 100);

                // Show success message
                frappe.show_alert({
                    message: __('Created {0} allocation rows with zero amounts. Fill in amounts and click Reconcile.', [r.message.length]),
                    indicator: 'green'
                });

                // Clear payment and invoice selections
                frm.fields_dict.payments.grid.grid_rows.forEach(function(grid_row) {
                    grid_row.doc.__checked = 0;
                });
                frm.fields_dict.invoices.grid.grid_rows.forEach(function(grid_row) {
                    grid_row.doc.__checked = 0;
                });
                frm.refresh_field('payments');
                frm.refresh_field('invoices');
            } else {
                frappe.msgprint({
                    title: __('No Allocations Created'),
                    message: __('No allocation entries were created. Please check your selection.'),
                    indicator: 'orange'
                });
            }
        },
        error: function(r) {
            frappe.msgprint({
                title: __('Error'),
                message: __('Failed to create allocations. Please try again.'),
                indicator: 'red'
            });
        }
    });
}

