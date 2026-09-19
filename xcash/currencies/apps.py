from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CurrenciesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "currencies"
    verbose_name = _("货币")

    def ready(self):
        import currencies.signals  # noqa
