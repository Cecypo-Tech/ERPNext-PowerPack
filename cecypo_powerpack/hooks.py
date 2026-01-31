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
app_include_css = [
    "/assets/cecypo_powerpack/css/cecypo_powerpack.css",
    "/assets/cecypo_powerpack/css/point_of_sale_powerpack.css",
    "/assets/cecypo_powerpack/css/sales_powerup.css"
]
app_include_js = [
    "/assets/cecypo_powerpack/js/cecypo_powerpack.js",
    "/assets/cecypo_powerpack/js/point_of_sale_powerpack.js",
    "/assets/cecypo_powerpack/js/sales_powerup.js"
]

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
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

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

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "cecypo_powerpack.utils.jinja_methods",
# 	"filters": "cecypo_powerpack.utils.jinja_filters"
# }

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
                    "POS Profile-powerpack_column_config"
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
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Sales Invoice": {
		"before_cancel": "cecypo_powerpack.validations.prevent_etr_invoice_cancellation"
	},
	"POS Invoice": {
		"before_cancel": "cecypo_powerpack.validations.prevent_etr_invoice_cancellation"
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
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "cecypo_powerpack.event.get_events"
# }
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

