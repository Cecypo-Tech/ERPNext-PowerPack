// Copyright (c) 2024, Cecypo.Tech and contributors
// For license information, please see license.txt

frappe.provide('cecypo_powerpack.sales_powerup');

cecypo_powerpack.sales_powerup = {
	enabled: false,
	settings: {},

	// Helper function to check if feature is enabled for a specific doctype
	is_enabled_for_doctype: function(doctype) {
		const settings = cecypo_powerpack.sales_powerup.settings;
		const doctype_map = {
			'Quotation': 'enable_quotation_powerup',
			'Sales Order': 'enable_sales_order_powerup',
			'Sales Invoice': 'enable_sales_invoice_powerup',
			'POS Invoice': 'enable_pos_invoice_powerup'
		};
		const field_name = doctype_map[doctype];
		return field_name && settings[field_name] === 1;
	},

	check_and_setup: function(frm) {
		// Fetch settings first
		frappe.call({
			method: 'frappe.client.get',
			args: {
				doctype: 'PowerPack Settings',
				name: 'PowerPack Settings'
			},
			callback: function(r) {
				if (r.message) {
					cecypo_powerpack.sales_powerup.settings = r.message;
					cecypo_powerpack.sales_powerup.enabled = cecypo_powerpack.sales_powerup.is_enabled_for_doctype(frm.doctype);

					if (cecypo_powerpack.sales_powerup.enabled) {
						cecypo_powerpack.sales_powerup.setup_all_items(frm);
					}
				}
			}
		});
	},

	setup_all_items: function(frm) {
		if (!frm.doc.items || !frm.doc.items.length) {
			return;
		}

		// Check if PowerPack is enabled
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';

		if (!powerpack_enabled) {
			return;
		}

		// Process each item in the grid
		frm.doc.items.forEach(function(item) {
			if (item.item_code) {
				cecypo_powerpack.sales_powerup.add_item_info(frm, item);
			}
		});

		// Add profit metrics if user has the required role
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
		if (frappe.user.has_role(visible_role)) {
			cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
		}
	},

	add_item_info: function(frm, item_doc) {
		const item_code = item_doc.item_code;
		const customer = frm.doc.party_name || frm.doc.customer;
		// Quotation uses set_warehouse, other doctypes use item warehouse
		const warehouse = item_doc.warehouse || frm.doc.set_warehouse;
		const item_rate = item_doc.rate || 0;

		// Only show info when both customer and warehouse are present
		if (!customer || !warehouse) {
			return;
		}


		// Find the grid row for this item
		const grid_row = frm.fields_dict.items.grid.grid_rows_by_docname[item_doc.name];
		if (!grid_row || !grid_row.wrapper) {
			return;
		}


		// Remove existing info container first
		grid_row.wrapper.find('.sales-item-info').remove();

		// Create new info container
		const info_container = $('<div class="sales-item-info"></div>');

		// Try multiple insertion strategies
		let inserted = false;

		// Strategy 1: After form-in-grid (when row is expanded)
		const form_grid = grid_row.wrapper.find('.form-in-grid');
		if (form_grid.length > 0) {
			form_grid.after(info_container);
			inserted = true;
		}

		// Strategy 2: After grid-row
		if (!inserted) {
			const row_elem = grid_row.wrapper.find('.grid-row').first();
			if (row_elem.length > 0) {
				row_elem.after(info_container);
				inserted = true;
			}
		}

		// Strategy 3: Append to wrapper
		if (!inserted) {
			grid_row.wrapper.append(info_container);
			inserted = true;
		}

		if (!inserted) {
			return;
		}

		// Show loading state
		info_container.html('<div class="text-muted" style="padding: 5px 10px; font-size: 11px;">Loading item info...</div>');

		// Fetch item information
		frappe.call({
			method: 'cecypo_powerpack.api.get_item_info_for_quotation',
			args: {
				item_code: item_code,
				customer: customer,
				warehouse: warehouse
			},
			callback: function(r) {
				if (r.message) {
					cecypo_powerpack.sales_powerup.render_item_info(info_container, r.message, item_rate, item_doc);

					// Store valuation rate in the item doc for profit calculation.
					// Use direct locals assignment instead of frappe.model.set_value to avoid
					// marking the form as dirty (which would revert Submit back to Save).
					const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
					if (r.message.valuation_rate && frappe.user.has_role(visible_role)) {
						if (locals[item_doc.doctype] && locals[item_doc.doctype][item_doc.name]) {
							locals[item_doc.doctype][item_doc.name].valuation_rate = r.message.valuation_rate;
						}

						// Update profit metrics after setting valuation rate
						setTimeout(function() {
							cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
						}, 200);
					}
				} else {
					info_container.empty();
				}
			},
			error: function(err) {
				console.error('Error fetching item info:', err);
				info_container.empty();
			}
		});
	},

	add_powerup_button: function(frm) {
		// Remove existing button
		frm.page.remove_inner_button('PowerUp');

		// Get current state
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';

		// Add PowerUp button (standalone, not in a group)
		frm.add_custom_button(__('PowerUp'), function() {
			// Toggle the state
			powerpack_enabled = !powerpack_enabled;

			// Save state
			localStorage.setItem('powerpack_enabled', powerpack_enabled);

			// Apply changes immediately
			if (powerpack_enabled) {
				// Enable: Refresh to show all features
				cecypo_powerpack.sales_powerup.check_and_setup(frm);
				frappe.show_alert({
					message: __('PowerPack Enabled'),
					indicator: 'green'
				});
			} else {
				// Disable: Hide all features
				$('.sales-item-info').remove();
				$('.profit-metrics-section').remove();
				frappe.show_alert({
					message: __('PowerPack Disabled'),
					indicator: 'orange'
				});
			}

			// Update button appearance
			cecypo_powerpack.sales_powerup.update_button_state(frm, powerpack_enabled);
		});

		// Set initial button state
		cecypo_powerpack.sales_powerup.update_button_state(frm, powerpack_enabled);
	},

	update_button_state: function(frm, enabled) {
		// Find the PowerUp button and update its appearance
		const button = frm.page.btn_secondary.find('.btn:contains("PowerUp")');
		if (button.length > 0) {
			if (enabled) {
				button.removeClass('btn-default').addClass('btn-primary');
				button.attr('title', 'Click to disable PowerPack features');
			} else {
				button.removeClass('btn-primary').addClass('btn-default');
				button.attr('title', 'Click to enable PowerPack features');
			}
		}
	},

	render_item_info: function(container, data, item_rate, item_doc) {
		let html_parts = [];

		// Check if user has the required role
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
		const has_permission = frappe.user.has_role(visible_role);

		// Get visibility settings
		const settings = cecypo_powerpack.sales_powerup.settings;
		const show_stock = settings.show_stock_info !== 0; // Default true
		const show_valuation = settings.show_valuation_rate !== 0; // Default true
		const show_profit = settings.show_profit_indicator !== 0; // Default true
		const show_last_purchase = settings.show_last_purchase !== 0; // Default true
		const show_last_sale = settings.show_last_sale !== 0; // Default true
		const show_last_sale_customer = settings.show_last_sale_to_customer !== 0; // Default true

		// Use shared profit calculator for consistent calculations
		const profit_calc = cecypo_powerpack.profit_calculator;
		const tax_inclusive = profit_calc.is_tax_inclusive(cur_frm);
		const item_tax_rate = profit_calc.calculate_item_tax_rate(item_doc.rate, item_doc.net_rate);

		// Helper function to format currency without symbol
		// If tax-inclusive, add tax to the value for display
		const format_amount = (value, add_tax = false) => {
			let display_value = value;
			if (add_tax && tax_inclusive && item_tax_rate > 0) {
				display_value = value * (1 + item_tax_rate);
			}
			return frappe.format(display_value, {fieldtype: 'Float', precision: 2});
		};

		// Helper function to format date as DD-MMM-YY
		const format_short_date = (date) => {
			return moment(date).format('DD-MMM-YY');
		};

		// Helper function to get profit indicator based on margin
		const get_profit_indicator = (margin) => {
			let profit_class, profit_label;

			if (margin < 0) {
				profit_class = 'profit-loss';
				profit_label = 'Loss';
			} else if (margin < 10) {
				profit_class = 'profit-low';
				profit_label = 'Low';
			} else if (margin < 20) {
				profit_class = 'profit-medium';
				profit_label = 'Med';
			} else if (margin < 30) {
				profit_class = 'profit-good';
				profit_label = 'Good';
			} else {
				profit_class = 'profit-excellent';
				profit_label = 'Excel';
			}

			return `<span class="item-profit-indicator ${profit_class}" title="Profit Margin: ${margin.toFixed(1)}%">
						<span class="profit-dot"></span>
						${margin.toFixed(1)}%
					</span>`;
		};

		// Stock information (detailed breakdown)
		if (show_stock && data.actual_qty !== null && data.actual_qty !== undefined) {
			let stock_parts = [];

			// Physical stock
			stock_parts.push(`Phy: ${frappe.format(data.actual_qty, {fieldtype: 'Float', precision: 0})}`);

			// Reserved stock
			if (data.reserved_qty && data.reserved_qty > 0) {
				stock_parts.push(`Res: ${frappe.format(data.reserved_qty, {fieldtype: 'Float', precision: 0})}`);
			}

			// Available stock
			if (data.available_qty !== null && data.available_qty !== undefined) {
				stock_parts.push(`Avl: ${frappe.format(data.available_qty, {fieldtype: 'Float', precision: 0})}`);
			}

			html_parts.push(`<span class="info-item"><strong>Stock:</strong> ${stock_parts.join('&nbsp;&bull;&nbsp;')}</span>`);
		}

		// Valuation rate (with permission check)
		// Show with tax if tax-inclusive to make it comparable to item rate
		if (has_permission && show_valuation && data.valuation_rate !== null && data.valuation_rate !== undefined) {
			const value_text = format_amount(data.valuation_rate, true);
			const tax_label = !tax_inclusive && item_tax_rate > 0 ? '+' : '';
			html_parts.push(`<span class="info-item"><strong>Value:</strong> ${value_text}${tax_label}</span>`);
		}

		// Last purchase (with permission check)
		// Show with tax if tax-inclusive to make it comparable to item rate
		if (has_permission && show_last_purchase && data.last_purchase_rate !== null && data.last_purchase_rate !== undefined) {
			let purchase_text = format_amount(data.last_purchase_rate, true);
			if (data.last_purchase_date) {
				purchase_text += ` (${format_short_date(data.last_purchase_date)})`;
			}
			const tax_label = !tax_inclusive && item_tax_rate > 0 ? '+' : '';
			html_parts.push(`<span class="info-item"><strong>Last Purchase:</strong> ${purchase_text}${tax_label}</span>`);
		}

		// Last sale to anyone
		// Show with tax if tax-inclusive to make it comparable to item rate
		if (show_last_sale && data.last_sale_rate !== null && data.last_sale_rate !== undefined) {
			let last_sale_text = format_amount(data.last_sale_rate, true);
			if (data.last_sale_date) {
				last_sale_text += ` (${format_short_date(data.last_sale_date)})`;
			}
			const tax_label = !tax_inclusive && item_tax_rate > 0 ? '+' : '';
			html_parts.push(`<span class="info-item"><strong>Last Sale:</strong> ${last_sale_text}${tax_label}</span>`);
		}

		// Last sale to this customer
		// Show with tax if tax-inclusive to make it comparable to item rate
		if (show_last_sale_customer && data.last_sale_to_customer_rate !== null && data.last_sale_to_customer_rate !== undefined) {
			let customer_sale_text = format_amount(data.last_sale_to_customer_rate, true);
			if (data.last_sale_to_customer_date) {
				customer_sale_text += ` (${format_short_date(data.last_sale_to_customer_date)})`;
			}
			const tax_label = !tax_inclusive && item_tax_rate > 0 ? '+' : '';
			html_parts.push(`<span class="info-item"><strong>Last Sold to Customer:</strong> ${customer_sale_text}${tax_label}</span>`);
		}

		// Calculate profit indicator separately (positioned on far right via CSS)
		let profit_indicator_html = '';
		if (has_permission && show_profit && data.valuation_rate !== null && data.valuation_rate !== undefined) {
			// Use shared profit calculator for consistent calculations
			const profit_result = profit_calc.calculate_item_profit({
				rate: item_rate || 0,
				net_rate: item_doc.net_rate || item_rate || 0,
				valuation_rate: data.valuation_rate || 0,
				qty: 1,
				tax_inclusive: tax_inclusive
			});
			profit_indicator_html = get_profit_indicator(profit_result.margin);
		}

		// Render the info if we have any data
		if (html_parts.length > 0 || profit_indicator_html) {
			const html = `<div class="sales-item-details" data-item-name="${item_doc.name}">${html_parts.join('')}${profit_indicator_html}</div>`;
			container.html(html);
		} else {
			container.html('');
		}
	},

	update_profit_indicator: function(frm, item_doc) {
		// Update profit indicator dynamically when rate changes
		const settings = cecypo_powerpack.sales_powerup.settings;
		const visible_role = settings.sales_visible_to_role || 'System Manager';
		const has_permission = frappe.user.has_role(visible_role);
		const show_profit = settings.show_profit_indicator !== 0;

		if (!has_permission || !show_profit || !item_doc.valuation_rate) {
			return;
		}

		// Find the profit indicator element for this item
		const info_container = $(`.sales-item-details[data-item-name="${item_doc.name}"]`);
		if (info_container.length === 0) {
			return;
		}

		// Use shared profit calculator for consistent calculations
		const profit_calc = cecypo_powerpack.profit_calculator;
		const tax_inclusive = profit_calc.is_tax_inclusive(frm);

		// Calculate new profit margin using shared calculator
		const profit_result = profit_calc.calculate_item_profit({
			rate: item_doc.rate || 0,
			net_rate: item_doc.net_rate || item_doc.rate || 0,
			valuation_rate: item_doc.valuation_rate || 0,
			qty: 1,
			tax_inclusive: tax_inclusive
		});
		const profit_margin = profit_result.margin;

		// Determine profit class
		let profit_class, profit_label;
		if (profit_margin < 0) {
			profit_class = 'profit-loss';
			profit_label = 'Loss';
		} else if (profit_margin < 10) {
			profit_class = 'profit-low';
			profit_label = 'Low';
		} else if (profit_margin < 20) {
			profit_class = 'profit-medium';
			profit_label = 'Med';
		} else if (profit_margin < 30) {
			profit_class = 'profit-good';
			profit_label = 'Good';
		} else {
			profit_class = 'profit-excellent';
			profit_label = 'Excel';
		}

		// Update the indicator
		const indicator_html = `<span class="item-profit-indicator ${profit_class}" title="Profit Margin: ${profit_margin.toFixed(1)}%">
									<span class="profit-dot"></span>
									${profit_margin.toFixed(1)}%
								</span>`;

		// Remove old indicator and add new one
		info_container.find('.item-profit-indicator').remove();
		info_container.append(indicator_html);
	},

	add_profit_metrics: function(frm) {
		// Remove existing profit metrics
		$('.profit-metrics-section').remove();
		frm.fields_dict.items.$wrapper.find('.clearfix').removeClass('profit-positive-bg profit-negative-bg');

		if (!frm.doc.items || !frm.doc.items.length) {
			return;
		}

		// Use shared profit calculator for consistent calculations
		const profit_calc = cecypo_powerpack.profit_calculator;
		const metrics = profit_calc.calculate_doc_profit(frm, frm.doc.items);

		const {
			total_cost,
			net_total,
			grand_total,
			total_taxes,
			profit,
			margin,
			tax_inclusive
		} = metrics;

		// Count items with cost for display purposes
		let items_with_cost = 0;
		frm.doc.items.forEach(function(item) {
			if (item.valuation_rate && item.valuation_rate > 0) {
				items_with_cost++;
			}
		});

		// Format values without currency symbols
		const format_amt = (val) => frappe.format(val, {fieldtype: 'Float', precision: 2});

		// Calculate cost with tax for display (when tax_inclusive)
		const doc_tax_rate = total_taxes > 0 && net_total > 0 ? total_taxes / net_total : 0;
		const display_cost = tax_inclusive && doc_tax_rate > 0 ? total_cost * (1 + doc_tax_rate) : total_cost;

		// Determine profit class
		let profit_class = '';
		if (items_with_cost > 0) {
			profit_class = profit >= 0 ? 'profit-positive-bg' : 'profit-negative-bg';
		}

		// Create profit metrics section based on tax setting
		let metrics_html;
		if (tax_inclusive && total_taxes > 0) {
			// Show tax-inclusive amounts (what customer sees)
			metrics_html = `
				<div class="profit-metrics-section ${profit_class}">
					<span class="metric-mini">Cost: ${format_amt(display_cost)} <span class="tax-info">(incl. tax)</span></span>
					<span class="metric-mini">Sale: ${format_amt(grand_total)} <span class="tax-info">(incl. tax)</span></span>
					<span class="metric-mini tax-info">Tax: ${format_amt(total_taxes)}</span>
					<span class="metric-mini metric-highlight">Profit: ${format_amt(profit)}</span>
					<span class="metric-mini">Margin: ${margin.toFixed(1)}%</span>
				</div>
			`;
		} else {
			// Show tax-exclusive amounts
			metrics_html = `
				<div class="profit-metrics-section ${profit_class}">
					<span class="metric-mini">Cost: ${format_amt(display_cost)}</span>
					<span class="metric-mini">Sale: ${format_amt(net_total)}</span>
					${total_taxes > 0 ? `<span class="metric-mini tax-info">+Tax: ${format_amt(total_taxes)}</span>` : ''}
					<span class="metric-mini metric-highlight">Profit: ${format_amt(profit)}</span>
					<span class="metric-mini">Margin: ${margin.toFixed(1)}%</span>
				</div>
			`;
		}

		// Try multiple approaches to find the right place
		const wrapper = frm.fields_dict.items.$wrapper;

		// Approach 1: Find the clearfix div that contains the label
		let label_container = wrapper.find('.clearfix').first();

		if (label_container.length > 0) {
			// Insert at the end of the label container
			label_container.append(metrics_html);
		} else {
			// Approach 2: Insert before the grid
			const grid_wrapper = frm.fields_dict.items.grid.wrapper;
			grid_wrapper.before(metrics_html);
		}
	}
};

// Hook into Quotation form
frappe.ui.form.on('Quotation', {
	refresh: function(frm) {
		// Add PowerUp button for System Managers
		if (frappe.user.has_role('System Manager')) {
			cecypo_powerpack.sales_powerup.add_powerup_button(frm);
		}

		// Small delay to ensure grid is fully rendered
		setTimeout(function() {
			cecypo_powerpack.sales_powerup.check_and_setup(frm);
		}, 500);
	},

	onload: function(frm) {
		setTimeout(function() {
			cecypo_powerpack.sales_powerup.check_and_setup(frm);
		}, 500);
	},

	// Update profit metrics when taxes change
	total_taxes_and_charges: function(frm) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';

		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled && frappe.user.has_role(visible_role)) {
			setTimeout(function() {
				cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
			}, 300);
		}
	},

	grand_total: function(frm) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';

		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled && frappe.user.has_role(visible_role)) {
			setTimeout(function() {
				cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
			}, 300);
		}
	}
});

// Also trigger when items are added or changed
frappe.ui.form.on('Quotation Item', {
	item_code: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
			setTimeout(function() {
				cecypo_powerpack.sales_powerup.add_item_info(frm, item);
				// Update profit metrics
				if (frappe.user.has_role(visible_role)) {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}
			}, 500);
		}
	},

	items_add: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
			setTimeout(function() {
				if (item.item_code) {
					cecypo_powerpack.sales_powerup.add_item_info(frm, item);
				}
				// Update profit metrics
				if (frappe.user.has_role(visible_role)) {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}
			}, 500);
		}
	},

	items_remove: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
			setTimeout(function() {
				// Update profit metrics after removal
				if (frappe.user.has_role(visible_role)) {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}
			}, 500);
		}
	},

	warehouse: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
			setTimeout(function() {
				if (item.item_code) {
					cecypo_powerpack.sales_powerup.add_item_info(frm, item);
				}
				// Update profit metrics
				if (frappe.user.has_role(visible_role)) {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}
			}, 500);
		}
	},

	qty: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';

		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled && frappe.user.has_role(visible_role)) {
			setTimeout(function() {
				cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
			}, 300);
		}
	},

	rate: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';

		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];

			// Update profit indicator for this specific item
			cecypo_powerpack.sales_powerup.update_profit_indicator(frm, item);

			// Update overall profit metrics if user has permission
			if (frappe.user.has_role(visible_role)) {
				setTimeout(function() {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}, 300);
			}
		}
	}
});

// Hook into Sales Order form
frappe.ui.form.on('Sales Order', {
	refresh: function(frm) {
		if (frappe.user.has_role('System Manager')) {
			cecypo_powerpack.sales_powerup.add_powerup_button(frm);
		}
		setTimeout(function() {
			cecypo_powerpack.sales_powerup.check_and_setup(frm);
		}, 500);
	},
	onload: function(frm) {
		setTimeout(function() {
			cecypo_powerpack.sales_powerup.check_and_setup(frm);
		}, 500);
	},
	total_taxes_and_charges: function(frm) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled && frappe.user.has_role(visible_role)) {
			setTimeout(function() {
				cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
			}, 300);
		}
	},
	grand_total: function(frm) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled && frappe.user.has_role(visible_role)) {
			setTimeout(function() {
				cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
			}, 300);
		}
	}
});

frappe.ui.form.on('Sales Order Item', {
	item_code: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
			setTimeout(function() {
				cecypo_powerpack.sales_powerup.add_item_info(frm, item);
				if (frappe.user.has_role(visible_role)) {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}
			}, 500);
		}
	},
	items_add: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
			setTimeout(function() {
				if (item.item_code) {
					cecypo_powerpack.sales_powerup.add_item_info(frm, item);
				}
				if (frappe.user.has_role(visible_role)) {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}
			}, 500);
		}
	},
	items_remove: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
			setTimeout(function() {
				if (frappe.user.has_role(visible_role)) {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}
			}, 500);
		}
	},
	warehouse: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
			setTimeout(function() {
				if (item.item_code) {
					cecypo_powerpack.sales_powerup.add_item_info(frm, item);
				}
				if (frappe.user.has_role(visible_role)) {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}
			}, 500);
		}
	},
	qty: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled && frappe.user.has_role(visible_role)) {
			setTimeout(function() {
				cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
			}, 300);
		}
	},
	rate: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			cecypo_powerpack.sales_powerup.update_profit_indicator(frm, item);
			if (frappe.user.has_role(visible_role)) {
				setTimeout(function() {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}, 300);
			}
		}
	}
});

// Hook into Sales Invoice form
frappe.ui.form.on('Sales Invoice', {
	refresh: function(frm) {
		if (frappe.user.has_role('System Manager')) {
			cecypo_powerpack.sales_powerup.add_powerup_button(frm);
		}
		setTimeout(function() {
			cecypo_powerpack.sales_powerup.check_and_setup(frm);
		}, 500);
	},
	onload: function(frm) {
		setTimeout(function() {
			cecypo_powerpack.sales_powerup.check_and_setup(frm);
		}, 500);
	},
	total_taxes_and_charges: function(frm) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled && frappe.user.has_role(visible_role)) {
			setTimeout(function() {
				cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
			}, 300);
		}
	},
	grand_total: function(frm) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled && frappe.user.has_role(visible_role)) {
			setTimeout(function() {
				cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
			}, 300);
		}
	}
});

frappe.ui.form.on('Sales Invoice Item', {
	item_code: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
			setTimeout(function() {
				cecypo_powerpack.sales_powerup.add_item_info(frm, item);
				if (frappe.user.has_role(visible_role)) {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}
			}, 500);
		}
	},
	items_add: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
			setTimeout(function() {
				if (item.item_code) {
					cecypo_powerpack.sales_powerup.add_item_info(frm, item);
				}
				if (frappe.user.has_role(visible_role)) {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}
			}, 500);
		}
	},
	items_remove: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
			setTimeout(function() {
				if (frappe.user.has_role(visible_role)) {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}
			}, 500);
		}
	},
	warehouse: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
			setTimeout(function() {
				if (item.item_code) {
					cecypo_powerpack.sales_powerup.add_item_info(frm, item);
				}
				if (frappe.user.has_role(visible_role)) {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}
			}, 500);
		}
	},
	qty: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled && frappe.user.has_role(visible_role)) {
			setTimeout(function() {
				cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
			}, 300);
		}
	},
	rate: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			cecypo_powerpack.sales_powerup.update_profit_indicator(frm, item);
			if (frappe.user.has_role(visible_role)) {
				setTimeout(function() {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}, 300);
			}
		}
	}
});

// Hook into POS Invoice form
frappe.ui.form.on('POS Invoice', {
	refresh: function(frm) {
		if (frappe.user.has_role('System Manager')) {
			cecypo_powerpack.sales_powerup.add_powerup_button(frm);
		}
		setTimeout(function() {
			cecypo_powerpack.sales_powerup.check_and_setup(frm);
		}, 500);
	},
	onload: function(frm) {
		setTimeout(function() {
			cecypo_powerpack.sales_powerup.check_and_setup(frm);
		}, 500);
	},
	total_taxes_and_charges: function(frm) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled && frappe.user.has_role(visible_role)) {
			setTimeout(function() {
				cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
			}, 300);
		}
	},
	grand_total: function(frm) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled && frappe.user.has_role(visible_role)) {
			setTimeout(function() {
				cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
			}, 300);
		}
	}
});

frappe.ui.form.on('POS Invoice Item', {
	item_code: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
			setTimeout(function() {
				cecypo_powerpack.sales_powerup.add_item_info(frm, item);
				if (frappe.user.has_role(visible_role)) {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}
			}, 500);
		}
	},
	items_add: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
			setTimeout(function() {
				if (item.item_code) {
					cecypo_powerpack.sales_powerup.add_item_info(frm, item);
				}
				if (frappe.user.has_role(visible_role)) {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}
			}, 500);
		}
	},
	items_remove: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
			setTimeout(function() {
				if (frappe.user.has_role(visible_role)) {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}
			}, 500);
		}
	},
	warehouse: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
			setTimeout(function() {
				if (item.item_code) {
					cecypo_powerpack.sales_powerup.add_item_info(frm, item);
				}
				if (frappe.user.has_role(visible_role)) {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}
			}, 500);
		}
	},
	qty: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled && frappe.user.has_role(visible_role)) {
			setTimeout(function() {
				cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
			}, 300);
		}
	},
	rate: function(frm, cdt, cdn) {
		let powerpack_enabled = localStorage.getItem('powerpack_enabled') !== 'false';
		const visible_role = cecypo_powerpack.sales_powerup.settings.sales_visible_to_role || 'System Manager';
		if (cecypo_powerpack.sales_powerup.enabled && powerpack_enabled) {
			const item = locals[cdt][cdn];
			cecypo_powerpack.sales_powerup.update_profit_indicator(frm, item);
			if (frappe.user.has_role(visible_role)) {
				setTimeout(function() {
					cecypo_powerpack.sales_powerup.add_profit_metrics(frm);
				}, 300);
			}
		}
	}
});
