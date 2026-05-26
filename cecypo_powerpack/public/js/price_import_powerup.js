(function () {

// ─── List view hook ───────────────────────────────────────────────────────────

frappe.listview_settings["Item Price"] = frappe.listview_settings["Item Price"] || {};
const _orig_onload = frappe.listview_settings["Item Price"].onload;
frappe.listview_settings["Item Price"].onload = function (listview) {
	if (_orig_onload) _orig_onload.call(this, listview);
	listview.page.add_menu_item(__("Import Prices (PowerPack)"), open_price_import_dialog);
};

// ─── Dialog ───────────────────────────────────────────────────────────────────

function open_price_import_dialog() {
	const state = { rows: [] };

	const dialog = new frappe.ui.Dialog({
		title: __("Import Prices"),
		size: "extra-large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "upload_area",
				options: `
					<div class="pip-upload-area" style="
						border:2px dashed #d1d5db;border-radius:6px;padding:28px 16px;
						text-align:center;cursor:pointer;color:#9ca3af;
						transition:border-color .15s;
					">
						<div style="font-size:28px;margin-bottom:8px;">📄</div>
						<div style="font-weight:600;color:#374151;margin-bottom:4px;">
							${__("Drop .xlsx or .csv here, or click to browse")}
						</div>
						<div style="font-size:11px;">
							${__("Required columns: item_code, price_list, rate")}
						</div>
						<input type="file" accept=".xlsx,.csv" class="pip-file-input" style="display:none;">
					</div>`,
			},
			{ fieldname: "review", fieldtype: "HTML", options: '<div class="pip-review-area" style="display:none;"></div>' },
		],
		primary_action_label: __("Apply Changes"),
		primary_action() { apply_changes(dialog, state); },
	});

	dialog.get_primary_btn().prop("disabled", true);
	wire_upload(dialog, state);
	dialog.show();
}

// ─── File upload wiring ───────────────────────────────────────────────────────

function wire_upload(dialog, state) {
	dialog.$wrapper.on("click", ".pip-upload-area", function (e) {
		if ($(e.target).is("input")) return;
		dialog.$wrapper.find(".pip-file-input").click();
	});

	dialog.$wrapper.on("change", ".pip-file-input", function (e) {
		const file = e.target.files[0];
		e.target.value = "";  // allow re-selecting the same file
		if (file) read_and_preview(file, dialog, state);
	});

	dialog.$wrapper.on("dragover", ".pip-upload-area", function (e) {
		e.preventDefault();
		$(this).css("border-color", "#405BFF");
	});

	dialog.$wrapper.on("dragleave drop", ".pip-upload-area", function (e) {
		e.preventDefault();
		$(this).css("border-color", "#d1d5db");
		if (e.type === "drop") {
			const file = e.originalEvent.dataTransfer.files[0];
			if (file) read_and_preview(file, dialog, state);
		}
	});
}

// ─── File read + server call ──────────────────────────────────────────────────

function read_and_preview(file, dialog, state) {
	const $review = dialog.fields_dict.review.$wrapper.find(".pip-review-area");
	$review.show().html(`<div style="text-align:center;padding:20px;color:var(--text-muted);">${__("Parsing file…")}</div>`);
	dialog.get_primary_btn().prop("disabled", true);

	const reader = new FileReader();
	reader.onerror = function () {
		$review.html(`<p style="color:#dc2626;padding:12px;">${__("Could not read file.")}</p>`);
	};
	reader.onload = function (e) {
		const base64 = e.target.result.split(",")[1];
		frappe.call({
			method: "cecypo_powerpack.api.preview_price_import",
			args: { file_content: base64, file_name: file.name },
			freeze: true,
			freeze_message: __("Reading prices…"),
			callback(r) {
				if (r.exc) {
					$review.html(`<p style="color:#dc2626;padding:12px;">${__("Error reading file. Check format and required columns.")}</p>`);
					return;
				}
				state.rows = r.message || [];
				render_review(dialog, state);
			},
		});
	};
	reader.readAsDataURL(file);
}

// ─── Review grid ──────────────────────────────────────────────────────────────

function change_badge(row) {
	if (row.status === "missing") {
		return `<span style="background:#fef3c7;color:#92400e;border-radius:3px;padding:2px 7px;font-size:11px;">&#9888; ${__("item not found")}</span>`;
	}
	if (row.status === "new") {
		return `<span style="background:#e0f2fe;color:#0369a1;border-radius:3px;padding:2px 7px;font-size:11px;">&#10022; ${__("new price")}</span>`;
	}
	const existing = parseFloat(row.existing_rate) || 0;
	const rate = parseFloat(row.rate) || 0;
	const diff = parseFloat((rate - existing).toFixed(2));
	const pct = existing ? parseFloat(((rate - existing) / existing * 100).toFixed(1)) : 0;

	if (diff === 0) {
		return `<span style="background:#f3f4f6;color:#9ca3af;border-radius:3px;padding:2px 7px;font-size:11px;">0.00 (0%)</span>`;
	}

	const is_up = diff > 0;
	const sign = is_up ? "+" : "−";
	const abs_diff = Math.abs(diff).toFixed(2);
	const abs_pct = Math.abs(pct).toFixed(1);
	const label = `${sign}${abs_diff} (${sign}${abs_pct}%)`;
	const magnitude = Math.abs(pct);

	let bg, color, fw = "600";
	if (magnitude < 5) {
		bg = is_up ? "#fef2f2" : "#f0fdf4";
		color = is_up ? "#dc2626" : "#16a34a";
	} else if (magnitude < 20) {
		bg = is_up ? "#fecaca" : "#bbf7d0";
		color = is_up ? "#b91c1c" : "#15803d";
		fw = "700";
	} else {
		bg = is_up ? "#dc2626" : "#16a34a";
		color = "#fff";
		fw = "700";
	}
	return `<span style="background:${bg};color:${color};font-weight:${fw};border-radius:3px;padding:2px 7px;font-size:11px;">${label}</span>`;
}

function row_style(status) {
	if (status === "missing") return "background:#fffbeb;";
	if (status === "new") return "background:#f0f9ff;";
	return "";
}

function format_num(n) {
	const v = parseFloat(n);
	return isNaN(v) ? "—" : v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function render_review(dialog, state) {
	const rows = state.rows;
	const $review = dialog.fields_dict.review.$wrapper.find(".pip-review-area");
	$review.show();

	if (!rows.length) {
		$review.html(`<p style="text-align:center;color:var(--text-muted);padding:16px;">${__("No rows found in file. Check that columns item_code, price_list, and rate are present.")}</p>`);
		dialog.get_primary_btn().prop("disabled", true);
		return;
	}

	const n_update  = rows.filter(r => r.status === "update").length;
	const n_new     = rows.filter(r => r.status === "new").length;
	const n_missing = rows.filter(r => r.status === "missing").length;
	const n_action  = n_update + n_new;

	const summary = `
		<div style="display:flex;gap:8px;flex-wrap:wrap;padding:10px 0 12px;">
			<span style="background:#f3f4f6;border-radius:4px;padding:3px 10px;font-size:11px;font-weight:600;color:#374151;">${rows.length} ${__("total")}</span>
			${n_update  ? `<span style="background:#f0fdf4;border-radius:4px;padding:3px 10px;font-size:11px;font-weight:600;color:#166534;">&#10003; ${n_update} ${__("updating")}</span>` : ""}
			${n_new     ? `<span style="background:#e0f2fe;border-radius:4px;padding:3px 10px;font-size:11px;font-weight:600;color:#0369a1;">&#10022; ${n_new} ${__("new prices")}</span>` : ""}
			${n_missing ? `<span style="background:#fffbeb;border-radius:4px;padding:3px 10px;font-size:11px;font-weight:600;color:#92400e;">&#9888; ${n_missing} ${__("not found")}</span>` : ""}
		</div>`;

	const tbody = rows.map(row => `
		<tr style="${row_style(row.status)}border-bottom:1px solid #f3f4f6;">
			<td style="padding:5px 10px;font-family:monospace;font-size:11px;${row.status === "missing" ? "color:#92400e;font-weight:700;" : ""}">${frappe.utils.escape_html(row.item_code)}</td>
			<td style="padding:5px 10px;font-size:11px;color:#6b7280;">${frappe.utils.escape_html(row.price_list)}</td>
			<td style="padding:5px 10px;text-align:right;font-size:11px;">
				${row.existing_rate != null ? format_num(row.existing_rate) : '<span style="color:#9ca3af;">—</span>'}
			</td>
			<td style="padding:5px 10px;text-align:right;font-size:11px;font-weight:600;">${format_num(row.rate)}</td>
			<td style="padding:5px 10px;text-align:right;">${change_badge(row)}</td>
		</tr>`).join("");

	$review.html(`
		${summary}
		<div style="max-height:420px;overflow-y:auto;border:1px solid #e5e7eb;border-radius:4px;">
			<table style="width:100%;border-collapse:collapse;">
				<thead style="position:sticky;top:0;background:#f3f4f6;z-index:1;">
					<tr>
						<th style="padding:6px 10px;text-align:left;font-size:11px;color:#6b7280;border-bottom:1px solid #e5e7eb;">${__("item_code")}</th>
						<th style="padding:6px 10px;text-align:left;font-size:11px;color:#6b7280;border-bottom:1px solid #e5e7eb;">${__("price_list")}</th>
						<th style="padding:6px 10px;text-align:right;font-size:11px;color:#6b7280;border-bottom:1px solid #e5e7eb;">${__("existing rate")}</th>
						<th style="padding:6px 10px;text-align:right;font-size:11px;color:#6b7280;border-bottom:1px solid #e5e7eb;">${__("new rate")}</th>
						<th style="padding:6px 10px;text-align:right;font-size:11px;color:#6b7280;border-bottom:1px solid #e5e7eb;">${__("change")}</th>
					</tr>
				</thead>
				<tbody>${tbody}</tbody>
			</table>
		</div>`);

	dialog.set_primary_action(__("Apply {0} Changes", [n_action]), function () {
		apply_changes(dialog, state);
	});
	dialog.get_primary_btn().prop("disabled", n_action === 0);
}

// ─── Apply ────────────────────────────────────────────────────────────────────

function apply_changes(dialog, state) {
	const n_action = state.rows.filter(r => r.status === "update" || r.status === "new").length;
	if (!n_action) return;

	dialog.get_primary_btn().prop("disabled", true);
	frappe.call({
		method: "cecypo_powerpack.api.apply_price_import",
		args: { rows: JSON.stringify(state.rows) },
		freeze: true,
		freeze_message: __("Applying price changes…"),
		callback(r) {
			if (r.exc) {
				dialog.get_primary_btn().prop("disabled", false);
				return;
			}
			const { updated = 0, created = 0, skipped = 0 } = r.message || {};
			dialog.hide();
			const parts = [];
			if (updated) parts.push(__("Updated {0} prices", [updated]));
			if (created) parts.push(__("created {0} new", [created]));
			const skipped_msg = skipped ? __(". {0} items not found were skipped.", [skipped]) : ".";
			frappe.show_alert({ message: parts.join(", ") + skipped_msg, indicator: "green" });
		},
	});
}

})();
