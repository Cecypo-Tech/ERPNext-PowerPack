// Copyright (c) 2026, Cecypo.Tech and contributors
// For license information, please see license.txt

frappe.query_reports["Withholding Due to KRA"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "account",
			label: __("Account"),
			fieldtype: "Link",
			options: "Account",
			get_query: () => ({ filters: { company: frappe.query_report.get_filter_value("company") } }),
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "Unpaid\nPaid\nReleased\nAll",
			default: "Unpaid",
		},
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
	],

	get_datatable_options(options) {
		return Object.assign(options, {
			checkboxColumn: true,
			events: { onCheckRow: () => update_selected_card(frappe.query_report) },
		});
	},

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.overdue) {
			value = `<span style="color: var(--red-500)">${value}</span>`;
		}
		return value;
	},

	onload(report) {
		report.page.add_inner_button(__("Issue Payment"), () => pay_kra(report));
		report.page.add_inner_button(__("Export iTax CSV"), () => export_itax_csv(report));
		if (frappe.user.has_role("Accounts Manager") || frappe.user.has_role("System Manager")) {
			report.page.add_inner_button(__("Release Withholding"), () => release_withholding(report));
		}
	},
};

// The server's last summary card is Selected: the unpaid amount of the ticked rows, which Issue Payment pays.
function update_selected_card(report) {
	const $card = report.$summary.find(".summary-item").last();
	if (!$card.length) return;
	const rows = report.get_checked_items().filter((r) => !r.kra_journal_entry && !r.released_by);
	const total = rows.reduce((sum, r) => sum + flt(r.amount), 0);
	const currency = (report.raw_data?.report_summary || []).at(-1)?.currency;
	$card.replaceWith(
		frappe.utils.build_summary_item({
			label: __("Selected ({0})", [rows.length]),
			value: total,
			datatype: "Currency",
			currency,
			indicator: "Green",
		})
	);
}

// Ticked rows, or every row shown when none is ticked. The server keeps VAT rows only.
function export_itax_csv(report) {
	let rows = report.get_checked_items();
	if (!rows.length) rows = report.data;
	// Released rows never go to iTax; with Status All they would make the server refuse the whole export.
	rows = rows.filter((r) => !r.released_by);
	if (!rows.length) {
		frappe.msgprint(__("No rows to export."));
		return;
	}
	const row_names = rows.map((r) => r.row_name);
	// The server's refusals (no VAT rows, missing PIN) show here: in the download tab below they would be
	// a bare error page. export_itax_csv still refuses on its own.
	frappe
		.call({ method: "cecypo_powerpack.kenya_withholding.check_itax_export", args: { row_names } })
		.then(() => {
			// POST: a GET URL carrying every row name outgrows URL length limits. Same window: this runs after
			// an async call, outside the click's user activation, so a new tab can be popup-blocked; the
			// attachment response does not navigate away from the report.
			open_url_post("/api/method/cecypo_powerpack.kenya_withholding.export_itax_csv", { row_names }, false);
		});
}

function pay_kra(report) {
	const rows = report.get_checked_items().filter((r) => !r.kra_journal_entry && !r.released_by);
	if (!rows.length) {
		frappe.msgprint(__("Tick the unpaid rows to pay."));
		return;
	}
	const row_names = rows.map((r) => r.row_name);
	// The server refuses a bad selection here, before a PRN is typed, and gives the bank (iTax) figure.
	frappe
		.call({ method: "cecypo_powerpack.kenya_withholding.pay_kra_preview", args: { row_names } })
		.then((r) => pay_kra_dialog(report, row_names, r.message));
}

function pay_kra_dialog(report, row_names, preview) {
	const company = report.get_filter_value("company");
	const today = frappe.datetime.get_today();
	const dialog = new frappe.ui.Dialog({
		title: __("Issue Payment: {0} rows, {1} to the bank", [row_names.length, format_currency(preview.bank)]),
		fields: [
			{
				// Merged part payments of one invoice are ceiled once, so the bank can pay less than was withheld.
				fieldname: "figures",
				fieldtype: "HTML",
				options: `<p class="text-muted">${__("Withheld {0}; the difference goes to the round-off account.", [
					format_currency(preview.withheld),
				])}</p>`,
				hidden: flt(preview.withheld) === flt(preview.bank),
			},
			{
				fieldname: "bank_account",
				label: __("Bank / Cash Account"),
				fieldtype: "Link",
				options: "Account",
				reqd: 1,
				get_query: () => ({
					filters: { account_type: ["in", ["Bank", "Cash"]], company, is_group: 0 },
				}),
			},
			{ fieldname: "posting_date", label: __("Posting Date"), fieldtype: "Date", default: today, reqd: 1 },
			{ fieldname: "prn", label: __("PRN"), fieldtype: "Data", reqd: 1 },
			{ fieldname: "reference_date", label: __("Reference Date"), fieldtype: "Date", default: today, reqd: 1 },
		],
		primary_action_label: __("Create Journal Entry"),
		primary_action(values) {
			dialog.disable_primary_action();
			frappe
				.call({
					method: "cecypo_powerpack.kenya_withholding.pay_kra",
					args: { row_names, ...values },
					freeze: true,
				})
				.then((r) => {
					dialog.hide();
					frappe.show_alert({
						message: __("Journal Entry {0} created", [r.message]),
						indicator: "green",
					});
					report.refresh();
				})
				.always(() => dialog.enable_primary_action());
		},
	});
	dialog.show();
}

// Deposit rows that will never get an invoice: the server refuses anything else (paid, released, mixed
// suppliers or companies), so the ticked rows go as they are.
function release_withholding(report) {
	const rows = report.get_checked_items();
	if (!rows.length) {
		frappe.msgprint(__("Tick the deposit rows waiting for their invoice."));
		return;
	}
	const row_names = rows.map((r) => r.row_name);
	const total = rows.reduce((sum, r) => sum + flt(r.amount), 0);
	const dialog = new frappe.ui.Dialog({
		title: __("Release Withholding: {0} rows, {1}", [
			row_names.length,
			format_currency(total, (report.raw_data?.report_summary || []).at(-1)?.currency),
		]),
		fields: [
			{
				fieldname: "posting_date",
				label: __("Posting Date"),
				fieldtype: "Date",
				default: frappe.datetime.get_today(),
				reqd: 1,
			},
			{ fieldname: "reason", label: __("Reason"), fieldtype: "Small Text", reqd: 1 },
		],
		primary_action_label: __("Release"),
		primary_action(values) {
			dialog.disable_primary_action();
			frappe
				.call({
					method: "cecypo_powerpack.kenya_withholding.release_withholding",
					args: { row_names, ...values },
					freeze: true,
				})
				.then((r) => {
					dialog.hide();
					frappe.show_alert({
						message: __("Journal Entry {0} created", [
							`<a href="${frappe.utils.get_form_link("Journal Entry", r.message)}">${r.message}</a>`,
						]),
						indicator: "green",
					});
					report.refresh();
				})
				.always(() => dialog.enable_primary_action());
		},
	});
	dialog.show();
}
