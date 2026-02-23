/**
 * Bulk Selection for Sales & Stock Documents
 * Supports: Quotation, Sales Order, Sales Invoice, Stock Reconciliation, Stock Entry
 *
 * Features:
 * - Bulk item selection with search and filtering
 * - Tax-adjusted cost calculation (sales docs)
 * - Simplified view for stock docs (no pricing/profit)
 * - Pagination and sorting
 * - Sales/purchase history tooltips (sales docs only)
 * - Wildcard search support
 */

// Configuration for different doctypes
const BULK_SELECTION_CONFIG = {
    'Quotation': {
        setting_field: 'enable_quotation_bulk_selection',
        requires_warehouse: false,  // Warehouse is optional for Quotation
        has_taxes: true,
        has_price: true,
        is_stock_doctype: false,
        customer_field: 'party_name',  // Quotation uses party_name
        warehouse_field: 'set_warehouse',  // Unified with Sales Order/Invoice
        item_warehouse_field: 'warehouse'
    },
    'Sales Order': {
        setting_field: 'enable_sales_order_bulk_selection',
        requires_warehouse: true,  // Warehouse is mandatory
        has_taxes: true,
        has_price: true,
        is_stock_doctype: false,
        customer_field: 'customer',
        warehouse_field: 'set_warehouse',
        item_warehouse_field: 'warehouse'
    },
    'Sales Invoice': {
        setting_field: 'enable_sales_invoice_bulk_selection',
        requires_warehouse: true,  // Warehouse is mandatory
        has_taxes: true,
        has_price: true,
        is_stock_doctype: false,
        customer_field: 'customer',
        warehouse_field: 'set_warehouse',
        item_warehouse_field: 'warehouse'
    },
    'Stock Reconciliation': {
        setting_field: 'enable_stock_reconciliation_bulk_selection',
        requires_warehouse: true,
        has_taxes: false,
        has_price: false,
        is_stock_doctype: true,
        customer_field: null,
        warehouse_field: 'set_warehouse',
        item_warehouse_field: 'warehouse'
    },
    'Stock Entry': {
        setting_field: 'enable_stock_entry_bulk_selection',
        requires_warehouse: false,  // depends on purpose; at least one of from/to
        has_taxes: false,
        has_price: false,
        is_stock_doctype: true,
        customer_field: null,
        warehouse_field: 'from_warehouse',
        item_warehouse_field: 's_warehouse'
    }
};

// Helper function to get customer value based on doctype
function get_customer(frm) {
    const config = BULK_SELECTION_CONFIG[frm.doctype];
    if (!config.customer_field) return null;
    return frm.doc[config.customer_field];
}

// Initialize for each supported doctype
Object.keys(BULK_SELECTION_CONFIG).forEach(doctype => {
    const config = BULK_SELECTION_CONFIG[doctype];

    let handlers = {
        onload: function(frm) {
            const cfg = BULK_SELECTION_CONFIG[frm.doctype];
            // Check if feature is enabled for this doctype
            frappe.db.get_single_value('PowerPack Settings', cfg.setting_field)
                .then(enabled => {
                    frm._bulk_selection_enabled = enabled;
                });
        },

        refresh: function(frm) {
            if (frm.doc.docstatus !== 0) return;
            if (!frm._bulk_selection_enabled) return;

            add_bulk_selection_button(frm);
            toggle_bulk_button(frm);
        }
    };

    // Sales-only handlers
    if (!config.is_stock_doctype) {
        handlers.selling_price_list = function(frm) {
            if (!frm._bulk_selection_enabled) return;
            toggle_bulk_button(frm);
            frm._bulk_item_cache = null;
        };

        handlers.taxes_and_charges = function(frm) {
            if (!frm._bulk_selection_enabled) return;
            // Clear cache when tax template changes (affects cost calculation)
            frm._bulk_item_cache = null;
        };
    }

    // Add customer field handler based on doctype (sales only)
    if (config.customer_field) {
        handlers[config.customer_field] = function(frm) {
            if (!frm._bulk_selection_enabled) return;
            toggle_bulk_button(frm);
            frm._bulk_item_cache = null;
        };
    }

    // Add warehouse field handler based on doctype
    handlers[config.warehouse_field] = function(frm) {
        if (!frm._bulk_selection_enabled) return;
        toggle_bulk_button(frm);
        frm._bulk_item_cache = null;
    };

    // Stock Entry: also watch to_warehouse
    if (doctype === 'Stock Entry') {
        handlers.to_warehouse = function(frm) {
            if (!frm._bulk_selection_enabled) return;
            toggle_bulk_button(frm);
            frm._bulk_item_cache = null;
        };
    }

    frappe.ui.form.on(doctype, handlers);
});

// Check if current user can see cost prices
function has_cost_permission() {
    const cost_roles = [
        "System Manager",
        "Stock Manager",
        "Accounts Manager",
        "Sales Master Manager",
        "Administrator"
    ];

    return cost_roles.some(role => frappe.user_roles.includes(role));
}

function add_bulk_selection_button(frm) {
    frm.fields_dict.items.$wrapper.find('.btn-bulk-selection').remove();

    let $add_multiple = frm.fields_dict.items.$wrapper.find('.grid-add-multiple-rows');

    if ($add_multiple.length) {
        let $bulk_btn = $(`
            <button type="button" class="btn btn-xs btn-primary btn-bulk-selection" style="margin-left: 5px;">
                <span class="hidden-xs">Bulk Selection</span>
            </button>
        `);

        $bulk_btn.on('click', function() {
            show_bulk_item_selector(frm);
        });

        $add_multiple.after($bulk_btn);
        frm._bulk_selection_btn = $bulk_btn;
    }
}

function toggle_bulk_button(frm) {
    let btn = frm._bulk_selection_btn;
    if (btn && btn.length) {
        const config = BULK_SELECTION_CONFIG[frm.doctype];
        let disabled = false;
        let title = '';

        if (config.is_stock_doctype) {
            // Stock doctypes: no customer check
            if (frm.doctype === 'Stock Entry') {
                // Stock Entry: require at least from_warehouse or to_warehouse
                let from_wh = frm.doc.from_warehouse;
                let to_wh = frm.doc.to_warehouse;
                if (!from_wh && !to_wh) {
                    disabled = true;
                    title = __('Please select a Source or Target Warehouse first');
                }
            } else {
                // Stock Reconciliation: requires warehouse
                let warehouse = get_warehouse(frm);
                if (!warehouse) {
                    disabled = true;
                    title = __('Please select a Warehouse first');
                }
            }
        } else {
            // Sales doctypes: existing logic
            let customer = get_customer(frm);
            let warehouse = get_warehouse(frm);

            if (config.requires_warehouse) {
                // Sales Order & Sales Invoice: Requires both customer and warehouse
                if (!customer && !warehouse) {
                    disabled = true;
                    title = __('Please select Customer and Warehouse first');
                } else if (!customer) {
                    disabled = true;
                    title = __('Please select a Customer first');
                } else if (!warehouse) {
                    disabled = true;
                    title = __('Please select a Warehouse first');
                }
            } else {
                // Quotation: Only requires customer (warehouse is optional)
                disabled = !customer;
                if (disabled) {
                    title = __('Please select a Customer first');
                }
            }
        }

        btn.prop('disabled', disabled).toggleClass('disabled', disabled);

        if (disabled) {
            btn.attr('title', title);
        } else {
            btn.removeAttr('title');
        }
    }
}

function get_cached_items(frm) {
    const config = BULK_SELECTION_CONFIG[frm.doctype];
    let warehouse = get_warehouse(frm);

    if (!frm._bulk_item_cache || frm._bulk_item_cache.warehouse !== warehouse) {
        return null;
    }

    if (config.is_stock_doctype) {
        // Stock doctypes: only validate warehouse
        return frm._bulk_item_cache.items;
    }

    // Sales doctypes: validate price_list, customer, taxes
    let customer = get_customer(frm);
    if (frm._bulk_item_cache.price_list === frm.doc.selling_price_list &&
        frm._bulk_item_cache.customer === customer &&
        frm._bulk_item_cache.taxes_and_charges === frm.doc.taxes_and_charges) {
        return frm._bulk_item_cache.items;
    }
    return null;
}

function set_cached_items(frm, items, warehouse) {
    const config = BULK_SELECTION_CONFIG[frm.doctype];

    frm._bulk_item_cache = {
        items: items,
        warehouse: warehouse,
        timestamp: Date.now()
    };

    if (!config.is_stock_doctype) {
        frm._bulk_item_cache.price_list = frm.doc.selling_price_list;
        frm._bulk_item_cache.customer = get_customer(frm);
        frm._bulk_item_cache.taxes_and_charges = frm.doc.taxes_and_charges;
    }
}

function get_warehouse(frm) {
    // Get warehouse from the appropriate field based on doctype
    const config = BULK_SELECTION_CONFIG[frm.doctype];
    return frm.doc[config.warehouse_field] || null;
}

function show_bulk_item_selector(frm) {
    const config = BULK_SELECTION_CONFIG[frm.doctype];

    if (config.is_stock_doctype) {
        // Stock doctypes: no customer validation needed
        let warehouse = get_warehouse(frm);

        if (frm.doctype === 'Stock Entry') {
            let from_wh = frm.doc.from_warehouse;
            let to_wh = frm.doc.to_warehouse;
            if (!from_wh && !to_wh) {
                frappe.msgprint(__('Please select a Source or Target Warehouse first'));
                return;
            }
            // Use from_warehouse for stock lookup, fallback to to_warehouse
            warehouse = from_wh || to_wh;
        } else if (!warehouse) {
            frappe.msgprint(__('Please select a Warehouse first'));
            return;
        }

        let can_see_cost = has_cost_permission();

        let cached = get_cached_items(frm);
        if (cached) {
            show_item_dialog(frm, cached.items, can_see_cost, warehouse);
            return;
        }

        frappe.show_progress(__('Loading Items'), 0, 100, __('Fetching item list...'));

        frappe.call({
            method: 'frappe.client.get_list',
            args: {
                doctype: 'Item',
                filters: { disabled: 0, is_stock_item: 1 },
                fields: ['name', 'item_name', 'stock_uom'],
                limit_page_length: 0
            },
            callback: function(r) {
                if (r.message && r.message.length > 0) {
                    frappe.show_progress(__('Loading Items'), 50, 100, __('Fetching details for {0} items...', [r.message.length]));
                    fetch_bulk_stock_item_details(frm, r.message, warehouse, can_see_cost);
                } else {
                    frappe.hide_progress();
                    frappe.msgprint(__('No stock items found'));
                }
            },
            error: function() {
                frappe.hide_progress();
                frappe.msgprint(__('Error loading items'));
            }
        });
    } else {
        // Sales doctypes: existing logic
        let customer = get_customer(frm);

        // Validate customer
        if (!customer) {
            frappe.msgprint(__('Please select a Customer first'));
            return;
        }

        // Get warehouse (optional for Quotation, mandatory for Sales Order/Invoice)
        let warehouse = get_warehouse(frm);

        // Validate warehouse for Sales Order/Invoice (where it's mandatory)
        if (config.requires_warehouse && !warehouse) {
            frappe.msgprint(__('Please select a Warehouse first'));
            return;
        }

        // Determine cost permission on client side
        let can_see_cost = has_cost_permission();

        let cached = get_cached_items(frm);
        if (cached) {
            show_item_dialog(frm, cached.items, can_see_cost, warehouse);
            return;
        }

        frappe.show_progress(__('Loading Items'), 0, 100, __('Fetching item list...'));

        frappe.call({
            method: 'frappe.client.get_list',
            args: {
                doctype: 'Item',
                filters: { disabled: 0, is_sales_item: 1 },
                fields: ['name', 'item_name', 'stock_uom'],
                limit_page_length: 0
            },
            callback: function(r) {
                if (r.message && r.message.length > 0) {
                    frappe.show_progress(__('Loading Items'), 50, 100, __('Fetching details for {0} items...', [r.message.length]));
                    fetch_bulk_item_details(frm, r.message, warehouse, can_see_cost);
                } else {
                    frappe.hide_progress();
                    frappe.msgprint(__('No items found'));
                }
            },
            error: function() {
                frappe.hide_progress();
                frappe.msgprint(__('Error loading items'));
            }
        });
    }
}

function fetch_bulk_item_details(frm, items, warehouse, can_see_cost) {
    frappe.call({
        method: 'cecypo_powerpack.api.get_bulk_item_details',
        args: {
            items: items.map(i => i.name),
            price_list: frm.doc.selling_price_list,
            warehouse: warehouse,
            customer: get_customer(frm),
            taxes_and_charges: frm.doc.taxes_and_charges,
            doctype: frm.doctype,
            optimized: true
        },
        callback: function(r) {
            frappe.hide_progress();
            if (r.message && r.message.items && Array.isArray(r.message.items)) {
                set_cached_items(frm, {
                    items: r.message.items
                }, warehouse);
                show_item_dialog(frm, r.message.items, can_see_cost, warehouse);
            } else {
                frappe.msgprint(__('Error loading item details'));
            }
        },
        error: function() {
            frappe.hide_progress();
            frappe.msgprint(__('Error fetching item details'));
        }
    });
}

function fetch_bulk_stock_item_details(frm, items, warehouse, can_see_cost) {
    frappe.call({
        method: 'cecypo_powerpack.api.get_bulk_stock_item_details',
        args: {
            items: items.map(i => i.name),
            warehouse: warehouse,
            doctype: frm.doctype
        },
        callback: function(r) {
            frappe.hide_progress();
            if (r.message && r.message.items && Array.isArray(r.message.items)) {
                set_cached_items(frm, {
                    items: r.message.items
                }, warehouse);
                show_item_dialog(frm, r.message.items, can_see_cost, warehouse);
            } else {
                frappe.msgprint(__('Error loading stock item details'));
            }
        },
        error: function() {
            frappe.hide_progress();
            frappe.msgprint(__('Error fetching stock item details'));
        }
    });
}

// Convert wildcard pattern (with %) to regex
function wildcard_to_regex(pattern) {
    // Escape special regex characters except %
    let escaped = pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    // Convert % to .* (match any characters)
    let regex_pattern = escaped.replace(/%/g, '.*');
    // Create case-insensitive regex
    return new RegExp(regex_pattern, 'i');
}

function show_item_dialog(frm, item_data, can_see_cost, warehouse) {
    if (!item_data || !Array.isArray(item_data) || item_data.length === 0) {
        frappe.msgprint(__('No items available to display'));
        return;
    }

    const config = BULK_SELECTION_CONFIG[frm.doctype];
    const is_stock = config.is_stock_doctype;
    const has_price = config.has_price;

    const PAGE_SIZE = 20;
    let state = {
        current_page: 1,
        total_pages: Math.ceil(item_data.length / PAGE_SIZE),
        sort_column: 'item_code',
        sort_direction: 'asc',
        filtered_data: [...item_data],
        quantities: {},
        sales_history_cache: {}
    };

    (frm.doc.items || []).forEach(row => {
        if (row.item_code && row.qty > 0) {
            state.quantities[row.item_code] = (state.quantities[row.item_code] || 0) + row.qty;
        }
    });

    let d = new frappe.ui.Dialog({
        title: __('Select Items ({0} total)', [item_data.length]),
        fields: [
            { fieldname: 'toolbar', fieldtype: 'HTML' },
            { fieldname: 'items', fieldtype: 'HTML' }
        ],
        size: 'extra-large',
        minimizable: true
    });

    function get_sorted_filtered_data() {
        let data = [...item_data];

        let search_term = (d.$wrapper.find('#bulk-search').val() || '').toLowerCase().trim();
        let show_available = d.$wrapper.find('#show-available').prop('checked');

        if (search_term) {
            // Check if using wildcard mode (contains %)
            let is_wildcard = search_term.includes('%');

            if (is_wildcard) {
                // Wildcard search mode
                let pattern = wildcard_to_regex(search_term);

                data = data.filter(item => {
                    let item_code_lower = (item.item_code || '').toLowerCase();
                    let item_name_lower = (item.item_name || '').toLowerCase();

                    return pattern.test(item_code_lower) || pattern.test(item_name_lower);
                });

                // Sort by relevance in wildcard mode
                data.sort((a, b) => {
                    let a_code = (a.item_code || '').toLowerCase();
                    let b_code = (b.item_code || '').toLowerCase();
                    let pattern_local = wildcard_to_regex(search_term);

                    // Prioritize item_code matches over item_name matches
                    let a_code_match = pattern_local.test(a_code);
                    let b_code_match = pattern_local.test(b_code);

                    if (a_code_match && !b_code_match) return -1;
                    if (!a_code_match && b_code_match) return 1;

                    // Then sort alphabetically
                    return a_code.localeCompare(b_code);
                });
            } else {
                // Natural multi-word search mode
                let tokens = search_term.split(/\s+/).filter(t => t.length > 0);

                let scored_items = [];

                data.forEach(item => {
                    let item_code_lower = (item.item_code || '').toLowerCase();
                    let item_name_lower = (item.item_name || '').toLowerCase();
                    let combined = item_code_lower + ' ' + item_name_lower;

                    // Check if ALL tokens match somewhere
                    let all_match = tokens.every(token => combined.includes(token));

                    if (all_match) {
                        let score = 0;

                        tokens.forEach(token => {
                            // Exact match in item_code (highest priority)
                            if (item_code_lower === token) score += 100;
                            // Item code starts with token
                            else if (item_code_lower.startsWith(token)) score += 50;
                            // Token in item_code
                            else if (item_code_lower.includes(token)) score += 30;

                            // Exact word match in item_name
                            let name_words = item_name_lower.split(/\s+/);
                            if (name_words.includes(token)) score += 25;
                            // Item name starts with token
                            else if (item_name_lower.startsWith(token)) score += 15;
                            // Token in item_name
                            else if (item_name_lower.includes(token)) score += 10;
                        });

                        // Bonus for shorter item codes (more specific matches)
                        score += Math.max(0, 20 - item_code_lower.length);

                        scored_items.push({ item, score });
                    }
                });

                // Sort by score descending
                scored_items.sort((a, b) => b.score - a.score);
                data = scored_items.map(s => s.item);
            }
        }

        // Apply stock filter
        if (show_available) {
            data = data.filter(item => (item.actual_qty || 0) > 0);
        }

        // Apply column sort only when not searching (search has its own relevance sort)
        if (!search_term) {
            data.sort((a, b) => {
                let val_a = a[state.sort_column];
                let val_b = b[state.sort_column];

                if (typeof val_a === 'string') {
                    val_a = (val_a || '').toLowerCase();
                    val_b = (val_b || '').toLowerCase();
                }

                let cmp = val_a > val_b ? 1 : val_a < val_b ? -1 : 0;
                return state.sort_direction === 'asc' ? cmp : -cmp;
            });
        }

        return data;
    }

    function get_page_data() {
        let data = get_sorted_filtered_data();
        state.filtered_data = data;
        state.total_pages = Math.ceil(data.length / PAGE_SIZE) || 1;

        if (state.current_page > state.total_pages) {
            state.current_page = state.total_pages;
        }

        let start = (state.current_page - 1) * PAGE_SIZE;
        return data.slice(start, start + PAGE_SIZE);
    }

    function render_toolbar() {
        let html = `
            <div class="bulk-toolbar">
                <div class="toolbar-left">
                    <input type="text" id="bulk-search" class="form-control"
                           placeholder="${__('Search... (use % for wildcard)')}"
                           style="width: 280px;">
                    <label class="checkbox-label">
                        <input type="checkbox" id="show-available">
                        <span>${__('Available only')}</span>
                    </label>
                </div>
                <div class="toolbar-right">
                    <div class="pagination-info">
                        <span id="page-info">Page 1 of 1</span>
                        <span class="separator">|</span>
                        <span id="showing-info">Showing 0 items</span>
                    </div>
                    <div class="pagination-controls">
                        <button class="btn btn-xs btn-default" id="page-first" title="First">&laquo;</button>
                        <button class="btn btn-xs btn-default" id="page-prev" title="Previous">&lsaquo;</button>
                        <input type="number" id="page-input" class="form-control" min="1" value="1" style="width: 60px;">
                        <button class="btn btn-xs btn-default" id="page-next" title="Next">&rsaquo;</button>
                        <button class="btn btn-xs btn-default" id="page-last" title="Last">&raquo;</button>
                    </div>
                </div>
            </div>
        `;
        d.fields_dict.toolbar.$wrapper.html(html);
    }

    function render_table() {
        let page_data = get_page_data();

        // Valuation Rate column (always shown for stock docs, only with cost permission for sales)
        let cost_header = '';
        if (is_stock) {
            cost_header = `<th class="sortable text-right" data-column="valuation_rate">Valuation Rate <span class="sort-icon"></span></th>`;
        } else if (can_see_cost) {
            cost_header = `<th class="sortable text-right" data-column="valuation_rate">Cost <span class="sort-icon"></span></th>`;
        }

        // Show stock column if warehouse is set
        let stock_header = warehouse
            ? `<th class="sortable text-right" data-column="actual_qty">Available <span class="sort-icon"></span></th>`
            : '';

        // Sell Price and Line Total only for sales docs
        let sell_price_header = has_price
            ? `<th class="sortable text-right" data-column="price_list_rate">Sell Price <span class="sort-icon"></span></th>`
            : '';
        let line_total_header = has_price
            ? `<th class="text-right line-total-header">Line Total</th>`
            : '';

        let html = `
            <div class="bulk-content-wrapper">
            <div class="bulk-table-container">
                <table class="table table-bordered bulk-table">
                    <thead>
                        <tr>
                            <th style="width: 35px;"><input type="checkbox" id="select-all-page"></th>
                            <th style="width: 70px;">Qty</th>
                            <th style="width: 45px;">Img</th>
                            <th class="sortable" data-column="item_code">Item Code <span class="sort-icon"></span></th>
                            <th class="sortable" data-column="item_name">Description <span class="sort-icon"></span></th>
                            ${cost_header}
                            ${sell_price_header}
                            ${stock_header}
                            ${line_total_header}
                        </tr>
                    </thead>
                    <tbody>
        `;

        if (page_data.length === 0) {
            // Calculate colspan dynamically
            let colspan = 5; // checkbox + qty + img + item_code + description
            if (is_stock || can_see_cost) colspan++;
            if (has_price) colspan++; // sell price
            if (warehouse) colspan++;
            if (has_price) colspan++; // line total
            html += `
                <tr>
                    <td colspan="${colspan}" class="text-center" style="padding: 40px;">
                        <div style="font-size: 48px;">&#128269;</div>
                        <div style="font-size: 16px; font-weight: 500; margin-top: 10px;">No items found</div>
                        <div style="font-size: 12px; color: var(--text-muted); margin-top: 5px;">
                            Try different keywords or use % for wildcard (e.g., sam%tv)
                        </div>
                    </td>
                </tr>
            `;
        } else {
            page_data.forEach(item => {
                let qty = state.quantities[item.item_code] || 0;
                let rate = has_price ? (item.price_list_rate || 0) : 0;
                let line_total = qty * rate;

                // For stock docs: only check stock availability
                // For sales docs: check both price and stock
                let is_unavailable;
                if (is_stock) {
                    is_unavailable = warehouse && (item.actual_qty || 0) <= 0;
                } else {
                    is_unavailable = rate <= 0 || (warehouse && (item.actual_qty || 0) <= 0);
                }
                let row_class = is_unavailable ? 'unavailable-row' : '';
                if (qty > 0) row_class += ' has-qty';

                let cost_cell = '';
                if (is_stock) {
                    cost_cell = `<td class="text-right">${format_currency(item.valuation_rate || 0)}</td>`;
                } else if (can_see_cost) {
                    cost_cell = `<td class="text-right cost-price-cell" data-item="${item.item_code}">${format_currency(item.valuation_rate || 0)}</td>`;
                }

                let stock_cell = warehouse
                    ? `<td class="text-right ${(item.actual_qty || 0) <= 0 ? 'text-danger' : ''}">${format_number(item.actual_qty || 0, null, 2)}</td>`
                    : '';

                let sell_price_cell = has_price
                    ? `<td class="text-right sell-price-cell" data-item="${item.item_code}">${format_currency(rate)}</td>`
                    : '';

                let line_total_cell = has_price
                    ? `<td class="text-right line-total">${format_currency(line_total)}</td>`
                    : '';

                let image_cell = item.image
                    ? `<td class="image-cell">
                         <div class="item-image-wrapper">
                           <img src="${item.image}" class="item-thumbnail" alt="${item.item_code}" onerror="this.style.display='none'">
                           <div class="image-lightbox"><img src="${item.image}" alt="${item.item_code}"></div>
                         </div>
                       </td>`
                    : `<td class="image-cell"></td>`;

                html += `
                    <tr class="item-row ${row_class}" data-item="${item.item_code}" data-rate="${rate}">
                        <td><input type="checkbox" class="item-checkbox" ${qty > 0 ? 'checked' : ''}></td>
                        <td class="qty-cell">
                            <input type="number" class="qty-input form-control input-sm"
                                   value="${qty}" min="0" step="1">
                        </td>
                        ${image_cell}
                        <td class="item-code">${item.item_code}</td>
                        <td>${item.item_name || ''}</td>
                        ${cost_cell}
                        ${sell_price_cell}
                        ${stock_cell}
                        ${line_total_cell}
                    </tr>
                `;
            });
        }

        html += `
                    </tbody>
                </table>
            </div>
            ${render_summary()}
        </div>
            ${render_styles()}
        `;

        d.fields_dict.items.$wrapper.html(html);
        update_sort_indicators();
        update_pagination_info();
        bind_table_events();
    }

    function render_summary() {
        let totals = calculate_totals();

        if (is_stock) {
            // Simplified summary for stock doctypes: just count + qty
            return `
                <div class="selection-summary">
                    <div class="summary-stats">
                        <div class="stat-item">
                            <span class="stat-label">Selected:</span>
                            <span class="stat-value" id="stat-selected">${totals.count}</span>
                        </div>
                        <div class="stat-item">
                            <span class="stat-label">Total Qty:</span>
                            <span class="stat-value" id="stat-qty">${format_number(totals.qty, null, 2)}</span>
                        </div>
                    </div>
                    <button class="btn btn-add-selected" id="btn-add-selected">
                        <span class="icon">&#10003;</span> ${__('Add Selected')}
                    </button>
                </div>
            `;
        }

        // Sales doc summary with profit info
        let profit_html = '';

        if (can_see_cost && totals.total > 0) {
            let margin_class = totals.margin_pct >= 0 ? 'profit-positive' : 'profit-negative';

            // Show tax info when tax-inclusive
            let tax_info = '';
            if (totals.tax_inclusive && totals.total_taxes > 0) {
                tax_info = ` | Tax: ${format_currency(totals.total_taxes)}`;
            }

            profit_html = `
                <div class="stat-item profit-info ${margin_class}">
                    <span class="profit-detail">
                        Cost: ${format_currency(totals.display_cost)}${totals.tax_inclusive ? ' <span class="tax-note">(incl. tax)</span>' : ''} |
                        Profit: ${format_currency(totals.profit)}
                        (${totals.margin_pct.toFixed(1)}%)${tax_info}
                    </span>
                </div>
            `;
        }

        return `
            <div class="selection-summary">
                <div class="summary-stats">
                    <div class="stat-item">
                        <span class="stat-label">Selected:</span>
                        <span class="stat-value" id="stat-selected">${totals.count}</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Total Qty:</span>
                        <span class="stat-value" id="stat-qty">${format_number(totals.qty, null, 2)}</span>
                    </div>
                    <div class="stat-item grand-total">
                        <span class="stat-label">Grand Total:</span>
                        <span class="stat-value" id="stat-total">${format_currency(totals.total)}</span>
                    </div>
                    ${profit_html}
                </div>
                <button class="btn btn-add-selected" id="btn-add-selected">
                    <span class="icon">&#10003;</span> ${__('Add Selected')}
                </button>
            </div>
        `;
    }

    function render_styles() {
        return `
            <style>
                .modal-dialog.modal-extra-large {
                    width: 96vw !important;
                    max-width: 1700px !important;
                    margin: 1vh auto !important;
                }

                .modal-dialog.modal-extra-large .modal-content {
                    height: 98vh;
                    overflow: hidden;
                }

                .modal-dialog.modal-extra-large .modal-header {
                    padding: 8px 15px;
                }

                .modal-dialog.modal-extra-large .modal-body {
                    padding: 8px 15px;
                    overflow: hidden;
                }

                .modal-dialog.modal-extra-large .modal-footer {
                    display: none !important;
                }

                .bulk-content-wrapper {
                    display: flex;
                    flex-direction: column;
                    height: calc(90vh - 80px) !important;
                    overflow: hidden;
                }

                .bulk-toolbar {
                    padding: 6px 0;
                    margin-bottom: 6px;
                    border-bottom: 1px solid var(--border-color);
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    flex-wrap: wrap;
                    gap: 8px;
                }

                .toolbar-left {
                    display: flex;
                    align-items: center;
                    gap: 15px;
                }

                .toolbar-right {
                    display: flex;
                    align-items: center;
                    gap: 20px;
                }

                .checkbox-label {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    margin: 0;
                    cursor: pointer;
                    font-weight: normal;
                }

                .pagination-info {
                    color: var(--text-muted);
                    font-size: 13px;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }

                .pagination-info .separator {
                    color: var(--border-color);
                }

                .pagination-controls {
                    display: flex;
                    align-items: center;
                    gap: 4px;
                }

                .pagination-controls .btn {
                    min-width: 32px;
                }

                .pagination-controls #page-input {
                    text-align: center;
                    height: 26px;
                    padding: 2px 4px;
                }

                .bulk-table-container {
                    flex: 1;
                    overflow-y: auto;
                    overflow-x: auto;
                    border: 1px solid var(--border-color);
                    border-radius: 4px;
                }

                .bulk-table {
                    margin-bottom: 0;
                    font-size: 12px;
                }

                .bulk-table thead {
                    position: sticky;
                    top: 0;
                    background: var(--fg-color);
                    z-index: 10;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                }

                .bulk-table th, .bulk-table td {
                    padding: 4px 6px !important;
                    vertical-align: middle !important;
                }

                .bulk-table .sortable {
                    cursor: pointer;
                    user-select: none;
                }

                .bulk-table .sortable:hover {
                    background: var(--gray-100);
                }

                .sort-icon::after { content: '\\21C5'; color: var(--text-muted); margin-left: 4px; }
                .sort-icon.asc::after { content: '\\25B2'; color: var(--primary); }
                .sort-icon.desc::after { content: '\\25BC'; color: var(--primary); }

                .qty-input {
                    width: 60px;
                    height: 24px;
                    padding: 2px 4px;
                    font-size: 12px;
                }

                .item-row { cursor: pointer; transition: background 0.15s; }
                .item-row:hover { background: var(--table-hover-bg, var(--gray-50)); color: var(--text-color); }
                .item-row.has-qty { background: rgba(102, 126, 234, 0.08) !important; }
                .item-row.has-qty .line-total { color: var(--green-700); font-weight: 600; }

                .unavailable-row { opacity: 0.5; }
                .unavailable-row .item-code,
                .unavailable-row td { color: var(--text-muted); }

                .line-total-header, .line-total {
                    background: var(--subtle-fg);
                    color: var(--text-color);
                }

                .sell-price-cell {
                    position: relative;
                    cursor: help;
                }

                .sales-history-tooltip {
                    display: none;
                    position: absolute;
                    right: 0;
                    top: 100%;
                    z-index: 1000;
                    background: #1a1a2e;
                    color: white;
                    padding: 10px 12px;
                    border-radius: 6px;
                    font-size: 12px;
                    min-width: 220px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                    white-space: nowrap;
                }

                .sales-history-tooltip::before {
                    content: '';
                    position: absolute;
                    top: -6px;
                    right: 20px;
                    border-left: 6px solid transparent;
                    border-right: 6px solid transparent;
                    border-bottom: 6px solid #1a1a2e;
                }

                .sales-history-tooltip .tooltip-title {
                    font-weight: 600;
                    margin-bottom: 6px;
                    color: #a0aec0;
                    font-size: 11px;
                    text-transform: uppercase;
                }

                .sales-history-tooltip .history-row {
                    display: flex;
                    justify-content: space-between;
                    padding: 3px 0;
                    border-bottom: 1px solid rgba(255,255,255,0.1);
                }

                .sales-history-tooltip .history-row:last-child {
                    border-bottom: none;
                }

                .sales-history-tooltip .history-date {
                    color: #a0aec0;
                }

                .sales-history-tooltip .history-price {
                    font-weight: 600;
                    color: #68d391;
                }

                .sales-history-tooltip .no-history {
                    color: #a0aec0;
                    font-style: italic;
                }

                .sell-price-cell:hover .sales-history-tooltip {
                    display: block;
                }

                .cost-price-cell {
                    position: relative;
                    cursor: help;
                }

                .purchase-history-tooltip {
                    display: none;
                    position: absolute;
                    right: 0;
                    top: 100%;
                    z-index: 1000;
                    background: #1e3a5f;
                    color: white;
                    padding: 10px 12px;
                    border-radius: 6px;
                    font-size: 12px;
                    min-width: 260px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                    white-space: nowrap;
                }

                .purchase-history-tooltip::before {
                    content: '';
                    position: absolute;
                    top: -6px;
                    right: 20px;
                    border-left: 6px solid transparent;
                    border-right: 6px solid transparent;
                    border-bottom: 6px solid #1e3a5f;
                }

                .purchase-history-tooltip .tooltip-title {
                    font-weight: 600;
                    margin-bottom: 6px;
                    color: #7dd3fc;
                    font-size: 11px;
                    text-transform: uppercase;
                }

                .purchase-history-tooltip .history-row {
                    display: flex;
                    justify-content: space-between;
                    gap: 10px;
                    padding: 3px 0;
                    border-bottom: 1px solid rgba(255,255,255,0.1);
                }

                .purchase-history-tooltip .history-row:last-child {
                    border-bottom: none;
                }

                .purchase-history-tooltip .history-date {
                    color: #94a3b8;
                    min-width: 70px;
                }

                .purchase-history-tooltip .history-supplier {
                    color: #e2e8f0;
                    flex: 1;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }

                .purchase-history-tooltip .purchase-price {
                    font-weight: 600;
                    color: #fbbf24;
                }

                .purchase-history-tooltip .no-history {
                    color: #94a3b8;
                    font-style: italic;
                }

                .cost-price-cell:hover .purchase-history-tooltip {
                    display: block;
                }

                .image-cell { padding: 2px !important; text-align: center; }
                .item-image-wrapper { position: relative; display: inline-block; }
                .item-thumbnail {
                    width: 36px; height: 36px;
                    object-fit: contain;
                    border-radius: 3px;
                    border: 1px solid var(--border-color);
                    cursor: pointer;
                    transition: transform 0.15s;
                }
                .item-thumbnail:hover { transform: scale(1.05); border-color: var(--primary); }
                .image-lightbox {
                    display: none;
                    position: fixed;
                    z-index: 10000;
                    background: white;
                    padding: 10px;
                    border-radius: 8px;
                    box-shadow: 0 8px 30px rgba(0,0,0,0.25);
                    border: 2px solid var(--primary);
                    pointer-events: none;
                }
                .image-lightbox img { max-width: 280px; max-height: 280px; object-fit: contain; }
                .item-image-wrapper:hover .image-lightbox { display: block; }

                .selection-summary {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    background: #1a1a2e;
                    border-radius: 6px;
                    padding: 6px 12px;
                    margin-top: 6px;
                    color: white;
                }

                .summary-stats {
                    display: flex;
                    align-items: center;
                    gap: 16px;
                    flex-wrap: wrap;
                }

                .stat-item {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                }

                .stat-label { font-size: 11px; opacity: 0.85; }
                .stat-value { font-size: 13px; font-weight: 600; }

                .grand-total {
                    background: rgba(255,255,255,0.15);
                    padding: 6px 12px;
                    border-radius: 6px;
                    margin-left: 8px;
                }

                .grand-total .stat-value { font-size: 16px; }

                .profit-info {
                    margin-left: 12px;
                    padding-left: 12px;
                    border-left: 1px solid rgba(255,255,255,0.2);
                }

                .profit-detail {
                    font-size: 10px;
                    opacity: 0.9;
                }

                .profit-positive .profit-detail {
                    color: #68d391;
                }

                .profit-negative .profit-detail {
                    color: #fc8181;
                }

                .btn-add-selected {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    padding: 8px 18px;
                    font-size: 13px;
                    font-weight: 600;
                    background: rgba(255,255,255,0.15) !important;
                    border: 1px solid rgba(255,255,255,0.3) !important;
                    color: white !important;
                    transition: background 0.2s;
                }

                .btn-add-selected:hover {
                    background: rgba(255,255,255,0.25) !important;
                    color: white !important;
                }

                .btn-add-selected .icon { font-size: 16px; }

                @media (max-width: 768px) {
                    .bulk-toolbar { flex-direction: column; align-items: stretch; }
                    .toolbar-left, .toolbar-right { flex-wrap: wrap; }
                    .selection-summary { flex-direction: column; gap: 12px; }
                    .summary-stats { flex-wrap: wrap; justify-content: center; }
                }
            </style>
        `;
    }

    function calculate_totals() {
        let count = 0, qty = 0;

        if (is_stock) {
            // Stock doctypes: just count and qty
            for (let item_code in state.quantities) {
                let q = state.quantities[item_code];
                if (q > 0) {
                    count++;
                    qty += q;
                }
            }
            return { count, qty };
        }

        // Sales doctypes: full calculation with profit
        let net_total = 0;  // Tax-exclusive total
        let total_cost = 0; // Total cost (no tax on cost)

        // Use shared profit calculator for consistent calculations
        const profit_calc = cecypo_powerpack.profit_calculator;
        const tax_inclusive = profit_calc.is_tax_inclusive(frm);

        // Calculate document tax rate for deriving net_rate when not available
        const doc_tax_rate = profit_calc.calculate_doc_tax_rate(frm);

        // If doc_tax_rate is 0 but we have tax_inclusive, try to derive from existing items or taxes
        let effective_tax_rate = doc_tax_rate;
        if (tax_inclusive && doc_tax_rate === 0) {
            // Strategy 1: Calculate from existing items that have both rate and net_rate
            if (frm.doc.items && frm.doc.items.length > 0) {
                let tax_rate_sum = 0;
                let tax_rate_count = 0;
                frm.doc.items.forEach(item => {
                    if (item.rate > 0 && item.net_rate > 0 && item.net_rate < item.rate) {
                        const item_tax_rate = (item.rate - item.net_rate) / item.net_rate;
                        tax_rate_sum += item_tax_rate;
                        tax_rate_count++;
                    }
                });
                if (tax_rate_count > 0) {
                    effective_tax_rate = tax_rate_sum / tax_rate_count;
                }
            }

            // Strategy 2: If still 0, calculate from taxes table with included_in_print_rate
            if (effective_tax_rate === 0 && frm.doc.taxes && frm.doc.taxes.length > 0) {
                let total_tax_rate = 0;
                frm.doc.taxes.forEach(tax => {
                    if (tax.included_in_print_rate === 1 && tax.rate) {
                        total_tax_rate += tax.rate;
                    }
                });
                if (total_tax_rate > 0) {
                    effective_tax_rate = total_tax_rate / 100; // Convert percentage to decimal
                }
            }
        }

        for (let item_code in state.quantities) {
            let q = state.quantities[item_code];
            if (q > 0) {
                count++;
                qty += q;
                let item = item_data.find(i => i.item_code === item_code);
                if (item) {
                    const rate = item.price_list_rate || 0;

                    // Calculate net_rate (tax-exclusive rate)
                    let net_rate = item.net_rate;

                    // If net_rate is not available or equals rate (no tax applied), try to derive it
                    if (!net_rate || net_rate === rate) {
                        // First: Try to find the item in the document's items table
                        const item_in_doc = (frm.doc.items || []).find(i => i.item_code === item_code);
                        if (item_in_doc && item_in_doc.net_rate && item_in_doc.net_rate < rate) {
                            // Use the net_rate from the document item (most accurate)
                            net_rate = item_in_doc.net_rate;
                        } else if (tax_inclusive && effective_tax_rate > 0 && rate > 0) {
                            // Derive net_rate from rate using effective tax rate
                            net_rate = rate / (1 + effective_tax_rate);
                        } else if (tax_inclusive && rate > 0) {
                            // Tax inclusive but no way to calculate net_rate accurately
                            net_rate = rate;
                        } else {
                            // Not tax inclusive, or rate is 0
                            net_rate = rate;
                        }
                    }

                    // Accumulate net total (tax-exclusive)
                    net_total += q * net_rate;

                    // Accumulate cost (no tax on cost)
                    total_cost += q * (item.valuation_rate || 0);
                }
            }
        }

        // Calculate totals
        // Use effective_tax_rate to calculate grand_total when doc_tax_rate is not available
        const tax_rate_for_total = doc_tax_rate > 0 ? doc_tax_rate : effective_tax_rate;
        const total_taxes = net_total > 0 ? net_total * tax_rate_for_total : 0;
        const grand_total = net_total + total_taxes;

        // Profit calculation (always use net total - tax is not business profit)
        const profit = net_total - total_cost;

        // For margin: if tax-inclusive, show margin on grand total (what customer sees)
        // This matches the sales form calculation: (net_rate - cost) / display_rate * 100
        const margin_base = tax_inclusive ? grand_total : net_total;
        const margin_pct = margin_base > 0 ? (profit / margin_base * 100) : 0;

        // Calculate cost with tax for display (when tax_inclusive)
        const display_cost = tax_inclusive && doc_tax_rate > 0
            ? total_cost * (1 + doc_tax_rate)
            : total_cost;

        return {
            count,
            qty,
            total: tax_inclusive ? grand_total : net_total,
            total_cost: total_cost,  // Raw cost for calculation
            display_cost: display_cost,  // Cost with tax for display
            profit: profit,
            margin_pct: margin_pct,
            tax_inclusive: tax_inclusive,
            total_taxes: total_taxes,
            net_total: net_total,
            grand_total: grand_total
        };
    }

    function update_summary() {
        let totals = calculate_totals();
        d.$wrapper.find('#stat-selected').text(totals.count);
        d.$wrapper.find('#stat-qty').text(format_number(totals.qty, null, 2));

        if (is_stock) {
            // Stock docs: no grand total or profit to update
            return;
        }

        d.$wrapper.find('#stat-total').text(format_currency(totals.total));

        if (can_see_cost) {
            let $profit = d.$wrapper.find('.profit-info');
            if (totals.total > 0) {
                let margin_class = totals.margin_pct >= 0 ? 'profit-positive' : 'profit-negative';

                // Show tax info when tax-inclusive
                let tax_info = '';
                if (totals.tax_inclusive && totals.total_taxes > 0) {
                    tax_info = ` | Tax: ${format_currency(totals.total_taxes)}`;
                }

                let detail_html = `Cost: ${format_currency(totals.display_cost)}${totals.tax_inclusive ? ' <span class="tax-note">(incl. tax)</span>' : ''} | ` +
                    `Profit: ${format_currency(totals.profit)} ` +
                    `(${totals.margin_pct.toFixed(1)}%)${tax_info}`;

                if ($profit.length) {
                    $profit.removeClass('profit-positive profit-negative').addClass(margin_class);
                    $profit.find('.profit-detail').html(detail_html);
                    $profit.show();
                } else {
                    let profit_html = `
                        <div class="stat-item profit-info ${margin_class}">
                            <span class="profit-detail">
                                ${detail_html}
                            </span>
                        </div>
                    `;
                    d.$wrapper.find('.grand-total').after(profit_html);
                }
            } else {
                $profit.hide();
            }
        }
    }

    function update_sort_indicators() {
        d.$wrapper.find('.sort-icon').removeClass('asc desc');
        d.$wrapper.find(`.sortable[data-column="${state.sort_column}"] .sort-icon`)
            .addClass(state.sort_direction);
    }

    function update_pagination_info() {
        let filtered = state.filtered_data.length;
        let total = item_data.length;
        let start = (state.current_page - 1) * PAGE_SIZE + 1;
        let end = Math.min(state.current_page * PAGE_SIZE, filtered);

        if (filtered === 0) {
            start = 0;
            end = 0;
        }

        d.$wrapper.find('#page-info').text(`Page ${state.current_page} of ${state.total_pages}`);
        d.$wrapper.find('#showing-info').text(`${start}-${end} of ${filtered}${filtered !== total ? ` (filtered from ${total})` : ''}`);
        d.$wrapper.find('#page-input').val(state.current_page).attr('max', state.total_pages);

        d.$wrapper.find('#page-first, #page-prev').prop('disabled', state.current_page <= 1);
        d.$wrapper.find('#page-next, #page-last').prop('disabled', state.current_page >= state.total_pages);
    }

    function go_to_page(page) {
        page = Math.max(1, Math.min(page, state.total_pages));
        if (page !== state.current_page) {
            state.current_page = page;
            render_table();
        }
    }

    function fetch_sales_history(item_code, $cell) {
        if (state.sales_history_cache[item_code] !== undefined) {
            show_sales_tooltip($cell, state.sales_history_cache[item_code]);
            return;
        }

        show_sales_tooltip($cell, null, true);

        let customer = get_customer(frm);
        frappe.xcall('frappe.client.get_list', {
            doctype: 'Sales Invoice',
            filters: {
                'customer': customer,
                'docstatus': 1
            },
            fields: ['name', 'posting_date', 'grand_total', 'net_total'],
            order_by: 'posting_date desc',
            limit_page_length: 20
        }).then(invoices => {
            if (!invoices || invoices.length === 0) {
                state.sales_history_cache[item_code] = [];
                show_sales_tooltip($cell, []);
                return;
            }

            let history = [];
            let processed = 0;

            for (let inv of invoices) {
                if (history.length >= 3) break;

                frappe.xcall('frappe.client.get', {
                    doctype: 'Sales Invoice',
                    name: inv.name
                }).then(doc => {
                    processed++;

                    if (doc && doc.items) {
                        let item_row = doc.items.find(row => row.item_code === item_code);
                        if (item_row && history.length < 3) {
                            let tax_multiplier = 1;
                            if (doc.net_total && doc.net_total > 0) {
                                tax_multiplier = doc.grand_total / doc.net_total;
                            }

                            let rate_with_tax = (item_row.rate || 0) * tax_multiplier;

                            history.push({
                                date: frappe.datetime.str_to_user(doc.posting_date),
                                qty: item_row.qty || 0,
                                rate: item_row.rate || 0,
                                rate_with_tax: Math.round(rate_with_tax * 100) / 100
                            });
                        }
                    }

                    if (history.length >= 3 || processed >= invoices.length) {
                        state.sales_history_cache[item_code] = history;
                        show_sales_tooltip($cell, history);
                    }
                }).catch(() => {
                    processed++;
                    if (processed >= invoices.length) {
                        state.sales_history_cache[item_code] = history;
                        show_sales_tooltip($cell, history);
                    }
                });
            }
        }).catch(() => {
            state.sales_history_cache[item_code] = [];
            show_sales_tooltip($cell, []);
        });
    }

    function show_sales_tooltip($cell, history, loading = false) {
        $cell.find('.sales-history-tooltip').remove();

        let customer = get_customer(frm);
        let customer_display = frm.doc.customer_name || customer;
        let tooltip_html = `<div class="sales-history-tooltip">
            <div class="tooltip-title">Last Sales to ${customer_display}</div>`;

        if (loading) {
            tooltip_html += `<div class="no-history">Loading...</div>`;
        } else if (!history || history.length === 0) {
            tooltip_html += `<div class="no-history">No previous sales found</div>`;
        } else {
            history.forEach(sale => {
                tooltip_html += `
                    <div class="history-row">
                        <span class="history-date">${sale.date}</span>
                        <span class="history-qty">Qty: ${sale.qty}</span>
                        <span class="history-price">${format_currency(sale.rate_with_tax)}</span>
                    </div>`;
            });
        }

        tooltip_html += `</div>`;
        $cell.append(tooltip_html);
    }

    function fetch_purchase_history(item_code, $cell) {
        let cache_key = 'purchase_' + item_code;
        if (state.sales_history_cache[cache_key] !== undefined) {
            show_purchase_tooltip($cell, state.sales_history_cache[cache_key]);
            return;
        }

        show_purchase_tooltip($cell, null, true);

        frappe.xcall('frappe.client.get_list', {
            doctype: 'Purchase Invoice',
            filters: {
                'docstatus': 1
            },
            fields: ['name', 'posting_date', 'supplier', 'supplier_name', 'grand_total', 'net_total'],
            order_by: 'posting_date desc',
            limit_page_length: 20
        }).then(invoices => {
            if (!invoices || invoices.length === 0) {
                state.sales_history_cache[cache_key] = [];
                show_purchase_tooltip($cell, []);
                return;
            }

            let history = [];
            let processed = 0;

            for (let inv of invoices) {
                if (history.length >= 3) break;

                frappe.xcall('frappe.client.get', {
                    doctype: 'Purchase Invoice',
                    name: inv.name
                }).then(doc => {
                    processed++;

                    if (doc && doc.items) {
                        let item_row = doc.items.find(row => row.item_code === item_code);
                        if (item_row && history.length < 3) {
                            let tax_multiplier = 1;
                            if (doc.net_total && doc.net_total > 0) {
                                tax_multiplier = doc.grand_total / doc.net_total;
                            }

                            let rate_with_tax = (item_row.rate || 0) * tax_multiplier;

                            history.push({
                                date: frappe.datetime.str_to_user(doc.posting_date),
                                supplier: doc.supplier_name || doc.supplier,
                                qty: item_row.qty || 0,
                                rate: item_row.rate || 0,
                                rate_with_tax: Math.round(rate_with_tax * 100) / 100
                            });
                        }
                    }

                    if (history.length >= 3 || processed >= invoices.length) {
                        state.sales_history_cache[cache_key] = history;
                        show_purchase_tooltip($cell, history);
                    }
                }).catch(() => {
                    processed++;
                    if (processed >= invoices.length) {
                        state.sales_history_cache[cache_key] = history;
                        show_purchase_tooltip($cell, history);
                    }
                });
            }
        }).catch(() => {
            state.sales_history_cache[cache_key] = [];
            show_purchase_tooltip($cell, []);
        });
    }

    function show_purchase_tooltip($cell, history, loading = false) {
        $cell.find('.purchase-history-tooltip').remove();

        let tooltip_html = `<div class="purchase-history-tooltip">
            <div class="tooltip-title">Last Purchases (Any Supplier)</div>`;

        if (loading) {
            tooltip_html += `<div class="no-history">Loading...</div>`;
        } else if (!history || history.length === 0) {
            tooltip_html += `<div class="no-history">No purchase history found</div>`;
        } else {
            history.forEach(purchase => {
                tooltip_html += `
                    <div class="history-row">
                        <span class="history-date">${purchase.date}</span>
                        <span class="history-supplier" title="${purchase.supplier}">${(purchase.supplier || '').substring(0, 15)}${(purchase.supplier || '').length > 15 ? '...' : ''}</span>
                        <span class="history-price purchase-price">${format_currency(purchase.rate_with_tax)}</span>
                    </div>`;
            });
        }

        tooltip_html += `</div>`;
        $cell.append(tooltip_html);
    }

    function bind_table_events() {
        d.$wrapper.find('.sortable').off('click').on('click', function() {
            let col = $(this).data('column');
            if (state.sort_column === col) {
                state.sort_direction = state.sort_direction === 'asc' ? 'desc' : 'asc';
            } else {
                state.sort_column = col;
                state.sort_direction = 'asc';
            }
            state.current_page = 1;
            render_table();
        });

        d.$wrapper.find('.item-row').off('click').on('click', function(e) {
            if ($(e.target).is('input') || $(e.target).closest('.item-image-wrapper').length) return;
            let checkbox = $(this).find('.item-checkbox');
            checkbox.prop('checked', !checkbox.prop('checked')).trigger('change');
        });

        d.$wrapper.find('.qty-input').off('input change').on('input change', function() {
            let $row = $(this).closest('tr');
            let item_code = $row.data('item');
            let qty = Math.max(0, parseFloat($(this).val()) || 0);

            state.quantities[item_code] = qty;

            if (has_price) {
                let rate = parseFloat($row.data('rate')) || 0;
                $row.find('.line-total').text(format_currency(qty * rate));
            }
            $row.find('.item-checkbox').prop('checked', qty > 0);
            $row.toggleClass('has-qty', qty > 0);

            update_summary();
        });

        d.$wrapper.find('.item-checkbox').off('change').on('change', function() {
            let $row = $(this).closest('tr');
            let item_code = $row.data('item');
            let qty_input = $row.find('.qty-input');

            if ($(this).prop('checked')) {
                if (!state.quantities[item_code] || state.quantities[item_code] <= 0) {
                    state.quantities[item_code] = 1;
                    qty_input.val(1);
                }
            } else {
                state.quantities[item_code] = 0;
                qty_input.val(0);
            }

            if (has_price) {
                let rate = parseFloat($row.data('rate')) || 0;
                $row.find('.line-total').text(format_currency(state.quantities[item_code] * rate));
            }
            $row.toggleClass('has-qty', state.quantities[item_code] > 0);

            update_summary();
        });

        d.$wrapper.find('#select-all-page').off('change').on('change', function() {
            let checked = $(this).prop('checked');
            d.$wrapper.find('.item-row').each(function() {
                let $row = $(this);
                let item_code = $row.data('item');
                let qty_input = $row.find('.qty-input');

                if (checked) {
                    if (!state.quantities[item_code] || state.quantities[item_code] <= 0) {
                        state.quantities[item_code] = 1;
                        qty_input.val(1);
                    }
                } else {
                    state.quantities[item_code] = 0;
                    qty_input.val(0);
                }

                $row.find('.item-checkbox').prop('checked', checked);
                if (has_price) {
                    let rate = parseFloat($row.data('rate')) || 0;
                    $row.find('.line-total').text(format_currency(state.quantities[item_code] * rate));
                }
                $row.toggleClass('has-qty', state.quantities[item_code] > 0);
            });

            update_summary();
        });

        d.$wrapper.find('#btn-add-selected').off('click').on('click', function() {
            let selected = [];
            for (let item_code in state.quantities) {
                let qty = state.quantities[item_code];
                if (qty > 0) {
                    let item = item_data.find(i => i.item_code === item_code);
                    if (item) {
                        selected.push({ ...item, qty });
                    }
                }
            }

            if (selected.length === 0) {
                frappe.msgprint(__('Please enter quantity for at least one item'));
                return;
            }

            add_items_to_doc(frm, selected, warehouse);
            d.hide();
        });

        // Sales history tooltips — only for sales docs
        if (has_price) {
            d.$wrapper.find('.sell-price-cell').off('mouseenter').on('mouseenter', function() {
                let $cell = $(this);
                let item_code = $cell.data('item');
                if (get_customer(frm) && item_code) {
                    fetch_sales_history(item_code, $cell);
                }
            });
        }

        // Purchase history tooltips — only for sales docs with cost permission
        if (!is_stock && can_see_cost) {
            d.$wrapper.find('.cost-price-cell').off('mouseenter').on('mouseenter', function() {
                let $cell = $(this);
                let item_code = $cell.data('item');
                if (item_code) {
                    fetch_purchase_history(item_code, $cell);
                }
            });
        }

        d.$wrapper.find('.item-thumbnail').off('mouseenter mouseleave')
            .on('mouseenter', function(e) {
                let $lightbox = $(this).siblings('.image-lightbox');
                $(document).on('mousemove.lightbox', function(ev) {
                    let x = ev.pageX + 15;
                    let y = ev.pageY + 15;
                    let lw = $lightbox.outerWidth() || 300;
                    let lh = $lightbox.outerHeight() || 300;

                    if (x + lw > $(window).width()) x = ev.pageX - lw - 15;
                    if (y + lh > $(window).height()) y = ev.pageY - lh - 15;

                    $lightbox.css({ left: x, top: y });
                });
            })
            .on('mouseleave', function() {
                $(document).off('mousemove.lightbox');
            });
    }

    function bind_toolbar_events() {
        let search_timeout;
        d.$wrapper.find('#bulk-search').off('input').on('input', function() {
            clearTimeout(search_timeout);
            search_timeout = setTimeout(() => {
                state.current_page = 1;
                render_table();
            }, 250);
        });

        d.$wrapper.find('#show-available').off('change').on('change', function() {
            state.current_page = 1;
            render_table();
        });

        d.$wrapper.find('#page-first').off('click').on('click', () => go_to_page(1));
        d.$wrapper.find('#page-prev').off('click').on('click', () => go_to_page(state.current_page - 1));
        d.$wrapper.find('#page-next').off('click').on('click', () => go_to_page(state.current_page + 1));
        d.$wrapper.find('#page-last').off('click').on('click', () => go_to_page(state.total_pages));

        d.$wrapper.find('#page-input').off('change keypress').on('change', function() {
            go_to_page(parseInt($(this).val()) || 1);
        }).on('keypress', function(e) {
            if (e.which === 13) {
                go_to_page(parseInt($(this).val()) || 1);
            }
        });
    }

    render_toolbar();

    // Only check "Available only" by default if warehouse is present
    // For Quotation (no warehouse), all items have actual_qty=0 so this would hide everything
    if (warehouse) {
        d.$wrapper.find('#show-available').prop('checked', true);
    } else {
        // Hide the "Available only" checkbox since it's not applicable without warehouse
        d.$wrapper.find('#show-available').closest('.checkbox-label').hide();
    }

    render_table();
    bind_toolbar_events();

    setTimeout(() => d.$wrapper.find('#bulk-search').focus(), 200);

    d.show();
}

/**
 * Add selected items to the document using proper ERPNext patterns.
 * Handles sales docs, Stock Reconciliation, and Stock Entry differently.
 */
function add_items_to_doc(frm, selected_items, warehouse) {
    const config = BULK_SELECTION_CONFIG[frm.doctype];

    // Step 1: Remove empty rows
    let items_to_remove = [];
    (frm.doc.items || []).forEach((row) => {
        if (!row.item_code) {
            items_to_remove.push(row);
        }
    });

    items_to_remove.forEach(row => {
        frm.get_field('items').grid.grid_rows_by_docname[row.name].remove();
    });

    // Step 2: Build map of existing items
    let existing_items = {};
    (frm.doc.items || []).forEach(row => {
        if (row.item_code) {
            if (!existing_items[row.item_code]) {
                existing_items[row.item_code] = [];
            }
            existing_items[row.item_code].push(row);
        }
    });

    let updated_count = 0;
    let added_count = 0;

    // Step 3: Process items sequentially to avoid race conditions
    let chain = Promise.resolve();

    if (frm.doctype === 'Stock Reconciliation') {
        // Stock Reconciliation: item_code -> warehouse -> wait for valuation -> qty
        selected_items.forEach(item => {
            chain = chain.then(() => {
                if (existing_items[item.item_code] && existing_items[item.item_code].length > 0) {
                    let existing_row = existing_items[item.item_code][0];
                    updated_count++;
                    return frappe.model.set_value(
                        existing_row.doctype,
                        existing_row.name,
                        'qty',
                        item.qty
                    );
                } else {
                    added_count++;
                    let child = frm.add_child('items');

                    return frappe.model.set_value(
                        child.doctype,
                        child.name,
                        'item_code',
                        item.item_code
                    ).then(() => {
                        return frappe.model.set_value(
                            child.doctype,
                            child.name,
                            'warehouse',
                            warehouse
                        );
                    }).then(() => {
                        // Wait for ERPNext to fetch valuation_rate and current_qty
                        return new Promise(resolve => setTimeout(resolve, 300));
                    }).then(() => {
                        return frappe.model.set_value(
                            child.doctype,
                            child.name,
                            'qty',
                            item.qty
                        );
                    });
                }
            });
        });
    } else if (frm.doctype === 'Stock Entry') {
        // Stock Entry: item_code (triggers get_item_details) -> wait -> qty -> set warehouses
        let s_warehouse = frm.doc.from_warehouse || '';
        let t_warehouse = frm.doc.to_warehouse || '';

        selected_items.forEach(item => {
            chain = chain.then(() => {
                if (existing_items[item.item_code] && existing_items[item.item_code].length > 0) {
                    let existing_row = existing_items[item.item_code][0];
                    updated_count++;
                    return frappe.model.set_value(
                        existing_row.doctype,
                        existing_row.name,
                        'qty',
                        item.qty
                    );
                } else {
                    added_count++;
                    let child = frm.add_child('items');

                    return frappe.model.set_value(
                        child.doctype,
                        child.name,
                        'item_code',
                        item.item_code
                    ).then(() => {
                        // Wait for ERPNext get_item_details
                        return new Promise(resolve => setTimeout(resolve, 500));
                    }).then(() => {
                        return frappe.model.set_value(
                            child.doctype,
                            child.name,
                            'qty',
                            item.qty
                        );
                    }).then(() => {
                        // Set source warehouse
                        if (s_warehouse) {
                            return frappe.model.set_value(
                                child.doctype,
                                child.name,
                                's_warehouse',
                                s_warehouse
                            );
                        }
                    }).then(() => {
                        // Set target warehouse
                        if (t_warehouse) {
                            return frappe.model.set_value(
                                child.doctype,
                                child.name,
                                't_warehouse',
                                t_warehouse
                            );
                        }
                    });
                }
            });
        });
    } else {
        // Sales doctypes: item_code -> qty -> warehouse
        selected_items.forEach(item => {
            chain = chain.then(() => {
                if (existing_items[item.item_code] && existing_items[item.item_code].length > 0) {
                    let existing_row = existing_items[item.item_code][0];
                    updated_count++;
                    return frappe.model.set_value(
                        existing_row.doctype,
                        existing_row.name,
                        'qty',
                        item.qty
                    );
                } else {
                    added_count++;
                    let child = frm.add_child('items');

                    return frappe.model.set_value(
                        child.doctype,
                        child.name,
                        'item_code',
                        item.item_code
                    ).then(() => {
                        return frappe.model.set_value(
                            child.doctype,
                            child.name,
                            'qty',
                            item.qty
                        );
                    }).then(() => {
                        if (config.requires_warehouse && warehouse) {
                            return frappe.model.set_value(
                                child.doctype,
                                child.name,
                                'warehouse',
                                warehouse
                            );
                        }
                    });
                }
            });
        });
    }

    // Step 4: After all items are processed, refresh and show message
    chain.then(() => {
        // Refresh the items grid to update UI
        frm.refresh_field('items');

        // Show success message
        let messages = [];
        if (added_count > 0) {
            messages.push(__('Added {0} items', [added_count]));
        }
        if (updated_count > 0) {
            messages.push(__('Updated {0} items', [updated_count]));
        }

        if (messages.length > 0) {
            frappe.show_alert({
                message: messages.join(', '),
                indicator: 'green'
            }, 5);
        }
    }).catch(err => {
        console.error('Error adding items:', err);
        frappe.msgprint({
            title: __('Error'),
            message: __('Error adding some items. Please check the console for details.'),
            indicator: 'red'
        });
    });
}

function format_currency(value) {
    if (value === null || value === undefined || value === 0) return '\u2014';
    // Use native formatting to avoid recursion with frappe's formatter system
    let formatted = parseFloat(value).toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
    // Get currency symbol from frappe settings
    let currency = frappe.defaults.get_default('currency') || frappe.boot.sysdefaults.currency || '';
    return currency ? `${currency} ${formatted}` : formatted;
}

function format_number(value, format, decimals) {
    if (value === null || value === undefined) return '\u2014';
    // Use toFixed to avoid recursion with frappe's formatter system
    let precision = decimals || 2;
    return parseFloat(value).toLocaleString('en-US', {
        minimumFractionDigits: precision,
        maximumFractionDigits: precision
    });
}
