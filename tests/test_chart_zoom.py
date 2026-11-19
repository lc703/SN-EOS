"""Chart zoom follows the wheel delta, and a trackpad pinch (ctrl+wheel, small deltas) moves faster than a mouse notch."""

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

# A short Mac trackpad pinch-out: ctrl held, pixel deltas, a burst of small negatives.
PINCH = [-2, -4, -7, -11, -9, -6, -4, -2]


def _page():
    html = """
    <div class="chart-shell" x-data="orgChart({})">
      <button type="button" @click="zoomIn()">in</button>
      <button type="button" @click="zoomOut()">out</button>
      <button type="button" @click="reset()">reset</button>
      <div class="chart-viewport" x-ref="viewport" @wheel.prevent="wheel($event)"
           style="width:800px;height:500px;position:relative">
        <div class="chart-stage" x-ref="stage" :style="`transform: ${transform}`"
             style="width:400px;height:300px"></div>
      </div>
    </div>
    """
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport={"width": 1000, "height": 700})
    page.set_content(html)
    page.add_script_tag(path=str(ROOT / "static/js/chart.js"))
    page.add_script_tag(path=str(ROOT / "static/js/alpine.min.js"))
    page.wait_for_function("() => document.querySelector('.chart-shell')?._x_dataStack?.[0]?.scale > 0")
    return playwright, browser, page


@pytest.fixture
def chart():
    playwright, browser, page = _page()
    yield page
    browser.close()
    playwright.stop()


def test_pinch_stream_zooms_continuously_and_stays_under_the_cursor(chart):
    result = chart.evaluate(
        """(stream) => {
          const data = document.querySelector('.chart-shell')._x_dataStack[0];
          const vp = document.querySelector('.chart-viewport');
          data.reset();
          const rect = vp.getBoundingClientRect();
          const relX = 220, relY = 140;
          const clientX = rect.left + relX, clientY = rect.top + relY;
          const point = () => [(relX - data.x) / data.scale, (relY - data.y) / data.scale];
          const before = point();
          for (const dy of stream) {
            vp.dispatchEvent(new WheelEvent('wheel', {
              deltaY: dy, deltaX: 0, deltaMode: 0, ctrlKey: true,
              clientX, clientY, bubbles: true, cancelable: true,
            }));
          }
          const moved = stream.reduce((px, dy) => px * Math.exp(-dy * 0.015), 1);
          const oldFactor = stream.reduce((px, dy) => px * Math.exp(-dy * 0.0022), 1);
          const after = point();
          return {scale: data.scale, moved, oldFactor, before, after};
        }""",
        PINCH,
    )
    assert result["scale"] == pytest.approx(result["moved"], abs=0.01)
    assert result["scale"] > result["oldFactor"] * 1.5  # the old factor barely moved
    assert result["scale"] < 2
    for a, b in zip(result["before"], result["after"]):
        assert a == pytest.approx(b, abs=0.05)


def test_mouse_notch_uses_the_smaller_factor_and_buttons_take_a_bigger_step(chart):
    result = chart.evaluate(
        """() => {
          const data = document.querySelector('.chart-shell')._x_dataStack[0];
          const vp = document.querySelector('.chart-viewport');
          const rect = vp.getBoundingClientRect();
          function notch(extra) {
            data.reset();
            vp.dispatchEvent(new WheelEvent('wheel', Object.assign({
              deltaY: -100, deltaX: 0, deltaMode: 0,
              clientX: rect.left + 200, clientY: rect.top + 100,
              bubbles: true, cancelable: true,
            }, extra)));
            return data.scale;
          }
          const command = notch({metaKey: true});
          const ctrlBig = notch({ctrlKey: true});  // a mouse notch, not a pinch: delta is 100
          data.reset();
          document.querySelector('button').click();
          const button = data.scale;
          data.zoomOut();
          const back = data.scale;
          // Two-finger scroll still pans.
          data.reset();
          const y = data.y;
          vp.dispatchEvent(new WheelEvent('wheel', {
            deltaY: 30, deltaX: 12, deltaMode: 0, bubbles: true, cancelable: true,
          }));
          return {command, ctrlBig, button, back, scale: data.scale, dy: data.y - y, dx: data.x};
        }"""
    )
    assert result["command"] == pytest.approx(2.718281828 ** 0.5, rel=0.01)  # exp(100 * 0.005)
    assert result["ctrlBig"] == pytest.approx(result["command"], rel=0.01)
    assert result["button"] == pytest.approx(1.4, rel=0.01)
    assert result["back"] == pytest.approx(1, rel=0.01)
    assert result["scale"] == pytest.approx(1, abs=0.001)
    assert result["dy"] == pytest.approx(-30)


def test_zoom_clamps_and_a_pinch_in_shrinks(chart):
    result = chart.evaluate(
        """() => {
          const data = document.querySelector('.chart-shell')._x_dataStack[0];
          const vp = document.querySelector('.chart-viewport');
          const rect = vp.getBoundingClientRect();
          data.reset();
          for (let i = 0; i < 40; i++) {
            vp.dispatchEvent(new WheelEvent('wheel', {
              deltaY: 12, deltaMode: 0, ctrlKey: true,
              clientX: rect.left + 100, clientY: rect.top + 100,
              bubbles: true, cancelable: true,
            }));
          }
          const shrunk = data.scale;
          data.reset();
          for (let i = 0; i < 40; i++) {
            vp.dispatchEvent(new WheelEvent('wheel', {
              deltaY: -12, deltaMode: 0, ctrlKey: true,
              clientX: rect.left + 100, clientY: rect.top + 100,
              bubbles: true, cancelable: true,
            }));
          }
          return {shrunk, grown: data.scale};
        }"""
    )
    assert result["shrunk"] == pytest.approx(0.15, abs=0.001)
    assert result["grown"] == pytest.approx(2, abs=0.001)
