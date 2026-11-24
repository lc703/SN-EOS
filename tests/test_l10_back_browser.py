"""Real browser: open a rock, issue, to-do or measurable from an L10 section, press Back, land on that section."""

import os

import pytest
from django.core.management import call_command

playwright_sync = pytest.importorskip("playwright.sync_api")

LINKS = {
    "rocks": 'a[href*="/rocks/"]',
    "ids": 'a[href*="/issues/"][href*="from="]',
    "todos": 'a[href*="/todos/"][href*="from="]',
}


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_browser_back_from_a_detail_page_restores_the_l10_section(live_server, client, monkeypatch):
    monkeypatch.setitem(os.environ, "DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    from core.models import User
    from meetings.models import SECTIONS, Meeting

    call_command("seed_demo")
    user = User.objects.get(name="Noah Bennett")
    meeting = Meeting.objects.filter(concluded_at__isnull=True).order_by("pk").first() or Meeting.objects.order_by("pk").first()
    client.force_login(user)
    cookie = client.cookies["sessionid"].value
    base = f"{live_server.url}/meetings/{meeting.pk}/"

    with playwright_sync.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium unavailable: {exc}")
        ctx = browser.new_context()
        ctx.add_cookies([{"name": "sessionid", "value": cookie, "url": live_server.url}])
        page = ctx.new_page()
        exercised = []
        for section, selector in LINKS.items():
            # Arrive on the bare meeting URL, the way "Rejoin L10" does, then move around the way a person would.
            page.goto(base)
            page.wait_for_load_state("load")
            page.click(f'nav[aria-label="Agenda"] a[href^="?s={section}"]')
            page.wait_for_url(f"**/meetings/{meeting.pk}/?s={section}*")
            page.wait_for_load_state("load")
            link = page.locator(f"#l10-body {selector}").first
            if not link.count():
                continue
            exercised.append(section)
            href = link.get_attribute("href")
            link.click()
            page.wait_for_load_state("load")
            page.wait_for_timeout(500)
            assert "/meetings/" not in page.url, f"{section}: link {href} did not open a detail page"
            back = page.locator("a.l10-back")
            assert back.count() == 1 and back.inner_text().startswith("← Back to L10"), section
            page.go_back()
            page.wait_for_load_state("load")
            assert f"?s={section}" in page.url, f"{section}: Back landed on {page.url}"
            assert page.locator("#l10-body").count() == 1
            assert page.locator("h2").first.inner_text() == dict(SECTIONS)[section]

            # The explicit link goes to the same place.
            link = page.locator(f"#l10-body {selector}").first
            link.click()
            page.wait_for_load_state("load")
            page.click("a.l10-back")
            page.wait_for_load_state("load")
            assert f"?s={section}" in page.url
        assert "rocks" in exercised and len(exercised) >= 2, exercised
        # The bare URL pins itself to the section on show, so even a plain back to it keeps the section.
        page.goto(base)
        page.wait_for_load_state("load")
        assert "?s=" in page.url
        browser.close()
