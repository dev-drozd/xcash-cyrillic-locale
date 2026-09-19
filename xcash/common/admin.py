from django.db import models
from unfold.admin import ModelAdmin as UnfoldModelAdmin
from unfold.admin import StackedInline as UnfoldStackedInline
from unfold.admin import TabularInline as UnfoldTabularInline

from common.admin_display import EMPTY_VALUE


class URLFieldFormfieldMixin:
    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if isinstance(db_field, models.URLField):
            # 后台表单显式采用 https 作为 URLField 默认 scheme，避免依赖 Django 6.0 过渡设置。
            kwargs.setdefault("assume_scheme", "https")
        return super().formfield_for_dbfield(db_field, request, **kwargs)


class XcashAdminDefaultsMixin:
    """全站后台统一的交互与展示默认值。

    收口在基类而不是逐个 ModelAdmin 重复声明，保证任何新增后台页天然一致：
      - empty_value_display：空值口径与 common.admin_display 保持同一个符号；
      - list_filter_submit：筛选面板改为显式提交，避免选多条件时逐项触发整页刷新；
      - warn_unsaved_form：表单有未保存改动时离开页面给出提示，防止误丢配置。
    """

    empty_value_display = EMPTY_VALUE
    list_filter_submit = True
    warn_unsaved_form = True


class ModelAdmin(XcashAdminDefaultsMixin, URLFieldFormfieldMixin, UnfoldModelAdmin):
    pass


class StackedInline(URLFieldFormfieldMixin, UnfoldStackedInline):
    empty_value_display = EMPTY_VALUE


class TabularInline(URLFieldFormfieldMixin, UnfoldTabularInline):
    empty_value_display = EMPTY_VALUE


class ReadOnlyModelAdmin(ModelAdmin):
    # 只读后台没有可提交的表单，未保存提示反而是噪音。
    warn_unsaved_form = False

    def has_change_permission(self, request, obj=None):
        return False  # 禁止编辑

    def has_delete_permission(self, request, obj=None):
        return False  # 禁止删除

    def has_add_permission(self, request):
        return False  # 禁止添加
