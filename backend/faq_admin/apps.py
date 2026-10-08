"""Django configuration for the internal FAQ-admin page."""
from django.apps import AppConfig


class FaqAdminConfig(AppConfig):
    """Register the FAQ-admin templates and future request handlers."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "faq_admin"
