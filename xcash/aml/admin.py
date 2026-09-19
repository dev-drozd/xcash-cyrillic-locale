from aml.models import RiskAssessment
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.contrib.filters.admin import ChoicesDropdownFilter
from unfold.contrib.filters.admin import RangeDateTimeFilter
from unfold.decorators import display

from common import admin_display as fmt
from common.admin import ReadOnlyModelAdmin


@admin.register(RiskAssessment)
class RiskAssessmentAdmin(ReadOnlyModelAdmin):
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("invoice", "deposit")
    list_filter_sheet = False
    list_display = (
        "display_target",
        "display_target_type",
        "display_risk",
        "display_status",
        "source",
        "display_address",
        "checked_at",
        "created_at",
    )
    list_filter = (
        ("risk_level", ChoicesDropdownFilter),
        ("status", ChoicesDropdownFilter),
        ("target_type", ChoicesDropdownFilter),
        "source",
        ("created_at", RangeDateTimeFilter),
    )
    search_fields = (
        "address",
        "tx_hash",
        "invoice__sys_no",
        "deposit__sys_no",
    )
    search_help_text = _("支持按地址、交易哈希、账单单号或充值单号搜索")
    readonly_fields = (
        "source",
        "status",
        "target_type",
        "invoice",
        "deposit",
        "display_full_address",
        "display_full_tx_hash",
        "risk_level",
        "risk_score",
        "display_raw_response",
        "display_error_message",
        "checked_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            _("筛查对象"),
            {
                "classes": ("tab",),
                "fields": (
                    "target_type",
                    "invoice",
                    "deposit",
                    "display_full_address",
                    "display_full_tx_hash",
                ),
            },
        ),
        (
            _("风险结果"),
            {
                "classes": ("tab",),
                "fields": (
                    "source",
                    "status",
                    "risk_level",
                    "risk_score",
                    "display_error_message",
                    "checked_at",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
        (
            _("原始响应"),
            {
                "classes": ("tab",),
                "fields": ("display_raw_response",),
            },
        ),
    )

    @display(description=_("筛查对象"), header=True)
    def display_target(self, instance: RiskAssessment):
        # 风险评估既可能挂在账单也可能挂在充值上，列表页统一展示归属单号，
        # 没有业务单号时退回自增 ID，避免出现整列空白。
        if instance.invoice_id:
            return (instance.invoice.sys_no, _("账单收款"))
        if instance.deposit_id:
            return (instance.deposit.sys_no, _("充值收款"))
        return (f"#{instance.pk}", "")

    @display(
        description=_("类型"),
        ordering="target_type",
        label={
            RiskAssessment.TargetType.INVOICE: "primary",
            RiskAssessment.TargetType.DEPOSIT: "info",
        },
    )
    def display_target_type(self, instance: RiskAssessment):
        return (instance.target_type, instance.get_target_type_display())

    @display(
        description=_("风险"),
        ordering="risk_level",
        label={
            "Low": "success",
            "Moderate": "warning",
            "High": "danger",
            "Severe": "danger",
        },
    )
    def display_risk(self, instance: RiskAssessment):
        if not instance.risk_level:
            return None
        return (instance.risk_level, f"{instance.risk_level} · {instance.risk_score}")

    @display(
        description=_("查询状态"),
        ordering="status",
        label={
            RiskAssessment.Status.SUCCESS: "success",
            RiskAssessment.Status.FAILED: "danger",
        },
    )
    def display_status(self, instance: RiskAssessment):
        return (instance.status, instance.get_status_display())

    @display(description=_("地址 / 哈希"))
    def display_address(self, instance: RiskAssessment):
        return fmt.truncated(instance.address or instance.tx_hash)

    @display(description=_("地址"))
    def display_full_address(self, instance: RiskAssessment):
        return fmt.mono(instance.address)

    @display(description=_("交易哈希"))
    def display_full_tx_hash(self, instance: RiskAssessment):
        return fmt.mono(instance.tx_hash)

    @display(description=_("原始响应"))
    def display_raw_response(self, instance: RiskAssessment):
        return fmt.scroll_box(instance.raw_response)

    @display(description=_("错误信息"))
    def display_error_message(self, instance: RiskAssessment):
        return fmt.scroll_box(instance.error_message)
