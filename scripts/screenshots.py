"""Capture page screenshots from a running dev server (uses the dev quick login).

    python scripts/screenshots.py --base http://localhost:8000 --out /tmp/shots --name "Ben Steuart"
"""

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = [
    ("home", "/"),
    ("scorecard", "/scorecard/"),
    ("rocks", "/rocks/"),
    ("issues", "/issues/"),
    ("todos", "/todos/"),
    ("meetings", "/meetings/"),
    ("vto", "/vto/"),
    ("chart", "/chart/"),
    ("people", "/people/"),
    ("conversations", "/people/conversations/"),
    ("sessions", "/sessions/"),
    ("api", "/settings/api/"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--out", default="screenshots")
    ap.add_argument("--name", default="Ben Steuart", help="Display name to pick on the dev login page")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--extra", nargs="*", default=[], help="name=/path pairs")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pages = PAGES + [tuple(x.split("=", 1)) for x in args.extra]
    if args.only:
        pages = [p for p in pages if p[0] in args.only]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": 900}, device_scale_factor=1)
        page.goto(f"{args.base}/dev-login/")
        page.locator("form button", has_text=args.name).first.click()
        page.wait_for_load_state("networkidle")
        for name, path in pages:
            page.goto(f"{args.base}{path}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(400)
            page.screenshot(path=str(out / f"{name}.png"), full_page=args.full)
            print("saved", out / f"{name}.png")
        browser.close()


if __name__ == "__main__":
    main()
