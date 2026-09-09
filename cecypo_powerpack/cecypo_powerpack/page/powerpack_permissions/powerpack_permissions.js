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

// frappe's router has no cancellable pre-navigation hook: `frappe.router` only ever
// fires "change" (router.js:152), and it fires it AFTER this.render() has already swapped
// the page; its emitter (router.js:698 -> event_emitter.js) hands handlers the data only
// and throws their return value away, so nothing a handler does can stop a route. So the
// in-app guard cannot block navigation — it preserves the change set instead and says so
// on the way back. See on_show() / show_stale_notice().
frappe.pages["powerpack-permissions"].on_page_show = (wrapper) =>
	wrapper.permission_manager && wrapper.permission_manager.on_show();

frappe.PowerPackPermissionManager = class PowerPackPermissionManager {
	constructor(wrapper, page) {
		this.wrapper = wrapper;
		this.page = page;
		this.$body = $('<div class="pp-perm"></div>').appendTo(this.page.main);

		// key -> {flag: new value}; only flags that differ from the loaded value
		this.dirty = {};
		this.filters = {};

		// Anchor for shift-click range select: the rowIndex of the last checkbox clicked.
		this._last_checked_index = null;
		// The page container fires "show" immediately after "load" (container.js:80), so the
		// very first on_show() would re-run the load this constructor is about to start.
		this._first_show_pending = true;

		this.bind_unload_guard();
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
		this._loading = true;
		this._last_checked_index = null;
		this.hide_stale_notice();
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
				this._loading = false;
				this.render();
			},
			error: () => {
				// The server already showed its permission message; leave a stub, not a spinner.
				this._loading = false;
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
		// The shift anchor is a rowIndex into the old view; it means nothing in the new one.
		this._last_checked_index = null;
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

		this.bind_shift_select();
		this.bind_header_sort();
	}

	// ── header sort ────────────────────────────────────────────────────────────

	/**
	 * frappe-datatable's own sort UI is the header dropdown, but its items always
	 * include "Remove column" (and Freeze/Unfreeze): DataTable.buildOptions
	 * concatenates whatever `headerDropdown` we pass AFTER its own DEFAULT_OPTIONS
	 * list (dist frappe-datatable.cjs.js:5933-5936 — `this.options.headerDropdown =
	 * [...this.DEFAULT_OPTIONS.headerDropdown, ...options.headerDropdown]`), so the
	 * defaults can never be excluded that way. refresh_row() maps cell values by
	 * `this.columns` index, so letting a column be removed would desync every
	 * later cell — passing `dropdown: true` (design (a)) is therefore not safe.
	 *
	 * Every column keeps `dropdown: false` (no header dropdown is rendered at all —
	 * getCellContent, dist :3427-3429 — so `.dt-dropdown__toggle` never exists) and
	 * sorting is driven directly: a delegated click on the header cell calls
	 * `datatable.sortColumn(colIndex, order)` (ColumnManager.sortColumn, dist
	 * :3767-3779), cycling none -> asc -> desc -> none. sortColumn() already calls
	 * refreshHeader() (dist :3771) which re-renders the header and, since every one
	 * of our columns has `sortable !== false`, repaints the built-in sort-indicator
	 * span from `cell.sortOrder` (getCellContent, dist :3418-3423) — no extra CSS
	 * needed for the arrow.
	 */
	bind_header_sort() {
		this.$table.on("click", ".dt-cell--header", (e) => {
			// The resize handle and, for can_edit, the select-all checkbox both live
			// inside the header cell and bubble a click here; leave them alone.
			if (e.target.closest('.dt-cell__resize-handle, [type="checkbox"]')) return;
			const cell = e.currentTarget;
			const col_index = parseInt(cell.dataset.colIndex, 10);
			if (isNaN(col_index)) return;
			// Column 0 (the checkbox column, when can_edit) and the serial-number
			// column frappe-datatable always prepends are not part of `this.columns`
			// and are not in the sortable set the brief asks for.
			if (col_index < this.datatable.columnmanager.getFirstColumnIndex()) return;
			const column = this.datatable.columnmanager.getColumn(col_index);
			const next = { none: "asc", asc: "desc", desc: "none" }[column.sortOrder] || "asc";
			this.datatable.sortColumn(col_index, next);
		});
	}

	// ── shift-click range select ───────────────────────────────────────────────

	/**
	 * frappe-datatable's own checkbox handler (RowManager.bindCheckbox, dist
	 * frappe-datatable.cjs.js:4064) delegates `click` on `.dt-cell--col-0 [type="checkbox"]`
	 * from the SAME element we hand the constructor (DataTable sets `this.wrapper = wrapper`,
	 * :5891), and it has no shift handling at all. Both listeners are therefore native
	 * listeners on one element and run in registration order — the datatable's first, since
	 * it was bound in its constructor above. So by the time we run, the clicked row has
	 * already been toggled and the checkbox carries its NEW state; we only extend that state
	 * over the range and never re-toggle the clicked row itself.
	 */
	bind_shift_select() {
		// Shift-clicking inside the grid would otherwise drag a text selection across every
		// row in between. mousedown's default is what starts that selection; suppressing it
		// does not stop the checkbox from toggling (activation happens on click).
		this.$table.on("mousedown", '.dt-cell--col-0 [type="checkbox"]', (e) => {
			if (e.shiftKey) e.preventDefault();
		});

		this.$table.on("click", '.dt-cell--col-0 [type="checkbox"]', (e) => {
			const cell = e.currentTarget.closest(".dt-cell");
			// The header cell is the select-all box; leave it entirely to the datatable.
			if (!cell || cell.dataset.isHeader) return;
			const row_index = parseInt(cell.dataset.rowIndex, 10);
			if (isNaN(row_index)) return;

			// The clicked box's new state is what the range follows: shift-clicking an
			// unchecked box checks the range, shift-clicking a checked one clears it.
			const state = !!e.currentTarget.checked;
			if (e.shiftKey && this._last_checked_index !== null && this._last_checked_index !== row_index) {
				this.check_range(this._last_checked_index, row_index, state);
			}
			// The anchor always moves to the row just clicked, shift or not, so a second
			// shift-click extends from the previous one rather than from the original click.
			this._last_checked_index = row_index;
		});
	}

	/**
	 * rowIndexes in VISUAL order. rowIndex is assigned at load and never changes; sorting only
	 * reorders `datamanager.rowViewOrder` (DataManager.prepareRowView, dist :2124-2129, and
	 * _sortRows, :2195), which is exactly what BodyRenderer.renderRows walks to paint the grid
	 * (dist :4863-4870). So a range that is contiguous on screen is contiguous in rowViewOrder,
	 * not in rowIndex.
	 */
	visual_order() {
		const dm = this.datatable && this.datatable.datamanager;
		const order = dm && dm.rowViewOrder;
		if (!order || !order.length) return this.view.map((_, i) => i);
		const renderer = this.datatable.bodyRenderer;
		if (renderer && renderer.visibleRowIndices && renderer.visibleRowIndices.length) {
			const visible = new Set(renderer.visibleRowIndices);
			return order.filter((i) => visible.has(i));
		}
		return order.slice();
	}

	check_range(anchor_index, target_index, state) {
		const order = this.visual_order();
		const from = order.indexOf(anchor_index);
		const to = order.indexOf(target_index);
		if (from < 0 || to < 0) return;
		const [start, end] = from < to ? [from, to] : [to, from];

		// checkRow fires onCheckRow per row, and update_footer counts the whole checkMap each
		// time — O(n^2) over a long range. Repaint the footer once, at the end.
		this._suspend_footer = true;
		try {
			for (let i = start; i <= end; i++) {
				const row_index = order[i];
				// The datatable already toggled the clicked row; toggling it again here would
				// undo it.
				if (row_index === target_index) continue;
				this.datatable.rowmanager.checkRow(row_index, state);
			}
		} finally {
			this._suspend_footer = false;
		}
		this.update_footer();
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
		this.hide_stale_notice();
		this.datatable.refresh(this.view, this.columns);
		this.update_footer();
	}

	// ── unsaved-changes guard ──────────────────────────────────────────────────

	/**
	 * Bound once per instance, and there is no teardown for the page, so it stays for the
	 * life of the tab. It reads this.dirty live rather than closing over a snapshot, so a
	 * clean store never prompts.
	 */
	bind_unload_guard() {
		if (this._unload_guard) return;
		this._unload_guard = (e) => {
			if (!Object.keys(this.dirty).length) return undefined;
			// preventDefault() is what modern browsers act on; returnValue is the legacy
			// spelling older ones still need. Neither shows our text — browsers use their own.
			e.preventDefault();
			const message = __("You have {0} unsaved permission change(s).", [
				Object.keys(this.dirty).length,
			]);
			e.returnValue = message;
			return message;
		};
		window.addEventListener("beforeunload", this._unload_guard);
	}

	/**
	 * Fired by the page container every time this page is shown (container.js:80 ->
	 * pageview.js:104-108), including once right after on_page_load. Clean: reload, so the
	 * grid is never stale. Dirty: keep the change set — the router already navigated away and
	 * back, and silently discarding edits would be worse than showing them again — and say so.
	 */
	on_show() {
		if (this._first_show_pending) {
			this._first_show_pending = false;
			return;
		}
		// First load failed, or is still in flight: it will render on its own.
		// A commit is in flight too: commit() already called hide_stale_notice()
		// and will call load() itself once it settles, so treat it the same way —
		// reloading here would race the commit and could repaint the stale notice
		// commit() just suppressed, right before its own callback clears this.dirty.
		if (this._loading || this._committing || !this.rows) return;

		if (!Object.keys(this.dirty).length) {
			this.load();
			return;
		}
		this.show_stale_notice();
		frappe.show_alert({
			message: __("{0} unsaved permission change(s) are still pending", [
				Object.keys(this.dirty).length,
			]),
			indicator: "orange",
		});
	}

	show_stale_notice() {
		if (!Object.keys(this.dirty).length || !this.$filters) return;
		// Rebuilt only when it is not on the page: render() empties $body, which detaches it.
		// on_show() can fire any number of times without stacking notices or handlers.
		if (!this.$stale || !this.$stale.parent().length) {
			this.$stale = $(`
				<div class="pp-perm-stale alert alert-warning">
					<span class="pp-perm-stale-text"></span>
					<button class="btn btn-xs btn-default pp-stale-review">${__("Review")}</button>
					<button class="btn btn-xs btn-default pp-stale-discard">${__("Discard")}</button>
					<button class="btn btn-xs btn-link pp-stale-dismiss" title="${__("Dismiss")}">&times;</button>
				</div>`);
			this.$stale.find(".pp-stale-review").on("click", () => this.review());
			this.$stale.find(".pp-stale-discard").on("click", () => this.discard());
			this.$stale.find(".pp-stale-dismiss").on("click", () => this.hide_stale_notice());
			this.$stale.insertBefore(this.$filters);
		}
		this.$stale
			.find(".pp-perm-stale-text")
			.text(
				__("{0} unsaved change(s) from earlier. Review to commit them, or Discard.", [
					Object.keys(this.dirty).length,
				])
			);
	}

	hide_stale_notice() {
		if (this.$stale) this.$stale.remove();
		this.$stale = null;
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
		// check_range() sets this while it walks a range: every checkRow fires onCheckRow, and
		// counting the whole checkMap per row is quadratic. It repaints once when it is done.
		if (this._suspend_footer) return;
		// The notice quotes the same count as the footer, so they cannot disagree.
		if (this.$stale && this.$stale.parent().length) {
			if (Object.keys(this.dirty).length) this.show_stale_notice();
			else this.hide_stale_notice();
		}
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
		// A page navigated away and back while this call is in flight must not show
		// "unsaved changes from earlier": there aren't any yet — they are mid-commit.
		// on_show() checks this._committing and does nothing while it is true.
		this.hide_stale_notice();
		this._committing = true;
		frappe.call({
			method: "cecypo_powerpack.permission_manager.commit_changes",
			args: { changes },
			freeze: true,
			freeze_message: __("Committing permission changes…"),
			callback: (r) => {
				this._committing = false;
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
			error: () => {
				// The server already showed the offending rule; nothing was written, so
				// this.dirty must survive untouched — the user's change set is still valid
				// and still needs a Commit.
				this._committing = false;
			},
		});
	}
};
