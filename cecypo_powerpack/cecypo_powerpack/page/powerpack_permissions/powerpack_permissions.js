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
				this.original = {};
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
		this.make_footer();
		this.apply_filters();
		this.update_footer();
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
		// The datatable keeps its checkbox map across refresh(), so a selection made under
		// one filter would silently apply to whatever rows occupy those indexes under the
		// next. A filter change always drops the selection.
		if (this.datatable.rowmanager) this.datatable.rowmanager.checkAll(false);
		this.datatable.refresh(this.view, this.columns);
		this.page.set_indicator(__("{0} rules", [this.view.length]), "blue");
		this.update_footer();
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
			{
				...text("doctype", __("Document Type"), 200),
				// Editing a standard (not-yet-custom) row detaches its doctype from app
				// permission updates on commit; mark it so that detachment risk is
				// visible in the grid.
				format: (value, row, column, data) => {
					const name = frappe.utils.escape_html(String(value ?? ""));
					return data.is_custom
						? name
						: `<span class="pp-standard" title="${__(
								"Standard rule — editing it detaches this doctype from app permission updates"
						  )}">${name}</span>`;
				},
			},
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
		// Server-enforced invariant (_parse_changes): Report cannot be set on a row
		// that is Only If Creator. Show it the same way as an inapplicable submit flag.
		if (flag === "report" && row.if_owner) {
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
		// refreshRow repaints the row's DOM, which only exists inside the virtual window
		// (~50 rows); for any other row CellManager.refreshCell sets innerHTML on null and
		// throws, which silently aborted a bulk apply mid-loop. Off-screen rows need no
		// repaint: every formatter reads the live object in data[], so they show current
		// values the moment they scroll into view.
		const first_col = this.datatable.columnmanager.getFirstColumnIndex();
		if (!this.datatable.cellmanager.getCell$(first_col, index)) return;
		// refreshRow wants an ARRAY of cell values (DataManager.updateRow -> prepareRow
		// calls row.map), not the row object. The object is still what format() sees:
		// the datatable keeps our objects in data[] untouched and we mutate them in place.
		this.datatable.refreshRow(this.columns.map((c) => row[c.id]), index);
		// DataManager.updateRow pads our (shorter) row to the datatable's column count
		// with a hardcoded unchecked '<input type="checkbox" />' for the _checkbox
		// column, and refreshRow repaints column 0 with it — even though
		// rowmanager.checkMap[index] still says the row is selected. Left alone, a bulk
		// apply visually un-selects every on-screen selected row while the footer still
		// reports them as selected. Restore the visual state from the model.
		const rm = this.datatable.rowmanager;
		if (rm.checkMap && rm.checkMap[index]) rm.checkRow(index, true);
	}

	// ── dirty store ────────────────────────────────────────────────────────────

	set_flag(row, flag, value) {
		if (!row || !this.can_edit) return;
		if (this.constructor.SUBMIT_FLAGS.includes(flag) && !row.is_submittable) return;

		this.original = this.original || {};
		this.original[row.key] = this.original[row.key] || {};
		if (!(flag in this.original[row.key])) this.original[row.key][flag] = row[flag] ? 1 : 0;

		row[flag] = value ? 1 : 0;

		const changes = (this.dirty[row.key] = this.dirty[row.key] || {});
		if (row[flag] === this.original[row.key][flag]) {
			delete changes[flag];
			if (!Object.keys(changes).length) delete this.dirty[row.key];
		} else {
			changes[flag] = row[flag];
		}
		this.refresh_row(row);
		this.update_footer();
	}

	checked_rows() {
		return this.datatable.rowmanager.getCheckedRows().map((i) => this.view[i]).filter(Boolean);
	}

	bulk_apply(flag, value) {
		const rows = this.checked_rows();
		if (!rows.length) {
			frappe.show_alert({ message: __("Select some rows first"), indicator: "orange" });
			return;
		}
		rows.forEach((row) => this.set_flag(row, flag, value));
		frappe.show_alert({
			message: __("{0} set to {1} on {2} rows", [frappe.unscrub(flag), value ? __("on") : __("off"), rows.length]),
			indicator: "blue",
		});
	}

	change_payload() {
		return Object.entries(this.dirty).map(([key, changes]) => {
			const row = this.by_key[key];
			return {
				doctype: row.doctype, role: row.role, permlevel: row.permlevel, if_owner: row.if_owner,
				changes: { ...changes },
			};
		});
	}

	discard() {
		Object.keys(this.dirty).forEach((key) => {
			const row = this.by_key[key];
			Object.entries(this.original[key] || {}).forEach(([flag, v]) => (row[flag] = v));
		});
		this.dirty = {};
		this.original = {};
		this.datatable.refresh(this.view, this.columns);
		this.update_footer();
	}

	// ── footer + bulk menu ─────────────────────────────────────────────────────

	make_footer() {
		if (!this.can_edit) return;
		this.$footer = $(`
			<div class="pp-perm-footer">
				<span class="pp-perm-count"></span>
				<button class="btn btn-default btn-sm pp-discard">${__("Discard")}</button>
				<button class="btn btn-default btn-sm pp-review">${__("Review")}</button>
				<button class="btn btn-primary btn-sm pp-commit">${__("Commit")}</button>
			</div>`).appendTo(this.$body);
		this.$footer.find(".pp-discard").on("click", () => this.discard());
		this.$footer.find(".pp-review").on("click", () => this.review());
		this.$footer.find(".pp-commit").on("click", () => this.review());

		// Bulk apply lives in the footer too: pick a flag, then Set or Clear it on the
		// checked rows. (Fifteen flags x set/clear as a dropdown would be thirty items.)
		this.$bulk = $(`
			<span class="pp-perm-bulk">
				<select class="form-control input-sm pp-bulk-flag"></select>
				<button class="btn btn-default btn-sm pp-bulk-set">${__("Set on selected")}</button>
				<button class="btn btn-default btn-sm pp-bulk-clear">${__("Clear on selected")}</button>
			</span>`).insertAfter(this.$footer.find(".pp-perm-count"));
		const $select = this.$bulk.find(".pp-bulk-flag");
		this.constructor.FLAGS.forEach((flag) =>
			$select.append(`<option value="${flag}">${frappe.unscrub(flag)}</option>`)
		);
		this.$bulk.find(".pp-bulk-set").on("click", () => this.bulk_apply($select.val(), 1));
		this.$bulk.find(".pp-bulk-clear").on("click", () => this.bulk_apply($select.val(), 0));
	}

	update_footer() {
		if (!this.$footer) return;
		const n = Object.keys(this.dirty).length;
		const selected = this.checked_rows().length;
		this.$footer.find(".pp-perm-count").text(
			n
				? __("{0} unsaved rule change(s), {1} row(s) selected", [n, selected])
				: __("No unsaved changes, {0} row(s) selected", [selected])
		);
		this.$footer.find(".pp-review, .pp-commit").prop("disabled", !n);
		this.$footer.find(".pp-discard").prop("disabled", !n);
	}

	// ── review + commit ────────────────────────────────────────────────────────

	review() {
		const changes = this.change_payload();
		if (!changes.length) return;
		frappe.call({
			method: "cecypo_powerpack.permission_manager.preview_changes",
			args: { changes },
			callback: (r) => this.render_review(r.message, changes),
		});
	}

	render_review(preview, changes) {
		const by_doctype = {};
		preview.rules.forEach((rule) => (by_doctype[rule.doctype] = by_doctype[rule.doctype] || []).push(rule));

		const flag_list = (rule) =>
			Object.entries(rule.changes)
				.map(([f, v]) => `<code>${frappe.unscrub(f)} ${v ? "on" : "off"}</code>`)
				.join(" ");

		let html = "";
		if (preview.detaching.length) {
			html += `<div class="pp-review-detach">
				<b>${__("{0} document type(s) will be detached from app updates", [preview.detaching.length])}</b>
				<p class="small">${__(
					"Their standard rules get copied into Custom DocPerm and, from then on, permission changes shipped by Frappe, ERPNext or any app on bench migrate no longer apply to them. This is permanent until reset in Frappe's Role Permissions Manager."
				)}</p>
				<ul>${preview.detaching
					.map((d) => `<li>${frappe.utils.escape_html(d.doctype)} <span class="text-muted">(${__("{0} standard rules frozen", [d.standard_rules])})</span></li>`)
					.join("")}</ul>
			</div>`;
		}
		html += Object.entries(by_doctype)
			.map(
				([doctype, rules]) => `<div class="mb-3"><b>${frappe.utils.escape_html(doctype)}</b><ul>${rules
					.map(
						(rule) => `<li>${frappe.utils.escape_html(rule.role)}${
							rule.permlevel ? ` (level ${rule.permlevel})` : ""
						}${rule.if_owner ? ` (${__("only if creator")})` : ""}: ${flag_list(rule)}</li>`
					)
					.join("")}</ul></div>`
			)
			.join("");

		const d = new frappe.ui.Dialog({
			title: __("Review {0} rule change(s) across {1} document type(s)", [
				preview.rules.length,
				Object.keys(by_doctype).length,
			]),
			size: "large",
			fields: [{ fieldtype: "HTML", fieldname: "body", options: `<div class="pp-perm-review">${html}</div>` }],
			primary_action_label: __("Commit"),
			primary_action: () => {
				d.hide();
				this.commit(changes);
			},
		});
		d.show();
	}

	commit(changes) {
		frappe.call({
			method: "cecypo_powerpack.permission_manager.commit_changes",
			args: { changes },
			freeze: true,
			freeze_message: __("Committing permission changes…"),
			callback: (r) => {
				const out = r.message;
				frappe.show_alert(
					{
						message: __("Committed {0} rule change(s) across {1} document type(s)", [out.rules, out.doctypes]),
						indicator: "green",
					},
					7
				);
				// Reload from the server so is_custom flags and any server-side normalisation
				// (e.g. validate_permissions zeroing create at level > 0) are reflected — the
				// server persists that normalisation now, so this reload shows the actual
				// values Custom DocPerm holds, not a stale pre-normalisation echo of ours.
				this.load();
			},
			// On error the server has already shown the offending rule; nothing was written.
		});
	}
};
