#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 用量监视 —— 桌面面板（PyQt5 原生绘制）

不依赖浏览器：所有图表用 QPainter 手绘，适合兆芯等 Chromium 无法运行的环境。
数据来自 server.Collector（只读 ~/.workbuddy）。

用法:
    python3 qt_app.py            # 打开窗口
    python3 qt_app.py --shot a.png   # 离屏渲染一张截图后退出
"""

import json
import math
import os
import re
import sys
import time

from PyQt5.QtCore import QDate, QPointF, QProcess, QRectF, QSize, Qt, QTimer
from PyQt5.QtGui import (QBrush, QColor, QFont, QFontMetrics, QIcon, QLinearGradient,
                         QPainter, QPainterPath, QPen, QPixmap, QRadialGradient)
from PyQt5.QtWidgets import (QApplication, QDateEdit, QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
                             QLabel, QMainWindow, QMenu, QPushButton, QScrollArea,
                             QSizePolicy, QVBoxLayout, QWidget)

__version__ = "1.0.0"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def _state_dir():
    """源码运行时写项目内 .runtime；装成系统包后写用户缓存目录。"""
    if os.path.exists(os.path.join(BASE_DIR, "run.sh")):
        d = os.path.join(BASE_DIR, ".runtime")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
            os.path.expanduser("~"), ".cache")
        d = os.path.join(base, "workbuddy-token-monitor")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


STATE_DIR = _state_dir()
UI_CONF = os.path.join(STATE_DIR, "ui.json")


def load_ui_conf():
    try:
        with open(UI_CONF, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_ui_conf(**kv):
    d = load_ui_conf()
    d.update(kv)
    try:
        os.makedirs(os.path.dirname(UI_CONF), exist_ok=True)
        with open(UI_CONF, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception:
        pass


def load_ui_scale():
    try:
        return min(2.0, max(0.75, float(load_ui_conf().get("scale", 1.0))))
    except Exception:
        return 1.0


def save_ui_scale(v):
    save_ui_conf(scale=round(float(v), 2))
import server  # noqa: E402

# ---------------------------------------------------------------- 主题

BG = QColor("#f4f6fb")
PANEL = QColor("#ffffff")
INK = QColor("#0f172a")
INK2 = QColor("#475569")
INK3 = QColor("#94a3b8")
LINE = QColor("#e8ecf4")
LINE2 = QColor("#eef2f8")

INDIGO = QColor("#6366f1")
VIOLET = QColor("#8b5cf6")
CYAN = QColor("#06b6d4")
AMBER = QColor("#f59e0b")
EMERALD = QColor("#10b981")
ROSE = QColor("#f43f5e")
SLATE = QColor("#64748b")

MODEL_COLORS = [INDIGO, CYAN, AMBER, EMERALD, VIOLET, ROSE, SLATE]


def F(px, weight=QFont.Normal):
    f = QFont("Droid Sans Fallback")
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def NUM(px, weight=QFont.Normal):
    f = QFont("DejaVu Sans")
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setStyleStrategy(QFont.PreferAntialias)
    return f


def ago_text(sec):
    if sec < 60:
        return "刚刚"
    if sec < 3600:
        return "%d 分钟" % (sec // 60)
    if sec < 86400:
        return "%d 小时" % (sec // 3600)
    return "%d 天" % (sec // 86400)


def fmt_sec(ms):
    s = (ms or 0) / 1000.0
    if abs(s - round(s)) < 0.05:
        return "%d" % int(round(s))
    return "%.1f" % s


def compact(n):
    n = float(n or 0)
    if n >= 1e9:
        return "%.2fB" % (n / 1e9)
    if n >= 1e6:
        return "%.2fM" % (n / 1e6)
    if n >= 1e4:
        return "%.1fK" % (n / 1e3)
    if n >= 1e3:
        return "%.2fK" % (n / 1e3)
    return "%d" % round(n)


def nice_max(v):
    if not v or v < 1:
        return 10.0
    exp = 10 ** math.floor(math.log10(v))
    f = v / exp
    if f <= 1:
        m = 1
    elif f <= 2:
        m = 2
    elif f <= 2.5:
        m = 2.5
    elif f <= 5:
        m = 5
    else:
        m = 10
    return m * exp


def rr(rect, r):
    p = QPainterPath()
    p.addRoundedRect(rect, r, r)
    return p


def smooth_path(pts):
    path = QPainterPath()
    if not pts:
        return path
    path.moveTo(pts[0])
    n = len(pts)
    for i in range(n - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[i + 2] if i + 2 < n else p2
        c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6.0, p1.y() + (p2.y() - p0.y()) / 6.0)
        c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6.0, p2.y() - (p3.y() - p1.y()) / 6.0)
        path.cubicTo(c1, c2, p2)
    return path


def txt(p, rect, s, font, color, flags=Qt.AlignLeft | Qt.AlignVCenter):
    p.setFont(font)
    p.setPen(color)
    p.drawText(rect, int(flags), s)


# ---------------------------------------------------------------- 卡片基类

class Card(QFrame):
    """白底圆角卡片，子类在 paintEvent 里绘制内容。"""

    def __init__(self, parent=None, pad=18):
        super(Card, self).__init__(parent)
        self.pad = pad
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.fillPath(rr(r, 14), PANEL)
        p.setPen(QPen(LINE, 1))
        p.drawPath(rr(r, 14))
        p.end()

    def _content_rect(self):
        return QRectF(self.pad, self.pad, self.width() - self.pad * 2, self.height() - self.pad * 2)


# ---------------------------------------------------------------- KPI

class KpiCard(Card):
    def __init__(self, label, accent, accent2, tone="#6366f1"):
        super(KpiCard, self).__init__(pad=16)
        self.label = label
        self.accent = QColor(accent)
        self.accent2 = QColor(accent2)
        self.value = "0"
        self.unit = ""
        self.foot = ""
        self.setFixedHeight(104)
        self.setMinimumWidth(150)

    def set_data(self, value, unit, foot):
        self.value = value
        self.unit = unit
        self.foot = foot
        self.update()

    def paintEvent(self, e):
        super(KpiCard, self).paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        shape = rr(QRectF(0.5, 0.5, W - 1, H - 1), 14)

        # 右上角光晕
        p.save()
        p.setClipPath(shape)
        g = QRadialGradient(W - 22, -6, 92)
        c = QColor(self.accent)
        c.setAlpha(38)
        g.setColorAt(0.0, c)
        c2 = QColor(self.accent)
        c2.setAlpha(0)
        g.setColorAt(1.0, c2)
        p.fillRect(0, 0, W, H, QBrush(g))
        # 底部色条
        lg = QLinearGradient(0, 0, W, 0)
        lg.setColorAt(0.0, self.accent)
        lg.setColorAt(1.0, self.accent2)
        p.fillRect(QRectF(0, H - 2.5, W, 2.5), QBrush(lg))
        p.restore()

        # 标签
        txt(p, QRectF(16, 13, W - 32, 16), self.label, F(11), INK3)

        # 数值 + 单位
        fm = QFontMetrics(NUM(27, QFont.DemiBold))
        vw = fm.width(self.value)
        p.setFont(NUM(27, QFont.DemiBold))
        p.setPen(INK)
        p.drawText(QRectF(15, 33, W - 30, 34), int(Qt.AlignLeft | Qt.AlignVCenter), self.value)
        if self.unit:
            txt(p, QRectF(15 + vw + 6, 44, 60, 16), self.unit, F(10), INK3)

        # 脚注
        txt(p, QRectF(16, H - 30, W - 32, 16), self.foot, F(10), INK3)
        p.end()


# ---------------------------------------------------------------- 吞吐面积图

class SpeedChart(Card):
    SPANS = ((15, "15分"), (60, "1时"), (360, "6时"), (1440, "24时"))

    def __init__(self, on_span=None, span=60):
        super(SpeedChart, self).__init__()
        self.series = []
        self.current = 0.0
        self.sub = "等待中"
        self.hover = -1
        self.span = span
        self.on_span = on_span
        self.setMouseTracking(True)
        self.setMinimumHeight(240)

        self.span_btns = []
        for mins, label in self.SPANS:
            b = QPushButton(label, self)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFont(F(9))
            b.setFixedHeight(21)
            b.setChecked(mins == span)
            b.setStyleSheet("""
                QPushButton { border: 1px solid #e8ecf4; background: #ffffff; color: #94a3b8;
                              border-radius: 7px; padding: 0 7px; }
                QPushButton:hover { background: #f7f8fc; color: #475569; }
                QPushButton:checked { background: #eef2ff; color: #4f46e5; border-color: #c7d2fe; }
            """)
            b.clicked.connect(lambda _=False, m=mins: self._pick(m))
            self.span_btns.append((mins, b))

    def resizeEvent(self, e):
        fm = QFontMetrics(F(9))
        x = self.width() - 14
        for mins, b in reversed(self.span_btns):
            w = fm.width(b.text()) + 16
            b.setFixedWidth(w)
            x -= w
            b.move(x, 12)
            x -= 4
        super(SpeedChart, self).resizeEvent(e)

    def _pick(self, mins):
        self.span = mins
        for m, b in self.span_btns:
            b.setChecked(m == mins)
        if self.on_span:
            self.on_span(mins)

    def set_data(self, series, current, sub):
        self.series = series
        self.current = current
        self.sub = sub
        self.update()

    def mouseMoveEvent(self, e):
        if not self.series:
            return
        rect = self._plot()
        n = len(self.series)
        if n < 2 or rect.width() <= 0:
            return
        idx = int(round((e.x() - rect.left()) / (rect.width() / (n - 1))))
        idx = max(0, min(n - 1, idx))
        if idx != self.hover:
            self.hover = idx
            self.update()

    def leaveEvent(self, e):
        self.hover = -1
        self.update()

    def _plot(self):
        return QRectF(46, 82, self.width() - 46 - 18, self.height() - 82 - 32)

    def paintEvent(self, e):
        super(SpeedChart, self).paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W = self.width()

        txt(p, QRectF(18, 14, 200, 18), "生成吞吐", F(13, QFont.DemiBold), INK)
        txt(p, QRectF(84, 15, 120, 16), "tokens/s", F(10), INK3)

        # 大字
        p.setFont(NUM(32, QFont.DemiBold))
        p.setPen(INK)
        p.drawText(QRectF(16, 36, 160, 40), int(Qt.AlignLeft | Qt.AlignVCenter),
                   "%.0f" % self.current)
        fm = QFontMetrics(NUM(32, QFont.DemiBold))
        txt(p, QRectF(18 + fm.width("%.0f" % self.current) + 6, 48, 60, 18),
            "tok/s", F(10), INK3)
        txt(p, QRectF(18 + fm.width("%.0f" % self.current) + 70, 48, 240, 18),
            self.sub, F(10), INK3)

        rect = self._plot()
        if rect.width() <= 10 or rect.height() <= 10:
            p.end()
            return

        vals = [s.get("v", 0) for s in self.series] or [0]
        mx = nice_max(max(vals + [10]))
        n = len(self.series)

        # 网格 + y 轴
        for i in range(6):
            y = rect.top() + rect.height() * i / 5.0
            p.setPen(QPen(LINE2, 1))
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            val = mx - mx * i / 5.0
            txt(p, QRectF(0, y - 8, rect.left() - 8, 16), compact(val), F(9), INK3,
                Qt.AlignRight | Qt.AlignVCenter)

        if n < 2:
            p.end()
            return

        pts = []
        for i, v in enumerate(vals):
            x = rect.left() + rect.width() * i / (n - 1.0)
            y = rect.bottom() - rect.height() * min(v, mx) / mx
            pts.append(QPointF(x, y))

        # 面积
        area = smooth_path(pts)
        area.lineTo(rect.right(), rect.bottom())
        area.lineTo(rect.left(), rect.bottom())
        area.closeSubpath()
        g = QLinearGradient(0, rect.top(), 0, rect.bottom())
        c = QColor(INDIGO)
        c.setAlpha(64)
        g.setColorAt(0.0, c)
        c2 = QColor(VIOLET)
        c2.setAlpha(10)
        g.setColorAt(0.65, c2)
        c3 = QColor(VIOLET)
        c3.setAlpha(0)
        g.setColorAt(1.0, c3)
        p.fillPath(area, QBrush(g))

        # 曲线
        lg = QLinearGradient(rect.left(), 0, rect.right(), 0)
        lg.setColorAt(0.0, INDIGO)
        lg.setColorAt(1.0, QColor("#a855f7"))
        p.setPen(QPen(QBrush(lg), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(smooth_path(pts))

        # 末端光点
        last = pts[-1]
        rg = QRadialGradient(last.x(), last.y(), 14)
        c = QColor(VIOLET)
        c.setAlpha(70)
        rg.setColorAt(0.0, c)
        c2 = QColor(VIOLET)
        c2.setAlpha(0)
        rg.setColorAt(1.0, c2)
        p.setBrush(QBrush(rg))
        p.setPen(Qt.NoPen)
        p.drawEllipse(last, 14, 14)
        p.setBrush(QBrush(QColor("#ffffff")))
        p.setPen(QPen(VIOLET, 2))
        p.drawEllipse(last, 3.6, 3.6)

        # x 轴
        txt(p, QRectF(rect.left(), rect.bottom() + 7, 80, 14), "-60 分钟", F(9), INK3)
        txt(p, QRectF(rect.right() - 80, rect.bottom() + 7, 80, 14), "现在", F(9), INK3,
            Qt.AlignRight | Qt.AlignVCenter)

        self._draw_hover(p, rect, pts)
        p.end()

    def _draw_hover(self, p, rect, pts):
        if not (0 <= self.hover < len(pts)):
            return
        s = self.series[self.hover]
        pt = pts[self.hover]
        p.setPen(QPen(QColor(99, 102, 241, 90), 1, Qt.DashLine))
        p.drawLine(QPointF(pt.x(), rect.top()), QPointF(pt.x(), rect.bottom()))
        p.setBrush(QBrush(QColor("#ffffff")))
        p.setPen(QPen(INDIGO, 2))
        p.drawEllipse(pt, 3.2, 3.2)

        tm = time.localtime(s.get("t", 0) / 1000.0)
        lines = [
            "%02d:%02d" % (tm.tm_hour, tm.tm_min),
            "%s tok/s" % ("%.0f" % s.get("v", 0)),
            "%d 次调用" % s.get("calls", 0),
        ]
        draw_tip(p, pt, lines, self.width(), self.height())


def draw_tip(p, anchor, lines, W, H):
    f0 = F(10, QFont.DemiBold)
    f1 = F(9)
    fm0 = QFontMetrics(f0)
    fm1 = QFontMetrics(f1)
    w = max([fm0.width(lines[0])] + [fm1.width(l) for l in lines[1:]]) + 20
    h = 15 + len(lines) * 14 + 6
    x = min(max(6.0, anchor.x() - w / 2), W - w - 6)
    y = anchor.y() - h - 12
    if y < 4:
        y = anchor.y() + 14
    r = QRectF(x, y, w, h)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor(15, 23, 42, 236)))
    p.drawPath(rr(r, 8))
    txt(p, QRectF(x + 10, y + 7, w - 20, 14), lines[0], f0, QColor("#ffffff"))
    for i, line in enumerate(lines[1:]):
        txt(p, QRectF(x + 10, y + 22 + i * 14, w - 20, 14), line, f1, QColor("#cbd5e1"))


# ---------------------------------------------------------------- 堆叠柱

class UsageChart(Card):
    def __init__(self):
        super(UsageChart, self).__init__()
        self.buckets = []
        self.gran = "hour"
        self.hover = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(250)

    def set_data(self, series):
        self.buckets = series.get("buckets", [])
        self.gran = series.get("granularity", "hour")
        self.update()

    def _plot(self):
        return QRectF(52, 46, self.width() - 52 - 16, self.height() - 46 - 40)

    def mouseMoveEvent(self, e):
        if not self.buckets:
            return
        rect = self._plot()
        n = len(self.buckets)
        if rect.width() <= 0:
            return
        idx = int((e.x() - rect.left()) / (rect.width() / n))
        idx = max(0, min(n - 1, idx))
        if idx != self.hover:
            self.hover = idx
            self.update()

    def leaveEvent(self, e):
        self.hover = -1
        self.update()

    def paintEvent(self, e):
        super(UsageChart, self).paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W = self.width()
        txt(p, QRectF(18, 14, 200, 18), "Token 用量", F(13, QFont.DemiBold), INK)
        txt(p, QRectF(W - 200, 15, 182, 16), "按小时" if self.gran == "hour" else "按天",
            F(10), INK3, Qt.AlignRight | Qt.AlignVCenter)

        rect = self._plot()
        n = len(self.buckets)
        if n == 0 or rect.width() < 10:
            p.end()
            return

        totals = [b["hit"] + b["miss"] + b["out"] for b in self.buckets]
        mx = nice_max(max(totals + [1]))

        for i in range(6):
            y = rect.top() + rect.height() * i / 5.0
            p.setPen(QPen(LINE2, 1))
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            txt(p, QRectF(0, y - 8, rect.left() - 8, 16), compact(mx - mx * i / 5.0),
                F(9), INK3, Qt.AlignRight | Qt.AlignVCenter)

        slot = rect.width() / n
        bw = max(3.0, min(26.0, slot * 0.6))
        base = rect.bottom()

        for i, b in enumerate(self.buckets):
            x = rect.left() + slot * i + (slot - bw) / 2
            y = base
            h1 = rect.height() * b["hit"] / mx
            h2 = rect.height() * b["miss"] / mx
            h3 = rect.height() * b["out"] / mx
            if self.hover == i:
                p.fillRect(QRectF(x - 2, rect.top(), bw + 4, rect.height()),
                           QBrush(QColor(99, 102, 241, 12)))

            if h1 > 0.4:
                c = QColor(CYAN)
                c.setAlpha(200)
                p.fillRect(QRectF(x, y - h1, bw, h1), QBrush(c))
                y -= h1
            if h2 > 0.4:
                c = QColor(AMBER)
                c.setAlpha(220)
                p.fillRect(QRectF(x, y - h2, bw, h2), QBrush(c))
                y -= h2
            if h3 > 0.4:
                c = QColor(VIOLET)
                c.setAlpha(235)
                path = QPainterPath()
                rad = min(3.0, bw / 2, h3)
                path.moveTo(x, y)
                path.lineTo(x, y - h3 + rad)
                path.quadTo(x, y - h3, x + rad, y - h3)
                path.lineTo(x + bw - rad, y - h3)
                path.quadTo(x + bw, y - h3, x + bw, y - h3 + rad)
                path.lineTo(x + bw, y)
                path.closeSubpath()
                p.fillPath(path, QBrush(c))
            elif h1 + h2 > 0.4:
                p.fillRect(QRectF(x, y - 1.5, bw, 1.5), QBrush(QColor(6, 182, 212, 200)))

        # x 标签
        step = max(1, int(math.ceil(n / 8.0)))
        for i in range(0, n, step):
            cx = rect.left() + slot * i + slot / 2
            txt(p, QRectF(cx - 40, base + 7, 80, 14), self.buckets[i]["label"], F(9), INK3,
                Qt.AlignHCenter | Qt.AlignTop)

        if 0 <= self.hover < n:
            b = self.buckets[self.hover]
            x = rect.left() + slot * self.hover + slot / 2
            lines = [
                b["label"],
                "命中 %s" % compact(b["hit"]),
                "未命中 %s" % compact(b["miss"]),
                "输出 %s" % compact(b["out"]),
                "%d 次调用 · %.2f 积分" % (b["calls"], b["credit"]),
            ]
            draw_tip(p, QPointF(x, rect.top() + rect.height() * 0.35), lines,
                     self.width(), self.height())
        p.end()


# ---------------------------------------------------------------- 模型环形

class ModelCard(Card):
    def __init__(self):
        super(ModelCard, self).__init__()
        self.models = []
        self.breakdown = None
        self.selected_model = None
        self.metric = "tokens"  # "tokens" | "credit"
        self.setMinimumHeight(250)
        self.setMinimumWidth(300)
        self.setCursor(Qt.PointingHandCursor)

    def set_data(self, models, breakdown=None, selected_model=None):
        self.models = models
        self.breakdown = breakdown
        self.selected_model = selected_model
        self.update()

    def mousePressEvent(self, e):
        # 点击右上角度量标签或标题切换度量（Token <-> 积分）
        if e.y() < 42 and e.x() > self.width() - 130:
            self.metric = "credit" if self.metric == "tokens" else "tokens"
            self.update()
        super(ModelCard, self).mousePressEvent(e)

    def paintEvent(self, e):
        super(ModelCard, self).paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()

        if self.breakdown and self.selected_model:
            sm = self.selected_model
            disp = sm[:12] + "…" if len(sm) > 13 else sm
            card_title = "模型构成 · %s" % disp
        else:
            card_title = "模型分布"

        txt(p, QRectF(18, 14, 220, 18), card_title, F(13, QFont.DemiBold), INK)

        is_credit = self.metric == "credit"
        tag_rect = QRectF(W - 120, 12, 102, 22)
        p.setPen(QPen(QColor("#c7d2fe") if is_credit else LINE, 1))
        p.setBrush(QBrush(QColor("#eef2ff") if is_credit else QColor("#f8fafc")))
        p.drawPath(rr(tag_rect, 6))
        txt(p, tag_rect, "按积分 ▾" if is_credit else "按 token ▾",
            F(10, QFont.DemiBold if is_credit else QFont.Normal),
            VIOLET if is_credit else INK2, Qt.AlignCenter)

        d = min(H - 60, W * 0.46, 168)
        cx, cy = 18 + d / 2, 46 + (H - 60) / 2
        R, r = d / 2, d / 2 * 0.66

        if self.breakdown:
            parts = self.breakdown["credit_parts"] if is_credit else self.breakdown["token_parts"]
            total = self.breakdown["credit"] if is_credit else self.breakdown["tokens"]
        else:
            parts = None
            total = sum((m["credit"] if is_credit else m["tokens"]) for m in self.models)

        if not total:
            p.setPen(QPen(LINE2, 12))
            p.drawEllipse(QPointF(cx, cy), (R + r) / 2, (R + r) / 2)
            txt(p, QRectF(18, cy - 10, d, 20), "暂无数据", F(10), INK3,
                Qt.AlignHCenter | Qt.AlignVCenter)
            p.end()
            return

        a0 = 90 * 16
        if self.breakdown and parts:
            for item in parts:
                frac = item["share"]
                span = -frac * 360 * 16
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor(item["color"])))
                path = QPainterPath()
                path.arcMoveTo(QRectF(cx - R, cy - R, R * 2, R * 2), a0 / 16.0)
                path.arcTo(QRectF(cx - R, cy - R, R * 2, R * 2), a0 / 16.0, span / 16.0)
                path.arcTo(QRectF(cx - r, cy - r, r * 2, r * 2), (a0 + span) / 16.0, -span / 16.0)
                path.closeSubpath()
                p.drawPath(path)
                a0 += span
        else:
            for i, m in enumerate(self.models):
                val = m["credit"] if is_credit else m["tokens"]
                frac = val / float(total) if total else 0
                span = -frac * 360 * 16
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(MODEL_COLORS[i % len(MODEL_COLORS)]))
                path = QPainterPath()
                path.arcMoveTo(QRectF(cx - R, cy - R, R * 2, R * 2), a0 / 16.0)
                path.arcTo(QRectF(cx - R, cy - R, R * 2, R * 2), a0 / 16.0, span / 16.0)
                path.arcTo(QRectF(cx - r, cy - r, r * 2, r * 2), (a0 + span) / 16.0, -span / 16.0)
                path.closeSubpath()
                p.drawPath(path)
                a0 += span

        # 中心
        center_txt = ("%.2f分" % total) if is_credit else compact(total)
        center_lbl = "总积分" if is_credit else "总 Token"
        txt(p, QRectF(cx - R * 0.7, cy - 18, R * 1.4, 20), center_txt,
            NUM(16 if is_credit else 17, QFont.DemiBold), INK, Qt.AlignHCenter | Qt.AlignVCenter)
        txt(p, QRectF(cx - R * 0.7, cy + 2, R * 1.4, 14), center_lbl, F(9), INK3,
            Qt.AlignHCenter | Qt.AlignVCenter)

        # 图例
        lx = cx + R + 22
        lw = W - lx - 16
        ly = 52
        if self.breakdown and parts:
            for item in parts:
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor(item["color"])))
                p.drawPath(rr(QRectF(lx, ly + 4, 7, 7), 2))
                name = item["name"]
                txt(p, QRectF(lx + 13, ly, 75, 15), name, F(10, QFont.DemiBold), INK2)
                val_str = ("%.2f分" % item["val"]) if is_credit else compact(item["val"])
                pct = item["share"] * 100
                txt(p, QRectF(lx + lw - 90, ly, 90, 15), "%s %.1f%%" % (val_str, pct), NUM(9), INK3,
                    Qt.AlignRight | Qt.AlignVCenter)

                # 第二行：估算价格（积分/1M Token）及配套数据
                price = item.get("price", 0.0)
                price_str = ("%.2f分/M" % price) if price > 0 else "0分/M"
                if is_credit:
                    comp_str = "用量 %s" % compact(item.get("tok", 0))
                else:
                    comp_str = "消耗 %.2f分" % item.get("crd", 0.0)
                txt(p, QRectF(lx + 13, ly + 15, lw - 13, 14),
                    "估算 %s · %s" % (price_str, comp_str), F(9), INK3)
                ly += 33

            avg_p = self.breakdown.get("avg_price", 0.0)
            txt(p, QRectF(lx + 13, ly + 4, lw - 13, 14),
                "综合单价 ~%.2f 分/Mtok" % avg_p, F(9, QFont.DemiBold), QColor("#4f46e5"))
            txt(p, QRectF(lx + 13, ly + 18, lw - 13, 13),
                "* 估算价格 = 积分 / 1M Token", F(8), INK3)
        else:
            models_sorted = sorted(self.models, key=lambda x: -(x["credit"] if is_credit else x["tokens"]))
            for i, m in enumerate(models_sorted[:5]):
                val = m["credit"] if is_credit else m["tokens"]
                pct = val / float(total) * 100 if total else 0
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(MODEL_COLORS[i % len(MODEL_COLORS)]))
                p.drawPath(rr(QRectF(lx, ly + 4, 7, 7), 2))
                name = m["name"]
                f = F(10)
                fm = QFontMetrics(f)
                avail = lw - 76
                while fm.width(name) > avail and len(name) > 4:
                    name = name[:-2]
                txt(p, QRectF(lx + 13, ly, avail, 15), name, f, INK2)
                val_str = ("%.1f分" % m["credit"]) if is_credit else compact(m["tokens"])
                txt(p, QRectF(lx + lw - 72, ly, 72, 15), "%s %.1f%%" % (val_str, pct), NUM(9), INK3,
                    Qt.AlignRight | Qt.AlignVCenter)
                ly += 21
        p.end()


# ---------------------------------------------------------------- 缓存命中率

class CacheChart(Card):
    def __init__(self):
        super(CacheChart, self).__init__()
        self.buckets = []
        self.gran = "hour"
        self.rate = 0.0
        self.hover = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(250)
        self.setMinimumWidth(300)

    def set_data(self, series, rate):
        self.buckets = series.get("buckets", [])
        self.gran = series.get("granularity", "hour")
        self.rate = rate
        self.update()

    def _plot(self):
        return QRectF(40, 48, self.width() - 40 - 14, self.height() - 48 - 38)

    def mouseMoveEvent(self, e):
        if not self.buckets:
            return
        rect = self._plot()
        n = len(self.buckets)
        if rect.width() <= 0:
            return
        idx = int((e.x() - rect.left()) / (rect.width() / n))
        idx = max(0, min(n - 1, idx))
        if idx != self.hover:
            self.hover = idx
            self.update()

    def leaveEvent(self, e):
        self.hover = -1
        self.update()

    def paintEvent(self, e):
        super(CacheChart, self).paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W = self.width()
        txt(p, QRectF(18, 14, 160, 18), "缓存命中率", F(13, QFont.DemiBold), INK)
        p.setFont(NUM(13, QFont.DemiBold))
        p.setPen(EMERALD)
        p.drawText(QRectF(W - 120, 13, 102, 18), int(Qt.AlignRight | Qt.AlignVCenter),
                   "%.1f%%" % (self.rate * 100))

        rect = self._plot()
        n = len(self.buckets)
        if n == 0 or rect.width() < 10:
            p.end()
            return

        for i in range(5):
            y = rect.top() + rect.height() * i / 4.0
            p.setPen(QPen(LINE2, 1))
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            txt(p, QRectF(0, y - 8, rect.left() - 7, 16), "%d%%" % (100 - i * 25),
                F(9), INK3, Qt.AlignRight | Qt.AlignVCenter)

        # 80% 参考线
        y80 = rect.top() + rect.height() * 0.2
        pen = QPen(QColor(16, 185, 129, 120), 1, Qt.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(rect.left(), y80), QPointF(rect.right(), y80))

        pts = []
        segs = []
        cur = []
        for i, b in enumerate(self.buckets):
            denom = b["hit"] + b["miss"]
            x = rect.left() + rect.width() * (i + 0.5) / n
            if denom <= 0:
                if len(cur) > 1:
                    segs.append(cur)
                cur = []
                pts.append(None)
                continue
            y = rect.bottom() - rect.height() * (b["hit"] / float(denom))
            pt = QPointF(x, y)
            pts.append(pt)
            cur.append(pt)
        if len(cur) > 1:
            segs.append(cur)

        for seg in segs:
            area = smooth_path(seg)
            area.lineTo(seg[-1].x(), rect.bottom())
            area.lineTo(seg[0].x(), rect.bottom())
            area.closeSubpath()
            g = QLinearGradient(0, rect.top(), 0, rect.bottom())
            c = QColor(EMERALD)
            c.setAlpha(46)
            g.setColorAt(0.0, c)
            c2 = QColor(EMERALD)
            c2.setAlpha(0)
            g.setColorAt(1.0, c2)
            p.fillPath(area, QBrush(g))
            p.setPen(QPen(EMERALD, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(smooth_path(seg))

        for i, pt in enumerate(pts):
            if pt is None:
                continue
            if n > 40 and i % 3 != 0:
                continue
            p.setBrush(QBrush(QColor("#ffffff")))
            p.setPen(QPen(EMERALD, 1.6))
            p.drawEllipse(pt, 2.4, 2.4)

        step = max(1, int(math.ceil(n / 6.0)))
        for i in range(0, n, step):
            cx = rect.left() + rect.width() * (i + 0.5) / n
            txt(p, QRectF(cx - 30, rect.bottom() + 7, 60, 14), self.buckets[i]["label"],
                F(9), INK3, Qt.AlignHCenter | Qt.AlignTop)

        if 0 <= self.hover < n:
            b = self.buckets[self.hover]
            denom = b["hit"] + b["miss"]
            if denom:
                x = rect.left() + rect.width() * (self.hover + 0.5) / n
                y = rect.bottom() - rect.height() * (b["hit"] / float(denom))
                lines = [
                    b["label"],
                    "命中率 %.1f%%" % (b["hit"] / float(denom) * 100),
                    "命中 %s / 未命中 %s" % (compact(b["hit"]), compact(b["miss"])),
                ]
                draw_tip(p, QPointF(x, y), lines, self.width(), self.height())
        p.end()


# ---------------------------------------------------------------- 会话表

class SessionTable(Card):
    COLS = [
        ("会话", 0, 300),
        ("模型", 1, 132),
        ("Token", 2, 76),
        ("调用", 3, 56),
        ("命中率", 4, 74),
        ("速度", 5, 62),
        ("积分", 6, 58),
        ("上下文", 7, 120),
    ]

    MODEL_COLS = [
        ("模型名称", 0, 240),
        ("Token 总量", 1, 90),
        ("输入 / 输出", 2, 130),
        ("缓存命中率", 3, 80),
        ("调用次数", 4, 70),
        ("平均速度", 5, 75),
        ("积分消耗", 6, 85),
        ("积分占比", 7, 80),
    ]

    def __init__(self):
        super(SessionTable, self).__init__(pad=0)
        self.rows = []
        self.models = []
        self.tab = "sessions"  # "sessions" | "models"
        self.hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def set_data(self, rows, models=None):
        self.rows = rows[:6]
        if models is not None:
            self.models = models
        count = len(self.rows) if self.tab == "sessions" else len(self.models)
        h = 80 + 42 * max(1, count)
        self.setFixedHeight(h)
        self.update()

    def mousePressEvent(self, e):
        if e.y() < 38:
            old = self.tab
            if e.x() < 125:
                self.tab = "sessions"
            elif 125 <= e.x() < 280:
                self.tab = "models"
            if old != self.tab:
                count = len(self.rows) if self.tab == "sessions" else len(self.models)
                self.setFixedHeight(80 + 42 * max(1, count))
                self.update()
        super(SessionTable, self).mousePressEvent(e)

    def mouseMoveEvent(self, e):
        cur_len = len(self.rows) if self.tab == "sessions" else len(self.models)
        idx = int((e.y() - 44) / 42)
        idx = idx if 0 <= idx < cur_len else -1
        if idx != self.hover:
            self.hover = idx
            self.update()

    def leaveEvent(self, e):
        self.hover = -1
        self.update()

    def paintEvent(self, e):
        super(SessionTable, self).paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W = self.width()

        is_sess = self.tab == "sessions"
        txt(p, QRectF(18, 14, 100, 18), "会话用量排行",
            F(13, QFont.DemiBold if is_sess else QFont.Normal),
            INK if is_sess else INK3)
        txt(p, QRectF(128, 14, 140, 18), "模型用量与积分明细",
            F(13, QFont.DemiBold if not is_sess else QFont.Normal),
            INK if not is_sess else INK3)

        ind_x = 18 if is_sess else 128
        ind_w = 82 if is_sess else 128
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(INDIGO))
        p.drawPath(rr(QRectF(ind_x, 34, ind_w, 2.5), 1.2))

        txt(p, QRectF(W - 260, 15, 242, 16),
            "上下文占用为当前窗口" if is_sess else "按模型查看累计消耗与积分",
            F(10), INK3, Qt.AlignRight | Qt.AlignVCenter)

        y = 44
        left = 20
        p.setPen(QPen(LINE2, 1))
        p.drawLine(QPointF(18, y), QPointF(W - 18, y))

        if is_sess:
            fixed = sum(c[2] for c in self.COLS[1:])
            spare = W - left - 20 - fixed
            title_w = max(220, min(spare, 420))
            ctx_extra = max(0, spare - title_w)
            widths = [title_w] + [c[2] for c in self.COLS[1:-1]] + [self.COLS[-1][2] + ctx_extra]

            x = left
            for i, (name, _, _) in enumerate(self.COLS):
                align = Qt.AlignLeft | Qt.AlignVCenter
                if i >= 2:
                    align = Qt.AlignRight | Qt.AlignVCenter
                txt(p, QRectF(x, y + 5, widths[i] - 8, 16), name, F(10), INK3, align)
                x += widths[i]

            if not self.rows:
                txt(p, QRectF(18, y + 50, W - 36, 20), "当前范围还没有会话记录", F(11), INK3,
                    Qt.AlignHCenter)
                p.end()
                return

            for ri, r in enumerate(self.rows):
                ry = y + 26 + ri * 42
                if self.hover == ri:
                    p.fillPath(rr(QRectF(10, ry - 4, W - 20, 40), 8),
                               QBrush(QColor(99, 102, 241, 9)))
                x = left

                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(INDIGO if ri == 0 else QColor("#eef2f7")))
                p.drawPath(rr(QRectF(x, ry + 6, 17, 17), 5))
                txt(p, QRectF(x, ry + 6, 17, 17), str(ri + 1), NUM(9, QFont.Bold),
                    QColor("#ffffff") if ri == 0 else INK3, Qt.AlignCenter)

                tw = widths[0] - 28
                name = r["title"]
                fm = QFontMetrics(F(11))
                while fm.width(name) > tw and len(name) > 4:
                    name = name[:-2] + "…"
                txt(p, QRectF(x + 24, ry + 1, tw, 17), name, F(12), INK)
                path = re.sub(r"^/home/[^/]+", "~", r.get("cwd", "")) if r.get("cwd") else ""
                fm2 = QFontMetrics(F(9))
                while fm2.width(path) > tw and len(path) > 6:
                    path = path[:-2] + "…"
                txt(p, QRectF(x + 24, ry + 19, tw, 14), path, F(9), INK3)
                x += widths[0]

                mw = widths[1] - 10
                mn = r["model"]
                fmm = QFontMetrics(F(9))
                while fmm.width(mn) > mw - 14 and len(mn) > 5:
                    mn = mn[:-2]
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor("#f1f5f9")))
                p.drawPath(rr(QRectF(x, ry + 9, min(mw, fmm.width(mn) + 16), 17), 5))
                txt(p, QRectF(x + 7, ry + 9, mw, 17), mn, F(9), INK2)
                x += widths[1]

                txt(p, QRectF(x, ry + 8, widths[2] - 8, 18), compact(r["tokens"]),
                    NUM(11), INK2, Qt.AlignRight | Qt.AlignVCenter)
                x += widths[2]
                txt(p, QRectF(x, ry + 8, widths[3] - 8, 18), str(r["calls"]),
                    NUM(11), INK2, Qt.AlignRight | Qt.AlignVCenter)
                x += widths[3]

                hr = r["hit_rate"]
                col = EMERALD if hr >= 0.9 else (AMBER if hr >= 0.6 else ROSE)
                bg = QColor(col)
                bg.setAlpha(26)
                pill = QRectF(x + widths[4] - 60, ry + 9, 50, 18)
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(bg))
                p.drawPath(rr(pill, 9))
                txt(p, pill, "%.1f%%" % (hr * 100), NUM(9), col, Qt.AlignCenter)
                x += widths[4]

                txt(p, QRectF(x, ry + 8, widths[5] - 8, 18),
                    "%.0f" % r["speed"] if r["speed"] else "—", NUM(10), INK2,
                    Qt.AlignRight | Qt.AlignVCenter)
                x += widths[5]
                txt(p, QRectF(x, ry + 8, widths[6] - 8, 18),
                    "%.2f" % r["credit"] if r["credit"] else "—", NUM(10), INK2,
                    Qt.AlignRight | Qt.AlignVCenter)
                x += widths[6]

                used, size = r["used"], r["size"]
                if used > 0 and size > 0:
                    ratio = min(1.0, used / float(size))
                    bw = min(widths[7] - 16, 120)
                    p.setPen(Qt.NoPen)
                    p.setBrush(QBrush(QColor("#eef2f7")))
                    p.drawPath(rr(QRectF(x, ry + 8, bw, 5), 2.5))
                    p.setBrush(QBrush(INDIGO))
                    p.drawPath(rr(QRectF(x, ry + 8, max(3.0, bw * ratio), 5), 2.5))
                    txt(p, QRectF(x, ry + 18, bw, 14),
                        "%s / %s · %.0f%%" % (compact(used), compact(size), ratio * 100),
                        NUM(8), INK3)
                else:
                    txt(p, QRectF(x, ry + 10, widths[7] - 16, 16), "—", NUM(9), INK3)
        else:
            # 模型明细表
            m_fixed = sum(c[2] for c in self.MODEL_COLS[1:])
            m_widths = [max(180, W - left - 20 - m_fixed)] + [c[2] for c in self.MODEL_COLS[1:]]

            x = left
            for i, (name, _, _) in enumerate(self.MODEL_COLS):
                align = Qt.AlignLeft | Qt.AlignVCenter
                if i >= 1:
                    align = Qt.AlignRight | Qt.AlignVCenter
                txt(p, QRectF(x, y + 5, m_widths[i] - 8, 16), name, F(10), INK3, align)
                x += m_widths[i]

            if not self.models:
                txt(p, QRectF(18, y + 50, W - 36, 20), "当前范围还没有模型调用记录", F(11), INK3,
                    Qt.AlignHCenter)
                p.end()
                return

            for ri, m in enumerate(self.models[:8]):
                ry = y + 26 + ri * 42
                if self.hover == ri:
                    p.fillPath(rr(QRectF(10, ry - 4, W - 20, 40), 8),
                               QBrush(QColor(99, 102, 241, 9)))
                x = left

                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(INDIGO if ri == 0 else QColor("#eef2f7")))
                p.drawPath(rr(QRectF(x, ry + 6, 17, 17), 5))
                txt(p, QRectF(x, ry + 6, 17, 17), str(ri + 1), NUM(9, QFont.Bold),
                    QColor("#ffffff") if ri == 0 else INK3, Qt.AlignCenter)

                tw = m_widths[0] - 28
                mname = m["name"]
                fmm = QFontMetrics(F(11, QFont.DemiBold))
                while fmm.width(mname) > tw - 10 and len(mname) > 4:
                    mname = mname[:-2] + "…"
                txt(p, QRectF(x + 24, ry + 8, tw, 18), mname, F(11, QFont.DemiBold), INK)
                x += m_widths[0]

                txt(p, QRectF(x, ry + 8, m_widths[1] - 8, 18), compact(m["tokens"]),
                    NUM(11, QFont.DemiBold), INK, Qt.AlignRight | Qt.AlignVCenter)
                x += m_widths[1]

                txt(p, QRectF(x, ry + 8, m_widths[2] - 8, 18),
                    "%s / %s" % (compact(m["in"]), compact(m["out"])),
                    NUM(10), INK2, Qt.AlignRight | Qt.AlignVCenter)
                x += m_widths[2]

                hr = m.get("hit_rate", 0.0)
                col = EMERALD if hr >= 0.9 else (AMBER if hr >= 0.6 else ROSE)
                bg = QColor(col)
                bg.setAlpha(26)
                pill = QRectF(x + m_widths[3] - 62, ry + 9, 52, 18)
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(bg))
                p.drawPath(rr(pill, 9))
                txt(p, pill, "%.1f%%" % (hr * 100), NUM(9), col, Qt.AlignCenter)
                x += m_widths[3]

                txt(p, QRectF(x, ry + 8, m_widths[4] - 8, 18), str(m["calls"]),
                    NUM(11), INK2, Qt.AlignRight | Qt.AlignVCenter)
                x += m_widths[4]

                spd = m.get("speed", 0.0)
                txt(p, QRectF(x, ry + 8, m_widths[5] - 8, 18),
                    "%.0f" % spd if spd else "—", NUM(10), INK2,
                    Qt.AlignRight | Qt.AlignVCenter)
                x += m_widths[5]

                txt(p, QRectF(x, ry + 8, m_widths[6] - 8, 18),
                    "%.2f 分" % m["credit"], NUM(11, QFont.DemiBold), AMBER,
                    Qt.AlignRight | Qt.AlignVCenter)
                x += m_widths[6]

                c_share = m.get("credit_share", 0.0) * 100
                txt(p, QRectF(x, ry + 8, m_widths[7] - 8, 18),
                    "%.1f%%" % c_share, NUM(10), INK3,
                    Qt.AlignRight | Qt.AlignVCenter)

        p.end()


# ---------------------------------------------------------------- 实时流

class StreamCard(Card):
    def __init__(self):
        super(StreamCard, self).__init__(pad=0)
        self.rows = []
        self.hover = -1
        self.setMouseTracking(True)

    def set_data(self, rows):
        self.rows = rows[:6]
        self.setFixedHeight(46 + 36 * max(1, len(self.rows)) + 6)
        self.update()

    def mouseMoveEvent(self, e):
        idx = int((e.y() - 46) / 36)
        idx = idx if 0 <= idx < len(self.rows) else -1
        if idx != self.hover:
            self.hover = idx
            self.update()

    def leaveEvent(self, e):
        self.hover = -1
        self.update()

    def paintEvent(self, e):
        super(StreamCard, self).paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W = self.width()
        txt(p, QRectF(18, 14, 200, 18), "实时调用流", F(13, QFont.DemiBold), INK)
        txt(p, QRectF(W - 220, 15, 202, 16), "最新 %d 次" % len(self.rows), F(10), INK3,
            Qt.AlignRight | Qt.AlignVCenter)

        if not self.rows:
            txt(p, QRectF(18, 60, W - 36, 20), "等待新的模型调用…", F(11), INK3,
                Qt.AlignHCenter)
            p.end()
            return

        y = 44
        for i, r in enumerate(self.rows):
            ry = y + i * 36
            if i == 0:
                g = QLinearGradient(14, 0, W * 0.6, 0)
                c = QColor(99, 102, 241)
                c.setAlpha(16)
                g.setColorAt(0.0, c)
                c2 = QColor(99, 102, 241)
                c2.setAlpha(0)
                g.setColorAt(1.0, c2)
                p.fillPath(rr(QRectF(10, ry + 2, W - 20, 32), 8), QBrush(g))
            elif self.hover == i:
                p.fillPath(rr(QRectF(10, ry + 2, W - 20, 32), 8),
                           QBrush(QColor(15, 23, 42, 6)))

            tm = time.localtime(r["t"] / 1000.0)
            txt(p, QRectF(20, ry + 8, 64, 16), time.strftime("%H:%M:%S", tm), NUM(10), INK3)

            mw = 150
            txt(p, QRectF(92, ry + 8, mw, 17), r["model"], F(10), INK2)

            # 缓存构成条
            denom = max(1, r["hit"] + r["miss"])
            bx, bw = 248, max(200, W - 248 - 350)
            if bw > 30:
                hp = bw * r["hit"] / float(denom)
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor("#eef2f7")))
                p.drawPath(rr(QRectF(bx, ry + 13, bw, 6), 3))
                p.setBrush(QBrush(CYAN))
                p.drawPath(rr(QRectF(bx, ry + 13, max(2.0, hp), 6), 3))
                p.setBrush(QBrush(AMBER))
                rest = bw - hp
                if rest > 1:
                    p.drawPath(rr(QRectF(bx + hp, ry + 13, rest, 6), 3))

            txt(p, QRectF(W - 330, ry + 8, 150, 16),
                "%s → %s" % (compact(r["in"]), compact(r["out"])),
                NUM(10), INK3, Qt.AlignRight | Qt.AlignVCenter)

            sp = "%.0f tok/s" % r["speed"] if r["speed"] else "—"
            txt(p, QRectF(W - 160, ry + 8, 62, 16), sp, NUM(11),
                INK if r["speed"] else INK3, Qt.AlignRight | Qt.AlignVCenter)
            txt(p, QRectF(W - 92, ry + 8, 76, 16), "%.2f 分" % r["credit"],
                NUM(10), INK3, Qt.AlignRight | Qt.AlignVCenter)

            if i < len(self.rows) - 1:
                p.setPen(QPen(LINE2, 1))
                p.drawLine(QPointF(18, ry + 35), QPointF(W - 18, ry + 35))
        p.end()


# ---------------------------------------------------------------- 自定义时间对话框

class CustomDateDialog(QDialog):
    def __init__(self, parent=None, initial_start=None, initial_end=None):
        super(CustomDateDialog, self).__init__(parent)
        self.setWindowTitle("选定查询时间")
        self.setFixedSize(360, 230)
        self.setStyleSheet("QDialog { background: #ffffff; }")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)

        title = QLabel("选择用量查询起止日期")
        title.setFont(F(12, QFont.DemiBold))
        title.setStyleSheet("color: #0f172a;")
        lay.addWidget(title)

        pre_lay = QHBoxLayout()
        pre_lay.setSpacing(6)
        today_d = QDate.currentDate()
        for lbl, s_d, e_d in [
            ("今日", today_d, today_d),
            ("昨日", today_d.addDays(-1), today_d.addDays(-1)),
            ("近 7 天", today_d.addDays(-6), today_d),
            ("近 30 天", today_d.addDays(-29), today_d),
            ("本月", QDate(today_d.year(), today_d.month(), 1), today_d),
        ]:
            b = QPushButton(lbl)
            b.setFont(F(10))
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(26)
            b.setStyleSheet("""
                QPushButton { border: 1px solid #e2e8f0; background: #f8fafc; color: #475569;
                              border-radius: 6px; padding: 0 8px; }
                QPushButton:hover { background: #eef2ff; color: #4f46e5; border-color: #c7d2fe; }
            """)
            b.clicked.connect(lambda _=False, sd=s_d, ed=e_d: self._set_dates(sd, ed))
            pre_lay.addWidget(b)
        lay.addLayout(pre_lay)

        form_lay = QHBoxLayout()
        form_lay.setSpacing(8)

        self.start_edit = QDateEdit(self)
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDate(initial_start or today_d.addDays(-7))
        self.start_edit.setFont(F(11))
        self.start_edit.setFixedHeight(32)
        self.start_edit.setStyleSheet("QDateEdit { border: 1px solid #cbd5e1; border-radius: 6px; padding: 4px 8px; color: #0f172a; }")

        sep = QLabel("至")
        sep.setFont(F(11))
        sep.setStyleSheet("color: #94a3b8;")

        self.end_edit = QDateEdit(self)
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDate(initial_end or today_d)
        self.end_edit.setFont(F(11))
        self.end_edit.setFixedHeight(32)
        self.end_edit.setStyleSheet("QDateEdit { border: 1px solid #cbd5e1; border-radius: 6px; padding: 4px 8px; color: #0f172a; }")

        form_lay.addWidget(self.start_edit, 1)
        form_lay.addWidget(sep)
        form_lay.addWidget(self.end_edit, 1)
        lay.addLayout(form_lay)

        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)
        btn_box.addStretch(1)

        cancel_b = QPushButton("取消")
        cancel_b.setFixedHeight(30)
        cancel_b.setFont(F(11))
        cancel_b.setCursor(Qt.PointingHandCursor)
        cancel_b.setStyleSheet("QPushButton { border: 1px solid #e2e8f0; border-radius: 7px; background: #fff; color: #475569; padding: 0 14px; } QPushButton:hover { background: #f8fafc; }")
        cancel_b.clicked.connect(self.reject)
        btn_box.addWidget(cancel_b)

        ok_b = QPushButton("确定查询")
        ok_b.setFixedHeight(30)
        ok_b.setFont(F(11, QFont.DemiBold))
        ok_b.setCursor(Qt.PointingHandCursor)
        ok_b.setStyleSheet("QPushButton { border: none; border-radius: 7px; background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #6366f1, stop:1 #8b5cf6); color: #fff; padding: 0 16px; } QPushButton:hover { opacity: 0.92; }")
        ok_b.clicked.connect(self.accept)
        btn_box.addWidget(ok_b)

        lay.addLayout(btn_box)

    def _set_dates(self, s, e):
        self.start_edit.setDate(s)
        self.end_edit.setDate(e)

    def get_range(self):
        s = self.start_edit.date()
        e = self.end_edit.date()
        if s > e:
            s, e = e, s
        s_ms = int(time.mktime((s.year(), s.month(), s.day(), 0, 0, 0, 0, 0, -1)) * 1000)
        e_ms = int(time.mktime((e.year(), e.month(), e.day(), 23, 59, 59, 0, 0, -1)) * 1000) + 999
        lbl = "%d/%d~%d/%d" % (s.month(), s.day(), e.month(), e.day()) if s != e else "%d/%d" % (s.month(), s.day())
        return s_ms, e_ms, lbl


# ---------------------------------------------------------------- 头部

def layers_icon(color, size=16, dpr=2.0):
    """两个叠放圆角矩形，示意「缩成小窗」。"""
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(color, 1.6))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(1.2, 5.6, 8.2, 8.2), 2.3, 2.3)
    p.drawRoundedRect(QRectF(6.8, 2.2, 8.2, 8.2), 2.3, 2.3)
    p.end()
    return pm


class Header(QWidget):
    def __init__(self, on_range, icon_path=None, on_scale=None, scale=1.0,
                 on_mini=None, on_refresh=None, refresh_ms=1600,
                 on_model=None, on_custom_range=None):
        super(Header, self).__init__()
        self.range = "today"
        self.on_range = on_range
        self.on_scale = on_scale
        self.on_mini = on_mini
        self.on_refresh = on_refresh
        self.refresh_ms = refresh_ms
        self.on_model = on_model
        self.on_custom_range = on_custom_range
        self.current_model = None
        self.scale = scale
        self.status = "正在读取本地记录…"
        self.icon = QPixmap(icon_path) if icon_path and os.path.exists(icon_path) else None
        self.setFixedHeight(62)
        self.buttons = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 4, 2, 4)
        lay.setSpacing(6)

        self.spacer = QWidget()
        self.spacer.setMinimumWidth(200)
        lay.addWidget(self.spacer, 1)

        # 自己在 paintEvent 里画品牌区，这里只放按钮
        self.spacer2 = QWidget()
        self.spacer2.setFixedWidth(4)
        lay.addWidget(self.spacer2)

        for key, label in (("today", "今日"), ("yesterday", "昨日"), ("7d", "近 7 天"),
                           ("30d", "近 30 天"), ("all", "全部")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(30)
            b.setMinimumWidth(56)
            b.setFont(F(11))
            b.setStyleSheet("""
                QPushButton { border: 1px solid #e8ecf4; background: #ffffff; color: #475569;
                              border-radius: 9px; padding: 0 9px; }
                QPushButton:hover { background: #f7f8fc; }
                QPushButton:checked { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                              stop:0 #6366f1, stop:1 #8b5cf6); color: #ffffff; border: none; }
            """)
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            self.buttons.append((key, b))
            lay.addWidget(b)
        self.buttons[0][1].setChecked(True)

        self.custom_btn = QPushButton("自定义 ▾")
        self.custom_btn.setCheckable(True)
        self.custom_btn.setCursor(Qt.PointingHandCursor)
        self.custom_btn.setFixedHeight(30)
        self.custom_btn.setFont(F(11))
        self.custom_btn.setStyleSheet("""
            QPushButton { border: 1px solid #e8ecf4; background: #ffffff; color: #475569;
                          border-radius: 9px; padding: 0 10px; }
            QPushButton:hover { background: #f7f8fc; }
            QPushButton:checked { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                          stop:0 #6366f1, stop:1 #8b5cf6); color: #ffffff; border: none; }
        """)
        self.custom_btn.clicked.connect(self._on_click_custom)
        lay.addWidget(self.custom_btn)

        # 模型筛选
        self.model_btn = QPushButton("模型: 全部 ▾")
        self.model_btn.setFixedHeight(30)
        self.model_btn.setFont(F(11))
        self.model_btn.setCursor(Qt.PointingHandCursor)
        self.model_btn.setStyleSheet("""
            QPushButton { border: 1px solid #e8ecf4; background: #ffffff; color: #475569;
                          border-radius: 9px; padding: 0 10px; }
            QPushButton:hover { background: #f7f8fc; }
            QPushButton::menu-indicator { image: none; width: 0px; }
        """)
        self.model_menu = QMenu(self.model_btn)
        self.model_menu.setFont(F(11))
        self.model_menu.setStyleSheet("""
            QMenu { background: #ffffff; border: 1px solid #e8ecf4; border-radius: 10px;
                    padding: 6px; }
            QMenu::item { padding: 7px 22px 7px 14px; border-radius: 6px; color: #334155; }
            QMenu::item:selected { background: #eef2ff; color: #4f46e5; }
        """)
        self.model_btn.setMenu(self.model_menu)
        lay.addWidget(self.model_btn)

        # 切换悬浮窗（用浅紫底突出，与普通按钮区分）
        self.mini_btn = QPushButton(" 悬浮")
        self.mini_btn.setCursor(Qt.PointingHandCursor)
        self.mini_btn.setFixedHeight(30)
        self.mini_btn.setFont(F(11, QFont.DemiBold))
        self.mini_btn.setToolTip("缩成置顶小窗，随时看关键指标")
        self.mini_btn.setIcon(QIcon(layers_icon(QColor("#4f46e5"))))
        self.mini_btn.setIconSize(QSize(15, 15))
        self.mini_btn.setStyleSheet("""
            QPushButton { border: 1px solid #c7d2fe; background: #eef2ff; color: #4f46e5;
                          border-radius: 9px; padding: 0 11px 0 7px; }
            QPushButton:hover { background: #e0e7ff; border-color: #a5b4fc; }
            QPushButton:pressed { background: #c7d2fe; }
        """)
        self.mini_btn.clicked.connect(lambda: self.on_mini and self.on_mini())
        lay.addWidget(self.mini_btn)

        # 刷新频率
        self.refresh_btn = QPushButton("刷新 ▾")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setFixedHeight(30)
        self.refresh_btn.setFont(F(11))
        self.refresh_btn.setToolTip("刷新间隔，越短越灵敏，也越费 CPU")
        self.refresh_btn.setStyleSheet("""
            QPushButton { border: 1px solid #e8ecf4; background: #ffffff; color: #475569;
                          border-radius: 9px; padding: 0 10px; }
            QPushButton:hover { background: #f7f8fc; }
            QPushButton::menu-indicator { image: none; width: 0px; }
        """)
        rmenu = QMenu(self.refresh_btn)
        rmenu.setFont(F(11))
        rmenu.setStyleSheet("""
            QMenu { background: #ffffff; border: 1px solid #e8ecf4; border-radius: 10px;
                    padding: 6px; }
            QMenu::item { padding: 7px 22px 7px 14px; border-radius: 6px; color: #334155; }
            QMenu::item:selected { background: #eef2ff; color: #4f46e5; }
        """)
        self.refresh_actions = []
        for label, ms in (("0.1 秒（极速）", 100), ("0.3 秒", 300), ("0.8 秒", 800),
                          ("1.6 秒（默认）", 1600), ("3 秒（省电）", 3000)):
            act = rmenu.addAction(label)
            act.setCheckable(True)
            act.setChecked(ms == refresh_ms)
            act.triggered.connect(lambda _=False, v=ms: self._pick_refresh(v))
            self.refresh_actions.append((ms, act))
        self.refresh_btn.setMenu(rmenu)
        lay.addWidget(self.refresh_btn)

        # 字号档位
        self.font_btn = QPushButton("字号 ▾")
        self.font_btn.setCursor(Qt.PointingHandCursor)
        self.font_btn.setFixedHeight(30)
        self.font_btn.setFont(F(11))
        self.font_btn.setStyleSheet("""
            QPushButton { border: 1px solid #e8ecf4; background: #ffffff; color: #475569;
                          border-radius: 9px; padding: 0 10px; }
            QPushButton:hover { background: #f7f8fc; }
            QPushButton::menu-indicator { image: none; width: 0px; }
        """)
        menu = QMenu(self.font_btn)
        menu.setFont(F(11))
        menu.setStyleSheet("""
            QMenu { background: #ffffff; border: 1px solid #e8ecf4; border-radius: 10px;
                    padding: 6px; }
            QMenu::item { padding: 7px 22px 7px 14px; border-radius: 6px; color: #334155; }
            QMenu::item:selected { background: #eef2ff; color: #4f46e5; }
        """)
        self.scale_actions = []
        for label, val in (("小", 0.9), ("标准", 1.0), ("大", 1.15), ("特大", 1.32)):
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(abs(val - scale) < 0.02)
            act.triggered.connect(lambda _=False, v=val: self._pick_scale(v))
            self.scale_actions.append((val, act))
        self.font_btn.setMenu(menu)
        lay.addWidget(self.font_btn)

        self.live = QLabel("● 实时")
        self.live.setFont(F(10))
        self.live.setStyleSheet("color:#059669; background:#ecfdf5; border:1px solid #d1fae5;"
                                "border-radius:10px; padding:4px 10px;")
        lay.addWidget(self.live)

    def _on_click_custom(self):
        dlg = CustomDateDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            s_ms, e_ms, lbl = dlg.get_range()
            self.range = "custom"
            for _, b in self.buttons:
                b.setChecked(False)
            self.custom_btn.setChecked(True)
            self.custom_btn.setText(lbl + " ▾")
            if self.on_custom_range:
                self.on_custom_range(s_ms, e_ms, lbl)
        else:
            if self.range != "custom":
                self.custom_btn.setChecked(False)

    def _pick(self, key):
        self.range = key
        for k, b in self.buttons:
            b.setChecked(k == key)
        self.custom_btn.setChecked(False)
        self.custom_btn.setText("自定义 ▾")
        self.on_range(key)

    def update_models_menu(self, models, current_model=None):
        self.current_model = current_model
        if current_model:
            disp = current_model[:12] + "…" if len(current_model) > 13 else current_model
            self.model_btn.setText("模型: %s ▾" % disp)
            self.model_btn.setStyleSheet("""
                QPushButton { border: 1px solid #c7d2fe; background: #eef2ff; color: #4f46e5;
                              border-radius: 9px; padding: 0 10px; font-weight: bold; }
                QPushButton::menu-indicator { image: none; width: 0px; }
            """)
        else:
            self.model_btn.setText("模型: 全部 ▾")
            self.model_btn.setStyleSheet("""
                QPushButton { border: 1px solid #e8ecf4; background: #ffffff; color: #475569;
                              border-radius: 9px; padding: 0 10px; }
                QPushButton:hover { background: #f7f8fc; }
                QPushButton::menu-indicator { image: none; width: 0px; }
            """)
        self.model_menu.clear()
        act_all = self.model_menu.addAction("全部模型")
        act_all.setCheckable(True)
        act_all.setChecked(not current_model)
        act_all.triggered.connect(lambda: self.on_model and self.on_model(None))
        for m in models:
            name = m["name"]
            lbl = "%s (%s tok · %.1f分)" % (name, compact(m["tokens"]), m["credit"])
            act = self.model_menu.addAction(lbl)
            act.setCheckable(True)
            act.setChecked(bool(current_model and current_model.lower() == name.lower()))
            act.triggered.connect(lambda _=False, nm=name: self.on_model and self.on_model(nm))

    def _pick_scale(self, val):
        for v, act in self.scale_actions:
            act.setChecked(abs(v - val) < 0.02)
        if self.on_scale:
            self.on_scale(val)

    def _pick_refresh(self, ms):
        self.refresh_ms = ms
        for v, act in self.refresh_actions:
            act.setChecked(v == ms)
        if self.on_refresh:
            self.on_refresh(ms)

    def set_status(self, text, ok=True):
        self.status = text
        self.live.setText("● 实时" if ok else "● 暂停")
        self.live.setStyleSheet(
            "color:%s; background:%s; border:1px solid %s; border-radius:10px; padding:4px 10px;"
            % ("#059669", "#ecfdf5", "#d1fae5") if ok
            else "color:#94a3b8; background:#f8fafc; border:1px solid #e8ecf4;"
                 "border-radius:10px; padding:4px 10px;")
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        x = 2
        if self.icon is not None:
            p.drawPixmap(QRectF(x, 10, 38, 38).toRect(), self.icon)
            x += 50
        max_w = max(160, self.spacer.width() + 44)
        txt(p, QRectF(x, 10, max_w, 22), "WorkBuddy 用量监视", F(16, QFont.DemiBold), INK)
        font10 = F(10)
        p.setFont(font10)
        metrics = QFontMetrics(font10)
        elided = metrics.elidedText(self.status, Qt.ElideRight, max_w)
        txt(p, QRectF(x + 1, 33, max_w, 16), elided, font10, INK3)
        p.end()


# ---------------------------------------------------------------- 悬浮小窗

class MiniWindow(QWidget):
    """置顶小窗：只显示关键指标，可拖动，双击还原完整面板。"""

    def __init__(self, collector, on_expand, on_quit, refresh_ms=1600):
        super(MiniWindow, self).__init__(None)
        self.collector = collector
        self.on_expand = on_expand
        self.on_quit = on_quit
        self.data = None
        self._drag = None
        self.refresh_ms = int(refresh_ms)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(326, 158)
        self.setWindowTitle("WorkBuddy 用量")
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("拖动可移动，双击展开完整面板")

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(26)
        shadow.setColor(QColor(15, 23, 42, 78))
        shadow.setOffset(0, 5)
        self.setGraphicsEffect(shadow)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)

    # -- 数据
    def set_refresh(self, ms):
        self.refresh_ms = int(ms)
        if self.timer.isActive():
            self.timer.start(self.refresh_ms)

    def showEvent(self, e):
        self.timer.start(self.refresh_ms)
        self.refresh()
        super(MiniWindow, self).showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        super(MiniWindow, self).hideEvent(e)

    def refresh(self):
        try:
            self.collector.scan()
            self.data = self.collector.snapshot("today", 60)
        except Exception:
            return
        self.update()

    # -- 交互
    def _r_expand(self):
        return QRectF(self.width() - 64, 11, 18, 18)

    def _r_close(self):
        return QRectF(self.width() - 34, 11, 18, 18)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = QPointF(e.pos())
        if self._r_close().contains(pos):
            self.on_quit()
            return
        if self._r_expand().contains(pos):
            self.on_expand()
            return
        self._drag = e.globalPos() - self.frameGeometry().topLeft()
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag is not None and (e.buttons() & Qt.LeftButton):
            self.move(e.globalPos() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, e):
        self.on_expand()

    # -- 绘制
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()

        shape = rr(QRectF(1, 1, W - 2, H - 2), 16)
        p.fillPath(shape, QColor(255, 255, 255, 250))
        p.setPen(QPen(QColor("#e3e8f2"), 1))
        p.drawPath(shape)

        # 标题
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(EMERALD))
        p.drawEllipse(QPointF(18, 20), 3.2, 3.2)
        txt(p, QRectF(27, 12, 150, 16), "WorkBuddy 用量", F(10, QFont.DemiBold), INK2)

        # 展开 / 关闭
        r = self._r_expand()
        p.setPen(QPen(INK3, 1.3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(r.left() + 4, r.bottom() - 4), QPointF(r.right() - 4, r.top() + 4))
        p.drawLine(QPointF(r.right() - 4, r.top() + 4), QPointF(r.right() - 8.5, r.top() + 4))
        p.drawLine(QPointF(r.right() - 4, r.top() + 4), QPointF(r.right() - 4, r.top() + 8.5))

        c = self._r_close()
        p.drawLine(QPointF(c.left() + 4.5, c.top() + 4.5), QPointF(c.right() - 4.5, c.bottom() - 4.5))
        p.drawLine(QPointF(c.right() - 4.5, c.top() + 4.5), QPointF(c.left() + 4.5, c.bottom() - 4.5))

        data = self.data or {}
        k = data.get("kpi") or {}
        gen = data.get("generated_at") or 0

        # 取最近一次调用，而不是窗口内的平均值——悬浮窗要的是「此刻」
        rows = data.get("recent") or []
        last = rows[0] if rows else None
        speed = 0.0
        idle = False
        if last is None:
            sub = "等待调用"
        else:
            speed = last.get("speed") or 0.0
            age = max(0.0, (gen - last["t"]) / 1000.0)
            if age > 180:
                idle = True
                sub = "空闲 · %s前" % ago_text(age)
            else:
                sub = "tok/s · %s · 输出 %s" % (
                    time.strftime("%H:%M:%S", time.localtime(last["t"] / 1000.0)),
                    compact(last.get("out") or 0))

        p.setFont(NUM(30, QFont.DemiBold))
        p.setPen(INK3 if idle else INK)
        p.drawText(QRectF(16, 30, 120, 34), int(Qt.AlignLeft | Qt.AlignVCenter), "%.0f" % speed)
        txt(p, QRectF(17, 63, 190, 13), sub, F(9), INK3)

        txt(p, QRectF(W - 168, 31, 152, 22), compact(k.get("tokens", 0)),
            NUM(17, QFont.DemiBold), INK, Qt.AlignRight | Qt.AlignVCenter)
        txt(p, QRectF(W - 168, 55, 152, 13), "今日 Token", F(9), INK3,
            Qt.AlignRight | Qt.AlignVCenter)

        # 迷你吞吐曲线
        rect = QRectF(16, 80, W - 32, 28)
        series = data.get("speeds") or []
        if len(series) > 1:
            vals = [s.get("v", 0) for s in series]
            mx = nice_max(max(vals + [10]))
            n = len(vals)
            pts = []
            for i, v in enumerate(vals):
                x = rect.left() + rect.width() * i / (n - 1.0)
                y = rect.bottom() - rect.height() * min(v, mx) / mx
                pts.append(QPointF(x, y))

            area = smooth_path(pts)
            area.lineTo(rect.right(), rect.bottom())
            area.lineTo(rect.left(), rect.bottom())
            area.closeSubpath()
            fill = QColor(INDIGO)
            fill.setAlpha(36)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(fill))
            p.drawPath(area)

            lg = QLinearGradient(rect.left(), 0, rect.right(), 0)
            lg.setColorAt(0.0, INDIGO)
            lg.setColorAt(1.0, QColor("#a855f7"))
            p.setPen(QPen(QBrush(lg), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(smooth_path(pts))

            p.setBrush(QBrush(QColor("#ffffff")))
            p.setPen(QPen(VIOLET, 1.5))
            p.drawEllipse(pts[-1], 2.6, 2.6)

        # 分隔与底部指标
        p.setPen(QPen(QColor("#eef2f8"), 1))
        p.drawLine(QPointF(16, 116), QPointF(W - 16, 116))

        line = "命中 %.1f%%   ·   %d 次   ·   %.1f 分" % (
            (k.get("hit_rate") or 0) * 100, k.get("calls") or 0, k.get("credit") or 0)
        txt(p, QRectF(16, 124, W - 32, 14), line, F(9), INK3)
        p.end()


# ---------------------------------------------------------------- 主窗口

class MainWindow(QMainWindow):
    def __init__(self, collector):
        super(MainWindow, self).__init__()
        self.collector = collector
        self.range = "today"
        self.speed_span = 60
        self.custom_start = None
        self.custom_end = None
        self.model_filter = None
        self.paused = False
        self.last = None
        self.mini = None

        conf = load_ui_conf()
        try:
            self.refresh_ms = max(80, int(conf.get("refresh_ms", 1600)))
        except Exception:
            self.refresh_ms = 1600
        self._last_paint = 0.0
        self._last_version = -1

        self.setWindowTitle("WorkBuddy 用量监视")
        icon = os.path.join(BASE_DIR, "web", "icon.png")
        if os.path.exists(icon):
            self.setWindowIcon(QIcon(icon))
        scr = QApplication.primaryScreen()
        area = scr.availableGeometry() if scr else None
        if area and area.width() > 800:
            w = min(1340, int(area.width() * 0.94))
            h = min(980, int(area.height() * 0.94))
        else:
            w, h = 1200, 840
        self.resize(max(1040, w), max(640, h))
        self.setMinimumSize(1000, 620)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;}"
                             "QScrollBar:vertical{background:transparent;width:9px;margin:0;}"
                             "QScrollBar::handle:vertical{background:#d5dbe7;border-radius:4px;"
                             "min-height:40px;}"
                             "QScrollBar::handle:vertical:hover{background:#c2c9d8;}"
                             "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
                             "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:none;}")
        self.setCentralWidget(scroll)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self.content = content
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(22, 14, 22, 20)
        root.setSpacing(14)

        self.header = Header(self._on_range, icon, self._on_scale, load_ui_scale(),
                             self._toggle_mini, self._on_refresh, self.refresh_ms,
                             on_model=self._on_model_filter,
                             on_custom_range=self._on_custom_range)
        root.addWidget(self.header)

        # KPI
        row = QHBoxLayout()
        row.setSpacing(12)
        self.kpis = {
            "tokens": KpiCard("总 Token", "#6366f1", "#8b5cf6"),
            "hit": KpiCard("缓存命中率", "#0891b2", "#06b6d4"),
            "speed": KpiCard("平均生成速度", "#7c3aed", "#a78bfa"),
            "credit": KpiCard("积分消耗", "#d97706", "#f59e0b"),
            "calls": KpiCard("调用次数", "#475569", "#94a3b8"),
        }
        for k in ("tokens", "hit", "speed", "credit", "calls"):
            row.addWidget(self.kpis[k], 1)
        root.addLayout(row)

        # 图表行 1
        r1 = QHBoxLayout()
        r1.setSpacing(14)
        self.speed_chart = SpeedChart(self._on_span, self.speed_span)
        self.model_card = ModelCard()
        r1.addWidget(self.speed_chart, 155)
        r1.addWidget(self.model_card, 100)
        root.addLayout(r1)

        # 图表行 2
        r2 = QHBoxLayout()
        r2.setSpacing(14)
        self.usage_chart = UsageChart()
        self.cache_chart = CacheChart()
        r2.addWidget(self.usage_chart, 155)
        r2.addWidget(self.cache_chart, 100)
        root.addLayout(r2)

        self.session_table = SessionTable()
        root.addWidget(self.session_table)

        self.stream_card = StreamCard()
        root.addWidget(self.stream_card)

        foot = QWidget()
        foot.setFixedHeight(22)
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(0, 0, 0, 0)
        self.foot_label = QLabel("数据源：~/.workbuddy")
        self.foot_label.setFont(F(9))
        self.foot_label.setStyleSheet("color:#94a3b8;")
        fl.addWidget(self.foot_label, 0, Qt.AlignCenter)
        root.addWidget(foot)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(self.refresh_ms)

        self.refresh()

    def _on_range(self, key):
        self.range = key
        self.custom_start = None
        self.custom_end = None
        self._last_version = -1
        self.refresh()

    def _on_custom_range(self, s_ms, e_ms, lbl):
        self.range = "custom"
        self.custom_start = s_ms
        self.custom_end = e_ms
        self._last_version = -1
        self.refresh()

    def _on_model_filter(self, model_name):
        self.model_filter = model_name
        self._last_version = -1
        self.refresh()

    def _on_span(self, mins):
        self.speed_span = mins
        self._last_version = -1
        self.refresh()

    def _on_refresh(self, ms):
        self.refresh_ms = max(80, int(ms))
        self.timer.start(self.refresh_ms)
        save_ui_conf(refresh_ms=self.refresh_ms)
        if self.mini is not None:
            self.mini.set_refresh(self.refresh_ms)
        self._last_version = -1
        self.refresh()

    # ---- 悬浮窗
    def _toggle_mini(self):
        if self.mini is None:
            self.mini = MiniWindow(self.collector, self._back_from_mini, QApplication.quit,
                                   self.refresh_ms)
            scr = QApplication.primaryScreen()
            area = scr.availableGeometry() if scr else None
            if area:
                self.mini.move(area.right() - self.mini.width() - 28, area.top() + 28)
        self.mini.refresh()
        self.mini.show()
        self.mini.raise_()
        self.timer.stop()
        self.hide()

    def _back_from_mini(self):
        if self.mini is not None:
            self.mini.hide()
        self.show()
        self.raise_()
        self.activateWindow()
        self.timer.start()
        self.refresh()

    def closeEvent(self, e):
        if self.mini is not None:
            self.mini.close()
            self.mini = None
        super(MainWindow, self).closeEvent(e)

    def _on_scale(self, val):
        save_ui_scale(val)
        # 通过 QT_SCALE_FACTOR 整体缩放，需重启进程生效
        args = []
        skip = False
        for a in sys.argv[1:]:
            if skip:
                skip = False
                continue
            if a == "--shot":
                skip = True
                continue
            args.append(a)
        QProcess.startDetached(sys.executable,
                              [os.path.abspath(__file__)] + args,
                              BASE_DIR)
        QApplication.quit()

    def refresh(self):
        if self.paused:
            return
        try:
            self.collector.scan()
            data = self.collector.snapshot(self.range, self.speed_span,
                                           start_ms=self.custom_start,
                                           end_ms=self.custom_end,
                                           model=self.model_filter)
        except Exception as e:
            self.header.set_status("读取失败：%s" % e, ok=False)
            return

        # 数据没变化且刚画过，跳过整轮重绘（高频刷新时省 CPU）
        ver = getattr(self.collector, "version", 0)
        now_t = time.time()
        if ver == self._last_version and (now_t - self._last_paint) < 0.2:
            return
        self._last_paint = now_t
        self._last_version = ver

        self.last = data
        k = data["kpi"]

        self.kpis["tokens"].set_data(
            compact(k["tokens"]), "",
            "输入 %s · 输出 %s" % (compact(k["input"]), compact(k["output"])))
        self.kpis["hit"].set_data(
            "%.1f" % (k["hit_rate"] * 100), "%",
            "命中 %s / 未命中 %s" % (compact(k["cache_hit"]), compact(k["cache_miss"])))
        self.kpis["speed"].set_data(
            "%.0f" % k["avg_speed"], "tok/s",
            "峰值 %.0f tok/s" % k["peak_speed"])
        self.kpis["credit"].set_data(
            "%.2f" % k["credit"], "分",
            "今日 %.2f 分" % k["today_credit"])
        self.kpis["calls"].set_data(
            str(k["calls"]), "次",
            "生成耗时 %.0f 分钟" % (k["gen_seconds"] / 60.0)
            if k["gen_seconds"] >= 120 else "生成耗时 %.0f 秒" % k["gen_seconds"])

        self.speed_chart.set_data(data["speeds"], self._live_speed(data), self._live_sub(data))
        self.model_card.set_data(data["models"], data.get("breakdown"), self.model_filter)
        self.usage_chart.set_data(data["series"])
        self.cache_chart.set_data(data["series"], k["hit_rate"])
        self.session_table.set_data(data["sessions"], data.get("all_models") or data.get("models"))
        self.stream_card.set_data(data["recent"])
        self.header.update_models_menu(data.get("all_models") or data.get("models", []), self.model_filter)

        t = time.localtime(data["generated_at"] / 1000.0)
        filter_hint = " · 筛选模型: %s" % self.model_filter if self.model_filter else ""
        self.header.set_status(
            "最近更新 %s · 每 %s 秒自动刷新 · %d 条调用记录%s"
            % (time.strftime("%H:%M:%S", t), fmt_sec(self.refresh_ms),
               data["status"]["records"], filter_hint))
        self.foot_label.setText(
            "数据源：%s　·　%d 个会话文件　·　%d 条调用记录"
            % (data["status"]["source"], data["status"]["files"], data["status"]["records"]))

    def _live_speed(self, data):
        now = data["generated_at"]
        recent = [r for r in data["recent"] if now - r["t"] < 300000 and r["dur"] > 200]
        if not recent:
            return 0.0
        d = sum(r["dur"] for r in recent)
        o = sum(r["out"] for r in recent)
        return o / (d / 1000.0) if d else 0.0

    def _live_sub(self, data):
        now = data["generated_at"]
        recent = [r for r in data["recent"] if now - r["t"] < 300000 and r["dur"] > 200]
        if recent:
            return "最近 5 分钟 · %d 次调用" % len(recent)
        if data["recent"]:
            return "空闲 · 上次 %s" % self._ago(now - data["recent"][0]["t"])
        return "等待记录"

    @staticmethod
    def _ago(ms):
        s = max(0, ms / 1000.0)
        if s < 60:
            return "刚刚"
        if s < 3600:
            return "%d 分钟前" % (s // 60)
        if s < 86400:
            return "%d 小时前" % (s // 3600)
        return "%d 天前" % (s // 86400)


def main():
    if "--version" in sys.argv or "-V" in sys.argv:
        print("workbuddy-token-monitor %s" % __version__)
        return

    shot = None
    if "--shot" in sys.argv:
        i = sys.argv.index("--shot")
        if i + 1 < len(sys.argv):
            shot = sys.argv[i + 1]

    shot_mini = None
    if "--shot-mini" in sys.argv:
        i = sys.argv.index("--shot-mini")
        if i + 1 < len(sys.argv):
            shot_mini = sys.argv[i + 1]

    scale = 1.0 if (shot or shot_mini) else load_ui_scale()
    os.environ["QT_SCALE_FACTOR"] = str(scale)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, not (shot or shot_mini))
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, not (shot or shot_mini))

    app = QApplication(sys.argv)
    app.setFont(F(int(11 * scale)))
    if "--demo" in sys.argv:
        import demo_data
        collector = demo_data.DemoSource()
    else:
        collector = server.Collector()
        collector.born()

    if shot_mini:
        mini = MiniWindow(collector, lambda: None, lambda: None)
        mini.show()
        for _ in range(8):
            app.processEvents()
            time.sleep(0.05)
        pm = mini.grab()
        canvas = QPixmap(pm.width() + 48, pm.height() + 48)
        canvas.fill(QColor("#f4f6fb"))
        pp = QPainter(canvas)
        pp.drawPixmap(24, 24, pm)
        pp.end()
        canvas.save(shot_mini)
        print("saved %s  %dx%d" % (shot_mini, canvas.width(), canvas.height()))
        return

    win = MainWindow(collector)
    if "--range" in sys.argv:
        i = sys.argv.index("--range")
        if i + 1 < len(sys.argv):
            win.header._pick(sys.argv[i + 1])
    if "--model" in sys.argv:
        i = sys.argv.index("--model")
        if i + 1 < len(sys.argv):
            win._on_model_filter(sys.argv[i + 1])
    if shot:
        win.resize(1180, 840)
        win.show()
        for _ in range(10):
            app.processEvents()
            time.sleep(0.05)
        for w in win.findChildren(QWidget):
            if hasattr(w, "hover"):
                w.hover = -1
                w.update()
        app.processEvents()
        pm = win.content.grab()
        pm.save(shot)
        print("saved %s  %dx%d" % (shot, pm.width(), pm.height()))
        return
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
