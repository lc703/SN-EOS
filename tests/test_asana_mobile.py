"""The Send to Asana button in a real phone-sized browser: no sideways scroll, a 44px tap target, and the row
swaps to the Asana link after one tap. Asana itself is faked. Skipped when Playwright's Chromium is missing."""

import os

import pytest
from django.utils import timezone
from django.core.management import call_command

playwright_sync = pytest.importorskip("playwright.sync_api")

from core import asana_client  # noqa: E402
from test_asana import FakeAsana  # noqa: E402

PHONE = {"width": 375, "height": 812}


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_send_to_asana_on_a_phone(live_server, client, monkeypatch, settings):
    monkeypatch.setitem(os.environ, "DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    settings.ASANA_PAT, settings.ASANA_WORKSPACE_GID, settings.ASANA_PROJECT_GID = "x", "W1", ""
    fake = FakeAsana()
    fake.users = [{"gid": "U-NOAH", "email": "noah.bennett@steuartnutrition.com"}]
    fake.completed = {}
    monkeypatch.setattr(asana_client.requests, "request", fake)

    from core.models import AppSetting, User
    from todos.models import Todo

    call_command("seed_demo")
    noah = User.objects.get(name="Noah Bennett")
    fake.users = [{"gid": "U-NOAH", "email": noah.email}]
    mine = list(Todo.objects.filter(owner=noah, done=False, is_private=False).order_by("pk")[:2])
    assert len(mine) == 2
    linked = mine[1]
    linked.asana_task_gid, linked.asana_unassigned = "1209999999999999", True
    linked.save()
    AppSetting.put("asana_last_sync", timezone.now().isoformat())  # keep the page's own sync out of this test
    client.force_login(noah)

    with playwright_sync.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium unavailable: {exc}")
        ctx = browser.new_context(viewport=PHONE, is_mobile=True, has_touch=True, device_scale_factor=2)
        ctx.add_cookies([{"name": "sessionid", "value": client.cookies["sessionid"].value, "url": live_server.url}])
        page = ctx.new_page()
        for path in ["/todos/", "/", f"/todos/{mine[0].pk}/", f"/todos/{linked.pk}/"]:
            page.goto(live_server.url + path)
            page.wait_for_load_state("load")
            assert page.evaluate("document.documentElement.scrollWidth") <= PHONE["width"], f"{path} scrolls sideways"

        page.goto(live_server.url + "/todos/")
        link = page.locator(f"#todo-{linked.pk} a", has_text="In Asana")
        assert "unassigned" in link.inner_text()
        assert link.get_attribute("href") == "https://app.asana.com/0/0/1209999999999999"
        button = page.locator(f"#todo-{mine[0].pk} [data-asana-send]")
        # Under touch the visible button may be smaller; its invisible hit area (::before) must reach 44px.
        box = button.bounding_box()
        hit = page.evaluate(
            "el => { const s = getComputedStyle(el, '::before'); return [parseFloat(s.width), parseFloat(s.height)]; }",
            button.element_handle(),
        )
        assert box["height"] >= 36 and max(box["height"], hit[1]) >= 44, (box, hit)
        button.tap()
        page.locator(f"#todo-{mine[0].pk} a", has_text="In Asana").wait_for()
        assert page.evaluate("document.documentElement.scrollWidth") <= PHONE["width"]
        browser.close()
    sent = Todo.objects.get(pk=mine[0].pk)
    assert sent.asana_task_gid and fake.count("POST", "/tasks") == 1
