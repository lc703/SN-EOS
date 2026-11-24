"""Every page fits a 375px phone: the document never scrolls sideways.

Wide tables may scroll inside their own container; this only fails when the page itself is wider than the
screen, which is what makes mobile browsers zoom the whole page out. Skipped when Playwright or its Chromium
is not installed (pip install playwright && playwright install chromium).
"""

import os

import pytest
from django.core.management import call_command

playwright_sync = pytest.importorskip("playwright.sync_api")

PHONE = {"width": 375, "height": 812}


def _pages():
    from core.models import User
    from issues.models import Issue
    from meetings.models import Meeting
    from people.models import OneOnOne
    from planning.models import Session
    from rocks.models import Rock

    person = User.objects.exclude(name="Noah Bennett").filter(is_active=True).order_by("pk").first()
    ids = {
        "person": person.pk,
        "rock": Rock.objects.order_by("pk").first().pk,
        "issue": Issue.objects.order_by("pk").first().pk,
        "meeting": Meeting.objects.order_by("pk").first().pk,
        "conversation": OneOnOne.objects.order_by("pk").first().pk,
        "session": Session.objects.order_by("pk").first().pk,
    }
    return [
        "/",
        f"/people/{ids['person']}/dashboard/",
        "/scorecard/",
        "/rocks/",
        f"/rocks/{ids['rock']}/",
        "/issues/",
        f"/issues/{ids['issue']}/",
        "/todos/",
        "/meetings/",
        f"/meetings/{ids['meeting']}/?s=scorecard",
        f"/meetings/{ids['meeting']}/?s=rocks",
        f"/meetings/{ids['meeting']}/?s=ids",
        f"/meetings/{ids['meeting']}/?s=conclude",
        "/vto/",
        "/chart/",
        "/people/",
        f"/people/{ids['person']}/",
        "/conversations/",
        f"/conversations/{ids['conversation']}/",
        "/planning/",
        f"/planning/{ids['session']}/",
        "/settings/api/",
        "/settings/audit/",
        "/scorecard/?team=kentucky",
        "/rocks/?team=kentucky",
        "/scorecard/?team=company",
        "/rocks/?team=company",
        "/todos/?team=company",
        "/issues/?team=company",
    ]


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_no_page_scrolls_sideways_on_a_phone(live_server, client, monkeypatch):
    # Playwright's sync API runs an event loop on this thread; the live server does the DB work.
    monkeypatch.setitem(os.environ, "DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    from core.models import User

    call_command("seed_demo")
    paths = _pages()
    client.force_login(User.objects.get(name="Noah Bennett"))
    session_cookie = client.cookies["sessionid"].value

    with playwright_sync.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # Chromium not downloaded
            pytest.skip(f"Chromium unavailable: {exc}")
        ctx = browser.new_context(viewport=PHONE, is_mobile=True, has_touch=True, device_scale_factor=2)
        ctx.add_cookies([{"name": "sessionid", "value": session_cookie, "url": live_server.url}])
        page = ctx.new_page()
        too_wide = []
        for path in paths:
            response = page.goto(live_server.url + path)
            assert response.ok, f"{path} returned {response.status}"
            assert "/accounts/login" not in page.url, f"{path} redirected to login"
            page.wait_for_load_state("load")
            page.wait_for_timeout(150)
            # Compare with the device width, not innerWidth: a too-wide page widens a mobile layout viewport.
            sw = page.evaluate("document.documentElement.scrollWidth")
            if sw > PHONE["width"]:
                too_wide.append(f"{path}: scrollWidth {sw} > {PHONE['width']}")
        browser.close()
    assert not too_wide, "Pages wider than a 375px phone:\n" + "\n".join(too_wide)
