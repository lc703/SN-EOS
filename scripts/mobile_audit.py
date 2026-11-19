"""Mobile QA: screenshot every page at phone and tablet sizes and report sideways overflow and small tap targets.

    python scripts/mobile_audit.py --base http://localhost:8000 --out /tmp/mobile --label after

Signs in through /dev-login/ (DEBUG only) as the first button matching --user.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

VIEWPORTS = {"375": (375, 812), "390": (390, 844), "768": (768, 1024)}

PROBE = """() => {
  const vw = document.documentElement.clientWidth;
  const clipped = (el) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (['auto', 'scroll', 'hidden', 'clip'].includes(s.overflowX)) return true;
    }
    return false;
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const label = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
    (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\\s+/).slice(0, 4).join('.') : '') +
    ' "' + (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 40).replace(/\\s+/g, ' ') + '"';
  const hits = [];
  for (const el of document.body.querySelectorAll('*')) {
    if (!visible(el) || clipped(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 || r.left < -1) hits.push(el);
  }
  // Report the innermost offenders: the elements actually sticking out, not every ancestor they stretch.
  const wide = hits.filter((el) => !hits.some((o) => o !== el && el.contains(o)))
    .map((el) => { const r = el.getBoundingClientRect(); return label(el) + ` [${Math.round(r.left)}..${Math.round(r.right)}]`; });
  // The box a finger can actually hit: the element, an enlarged ::before hit area, and any label for it.
  const hitBox = (el) => {
    const r = el.getBoundingClientRect();
    let [l, t, rt, b] = [r.left, r.top, r.right, r.bottom];
    const grow = (o) => { l = Math.min(l, o.left); t = Math.min(t, o.top); rt = Math.max(rt, o.right); b = Math.max(b, o.bottom); };
    const before = getComputedStyle(el, '::before');
    if (before.content !== 'none' && before.position === 'absolute') {
      const n = (v) => parseFloat(v) || 0;
      grow({left: r.left + n(before.left), top: r.top + n(before.top), right: r.right - n(before.right), bottom: r.bottom - n(before.bottom)});
    }
    for (const lab of (el.labels || [])) grow(lab.getBoundingClientRect());
    const wrap = el.closest('label');
    if (wrap) grow(wrap.getBoundingClientRect());
    return {w: rt - l, h: b - t};
  };
  const inText = (el) => {
    if (el.tagName !== 'A' || getComputedStyle(el).display !== 'inline') return false;
    const host = el.parentElement;
    return host && (host.innerText || '').trim().length > (el.innerText || '').trim().length + 12;
  };
  const small = [];
  for (const el of document.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea, [role=button], summary')) {
    if (!visible(el) && !(el.labels && el.labels.length)) continue;
    if (el.closest('[aria-hidden=true], .chart-stage') || inText(el)) continue;
    const box = hitBox(el);
    if (box.w === 0 || box.h === 0) continue;
    if (box.h < 43.5 || box.w < 43.5) small.push(label(el) + ` ${Math.round(box.w)}x${Math.round(box.h)}`);
  }
  return {vw, sw: document.documentElement.scrollWidth, bw: document.body.scrollWidth,
          meta: document.querySelector('meta[name=viewport]')?.content || null,
          wide: wide.slice(0, 15), small: small.slice(0, 40), nsmall: small.length, coarse: matchMedia('(pointer: coarse)').matches};
}"""


def pages(ids):
    return [
        ("home", "/"),
        ("person-dashboard", f"/people/{ids['person']}/dashboard/"),
        ("scorecard", "/scorecard/"),
        ("rocks", "/rocks/"),
        ("rock-detail", f"/rocks/{ids['rock']}/"),
        ("issues", "/issues/"),
        ("issue-detail", f"/issues/{ids['issue']}/"),
        ("todos", "/todos/"),
        ("meetings", "/meetings/"),
        ("l10-scorecard", f"/meetings/{ids['meeting']}/?s=scorecard"),
        ("l10-rocks", f"/meetings/{ids['meeting']}/?s=rocks"),
        ("l10-ids", f"/meetings/{ids['meeting']}/?s=ids"),
        ("l10-conclude", f"/meetings/{ids['meeting']}/?s=conclude"),
        ("vto", "/vto/"),
        ("chart", "/chart/"),
        ("people", "/people/"),
        ("person-1on1s", f"/people/{ids['person']}/"),
        ("conversations", "/conversations/"),
        ("conversation", f"/conversations/{ids['conversation']}/"),
        ("planning", "/planning/"),
        ("session", f"/planning/{ids['session']}/"),
        ("api-tokens", "/settings/api/"),
        ("audit", "/settings/audit/"),
    ]


def extras(page, name, vp, w, out, report, url):
    if name == "home":
        page.get_by_role("button", name="View someone’s 90").click(timeout=4000)
        page.wait_for_timeout(300)
        report[f"{vp}/person-picker"] = page.evaluate(PROBE)
        box = page.locator("[role=listbox]").first.evaluate("e => e.parentElement.getBoundingClientRect().toJSON()")
        report[f"{vp}/person-picker"]["menu"] = box
        page.screenshot(path=str(out / f"{vp}-person-picker.png"))
        if w < 1024:
            page.goto(url); page.wait_for_load_state("networkidle")
            page.locator("nav.fixed button", has_text="More").click(timeout=4000)
            page.wait_for_timeout(200)
            page.screenshot(path=str(out / f"{vp}-more-menu.png"))
    if name == "scorecard":
        page.evaluate("document.querySelector('.card.overflow-x-auto').scrollLeft = 400")
        page.wait_for_timeout(150)
        page.screenshot(path=str(out / f"{vp}-scorecard-scrolled.png"))
        page.locator("button[data-panel]").first.click(timeout=4000)
        page.wait_for_timeout(700)
        report[f"{vp}/scorecard-panel"] = page.evaluate(PROBE)
        page.screenshot(path=str(out / f"{vp}-scorecard-panel.png"))
    if name == "chart":
        page.wait_for_timeout(300)
        page.screenshot(path=str(out / f"{vp}-chart-view.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--out", default="/tmp/mobile")
    ap.add_argument("--label", default="after")
    ap.add_argument("--user", default="Noah Bennett")
    ap.add_argument("--ids", default='{"person": 6, "rock": 1, "issue": 8, "meeting": 1, "conversation": 1, "session": 1}')
    ap.add_argument("--only", default="")
    ap.add_argument("--viewports", default="375,390,768")
    args = ap.parse_args()
    ids = json.loads(args.ids)
    out = Path(args.out) / args.label
    out.mkdir(parents=True, exist_ok=True)
    report = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for vp in args.viewports.split(","):
            w, h = VIEWPORTS[vp]
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2, is_mobile=w < 700, has_touch=True,
                                      user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120.0 Mobile/15E148 Safari/604.1")
            page = ctx.new_page()
            page.goto(args.base + "/accounts/login/")
            page.wait_for_load_state("networkidle")
            report[f"{vp}/login"] = page.evaluate(PROBE)
            page.screenshot(path=str(out / f"{vp}-login.png"), full_page=True)
            page.goto(args.base + "/dev-login/")
            page.locator("form button", has_text=args.user).first.click()
            page.wait_for_load_state("networkidle")
            for name, path in pages(ids):
                if args.only and name not in args.only.split(","):
                    continue
                page.goto(args.base + path)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(250)
                report[f"{vp}/{name}"] = page.evaluate(PROBE)
                page.screenshot(path=str(out / f"{vp}-{name}.png"), full_page=True)
                try:
                    extras(page, name, vp, w, out, report, args.base + path)
                except Exception as exc:  # an interaction that cannot happen is itself a finding
                    report[f"{vp}/{name}-interaction"] = {"vw": w, "sw": w, "nsmall": 0, "wide": [f"FAILED: {str(exc).splitlines()[0]}"]}
            ctx.close()
        browser.close()
    for key, r in report.items():
        # A too-wide page widens a mobile layout viewport, so compare with the device width, not clientWidth.
        r["vw"] = VIEWPORTS[key.split("/")[0]][0]
        flag = "OVERFLOW" if r["sw"] > r["vw"] else "ok"
        print(f"{key:28} {flag:8} sw={r['sw']} vw={r['vw']} small={r['nsmall']}")
        for wdx in r["wide"][:6]:
            print("     wide:", wdx)
    (out / "report.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
