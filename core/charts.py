"""Small server-rendered SVG charts: sparklines, trend lines with a goal line, donuts and bars.

Every function returns an SVG string; the template tags in core/templatetags/sn.py mark it safe.
"""

from decimal import Decimal
from html import escape

GREEN, RED, YELLOW, INK, MUTED, BOLT = "#16a34a", "#dc2626", "#eab308", "#0a0a0a", "#d4d4d1", "#D5FF03"


def _f(v):
    return None if v is None else float(Decimal(v))


def _scale(values, extra=()):
    nums = [v for v in list(values) + list(extra) if v is not None]
    if not nums:
        return 0.0, 1.0
    lo, hi = min(nums), max(nums)
    if lo == hi:
        pad = abs(lo) * 0.1 or 1.0
        return lo - pad, hi + pad
    pad = (hi - lo) * 0.12
    return lo - pad, hi + pad


def sparkline(values, goal=None, states=None, width=96, height=26, stroke=INK):
    """values: list (None = no data). states: matching list of 'green'/'red'/'' to color the dots."""
    vals = [_f(v) for v in values]
    g = _f(goal)
    pts = [(i, v) for i, v in enumerate(vals) if v is not None]
    if not pts:
        return f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" aria-hidden="true"><line x1="2" x2="{width - 2}" y1="{height / 2}" y2="{height / 2}" stroke="{MUTED}" stroke-dasharray="2 3"/></svg>'
    lo, hi = _scale(vals, [g] if g is not None else [])
    n = max(len(vals) - 1, 1)

    def xy(i, v):
        x = 3 + (width - 6) * i / n
        y = height - 3 - (height - 6) * (v - lo) / (hi - lo)
        return round(x, 1), round(y, 1)

    parts = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" class="overflow-visible" aria-hidden="true">']
    if g is not None:
        _, gy = xy(0, g)
        parts.append(f'<line x1="0" x2="{width}" y1="{gy}" y2="{gy}" stroke="{GREEN}" stroke-opacity=".45" stroke-dasharray="3 3"/>')
    line = " ".join(f"{x},{y}" for x, y in (xy(i, v) for i, v in pts))
    if len(pts) > 1:
        parts.append(f'<polyline points="{line}" fill="none" stroke="{stroke}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>')
    states = states or []
    last = pts[-1]
    for i, v in pts:
        x, y = xy(i, v)
        st = states[i] if i < len(states) else ""
        color = GREEN if st == "green" else RED if st == "red" else INK
        r = 2.6 if (i, v) == last else 1.6
        parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>')
    parts.append("</svg>")
    return "".join(parts)


def line_chart(points, goal=None, width=640, height=220, fmt=str, title=""):
    """points: [(label, value-or-None, state)]. Draws a trend line, a dashed goal line and labelled axes."""
    vals = [_f(v) for _, v, _ in points]
    g = _f(goal)
    pl, pr, pt, pb = 46, 14, 14, 26
    w, h = width - pl - pr, height - pt - pb
    lo, hi = _scale(vals, [g] if g is not None else [])
    n = max(len(points) - 1, 1)

    def x(i):
        return round(pl + w * i / n, 1)

    def y(v):
        return round(pt + h - h * (v - lo) / (hi - lo), 1)

    out = [f'<svg viewBox="0 0 {width} {height}" class="w-full h-auto" role="img" aria-label="{escape(title)}">']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        yy = y(v)
        out.append(f'<line x1="{pl}" x2="{width - pr}" y1="{yy}" y2="{yy}" stroke="#000" stroke-opacity=".06"/>')
        out.append(f'<text x="{pl - 8}" y="{yy + 3.5}" text-anchor="end" font-size="10" fill="#8a8a87">{escape(fmt(v))}</text>')
    step = max(1, len(points) // 7)
    for i, (label, _, _) in enumerate(points):
        if i % step == 0 or i == len(points) - 1:
            out.append(f'<text x="{x(i)}" y="{height - 8}" text-anchor="middle" font-size="10" fill="#8a8a87">{escape(str(label))}</text>')
    if g is not None:
        gy = y(g)
        out.append(f'<line x1="{pl}" x2="{width - pr}" y1="{gy}" y2="{gy}" stroke="{GREEN}" stroke-width="1.5" stroke-dasharray="5 4"/>')
        out.append(f'<text x="{width - pr}" y="{gy - 5}" text-anchor="end" font-size="10" font-weight="600" fill="{GREEN}">Goal {escape(fmt(g))}</text>')
    pts = [(i, v) for i, v in enumerate(vals) if v is not None]
    if len(pts) > 1:
        area = " ".join(f"{x(i)},{y(v)}" for i, v in pts)
        out.append(f'<polygon points="{x(pts[0][0])},{pt + h} {area} {x(pts[-1][0])},{pt + h}" fill="{BOLT}" fill-opacity=".28"/>')
        out.append(f'<polyline points="{area}" fill="none" stroke="{INK}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
    for i, v in pts:
        st = points[i][2]
        color = GREEN if st == "green" else RED if st == "red" else INK
        out.append(f'<circle cx="{x(i)}" cy="{y(v)}" r="3.6" fill="#fff" stroke="{color}" stroke-width="2"><title>{escape(str(points[i][0]))}: {escape(fmt(v))}</title></circle>')
    out.append("</svg>")
    return "".join(out)


def donut(segments, size=92, thickness=12, center="", sub=""):
    """segments: [(value, color, label)]."""
    total = sum(v for v, _, _ in segments) or 0
    r = (size - thickness) / 2
    c = size / 2
    circ = 2 * 3.14159265 * r
    out = [f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img">']
    out.append(f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="#ececea" stroke-width="{thickness}"/>')
    offset = 0.0
    if total:
        for v, color, label in segments:
            if not v:
                continue
            length = circ * v / total
            out.append(
                f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="{color}" stroke-width="{thickness}" '
                f'stroke-dasharray="{length:.2f} {circ - length:.2f}" stroke-dashoffset="{-offset:.2f}" '
                f'transform="rotate(-90 {c} {c})"><title>{escape(label)}: {v}</title></circle>'
            )
            offset += length
    if center:
        out.append(f'<text x="{c}" y="{c + (2 if sub else 6)}" text-anchor="middle" font-family="Montserrat, Inter, sans-serif" font-weight="800" font-size="{size * 0.22:.0f}" fill="{INK}">{escape(center)}</text>')
    if sub:
        out.append(f'<text x="{c}" y="{c + size * 0.17:.0f}" text-anchor="middle" font-size="{size * 0.1:.0f}" fill="#8a8a87">{escape(sub)}</text>')
    out.append("</svg>")
    return "".join(out)


def bars(items, height=72, goal=None, width=None, unit="%"):
    """items: [(label, value-or-None)] for 0-100 values. Bars are green at/above goal, red below."""
    n = len(items) or 1
    width = width or n * 26
    bw = width / n
    out = [f'<svg viewBox="0 0 {width} {height + 16}" class="w-full h-auto" role="img">']
    if goal is not None:
        gy = height - height * goal / 100
        out.append(f'<line x1="0" x2="{width}" y1="{gy}" y2="{gy}" stroke="{GREEN}" stroke-dasharray="3 3" stroke-opacity=".7"/>')
    for i, (label, v) in enumerate(items):
        x = i * bw + bw * 0.18
        if v is None:
            out.append(f'<rect x="{x:.1f}" y="{height - 3}" width="{bw * 0.64:.1f}" height="3" rx="1.5" fill="#e5e5e3"/>')
        else:
            bh = max(3, height * v / 100)
            color = INK if goal is None else (GREEN if v >= goal else RED)
            out.append(f'<rect x="{x:.1f}" y="{height - bh:.1f}" width="{bw * 0.64:.1f}" height="{bh:.1f}" rx="3" fill="{color}"><title>{escape(str(label))}: {v}{unit}</title></rect>')
        out.append(f'<text x="{i * bw + bw / 2:.1f}" y="{height + 12}" text-anchor="middle" font-size="9" fill="#8a8a87">{escape(str(label))}</text>')
    out.append("</svg>")
    return "".join(out)
