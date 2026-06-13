// Copyright (c) 2026, Cecypo.Tech and contributors
// For license information, please see license.txt

frappe.ui.form.on('PowerPack Settings', {
	refresh: function(frm) {
		frm.set_intro(__('Configure PowerPack features and settings'));
		cecypo_check_min_price_conflict(frm);
		cecypo_add_load_group_buttons(frm);
		cecypo_refresh_min_price_grid(frm);
	},

	min_selling_price_rules_add: function(frm) { cecypo_refresh_min_price_grid(frm); },
	min_selling_price_rules_remove: function(frm) { cecypo_refresh_min_price_grid(frm); },
	after_save: function(frm) { cecypo_refresh_min_price_grid(frm); },

	enable_min_selling_price: function(frm) {
		cecypo_check_min_price_conflict(frm);
	},

	enable_pos_powerup: function(frm) {
		if (frm.doc.enable_pos_powerup) {
			frappe.show_alert({ message: __('Point of Sale Powerup has been enabled'), indicator: 'green' });
		}
	},

	enable_quotation_powerup: function(frm) {
		if (frm.doc.enable_quotation_powerup) {
			frappe.show_alert({ message: __('Quotation Powerup has been enabled'), indicator: 'green' });
		}
	}
});

function cecypo_check_min_price_conflict(frm) {
	if (!frm.doc.enable_min_selling_price) {
		frm.dashboard.clear_comment();
		return;
	}
	frappe.db.get_single_value('Selling Settings', 'validate_selling_price').then(function (val) {
		frm.dashboard.clear_comment();
		if (cint(val)) {
			frm.dashboard.add_comment(
				__('Conflict: Selling Settings → "Validate Selling Price for Item" is ON. It hard-blocks any sale below cost and overrides negative (rebate) floors. Turn it OFF to let PowerPack be the single authority.'),
				'yellow',
				true
			);
		}
	});
}

function cecypo_add_load_group_buttons(frm) {
	const field = frm.fields_dict.min_selling_price_rules;
	if (!field || !field.grid) {
		return;
	}
	field.grid.add_custom_button(__('Load Leaf Item Groups'), function () {
		cecypo_load_item_groups(frm, 0);
	});
	field.grid.add_custom_button(__('Load Parent Item Groups'), function () {
		cecypo_load_item_groups(frm, 1);
	});
}

function cecypo_refresh_min_price_grid(frm) {
	if (!(frm.doc.min_selling_price_rules || []).length) return;

	frappe.call({
		method: 'cecypo_powerpack.api.get_item_group_tree_for_rules',
		callback: function(r) {
			const all_groups = r.message || [];
			const lft_map = {}, depth_map = {};
			all_groups.forEach(function(g) {
				lft_map[g.name] = g.lft;
				depth_map[g.name] = g.depth || 0;
			});

			const grid = frm.fields_dict.min_selling_price_rules && frm.fields_dict.min_selling_price_rules.grid;
			if (!grid) return;
			frm.doc.min_selling_price_rules.sort(function(a, b) {
				return (lft_map[a.item_group] || 0) - (lft_map[b.item_group] || 0);
			});
			grid.refresh();
			cecypo_indent_min_price_grid(grid, frm.doc.min_selling_price_rules, depth_map);
		}
	});
}

function cecypo_indent_min_price_grid(grid, doc_rows, depth_map) {
	if (!grid || !grid.grid_rows) return;
	grid.grid_rows.forEach(function(grid_row, i) {
		const doc_row = doc_rows[i];
		if (!doc_row) return;
		const depth = depth_map[doc_row.item_group] || 0;
		const $row = grid_row.row;
		if (!$row || !$row.length) return;
		const icon = depth === 0 ? 'fa-sitemap' : (depth === 1 ? 'fa-folder-o' : 'fa-tag');
		// The first .static-area in the row corresponds to the item_group column.
		const $area = $row.find('.static-area').first();
		if (!$area.length) return;
		$area.css('padding-left', (depth * 14 + 4) + 'px');
		if (!$area.find('.msp-grid-icon').length) {
			$area.prepend('<i class="fa ' + icon + ' msp-grid-icon"></i>');
		}
	});
}

function cecypo_load_item_groups(frm, is_group) {
	const existing = new Set((frm.doc.min_selling_price_rules || []).map(function (r) {
		return r.item_group;
	}));
	const default_basis = frm.doc.min_selling_price_default_basis || 'Valuation Rate';

	frappe.db.get_list('Item Group', {
		filters: { is_group: is_group },
		fields: ['name'],
		order_by: 'name asc',
		limit: 0
	}).then(function (groups) {
		let added = 0;
		(groups || []).forEach(function (g) {
			if (existing.has(g.name)) {
				return;
			}
			frm.add_child('min_selling_price_rules', {
				item_group: g.name,
				basis: default_basis,
				floor_percent: 0
			});
			existing.add(g.name);
			added += 1;
		});
		frm.refresh_field('min_selling_price_rules');
		if (added) {
			frm.dirty();
			frappe.show_alert({
				message: __('Added {0} item group(s) at 0% (inert). Review and save.', [added]),
				indicator: 'green'
			}, 7);
		} else {
			frappe.show_alert({ message: __('No new item groups to add.'), indicator: 'blue' });
		}
	});
}
