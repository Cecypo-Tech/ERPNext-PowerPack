# Copyright (c) 2024, Cecypo.Tech and contributors
# For license information, please see license.txt

"""
Utility Functions for Cecypo PowerPack
"""

import frappe
from frappe import _


def get_user_settings(user: str = None) -> dict:
    """
    Get settings for a user.
    
    Args:
        user: Username (defaults to current user)
        
    Returns:
        dict: User settings
    """
    if not user:
        user = frappe.session.user
    
    return {
        "user": user,
        "settings": {}
    }


def format_date(date_str: str, format: str = "dd-MM-yyyy") -> str:
    """
    Format a date string.
    
    Args:
        date_str: Date string to format
        format: Output format
        
    Returns:
        str: Formatted date
    """
    return frappe.utils.formatdate(date_str, format)


def send_notification(user: str, title: str, message: str):
    """
    Send a notification to a user.

    Args:
        user: Target user
        title: Notification title
        message: Notification message
    """
    frappe.publish_realtime(
        event="msgprint",
        message={"message": message, "title": title},
        user=user
    )


def get_powerpack_settings() -> dict:
    """
    Get PowerPack Settings.

    Returns:
        dict: PowerPack Settings as a dictionary
    """
    try:
        settings = frappe.get_single("PowerPack Settings")
        return settings.as_dict()
    except Exception as e:
        frappe.log_error(f"Error getting PowerPack Settings: {str(e)}")
        return {
            "enable_pos_powerup": 0,
            "enable_quotation_tweaks": 0
        }


@frappe.whitelist()
def is_feature_enabled(feature_name: str) -> bool:
    """
    Check if a PowerPack feature is enabled.

    Args:
        feature_name: Name of the feature field (e.g., 'enable_pos_powerup')

    Returns:
        bool: True if feature is enabled, False otherwise
    """
    try:
        settings = get_powerpack_settings()
        result = bool(int(settings.get(feature_name, 0)))
        frappe.logger().debug(f"Feature {feature_name} enabled: {result}, value: {settings.get(feature_name)}")
        return result
    except Exception as e:
        frappe.log_error(f"Error checking feature {feature_name}: {str(e)}")
        return False
