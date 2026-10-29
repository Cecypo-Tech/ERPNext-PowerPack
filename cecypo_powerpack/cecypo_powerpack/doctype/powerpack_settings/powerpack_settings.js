// Copyright (c) 2026, Cecypo.Tech and contributors
// For license information, please see license.txt

frappe.ui.form.on('PowerPack Settings', {
	setup: function(frm) {
		// Withholding posts to a ledger (tax liability) account, never a group or a party account.
		const wht_account = function () {
			return { filters: { is_group: 0, account_type: ['not in', ['Payable', 'Receivable']] } };
		};
		frm.set_query('account', 'withholding_rules', wht_account);
		// A Table MultiSelect has no grid: its control is itself the Link, so it takes a parent-style query.
		frm.set_query('withholding_vat_accounts', wht_account);
	},

	refresh: function(frm) {
		frm.set_intro(__('Configure PowerPack features and settings'));
		cecypo_check_min_price_conflict(frm);
		cecypo_add_load_group_buttons(frm);
		cecypo_refresh_min_price_grid(frm);
		cecypo_add_permission_manager_button(frm);
		cecypo_mark_dup_withholding_rules(frm);
		cecypo_add_naming_guide(frm);
	},

	min_selling_price_rules_add: function(frm) { cecypo_refresh_min_price_grid(frm); },
	min_selling_price_rules_remove: function(frm) { cecypo_refresh_min_price_grid(frm); },
	after_save: function(frm) { cecypo_refresh_min_price_grid(frm); },

	enable_min_selling_price: function(frm) {
		cecypo_check_min_price_conflict(frm);
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

function cecypo_add_permission_manager_button(frm) {
	// Reading the page is gated server-side on User Permission read; only System
	// Managers can change anything, so that is who gets the shortcut.
	if (!frappe.user.has_role('System Manager')) return;
	frm.add_custom_button(__('Permission Manager'), function () {
		frappe.set_route('powerpack-permissions');
	});
}

// Highlight withholding rules that share a non-blank item or supplier with another row.
function cecypo_mark_dup_withholding_rules(frm) {
	const grid = frm.fields_dict.withholding_rules && frm.fields_dict.withholding_rules.grid;
	if (!grid) return;
	const rows = frm.doc.withholding_rules || [];
	const count = function (f, v) { return rows.filter(function (r) { return r[f] === v; }).length; };
	// Grid rows are rebuilt after an edit, so mark once the redraw has happened.
	setTimeout(function () {
		(grid.grid_rows || []).forEach(function (gr) {
			const d = gr.doc || {};
			const dup = (d.item && count('item', d.item) > 1) || (d.supplier && count('supplier', d.supplier) > 1);
			gr.wrapper && $(gr.wrapper).toggleClass('pp-wht-dup', !!dup);
		});
	}, 0);
}

// Grid add/remove events fire on the child doctype (grid.js / grid_row.js), not on the parent.
frappe.ui.form.on('Withholding Rule', {
	withholding_rules_add: function(frm) { cecypo_mark_dup_withholding_rules(frm); },
	withholding_rules_remove: function(frm) { cecypo_mark_dup_withholding_rules(frm); },
	item: function(frm) { cecypo_mark_dup_withholding_rules(frm); },
	supplier: function(frm) { cecypo_mark_dup_withholding_rules(frm); },
});

// Document Naming: a short line plus a button that opens the placeholder table and setup steps.
function cecypo_add_naming_guide(frm) {
	const field = frm.fields_dict.branch_naming_description;
	if (!field) {
		return;
	}
	field.$wrapper.html(`
		<p class="text-muted">${__('Short company, branch and return codes in document names, e.g. AC/HQ/SI/00001.')}</p>
		<button class="btn btn-xs btn-default cecypo-naming-guide">
			${frappe.utils.icon('info', 'xs')} ${__('Naming guide')}
		</button>`);
	field.$wrapper.find('.cecypo-naming-guide').on('click', cecypo_show_naming_guide);
}

function cecypo_show_naming_guide() {
	const link = (doctype, label) => `<a href="/app/${frappe.router.slug(doctype)}" target="_blank">${label || __(doctype)}</a>`;
	const rows = (list) => list.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('');
	const placeholders = [
		['<code>.CO.</code>', __('Company code'), __('{0} → Naming Code (else Abbr)', [link('Company')]), 'AC'],
		['<code>.BR/.</code>', __('Branch code of the header warehouse (Set Warehouse). Stock Entry: source-target. Return: the original document\'s branch'), __('{0} → Naming Code', [link('Warehouse')]), 'HQ/ · HQ-TN/'],
		['<code>.SET/.</code>', __('Stock Entry Type code'), __('{0} → Naming Code', [link('Stock Entry Type')]), 'MT/'],
		['<code>.PAYDIR.</code>', __('Payment Entry direction'), __('Payment Type'), 'IN · OUT · TRF'],
		['<code>.RET/.</code>', __('RET on a return, DR on a Sales Invoice debit note'), __('Is Return / Is Debit Note'), 'RET/ · DR/'],
	];
	const examples = [
		[__('Sales Invoice'), '<code>.CO./.BR/.SI/.RET/.#####</code>', 'AC/HQ/SI/00001', 'AC/HQ/SI/RET/00001'],
		[__('Delivery Note'), '<code>.CO./.BR/.DN/.RET/.#####</code>', 'AC/HQ/DN/00001', 'AC/HQ/DN/RET/00001'],
		[__('Purchase Invoice'), '<code>.CO./.BR/.PI/.RET/.#####</code>', 'AC/HQ/PI/00001', 'AC/HQ/PI/RET/00001'],
		[__('Quotation'), '<code>.CO./.BR/.QT/.#####</code>', 'AC/HQ/QT/00001', __('No warehouse: {0}', ['AC/QT/00001'])],
		[__('Stock Entry'), '<code>.CO./.BR/.STK/.#####</code>', 'AC/HQ-TN/STK/00001', __('HQ to TN transfer')],
		[__('Payment Entry'), '<code>.CO.-PAY-.PAYDIR.-.#####</code>', 'AC-PAY-IN-00001', 'AC-PAY-OUT-00001'],
	];
	const table = (head, body) => `<table class="table table-bordered table-sm" style="font-size: var(--text-sm)">
		<thead><tr>${head.map((h) => `<th>${h}</th>`).join('')}</tr></thead><tbody>${rows(body)}</tbody></table>`;

	const d = new frappe.ui.Dialog({ title: __('Document Naming guide'), size: 'extra-large', fields: [{ fieldtype: 'HTML', fieldname: 'guide' }] });
	d.fields_dict.guide.$wrapper.html(`
		<h5>${__('Set up')}</h5>
		<ol>
			<li>${__('Tick <b>Enable Branch Naming Codes</b> and save. A <b>Naming Code</b> field is added to Company, Warehouse and Stock Entry Type.')}</li>
			<li>${__('Fill the Naming Code on each {0}, {1} and {2}, e.g. AC, HQ, MT.', [link('Company'), link('Warehouse'), link('Stock Entry Type')])}</li>
			<li>${__('Open {0}, pick the Transaction, put the series on the <b>first line</b> of the Series List (the first line is the default, also for POS) and click <b>Update Series List</b>.', [link('Document Naming Settings')])}</li>
		</ol>
		<h5>${__('Placeholders')}</h5>
		${table([__('Placeholder'), __('Gives'), __('Taken from'), __('Example')], placeholders)}
		<h5>${__('Example series')}</h5>
		${table([__('Document'), __('Series'), __('Gives'), __('Return / other')], examples)}
		<p class="text-muted small">
			${__('The separator written inside a placeholder (<code>.BR/.</code>, <code>.BR-.</code>, <code>.BR_.</code>) is left out when the code is blank, so a sale with no warehouse is AC/SI/00001.')}
			${__('Each prefix keeps its own counter. Only new documents are affected. A matching Document Naming Rule still wins over the series.')}
			${__('Once enabled, a series part that is exactly CO, BR, SET, PAYDIR or RET is read as a placeholder.')}
		</p>`);
	d.show();
}
