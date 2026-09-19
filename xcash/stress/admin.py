# xcash/stress/admin.py
from django.contrib import admin
from django.contrib import messages
from django.db import connection
from django.db import transaction
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from stress.models import DepositStressCase
from stress.models import DepositStressCaseStatus
from stress.models import InvoiceStressCase
from stress.models import InvoiceStressCaseStatus
from stress.models import StressRun
from stress.models import StressRunStatus
from stress.service import StressService
from stress.tasks import prepare_stress
from unfold.contrib.filters.admin import ChoicesDropdownFilter
from unfold.contrib.filters.admin import RelatedDropdownFilter
from unfold.decorators import display

from common import admin_display as fmt
from common.admin import ModelAdmin
from common.admin import TabularInline

# 压测 case 的状态是一条线性流水线，配色只区分「进行中 / 成功 / 失败 / 跳过」四档，
# 避免为每个中间态各配一种颜色反而看不出结论。
STRESS_CASE_STATUS_LABELS = {
    "pending": "",
    "creating": "info",
    "created": "info",
    "paying": "info",
    "paid": "info",
    "webhook_ok": "info",
    "succeeded": "success",
    "failed": "danger",
    "skipped": "warning",
}

STRESS_RUN_STATUS_LABELS = {
    StressRunStatus.DRAFT: "",
    StressRunStatus.PREPARING: "info",
    StressRunStatus.FAILED: "danger",
    StressRunStatus.READY: "warning",
    StressRunStatus.RUNNING: "info",
    StressRunStatus.COMPLETED: "success",
}


class InvoiceStressCaseInline(TabularInline):
    model = InvoiceStressCase
    tab = True
    show_count = True
    per_page = 20
    fields = (
        "sequence",
        "status",
        "crypto",
        "chain",
        "invoice_sys_no",
        "tx_hash",
        "webhook_signature_ok",
        "webhook_payload_ok",
        "webhook_nonce_ok",
        "webhook_timestamp_ok",
        "collection_verified",
        "error",
    )
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


class DepositStressCaseInline(TabularInline):
    model = DepositStressCase
    tab = True
    show_count = True
    per_page = 20
    fields = (
        "sequence",
        "status",
        "customer_uid",
        "crypto",
        "chain",
        "amount",
        "tx_hash",
        "webhook_signature_ok",
        "webhook_payload_ok",
        "webhook_nonce_ok",
        "webhook_timestamp_ok",
        "collection_verified",
        "error",
    )
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


def _percentile_metrics(
    table: str,
    stress_run_id: int,
    status_value: str,
    stages: list[tuple[str, str, str]],
) -> list[dict]:
    """聚合各阶段耗时的 P50 / P95 / P99 / max（毫秒）。

    只统计 SUCCEEDED 的 case；end 或 start 字段为 NULL 的样本会被
    PostgreSQL 的 EXTRACT(EPOCH FROM ...) 自然忽略（NULL 不参与聚合）。
    通过 PostgreSQL 的 percentile_cont 在数据库层完成分位数计算，避免
    把所有 case 拉到内存再排序。

    stages: [(label, start_field, end_field), ...]
    返回每个阶段一个 dict：
        {label, count, p50, p95, p99, max}
    若 count == 0（即所有样本两端都有 NULL），跳过该阶段。
    """
    if not stages:
        return []

    # 每个阶段构造 4 个聚合表达式 + 1 个非空计数；一次 SQL 取齐
    select_parts: list[str] = []
    for idx, (_label, start_f, end_f) in enumerate(stages):
        diff_secs = f"EXTRACT(EPOCH FROM ({end_f} - {start_f}))"
        # 仅统计两端都非空的样本
        valid = f"({start_f} IS NOT NULL AND {end_f} IS NOT NULL)"
        select_parts.extend(
            [
                f"COUNT(*) FILTER (WHERE {valid}) AS cnt_{idx}",
                (
                    f"PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY {diff_secs}) "
                    f"FILTER (WHERE {valid}) AS p50_{idx}"
                ),
                (
                    f"PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY {diff_secs}) "
                    f"FILTER (WHERE {valid}) AS p95_{idx}"
                ),
                (
                    f"PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY {diff_secs}) "
                    f"FILTER (WHERE {valid}) AS p99_{idx}"
                ),
                f"MAX({diff_secs}) FILTER (WHERE {valid}) AS max_{idx}",
            ]
        )
    # 表名与字段均由调用方内部常量传入，不存在用户可控输入；%s 占位符用于参数化查询。
    sql = (
        f"SELECT {', '.join(select_parts)} "  # noqa: S608
        f"FROM {table} "
        f"WHERE stress_run_id = %s AND status = %s"
    )

    with connection.cursor() as cur:
        cur.execute(sql, [stress_run_id, status_value])
        row = cur.fetchone()

    if row is None:
        return []

    results: list[dict] = []
    cols_per_stage = 5
    for idx, (label, _start_f, _end_f) in enumerate(stages):
        base = idx * cols_per_stage
        cnt = row[base]
        if not cnt:
            continue
        # secs -> ms; PERCENTILE_CONT 返回 float（秒），MAX 返回 interval
        # 上面用 EXTRACT(EPOCH FROM ...) 已转成秒
        results.append(
            {
                "label": label,
                "count": cnt,
                "p50_ms": round((row[base + 1] or 0) * 1000, 2),
                "p95_ms": round((row[base + 2] or 0) * 1000, 2),
                "p99_ms": round((row[base + 3] or 0) * 1000, 2),
                "max_ms": round((row[base + 4] or 0) * 1000, 2),
            }
        )
    return results


@admin.register(StressRun)
class StressRunAdmin(ModelAdmin):
    inlines = ()

    ordering = ("-created_at",)
    list_display = (
        "display_identity",
        "display_status",
        "display_scale",
        "display_result",
        "created_at",
        "finished_at",
    )
    list_filter = (("status", ChoicesDropdownFilter),)
    search_fields = ("name",)
    search_help_text = _("支持按轮次名称搜索")
    readonly_fields = (
        "status",
        "project",
        "succeeded",
        "failed",
        "skipped",
        "error",
        "started_at",
        "finished_at",
        "metrics_summary",
    )
    actions = ["start_stress"]

    def get_fields(self, request, obj=None):
        if obj is None:
            return (
                "name",
                "count",
                "evm_invoice_receiving_mode",
                "deposit_count",
                "deposit_customer_count",
            )
        return (
            "name",
            "count",
            "evm_invoice_receiving_mode",
            "deposit_count",
            "deposit_customer_count",
            "status",
            "project",
            "succeeded",
            "failed",
            "skipped",
            "error",
            "started_at",
            "finished_at",
            "metrics_summary",
        )

    @display(description=_("轮次"), ordering="name", header=True)
    def display_identity(self, obj: StressRun):
        return (obj.name, obj.get_evm_invoice_receiving_mode_display())

    @display(description=_("状态"), ordering="status", label=STRESS_RUN_STATUS_LABELS)
    def display_status(self, obj: StressRun):
        return (obj.status, obj.get_status_display())

    @display(description=_("规模"))
    def display_scale(self, obj: StressRun):
        # 账单与充值两类用例数一起决定本轮压测强度，拆成两列反而要来回对照。
        return fmt.stacked(
            _("账单 %(count)s") % {"count": obj.count},
            _("充值 %(count)s / 客户 %(customers)s")
            % {"count": obj.deposit_count, "customers": obj.deposit_customer_count},
        )

    @display(description=_("结果"))
    def display_result(self, obj: StressRun):
        return fmt.stacked(
            _("成功 %(n)s") % {"n": obj.succeeded},
            _("失败 %(failed)s / 跳过 %(skipped)s")
            % {"failed": obj.failed, "skipped": obj.skipped},
        )

    @admin.display(description=_("各阶段耗时分位数"))
    def metrics_summary(self, obj: StressRun):
        """展示三类业务关键阶段延迟的 P50/P95/P99/max（毫秒）。

        只对状态为 SUCCEEDED 的 case 聚合；任何阶段两端时间戳为空的样本
        会自然被排除。无可用数据时返回 "无数据可聚合"。
        """
        if obj is None or obj.pk is None:
            return _("无数据可聚合")

        invoice_stages = [
            ("api_create_ms", "started_at", "invoice_created_at"),
            ("api_select_method_ms", "invoice_created_at", "api_done_at"),
            ("chain_pay_ms", "api_done_at", "chain_paid_at"),
            ("webhook_wait_ms", "chain_paid_at", "webhook_received_at"),
            ("collection_wait_ms", "webhook_received_at", "collection_done_at"),
            ("total_ms", "started_at", "finished_at"),
        ]
        deposit_stages = [
            ("api_ms", "started_at", "api_done_at"),
            ("chain_pay_ms", "api_done_at", "chain_paid_at"),
            ("webhook_wait_ms", "chain_paid_at", "webhook_received_at"),
            ("collection_wait_ms", "webhook_received_at", "collection_done_at"),
            ("total_ms", "started_at", "finished_at"),
        ]

        sections = [
            (
                _("Invoice"),
                _percentile_metrics(
                    InvoiceStressCase._meta.db_table,
                    obj.pk,
                    InvoiceStressCaseStatus.SUCCEEDED,
                    invoice_stages,
                ),
            ),
            (
                _("Deposit"),
                _percentile_metrics(
                    DepositStressCase._meta.db_table,
                    obj.pk,
                    DepositStressCaseStatus.SUCCEEDED,
                    deposit_stages,
                ),
            ),
        ]

        # 过滤掉完全无数据的 section
        sections = [(title, rows) for title, rows in sections if rows]
        if not sections:
            return _("无数据可聚合")

        parts: list[str] = []
        for title, rows in sections:
            parts.append(f"<h4 style='margin:8px 0 4px 0'>{title}</h4>")
            parts.append(
                "<table style='border-collapse:collapse;margin-bottom:8px'>"
                "<thead><tr>"
                "<th style='text-align:left;padding:2px 12px 2px 0'>stage</th>"
                "<th style='text-align:right;padding:2px 12px 2px 0'>n</th>"
                "<th style='text-align:right;padding:2px 12px 2px 0'>P50 (ms)</th>"
                "<th style='text-align:right;padding:2px 12px 2px 0'>P95 (ms)</th>"
                "<th style='text-align:right;padding:2px 12px 2px 0'>P99 (ms)</th>"
                "<th style='text-align:right;padding:2px 12px 2px 0'>max (ms)</th>"
                "</tr></thead><tbody>"
            )
            parts.extend(
                "<tr>"
                f"<td style='padding:2px 12px 2px 0'>{r['label']}</td>"
                f"<td style='text-align:right;padding:2px 12px 2px 0'>{r['count']}</td>"
                f"<td style='text-align:right;padding:2px 12px 2px 0'>{r['p50_ms']}</td>"
                f"<td style='text-align:right;padding:2px 12px 2px 0'>{r['p95_ms']}</td>"
                f"<td style='text-align:right;padding:2px 12px 2px 0'>{r['p99_ms']}</td>"
                f"<td style='text-align:right;padding:2px 12px 2px 0'>{r['max_ms']}</td>"
                "</tr>"
                for r in rows
            )
            parts.append("</tbody></table>")

        # 整个 HTML 由我们自行拼接，所有数据来自 PostgreSQL 聚合的数值/常量标签，
        # 没有用户可控字符串，可安全标记为 safe。
        return mark_safe("".join(parts))  # noqa: S308

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change and obj.status == StressRunStatus.DRAFT:
            obj.status = StressRunStatus.PREPARING
            obj.save(update_fields=["status"])
            transaction.on_commit(lambda: prepare_stress.delay(obj.pk))
            messages.success(request, _("测试数据正在后台准备，稍后刷新页面查看状态"))

    @admin.action(description=_("开始执行"))
    def start_stress(self, request, queryset):
        started = 0
        for stress in queryset:
            if stress.status != StressRunStatus.READY:
                messages.warning(
                    request,
                    _("%(name)s 状态为 %(status)s，只有就绪状态才能执行")
                    % {"name": stress.name, "status": stress.get_status_display()},
                )
                continue
            StressService.start(stress)
            started += 1

        if started:
            messages.success(request, _("已启动 %(count)d 个测试") % {"count": started})


@admin.register(InvoiceStressCase)
class InvoiceStressCaseAdmin(ModelAdmin):
    ordering = ("stress_run", "sequence")
    list_select_related = ("stress_run",)
    list_display = (
        "display_identity",
        "stress_run",
        "display_status",
        "display_method",
        "display_tx_hash",
        "display_webhook_checks",
        "display_collection",
    )
    list_filter = (
        ("stress_run", RelatedDropdownFilter),
        ("status", ChoicesDropdownFilter),
    )
    search_fields = ("invoice_sys_no", "invoice_out_no", "tx_hash")
    search_help_text = _("支持按账单单号、商户单号或交易哈希搜索")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @display(description=_("用例"), ordering="sequence", header=True)
    def display_identity(self, obj):
        return (f"#{obj.sequence}", obj.invoice_sys_no or fmt.EMPTY_VALUE)

    @display(description=_("状态"), ordering="status", label=STRESS_CASE_STATUS_LABELS)
    def display_status(self, obj):
        return (obj.status, obj.get_status_display())

    @display(description=_("收款方式"))
    def display_method(self, obj):
        return fmt.stacked(obj.crypto, obj.chain)

    @display(description=_("交易哈希"), ordering="tx_hash")
    def display_tx_hash(self, obj):
        return fmt.truncated(obj.tx_hash)

    @display(
        description=_("Webhook 校验"),
        label={"ok": "success", "partial": "warning", "none": ""},
    )
    def display_webhook_checks(self, obj):
        # 四个校验位逐列展示会占掉半屏且难判断结论，压缩成一个「全过 / 部分 / 未收到」标签。
        if not obj.webhook_received:
            return ("none", _("未收到"))
        checks = (
            obj.webhook_signature_ok,
            obj.webhook_payload_ok,
            obj.webhook_nonce_ok,
            obj.webhook_timestamp_ok,
        )
        if all(checks):
            return ("ok", _("全部通过"))
        return (
            "partial",
            _("%(passed)s/4 通过") % {"passed": sum(bool(c) for c in checks)},
        )

    @display(
        description=_("归集"),
        ordering="collection_verified",
        label={"verified": "success", "pending": ""},
    )
    def display_collection(self, obj):
        return (
            ("verified", _("已验证"))
            if obj.collection_verified
            else ("pending", _("未验证"))
        )


@admin.register(DepositStressCase)
class DepositStressCaseAdmin(ModelAdmin):
    ordering = ("stress_run", "sequence")
    list_select_related = ("stress_run",)
    list_display = (
        "display_identity",
        "stress_run",
        "display_status",
        "display_method",
        "display_amount",
        "display_tx_hash",
        "display_webhook_checks",
        "display_collection",
    )
    list_filter = (
        ("stress_run", RelatedDropdownFilter),
        ("status", ChoicesDropdownFilter),
    )
    search_fields = ("customer_uid", "tx_hash", "collection_hash")
    search_help_text = _("支持按客户 UID、交易哈希或归集哈希搜索")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @display(description=_("用例"), ordering="sequence", header=True)
    def display_identity(self, obj):
        return (f"#{obj.sequence}", obj.customer_uid)

    @display(description=_("金额"), ordering="amount")
    def display_amount(self, obj):
        return fmt.number(obj.amount, unit=str(obj.crypto))

    @display(description=_("状态"), ordering="status", label=STRESS_CASE_STATUS_LABELS)
    def display_status(self, obj):
        return (obj.status, obj.get_status_display())

    @display(description=_("收款方式"))
    def display_method(self, obj):
        return fmt.stacked(obj.crypto, obj.chain)

    @display(description=_("交易哈希"), ordering="tx_hash")
    def display_tx_hash(self, obj):
        return fmt.truncated(obj.tx_hash)

    @display(
        description=_("Webhook 校验"),
        label={"ok": "success", "partial": "warning", "none": ""},
    )
    def display_webhook_checks(self, obj):
        # 四个校验位逐列展示会占掉半屏且难判断结论，压缩成一个「全过 / 部分 / 未收到」标签。
        if not obj.webhook_received:
            return ("none", _("未收到"))
        checks = (
            obj.webhook_signature_ok,
            obj.webhook_payload_ok,
            obj.webhook_nonce_ok,
            obj.webhook_timestamp_ok,
        )
        if all(checks):
            return ("ok", _("全部通过"))
        return (
            "partial",
            _("%(passed)s/4 通过") % {"passed": sum(bool(c) for c in checks)},
        )

    @display(
        description=_("归集"),
        ordering="collection_verified",
        label={"verified": "success", "pending": ""},
    )
    def display_collection(self, obj):
        return (
            ("verified", _("已验证"))
            if obj.collection_verified
            else ("pending", _("未验证"))
        )
