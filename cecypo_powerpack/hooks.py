app_name = "cecypo_powerpack"
app_title = "Cecypo PowerPack"
app_publisher = "Cecypo.Tech"
app_description = "Custom Frappe app for Cecypo PowerPack features"
app_email = "support@cecypo.tech"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "cecypo_powerpack",
# 		"logo": "/assets/cecypo_powerpack/logo.png",
# 		"title": "Cecypo PowerPack",
# 		"route": "/cecypo_powerpack",
# 		"has_permission": "cecypo_powerpack.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
#
# These are BARE BUNDLE NAMES, not /assets/... paths, and that distinction matters.
# Frappe resolves a name containing ".bundle." through assets.json to a
# content-hashed file (bundled_asset(), frappe/utils/jinja_globals.py:147); a
# literal /assets path is served verbatim, with no hash and no ?ver=, so browsers
# cache it indefinitely and deployed changes never reach anyone who does not
# manually hard-reload. The individual source files are imported, in order, by the
# two bundle entry points. The CSS entry is authored as .scss (so sass can
# resolve its sibling imports) but esbuild emits .css, and assets.json is keyed
# by the OUTPUT name -- hence ".bundle.css" here, same as erpnext.
app_include_css = "cecypo_powerpack.bundle.css"
app_include_js = "cecypo_powerpack.bundle.js"

# include js, css files in header of web template
# web_include_css = "/assets/cecypo_powerpack/css/cecypo_powerpack.css"
# web_include_js = "/assets/cecypo_powerpack/js/cecypo_powerpack.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "cecypo_powerpack/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
    "Sales Order": [
        "public/js/quick_pay.js",
        "public/js/quick_pay_mpesa.js",
    ],
    "Email Group": [
        "public/js/email_group_powerup.js",
    ],
}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "cecypo_powerpack/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Website Route Rules
# -------------------
website_route_rules = [
	{"from_route": "/s/<token>", "to_route": "s"},
]

# Jinja
# ----------

# add methods and filters to jinja environment
jinja = {
	"methods": [
		"cecypo_powerpack.api.get_document_public_link",
		"cecypo_powerpack.barcode.qr_data_uri",
	],
}

# Installation
# ------------

# before_install = "cecypo_powerpack.install.before_install"
# after_install = "cecypo_powerpack.install.after_install"

# Fixtures
# --------

fixtures = [
    {
        "dt": "Custom Field",
        "filters": [
            [
                "name",
                "in",
                [
                    "POS Profile-enable_powerpack_by_cecypo",
                    "POS Profile-powerpack_column_config",
                    "Quotation-set_warehouse"
                ]
            ]
        ]
    },
    {
        "dt": "Print Format",
        "filters": [
            ["name", "in", ["Powerpack POS Template"]]
        ]
    },
    {
        "dt": "Server Script",
        "filters": [
            ["module", "in", ["Cecypo PowerPack"]]
        ]
    },
    {
        "dt": "Client Script",
        "filters": [
            ["module", "in", ["Cecypo PowerPack"]]
        ]
    }
]

# Uninstallation
# ------------

# before_uninstall = "cecypo_powerpack.uninstall.before_uninstall"
# after_uninstall = "cecypo_powerpack.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "cecypo_powerpack.utils.before_app_install"
# after_app_install = "cecypo_powerpack.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "cecypo_powerpack.utils.before_app_uninstall"
# after_app_uninstall = "cecypo_powerpack.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "cecypo_powerpack.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Extend standard doctype classes (v16+). Layers our mixin on top of ERPNext's
# controller instead of replacing it, so upstream fixes are preserved and other
# apps extending the same doctype are not clobbered.

extend_doctype_class = {
	"Payment Reconciliation": "cecypo_powerpack.custom_payment_reconciliation.CustomPaymentReconciliation"
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Quotation": {
		"validate": "cecypo_powerpack.min_selling_price.validate_min_selling_price"
	},
	"Sales Order": {
		"validate": "cecypo_powerpack.min_selling_price.validate_min_selling_price"
	},
	"Sales Invoice": {
		"before_cancel": "cecypo_powerpack.validations.prevent_etr_invoice_cancellation",
		"validate": "cecypo_powerpack.min_selling_price.validate_min_selling_price"
	},
	"POS Invoice": {
		"before_cancel": "cecypo_powerpack.validations.prevent_etr_invoice_cancellation",
		"validate": "cecypo_powerpack.min_selling_price.validate_min_selling_price"
	},
	"Delivery Note": {
		"validate": "cecypo_powerpack.min_selling_price.validate_min_selling_price"
	},
	"Payment Reconciliation": {
		"validate": "cecypo_powerpack.overrides.validate_allocation_with_zero_support"
	}
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"cecypo_powerpack.tasks.all"
# 	],
# 	"daily": [
# 		"cecypo_powerpack.tasks.daily"
# 	],
# 	"hourly": [
# 		"cecypo_powerpack.tasks.hourly"
# 	],
# 	"weekly": [
# 		"cecypo_powerpack.tasks.weekly"
# 	],
# 	"monthly": [
# 		"cecypo_powerpack.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "cecypo_powerpack.install.before_tests"

# Overriding Methods
# ------------------------------
#
override_whitelisted_methods = {
	# search_link is the actual HTTP endpoint the Link field calls.
	# search_link → search_widget → frappe.call(query) all happen in Python, bypassing
	# handler.py's override_whitelisted_methods lookup. Overriding search_link lets us
	# substitute custom_item_query before the chain runs.
	"frappe.desk.search.search_link": "cecypo_powerpack.api.custom_search_link",
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "cecypo_powerpack.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["cecypo_powerpack.utils.before_request"]
# after_request = ["cecypo_powerpack.utils.after_request"]

# Job Events
# ----------
# before_job = ["cecypo_powerpack.utils.before_job"]
# after_job = ["cecypo_powerpack.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"cecypo_powerpack.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

