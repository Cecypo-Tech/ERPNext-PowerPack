// cecypo_powerpack/cecypo_powerpack/page/powerpack_permissions/powerpack_permissions.js
// Copyright (c) 2026, Cecypo.Tech and contributors
// For license information, please see license.txt

/**
 * PowerPack Permission Manager.
 *
 * Every role permission rule on the site in one virtualized table. Nothing is written
 * until Commit, which sends the whole change set to
 * cecypo_powerpack.permission_manager.commit_changes in one round trip.
 *
 * This file is loaded by frappe's page loader, not by the app bundle, so it is a
 * classic script: top-level names here ARE global. Keep everything on the class.
 */

frappe.pages["powerpack-permissions"].on_page_load = (wrapper) => {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("PowerPack Permission Manager"),
		single_column: true,
	});
	frappe.breadcrumbs.add("Setup");
	wrapper.permission_manager = new frappe.PowerPackPermissionManager(wrapper, page);
};

frappe.PowerPackPermissionManager = class PowerPackPermissionManager {
	constructor(wrapper, page) {
		this.wrapper = wrapper;
		this.page = page;
		this.$body = $('<div class="pp-perm"></div>').appendTo(this.page.main);

		// key -> {flag: new value}; only flags that differ from the loaded value
		this.dirty = {};
		this.filters = {};

		this.load();
	}

	// Editable flags, in display order. submit/cancel/amend are blanked for
	// non-submittable doctypes in render_flag.
	static get FLAGS() {
		return [
			"select", "read", "write", "create", "delete",
			"submit", "cancel", "amend",
			"print", "email", "report", "import", "export", "share", "mask",
		];
	}
	static get SUBMIT_FLAGS() { return ["submit", "cancel", "amend"]; }

	key_of(row) {
		// JSON, not concatenation: "Foo Bar"+"Baz" would collide with "Foo"+"Bar Baz", and
		// an invisible control-character delimiter gets stripped by copy paths and HTML
		// parsing. JSON is unambiguous and round-trips through a data- attribute.
		return JSON.stringify([row.doctype, row.role, row.permlevel, row.if_owner]);
	}

	load() {
		this.$body.html(`<div class="pp-perm-empty">${__("Loading permission rules…")}</div>`);
		frappe.call({
			method: "cecypo_powerpack.permission_manager.get_permission_rules",
			callback: (r) => {
				this.rows = r.message.rows;
				this.can_edit = r.message.can_edit;
				this.by_key = {};
				this.rows.forEach((row) => {
					row.key = this.key_of(row);
					this.by_key[row.key] = row;
				});
				this.dirty = {};
				this.render();
			},
			error: () => {
				// The server already showed its permission message; leave a stub, not a spinner.
				this.$body.html(`<div class="pp-perm-empty">${__("You do not have access to permission rules.")}</div>`);
			},
		});
	}

	render() {
		this.$body.empty();
		this.make_filters();
		this.$table = $('<div class="pp-perm-table"></div>').appendTo(this.$body);
		this.make_table();
		this.apply_filters();
	}

	// ── filters ────────────────────────────────────────────────────────────────

	make_filters() {
		this.$filters = $('<div class="pp-perm-filters"></div>').appendTo(this.$body);
		const add = (df) => {
			const field = frappe.ui.form.make_control({ df, parent: this.$filters, render_input: true });
			field.$wrapper.addClass("pp-filter");
			field.df.change = () => {
				this.filters[df.fieldname] = field.get_value();
				this.apply_filters();
			};
			return field;
		};
		add({ fieldtype: "Link", fieldname: "module", label: __("Module"), options: "Module Def" });
		add({ fieldtype: "Link", fieldname: "doctype", label: __("Document Type"), options: "DocType" });
		add({ fieldtype: "Link", fieldname: "role", label: __("Role"), options: "Role" });
		add({ fieldtype: "Data", fieldname: "search", label: __("Search") });
		add({ fieldtype: "Check", fieldname: "modified_only", label: __("Modified only") });
	}

	apply_filters() {
		const f = this.filters;
		const q = (f.search || "").toLowerCase();
		this.view = this.rows.filter((row) => {
			if (f.module && row.module !== f.module) return false;
			if (f.doctype && row.doctype !== f.doctype) return false;
			if (f.role && row.role !== f.role) return false;
			if (f.modified_only && !this.dirty[row.key]) return false;
			if (q && !(`${row.doctype} ${row.role} ${row.module}`.toLowerCase().includes(q))) return false;
			return true;
		});
		this.datatable.refresh(this.view, this.columns);
		this.page.set_indicator(__("{0} rules", [this.view.length]), "blue");
	}

	// ── table ──────────────────────────────────────────────────────────────────

	make_table() {
		const text = (id, name, width) => ({
			id, name, width, editable: false, dropdown: false, resizable: true,
			format: (value) => frappe.utils.escape_html(String(value ?? "")),
		});
		const flag = (id) => ({
			id, name: __(frappe.unscrub(id)).slice(0, 3), width: 44, align: "center",
			editable: false, dropdown: false, sortable: true,
			format: (value, row, column, data) => this.render_flag(data, id),
		});

		this.columns = [
			text("module", __("Module"), 130),
			text("doctype", __("Document Type"), 200),
			text("role", __("Role"), 150),
			{ id: "permlevel", name: __("Lvl"), width: 44, align: "center", editable: false, dropdown: false },
			{
				id: "if_owner", name: __("Own"), width: 44, align: "center", editable: false, dropdown: false,
				format: (v) => (v ? "✓" : ""),
			},
			...this.constructor.FLAGS.map(flag),
		];

		this.datatable = new frappe.DataTable(this.$table[0], {
			columns: this.columns,
			data: [],
			checkboxColumn: this.can_edit,
			inlineFilters: false,
			cellHeight: 28,
			noDataMessage: __("No permission rules match"),
			events: { onCheckRow: () => this.update_footer() },
		});

		// Flag checkboxes are plain HTML inside datatable cells; delegate their clicks.
		this.$table.on("change", "input.pp-flag", (e) => {
			const $cb = $(e.currentTarget);
			// Raw attribute, not $cb.data("key"): jQuery auto-parses a JSON-looking
			// data-key string into an array, and by_key[array] stringifies it back via
			// Array.toString() (comma-joined, unquoted) which no longer matches the
			// JSON.stringify key used to build by_key.
			const key = e.currentTarget.getAttribute("data-key");
			this.set_flag(this.by_key[key], $cb.data("flag"), $cb.prop("checked") ? 1 : 0);
		});
	}

	render_flag(row, flag) {
		if (this.constructor.SUBMIT_FLAGS.includes(flag) && !row.is_submittable) {
			return '<span class="pp-flag-na">·</span>';
		}
		const value = row[flag] ? 1 : 0;
		const dirty = this.dirty[row.key] && flag in this.dirty[row.key];
		const cls = `pp-flag${dirty ? " pp-dirty" : ""}`;
		if (!this.can_edit) {
			return `<span class="${cls}">${value ? "✓" : ""}</span>`;
		}
		return `<input type="checkbox" class="${cls}" data-key="${frappe.utils.escape_html(row.key)}" data-flag="${flag}"${value ? " checked" : ""}>`;
	}

	refresh_row(row) {
		const index = this.view.indexOf(row);
		if (index < 0) return;
		// refreshRow wants an ARRAY of cell values (DataManager.updateRow -> prepareRow
		// calls row.map), not the row object. The object is still what format() sees:
		// the datatable keeps our objects in data[] untouched and we mutate them in place.
		this.datatable.refreshRow(this.columns.map((c) => row[c.id]), index);
	}

	// Filled in by Task 6.
	set_flag() {}
	update_footer() {}
};
