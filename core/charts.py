"""Small server-rendered SVG charts. No JS, prints cleanly, works in emails."""

from decimal import Decimal
from html import escape

GREEN, RED, INK, MUTED, BOLT = "#22a559", "#e5372a", "#111111", "#d4d4d0", "#D5FF03"


def _num(v):
    if v is None or v == "":
        return None
    return float(v) if isinstance(v, (int, float, Decimal)) else None


def _scale(values, goal=None, pad=0.08):
    nums = [v for v in values if v is not None]
    if goal is not None:
        nums.append(goal)
    if not nums:
        return 0.0, 1.0
    lo, hi = min(nums), max(nums)
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    span = hi - lo
    return lo - span * pad, hi + span * pad


def _points(values, w, h, lo, hi, left=0.0, top=0.0):
    n = len(values)
    step = w / (n - 1) if n > 1 else 0
    pts = []
    for i, v in enumerate(values):
        if v is None:
            pts.append(None)
            continue
        x = left + i * step if n > 1 else left + w / 2
        y = top + h - (v - lo) / (hi - lo) * h
        pts.append((round(x, 1), round(y, 1)))
    return pts


def _path(pts):
    out, pen = [], False
    for p in pts:
        if p is None:
            pen = False
            continue
        out.append(("L" if pen else "M") + f"{p[0]},{p[1]}")
        pen = True
    return " ".join(out)


def sparkline(values, goal=None, ok=None, width=96, height=26):
    """Tiny trend line. `ok` is a parallel list of True/False/None used to color the last point."""
    vals = [_num(v) for v in values]
    if sum(v is not None for v in vals) < 2:
        return f'<svg class="spark" width="{width}" height="{height}" aria-hidden="true"><line x1="0" y1="{height/2}" x2="{width}" y2="{height/2}" stroke="{MUTED}" stroke-dasharray="2 3"/></svg>'
    g = _num(goal)
    lo, hi = _scale(vals, g)
    pts = _points(vals, width - 4, height - 4, lo, hi, 2, 2)
    parts = [f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" aria-hidden="true">']
    if g is not None:
        gy = round(2 + (height - 4) - (g - lo) / (hi - lo) * (height - 4), 1)
        parts.append(f'<line x1="0" y1="{gy}" x2="{width}" y2="{gy}" stroke="{INK}" stroke-opacity=".25" stroke-dasharray="2 2"/>')
    parts.append(f'<path d="{_path(pts)}" fill="none" stroke="{INK}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>')
    last = max(i for i, p in enumerate(pts) if p is not None)
    color = INK
    if ok and last < len(ok) and ok[last] is not None:
        color = GREEN if ok[last] else RED
    x, y = pts[last]
    parts.append(f'<circle cx="{x}" cy="{y}" r="2.6" fill="{color}" stroke="#fff" stroke-width="1"/>')
    parts.append("</svg>")
    return "".join(parts)


def trend_chart(labels, values, goal=None, ok=None, width=560, height=200, fmt=str):
    """Line chart with goal line, colored points and x labels."""
    vals = [_num(v) for v in values]
    g = _num(goal)
    left, right, top, bottom = 44, 12, 14, 26
    w, h = width - left - right, height - top - bottom
    lo, hi = _scale(vals, g, pad=0.12)
    pts = _points(vals, w, h, lo, hi, left, top)
    out = [f'<svg class="w-full h-auto" viewBox="0 0 {width} {height}" role="img" aria-label="Trend">']
    for i in range(4):
        v = lo + (hi - lo) * i / 3
        y = round(top + h - (v - lo) / (hi - lo) * h, 1)
        out.append(f'<line x1="{left}" y1="{y}" x2="{width-right}" y2="{y}" stroke="#000" stroke-opacity=".06"/>')
        out.append(f'<text x="{left-8}" y="{y+3.5}" text-anchor="end" font-size="10" fill="#8a8a8a">{escape(fmt(v))}</text>')
    if g is not None:
        gy = round(top + h - (g - lo) / (hi - lo) * h, 1)
        out.append(f'<line x1="{left}" y1="{gy}" x2="{width-right}" y2="{gy}" stroke="{INK}" stroke-width="1.2" stroke-dasharray="4 3"/>')
        out.append(f'<text x="{width-right}" y="{gy-5}" text-anchor="end" font-size="10" font-weight="700" fill="{INK}">Goal {escape(fmt(g))}</text>')
    path = _path(pts)
    if path:
        out.append(f'<path d="{path}" fill="none" stroke="{INK}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
    for i, p in enumerate(pts):
        if p is None:
            continue
        good = ok[i] if ok and i < len(ok) else None
        color = GREEN if good else RED if good is False else INK
        out.append(f'<circle cx="{p[0]}" cy="{p[1]}" r="3.6" fill="{color}" stroke="#fff" stroke-width="1.5"><title>{escape(labels[i])}: {escape(fmt(vals[i]))}</title></circle>')
    n = len(labels)
    step = w / (n - 1) if n > 1 else 0
    for i, lab in enumerate(labels):
        if n > 8 and i % 2:
            continue
        x = round(left + i * step, 1)
        out.append(f'<text x="{x}" y="{height-8}" text-anchor="middle" font-size="10" fill="#8a8a8a">{escape(lab)}</text>')
    out.append("</svg>")
    return "".join(out)


def donut(segments, size=96, thickness=12, label="", sub=""):
    """segments: [(value, color)]."""
    total = sum(v for v, _ in segments) or 0
    r = (size - thickness) / 2
    c = 2 * 3.14159265 * r
    cx = cy = size / 2
    out = [f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img" aria-label="{escape(label)} {escape(sub)}">',
           f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#efefec" stroke-width="{thickness}"/>']
    offset = 0.0
    for value, color in segments:
        if not total or not value:
            continue
        length = c * value / total
        out.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{thickness}" '
            f'stroke-dasharray="{length:.2f} {c - length:.2f}" stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})"/>'
        )
        offset += length
    if label:
        out.append(f'<text x="{cx}" y="{cy + (2 if sub else 6)}" text-anchor="middle" font-size="{size/4.6:.0f}" class="donut-label" fill="#000">{escape(label)}</text>')
    if sub:
        out.append(f'<text x="{cx}" y="{cy + size/6.5:.0f}" text-anchor="middle" font-size="{size/10:.0f}" fill="#737373">{escape(sub)}</text>')
    out.append("</svg>")
    return "".join(out)


def bars(labels, values, width=280, height=90, goal=None, max_value=None, fmt=lambda v: f"{v:.0f}"):
    """Vertical bars (e.g. weekly to-do completion %). None = no data."""
    vals = [_num(v) for v in values]
    n = len(vals) or 1
    top, bottom = 10, 18
    h = height - top - bottom
    hi = max_value or max([v for v in vals if v is not None] + [_num(goal) or 0, 1])
    gap = 6
    bw = (width - gap * (n - 1)) / n
    out = [f'<svg class="w-full h-auto" viewBox="0 0 {width} {height}" role="img" aria-label="Bars">']
    g = _num(goal)
    for i, v in enumerate(vals):
        x = round(i * (bw + gap), 1)
        out.append(f'<rect x="{x}" y="{top}" width="{bw:.1f}" height="{h}" rx="3" fill="#f1f1ee"/>')
        if v is not None:
            bh = max(2, h * min(v, hi) / hi)
            color = INK if g is None or v >= g else "#a3a3a3"
            out.append(f'<rect x="{x}" y="{top + h - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="3" fill="{color}"><title>{escape(labels[i])}: {escape(fmt(v))}</title></rect>')
            if v >= (g or 0) and g is not None:
                out.append(f'<rect x="{x}" y="{top + h - bh:.1f}" width="{bw:.1f}" height="3" rx="1.5" fill="{BOLT}"/>')
        out.append(f'<text x="{x + bw/2:.1f}" y="{height-5}" text-anchor="middle" font-size="9.5" fill="#8a8a8a">{escape(labels[i])}</text>')
    if g is not None:
        gy = round(top + h - h * g / hi, 1)
        out.append(f'<line x1="0" y1="{gy}" x2="{width}" y2="{gy}" stroke="{INK}" stroke-opacity=".45" stroke-dasharray="3 3"/>')
    out.append("</svg>")
    return "".join(out)
