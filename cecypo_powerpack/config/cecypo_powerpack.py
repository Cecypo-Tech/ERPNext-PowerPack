# Copyright (c) 2024, Cecypo.Tech and contributors
# For license information, please see license.txt

from frappe import _


def get_data():
	return [
		{
			"label": _("Setup"),
			"items": [
				{
					"type": "doctype",
					"name": "PowerPack Settings",
					"label": _("PowerPack Settings"),
					"description": _("Configure PowerPack features and settings"),
				}
			]
		}
	]
