"""研报级 matplotlib 图表样式与保存工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

PALETTE = {
    "primary": "#2D4A7A",
    "secondary": "#5B8FD9",
    "accent": "#B8956A",
    "positive": "#0D9488",
    "negative": "#DC4446",
    "purple": "#6D5BD0",
    "neutral": "#64748B",
    "muted": "#94A3B8",
    "text": "#0F172A",
    "grid": "#E8ECF2",
    "bg": "#FAFBFC",
    "up": "#DC4446",
    "down": "#0D9488",
}

SERIES_COLORS = (
    PALETTE["secondary"],
    PALETTE["accent"],
    PALETTE["negative"],
    PALETTE["purple"],
    PALETTE["positive"],
    PALETTE["primary"],
)

FIELD_LABELS: dict[str, str] = {
    "close": "收盘价",
    "volume": "成交量",
    "MA20": "MA20",
    "MA60": "MA60",
    "return": "收益率",
    "cum_return": "累计收益率",
    "drawdown": "回撤",
    "rsi14": "RSI14",
    "macd": "MACD",
    "macd_signal": "信号线",
    "macd_hist": "MACD 柱",
    "today": "日换手",
    "month": "月均值",
    "net_value": "净流入",
    "cum_net_value": "累计净流入",
    "buy_value": "买入金额",
    "sell_value": "卖出金额",
    "pe_ratio_ttm": "PE(TTM)",
    "pb_ratio_ttm": "PB(TTM)",
    "ps_ratio_ttm": "PS(TTM)",
    "margin_balance": "融资余额",
    "short_balance": "融券余额",
    "total_balance": "两融余额",
    "buy_on_margin_value": "融资买入",
    "margin_repayment": "融资偿还",
    "total": "总股本",
    "circulation_a": "流通 A 股",
    "free_circulation": "自由流通",
    "market_cap": "总市值",
    "dividend_yield_ttm": "股息率(TTM)",
    "gross_profit_margin_ttm": "毛利率(TTM)",
    "net_profit_margin_ttm": "净利率(TTM)",
    "debt_to_asset_ratio": "资产负债率",
    "current_ratio": "流动比率",
    "quick_ratio": "速动比率",
    "nav": "净值",
    "total_turnover": "成交额",
    "roe_ttm": "ROE(TTM)",
    "net_profit_growth_ratio_ttm": "净利润增速(TTM)",
    "operating_profit_growth_ratio_ttm": "营业利润增速(TTM)",
    "gross_profit_growth_ratio_ttm": "毛利润增速(TTM)",
    "operating_revenue_growth_ratio_ttm": "营收增速(TTM)",
}

# 米筐 get_factor：以下字段以小数比例存储（0.905 = 90.5%）；debt_to_asset_ratio 为百分数点（12.12 = 12.12%）
FACTOR_DECIMAL_FRACTION_FIELDS = frozenset(
    {
        "gross_profit_margin_ttm",
        "net_profit_margin_ttm",
        "dividend_yield_ttm",
        "roe_ttm",
        "net_profit_growth_ratio_ttm",
        "net_profit_parent_company_growth_ratio_ttm",
        "operating_profit_growth_ratio_ttm",
        "gross_profit_growth_ratio_ttm",
        "operating_revenue_growth_ratio_ttm",
    }
)
FACTOR_PERCENT_POINT_FIELDS = frozenset({"debt_to_asset_ratio"})
FACTOR_MULTIPLE_FIELDS = frozenset({"current_ratio", "quick_ratio", "pe_ratio_ttm", "pb_ratio_ttm", "ps_ratio_ttm"})


def factor_to_chart_scale(field: str, values: Any) -> Any:
    """将因子序列统一为图表可读量纲（百分数点 / 倍数）。"""
    import pandas as pd

    series = pd.to_numeric(pd.Series(values), errors="coerce")
    if field in FACTOR_DECIMAL_FRACTION_FIELDS:
        return series * 100
    return series


def snapshot_bar_value(field: str, value: float | None) -> float | None:
    """快照横条图：同类指标才放在同一坐标轴。"""
    if value is None:
        return None
    if field in FACTOR_DECIMAL_FRACTION_FIELDS:
        return value * 100
    return value


def format_factor_display(field: str, raw_value: Any) -> str | None:
    """因子快照表格：按字段量纲格式化为可读字符串。"""
    from .technical import safe_float

    value = safe_float(raw_value)
    if value is None:
        return None
    if field in FACTOR_DECIMAL_FRACTION_FIELDS:
        return f"{value * 100:.2f}%"
    if field in FACTOR_PERCENT_POINT_FIELDS:
        return f"{value:.2f}%"
    if field in FACTOR_MULTIPLE_FIELDS:
        suffix = " 倍" if field in {"current_ratio", "quick_ratio"} else ""
        return f"{value:.2f}{suffix}"
    if field == "market_cap":
        if abs(value) >= 100_000_000:
            return f"{value / 100_000_000:.2f} 亿"
        if abs(value) >= 10_000:
            return f"{value / 10_000:.2f} 万"
    return f"{value:.4g}"


def compute_rsi(close: Any, *, period: int = 14) -> Any:
    """Wilder 风格 RSI 近似（rolling mean），loss=0 时 RSI=100。"""
    import pandas as pd

    close = pd.to_numeric(pd.Series(close), errors="coerce")
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, pd.NA)
    rsi = 100 - 100 / (1 + rs)
    bull = loss.eq(0) & gain.gt(0)
    return rsi.where(~bull, 100)

_setup_done = False

CJK_FONT_CANDIDATES: tuple[str, ...] = (
    "Microsoft YaHei",
    "PingFang SC",
    "SimHei",
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "Source Han Sans SC",
    "Source Han Sans CN",
    "WenQuanYi Micro Hei",
    "WenQuanYi Zen Hei",
    "Arial Unicode MS",
    "Droid Sans Fallback",
)

CJK_FONT_KEYWORDS: tuple[str, ...] = (
    "noto sans cjk",
    "noto sans sc",
    "source han sans",
    "wenquanyi",
    "wqy",
    "simhei",
    "yahei",
    "pingfang",
    "heiti",
    "songti",
    "fangsong",
    "cjk",
)


def _register_font_from_path(font_manager: Any, font_path: str) -> str | None:
    from pathlib import Path

    path = Path(font_path)
    if not path.is_file():
        return None
    try:
        font_manager.fontManager.addfont(str(path))
        prop = font_manager.FontProperties(fname=str(path))
        return prop.get_name()
    except Exception:
        return None


def pick_cjk_font(font_manager: Any) -> str:
    """选择可用于中文/符号的 sans 字体；Linux 服务器需安装 Noto CJK 或文泉驿。"""
    import os

    for env_key in ("FINAGENT_CJK_FONT_PATH", "FINAGENT_CJK_FONT"):
        custom = os.environ.get(env_key, "").strip()
        if custom:
            registered = _register_font_from_path(font_manager, custom)
            if registered:
                return registered

    available = {getattr(entry, "name", "") for entry in font_manager.fontManager.ttflist}
    for name in CJK_FONT_CANDIDATES:
        if name in available:
            return name

    for entry in font_manager.fontManager.ttflist:
        name = (getattr(entry, "name", "") or "").strip()
        if not name:
            continue
        fname = (getattr(entry, "fname", "") or "").lower()
        blob = f"{name} {fname}"
        lower = blob.lower()
        if "emoji" in lower or "symbol" in lower:
            continue
        if any(keyword in lower for keyword in CJK_FONT_KEYWORDS):
            return name

    return "DejaVu Sans"


# 折线视觉：圆角连接/端点（非数据平滑，仅渲染更顺滑）
LINE_STYLE: dict[str, Any] = {
    "solid_capstyle": "round",
    "solid_joinstyle": "round",
    "antialiased": True,
}


def setup_matplotlib() -> None:
    global _setup_done
    if _setup_done:
        return
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    chosen = pick_cjk_font(font_manager)
    sans = [chosen]
    for name in CJK_FONT_CANDIDATES:
        if name != chosen and name not in sans:
            sans.append(name)
    sans.extend(["DejaVu Sans", "Arial", "sans-serif"])

    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": sans,
            "axes.unicode_minus": False,
            "figure.facecolor": PALETTE["bg"],
            "axes.facecolor": "#FFFFFF",
            "axes.edgecolor": "#CBD5E1",
            "axes.labelcolor": "#475569",
            "axes.titleweight": "600",
            "axes.titlesize": 12.5,
            "axes.labelsize": 9.5,
            "axes.titlepad": 14,
            "xtick.color": "#64748B",
            "ytick.color": "#64748B",
            "xtick.labelsize": 8.5,
            "ytick.labelsize": 8.5,
            "grid.color": PALETTE["grid"],
            "grid.linestyle": "-",
            "grid.linewidth": 0.55,
            "grid.alpha": 0.85,
            "legend.frameon": False,
            "legend.fontsize": 8.5,
            "font.size": 9.5,
            "figure.dpi": 100,
            "savefig.dpi": 180,
            "savefig.facecolor": PALETTE["bg"],
            "savefig.edgecolor": "none",
            "lines.linewidth": 1.75,
            "lines.antialiased": True,
            "lines.solid_capstyle": "round",
            "lines.solid_joinstyle": "round",
            "path.simplify": True,
            "path.simplify_threshold": 0.3,
            "patch.linewidth": 0,
        }
    )
    _setup_done = True


def prepare_date_index(dates: Any) -> tuple[Any, Any]:
    """用交易日序号作 X 轴，避免周末空档造成折线斜拉。"""
    import pandas as pd

    dt = pd.to_datetime(dates, errors="coerce")
    return range(len(dt)), dt


def apply_date_tick_labels(ax: Any, dates: Any, *, max_ticks: int = 7) -> None:
    import pandas as pd

    dt = pd.to_datetime(pd.Series(dates), errors="coerce")
    n = len(dt)
    if n == 0:
        return
    count = min(max_ticks, n)
    if count == 1:
        positions = [0]
    else:
        positions = sorted({int(round(i * (n - 1) / (count - 1))) for i in range(count)})
    span_days = (dt.iloc[-1] - dt.iloc[0]).days if n > 1 else 0
    fmt = "%Y-%m" if span_days > 120 else "%m-%d"
    ax.set_xticks(positions)
    ax.set_xticklabels([dt.iloc[i].strftime(fmt) for i in positions])
    for tick in ax.get_xticklabels():
        tick.set_rotation(0)
        tick.set_ha("center")


def plot_line(
    ax: Any,
    dates: Any,
    y: Any,
    *,
    color: str,
    linewidth: float = 1.75,
    label: str | None = None,
    alpha: float = 1.0,
    zorder: int = 3,
) -> Any:
    """在交易日序号轴上绘制折线（ faithful to data，不做数值平滑）。"""
    import pandas as pd

    x, _ = prepare_date_index(dates)
    values = pd.to_numeric(pd.Series(y), errors="coerce").reset_index(drop=True)
    return ax.plot(
        x,
        values,
        color=color,
        linewidth=linewidth,
        label=label,
        alpha=alpha,
        zorder=zorder,
        **LINE_STYLE,
    )


def bar_on_dates(
    ax: Any,
    dates: Any,
    y: Any,
    *,
    color: str | list[str],
    alpha: float = 0.82,
    width: float = 0.82,
    zorder: int = 2,
) -> Any:
    import pandas as pd

    x, _ = prepare_date_index(dates)
    values = pd.to_numeric(pd.Series(y), errors="coerce").reset_index(drop=True)
    return ax.bar(x, values, color=color, alpha=alpha, width=width, zorder=zorder)


def label(name: str) -> str:
    return FIELD_LABELS.get(name, name.replace("_", " "))


def chart_title(order_book_id: str, chart_key: str, *, extra: str | None = None) -> str:
    from .chart_catalog import CHART_CAPTIONS

    subtitle = CHART_CAPTIONS.get(chart_key, chart_key.replace("_", " "))
    if extra:
        subtitle = f"{subtitle} · {extra}"
    return f"{order_book_id}  ·  {subtitle}"


def new_figure(*, nrows: int = 1, ncols: int = 1, figsize: tuple[float, float] | None = None, sharex: bool = False):
    import matplotlib.pyplot as plt

    setup_matplotlib()
    if figsize is None:
        height = 4.6 if nrows == 1 else 3.2 * nrows + 0.8
        figsize = (10.2, height)
    if nrows == 1 and ncols == 1:
        fig, ax = plt.subplots(figsize=figsize)
        return fig, ax
    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=figsize, sharex=sharex)
    return fig, axes


def style_axes(
    ax: Any,
    *,
    title: str | None = None,
    ylabel: str | None = None,
    xlabel: str | None = None,
    grid: bool = True,
    date_axis: bool = False,
    date_index: Any | None = None,
) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#CBD5E1")
    ax.spines["bottom"].set_color("#CBD5E1")
    ax.tick_params(axis="both", length=0, pad=6)
    if grid:
        ax.grid(True, axis="y", zorder=0)
        ax.set_axisbelow(True)
    if title:
        ax.set_title(title, loc="left", color=PALETTE["text"], fontsize=12.5, fontweight=600, pad=12)
    if ylabel:
        ax.set_ylabel(ylabel, color="#475569", fontsize=9)
    if xlabel:
        ax.set_xlabel(xlabel, color="#475569", fontsize=9)
    if date_index is not None:
        apply_date_tick_labels(ax, date_index)
    elif date_axis:
        style_date_axis(ax)


def style_date_axis(ax: Any) -> None:
    import matplotlib.dates as mdates

    locator = mdates.AutoDateLocator(minticks=4, maxticks=8)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    for tick in ax.get_xticklabels():
        tick.set_rotation(0)
        tick.set_ha("center")


def style_twin_axes(ax: Any) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["right"].set_color("#CBD5E1")
    ax.tick_params(axis="y", colors="#64748B", length=0, pad=6)
    ax.set_axisbelow(True)


def style_legend(ax: Any, *, loc: str = "upper left", ncol: int | None = None) -> None:
    handles, labels_ = ax.get_legend_handles_labels()
    if not handles:
        return
    ax.legend(
        handles,
        labels_,
        loc=loc,
        ncol=ncol or min(len(handles), 4),
        framealpha=0.92,
        borderpad=0.6,
        labelspacing=0.45,
        handlelength=1.8,
        handletextpad=0.6,
    )


def add_zero_line(ax: Any, *, color: str | None = None, linestyle: str = "--") -> None:
    ax.axhline(0, color=color or PALETTE["muted"], linewidth=0.9, linestyle=linestyle, zorder=1)


def add_ref_line(ax: Any, value: float, *, color: str | None = None, linestyle: str = "--") -> None:
    ax.axhline(value, color=color or PALETTE["muted"], linewidth=0.9, linestyle=linestyle, zorder=1)


def to_percent_points(value: float | None) -> float | None:
    """统一利率/收益率量纲为百分数点（3.89 表示 3.89%）。"""
    if value is None:
        return None
    number = float(value)
    if abs(number) <= 1.0:
        return number * 100
    return number


def plot_category_bars(
    ax: Any,
    categories: list[str],
    values: list[float],
    *,
    colors: list[str] | None = None,
    width: float = 0.58,
    show_values: bool = True,
    value_suffix: str = "%",
) -> None:
    palette = colors or [PALETTE["secondary"]] * len(categories)
    ax.bar(categories, values, color=palette, alpha=0.88, width=width, zorder=2)
    if show_values:
        for idx, value in enumerate(values):
            ax.text(
                idx,
                value,
                f"{value:.2f}{value_suffix}",
                ha="center",
                va="bottom" if value >= 0 else "top",
                fontsize=8.5,
                color=PALETTE["text"],
            )


def save_chart(fig: Any, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(pad=1.1)
    fig.savefig(
        path,
        dpi=180,
        facecolor=fig.get_facecolor(),
        edgecolor="none",
        bbox_inches="tight",
        pad_inches=0.22,
    )


def close_figure(fig: Any) -> None:
    import matplotlib.pyplot as plt

    plt.close(fig)
