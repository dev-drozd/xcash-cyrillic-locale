"""后台列表页 / 详情页的通用展示函数。

统一收口三类反复出现的渲染需求，避免每个 app 各写一份口径不同的实现：
  - 金额与数量：去掉末尾无意义的 0，并用等宽数字让同列小数点对齐；
  - 地址与交易哈希：等宽字体 + 中段省略，完整值放 title；
  - 空值：统一渲染为 EMPTY_VALUE，不要出现 None / 空字符串 / "-" 三种写法并存。

这里只做展示层格式化，不含任何业务判断。
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from django.utils.html import format_html

from common.utils.math import format_decimal_stripped

if TYPE_CHECKING:
    from django.utils.safestring import SafeString

# 全站统一的空值占位符。用 em dash 而非 "-"，在密集表格里更容易和减号区分。
EMPTY_VALUE = "—"

# 哈希/地址在列表页保留的首尾字符数。20 位左右既能人工比对，又不挤占其他列。
TRUNCATE_HEAD = 10
TRUNCATE_TAIL = 8


def empty() -> str:
    return EMPTY_VALUE


def number(value: Decimal | float | None, *, unit: str = "") -> SafeString | str:
    """渲染数量：去尾零 + 等宽数字，单位以次要色跟在数值后。"""
    if value is None:
        return EMPTY_VALUE
    text = (
        format_decimal_stripped(value)
        if isinstance(value, Decimal)
        else f"{value:,}" if isinstance(value, int) else str(value)
    )
    if not unit:
        return format_html('<span class="xc-num whitespace-nowrap">{}</span>', text)
    # 数值与单位必须同行：拆行后同列的小数点错位，扫读金额时极易看错量级。
    return format_html(
        '<span class="xc-num whitespace-nowrap">{} <span class="text-base-400">{}</span></span>',
        text,
        unit,
    )


def usd(value: Decimal | float | None) -> SafeString | str:
    """渲染美元价值：固定两位小数并加千分位，便于跨行比较量级。"""
    if value is None:
        return EMPTY_VALUE
    return format_html(
        '<span class="xc-num whitespace-nowrap">$ {}</span>', f"{Decimal(value):,.2f}"
    )


def truncated(value: str | None, *, title: str | None = None) -> SafeString | str:
    """渲染地址 / 哈希：中段省略，完整值挂 title 供鼠标悬停查看。"""
    if not value:
        return EMPTY_VALUE
    text = str(value)
    if len(text) > TRUNCATE_HEAD + TRUNCATE_TAIL + 1:
        text = f"{text[:TRUNCATE_HEAD]}…{text[-TRUNCATE_TAIL:]}"
    return format_html(
        '<span class="xc-mono" title="{}">{}</span>', title or str(value), text
    )


def mono(value: str | None) -> SafeString | str:
    """渲染完整的等宽文本（详情页地址、哈希、密钥指纹等）。"""
    if not value:
        return EMPTY_VALUE
    return format_html('<span class="xc-mono">{}</span>', value)


def scroll_box(value: object | None) -> SafeString | str:
    """渲染长文本（payload / 原始响应 / 报错堆栈）：限高可滚动，避免撑爆详情页。"""
    if value in (None, "", {}, []):
        return EMPTY_VALUE
    return format_html('<pre class="xc-scroll-box">{}</pre>', value)


def secondary(value: object | None) -> SafeString | str:
    """渲染次要信息（副标题、说明），用弱化色与主字段拉开层级。"""
    if value in (None, ""):
        return EMPTY_VALUE
    return format_html('<span class="text-base-400">{}</span>', value)


def stacked(primary: object, sub: object | None) -> SafeString:
    """两行堆叠：主值在上、补充信息在下，用于在有限列宽里合并强相关字段。"""
    if sub in (None, ""):
        return format_html("{}", primary)
    return format_html(
        '<span class="flex flex-col"><span>{}</span>'
        '<span class="text-base-400 text-xs">{}</span></span>',
        primary,
        sub,
    )
