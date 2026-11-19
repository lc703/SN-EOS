/* Accountability Chart: zoom, pan, fit, collapse, titles-only, drag to re-parent, print layout. */
(function () {
  "use strict";
  if (window.SNChart) { window.SNChart.boot(); return; }
  var MIN = 0.2, MAX = 2.5;

  function init(vp) {
    if (!vp || vp._chart) return;
    var key = "sn-chart-" + (vp.dataset.team || "0");
    var saved = {};
    try { saved = JSON.parse(localStorage.getItem(key) || "{}"); } catch (e) { saved = {}; }
    var st = { scale: saved.scale || 1, x: saved.x || 0, y: saved.y || 0, collapsed: saved.collapsed || [], titles: !!saved.titles };
    var canEdit = vp.dataset.canEdit === "1";
    var zoomLabel = vp.querySelector("[data-chart-zoom]");
    var titlesBtn = vp.querySelector('[data-chart="titles"]');
    vp._chart = st;

    function canvas() { return vp.querySelector("#chart-canvas"); }
    function save() {
      try { localStorage.setItem(key, JSON.stringify(st)); } catch (e) { /* storage full or blocked */ }
    }
    function apply(animate) {
      var c = canvas();
      if (!c) return;
      c.style.transition = animate ? "transform .25s cubic-bezier(.2,.8,.2,1)" : "none";
      c.style.transform = "translate(" + st.x + "px," + st.y + "px) scale(" + st.scale + ")";
      if (zoomLabel) zoomLabel.textContent = Math.round(st.scale * 100) + "%";
      save();
    }
    function applyCollapsed() {
      var c = canvas();
      if (!c) return;
      c.querySelectorAll("[data-seat-li]").forEach(function (li) {
        var on = st.collapsed.indexOf(li.dataset.seatLi) !== -1 && li.querySelector(":scope > ul");
        li.classList.toggle("collapsed", !!on);
        var icon = li.querySelector(":scope > .seat [data-toggle-icon]");
        if (icon) icon.textContent = on ? "+" : "−";
      });
    }
    function applyTitles() {
      vp.classList.toggle("chart-titles", st.titles);
      if (titlesBtn) titlesBtn.setAttribute("aria-pressed", st.titles ? "true" : "false");
    }
    function zoomAt(factor, cx, cy, animate) {
      var r = vp.getBoundingClientRect();
      var px = cx === undefined ? r.width / 2 : cx - r.left;
      var py = cy === undefined ? r.height / 2 : cy - r.top;
      var next = Math.min(MAX, Math.max(MIN, st.scale * factor));
      var k = next / st.scale;
      st.x = px - (px - st.x) * k;
      st.y = py - (py - st.y) * k;
      st.scale = next;
      apply(animate);
    }
    function fit(animate) {
      var c = canvas();
      if (!c) return;
      var r = vp.getBoundingClientRect();
      var w = c.scrollWidth, h = c.scrollHeight;
      if (!w || !h) return;
      var s = Math.min(1.1, Math.max(MIN, Math.min((r.width - 24) / w, (r.height - 70) / h)));
      st.scale = s;
      st.x = (r.width - w * s) / 2;
      st.y = Math.max(44, (r.height - h * s) / 2);
      apply(animate);
    }
    function reset() {
      var c = canvas();
      var r = vp.getBoundingClientRect();
      st.scale = 1;
      var root = c && c.querySelector(".seat.is-root");
      if (root) {
        var cr = c.getBoundingClientRect();
        var rr = root.getBoundingClientRect();
        var curScale = cr.width / c.offsetWidth || 1;
        var rootCenter = (rr.left - cr.left) / curScale + rr.width / curScale / 2;
        st.x = r.width / 2 - rootCenter;
      } else st.x = 0;
      st.y = 44;
      apply(true);
    }

    /* toolbar */
    vp.addEventListener("click", function (e) {
      var b = e.target.closest("[data-chart]");
      if (!b) return;
      e.stopPropagation();
      var a = b.dataset.chart;
      if (a === "in") zoomAt(1.2, undefined, undefined, true);
      else if (a === "out") zoomAt(1 / 1.2, undefined, undefined, true);
      else if (a === "fit") fit(true);
      else if (a === "reset") reset();
      else if (a === "titles") { st.titles = !st.titles; applyTitles(); save(); }
      else if (a === "expand") { st.collapsed = []; applyCollapsed(); save(); }
      else if (a === "collapse") {
        st.collapsed = [];
        canvas().querySelectorAll('.seat[data-depth="1"]').forEach(function (s) {
          var li = s.closest("[data-seat-li]");
          if (li.querySelector(":scope > ul")) st.collapsed.push(li.dataset.seatLi);
        });
        applyCollapsed(); save(); fit(true);
      }
    });

    /* focusing a seat must not scroll the clipped viewport; panning is done with transforms */
    vp.addEventListener("scroll", function () { vp.scrollTop = 0; vp.scrollLeft = 0; });

    /* wheel: pinch / ctrl+wheel zooms, plain wheel pans */
    vp.addEventListener("wheel", function (e) {
      e.preventDefault();
      if (e.ctrlKey || e.metaKey) zoomAt(Math.exp(-e.deltaY * 0.01), e.clientX, e.clientY);
      else { st.x -= e.deltaX; st.y -= e.deltaY; apply(); }
    }, { passive: false });

    /* pointer: pan on background, click or drag on seats */
    var drag = null;
    vp.addEventListener("pointerdown", function (e) {
      if (e.button !== 0 || e.target.closest("[data-chart], .chart-toolbar, a, button.seat-toggle")) return;
      var seat = e.target.closest(".seat");
      drag = { sx: e.clientX, sy: e.clientY, x: st.x, y: st.y, seat: seat, moved: false, id: e.pointerId };
      vp.setPointerCapture(e.pointerId);
    });
    vp.addEventListener("pointermove", function (e) {
      if (!drag || e.pointerId !== drag.id) return;
      var dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
      if (!drag.moved && Math.abs(dx) + Math.abs(dy) < 6) return;
      if (!drag.moved) {
        drag.moved = true;
        if (drag.seat && canEdit && !drag.seat.classList.contains("is-root-only")) {
          drag.ghost = drag.seat.cloneNode(true);
          drag.ghost.classList.add("seat-ghost");
          drag.ghost.style.width = drag.seat.offsetWidth + "px";
          document.body.appendChild(drag.ghost);
          drag.seat.classList.add("dragging");
        } else {
          drag.seat = null;
          vp.classList.add("panning");
        }
      }
      if (drag.ghost) {
        drag.ghost.style.left = e.clientX - 40 + "px";
        drag.ghost.style.top = e.clientY - 20 + "px";
        var under = document.elementFromPoint(e.clientX, e.clientY);
        var target = under && under.closest && under.closest(".seat");
        var li = drag.seat.closest("[data-seat-li]");
        if (target && li.contains(target)) target = null;
        if (drag.target && drag.target !== target) drag.target.classList.remove("drop-target");
        drag.target = target;
        if (target) target.classList.add("drop-target");
        edgePan(e);
      } else {
        st.x = drag.x + dx; st.y = drag.y + dy; apply();
      }
    });
    function edgePan(e) {
      var r = vp.getBoundingClientRect(), m = 40, step = 12;
      if (e.clientX < r.left + m) st.x += step;
      else if (e.clientX > r.right - m) st.x -= step;
      if (e.clientY < r.top + m) st.y += step;
      else if (e.clientY > r.bottom - m) st.y -= step;
      apply();
    }
    function endDrag(e) {
      if (!drag || (e && e.pointerId !== drag.id)) return;
      var d = drag;
      drag = null;
      vp.classList.remove("panning");
      if (d.ghost) {
        d.ghost.remove();
        d.seat.classList.remove("dragging");
        if (d.target) {
          d.target.classList.remove("drop-target");
          move(d.seat.dataset.seat, d.target.dataset.seat);
        }
        return;
      }
      if (!d.moved && d.seat) openSeat(d.seat.dataset.seat);
    }
    vp.addEventListener("pointerup", endDrag);
    vp.addEventListener("pointercancel", endDrag);

    function openSeat(id) {
      canvas().querySelectorAll(".seat.selected").forEach(function (s) { s.classList.remove("selected"); });
      var s = canvas().querySelector('.seat[data-seat="' + id + '"]');
      if (s) s.classList.add("selected");
      window.htmx.ajax("GET", vp.dataset.panelUrl.replace("/0/", "/" + id + "/"), { target: "#panel-content", swap: "innerHTML" });
      var url = new URL(window.location);
      url.searchParams.set("open", id);
      history.replaceState(history.state, "", url);
    }
    function move(id, parent) {
      var body = new URLSearchParams();
      body.append("parent", parent || "");
      fetch(vp.dataset.moveUrl.replace("/0/", "/" + id + "/"), {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": window.SN.csrf(), "HX-Request": "true", "Content-Type": "application/x-www-form-urlencoded" },
        body: body,
      }).then(function (r) {
        var trig = r.headers.get("HX-Trigger");
        var msg = null, kind = r.ok ? "" : "error";
        try { msg = trig && JSON.parse(trig).toast; } catch (err) { msg = null; }
        window.SN.toast((msg && msg.value) || (r.ok ? "Moved." : "Couldn't move that seat."), (msg && msg.kind) || kind);
        if (r.ok) window.htmx.trigger(document.body, "chartChanged");
      });
    }

    /* collapse toggles */
    vp.addEventListener("click", function (e) {
      var t = e.target.closest("[data-toggle]");
      if (!t) return;
      e.stopPropagation();
      var id = t.dataset.toggle, i = st.collapsed.indexOf(id);
      if (i === -1) st.collapsed.push(id); else st.collapsed.splice(i, 1);
      applyCollapsed(); save();
    });

    /* keyboard on a focused seat */
    vp.addEventListener("keydown", function (e) {
      var s = e.target.closest && e.target.closest(".seat");
      if (s && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openSeat(s.dataset.seat); }
    });

    /* re-apply after the canvas is refreshed */
    document.body.addEventListener("htmx:afterSwap", function (e) {
      if (!vp.isConnected || !canvas()) return;
      if (e.detail.target && (e.detail.target.id === "chart-canvas" || e.detail.target.contains && e.detail.target.contains(canvas()))) {
        applyCollapsed(); apply();
        var open = new URL(window.location).searchParams.get("open");
        if (open) { var sel = canvas().querySelector('.seat[data-seat="' + open + '"]'); if (sel) sel.classList.add("selected"); }
      }
    });

    /* print: scale the whole chart to the page width */
    window.addEventListener("beforeprint", function () {
      if (!vp.isConnected) return;
      var c = canvas();
      if (!c) return;
      c.style.transition = "none";
      var s = Math.min(1, 1000 / c.scrollWidth);
      c.style.transform = "scale(" + s + ")";
      vp.style.height = c.scrollHeight * s + 20 + "px";
    });
    window.addEventListener("afterprint", function () { if (vp.isConnected) { vp.style.height = ""; apply(); } });

    applyTitles();
    applyCollapsed();
    if (saved.scale) apply(); else fit(false);
    if (vp.dataset.open) openSeat(vp.dataset.open);
  }

  document.addEventListener("keydown", function (e) {
    var vp = document.getElementById("chart-viewport");
    if (!vp || !vp._chart || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.target && (e.target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName))) return;
    var btn = null;
    if (e.key === "+" || e.key === "=") btn = "in";
    else if (e.key === "-" || e.key === "_") btn = "out";
    else if (e.key === "0") btn = "fit";
    else if (e.key === "t" || e.key === "T") btn = "titles";
    if (btn) { e.preventDefault(); vp.querySelector('[data-chart="' + btn + '"]').click(); }
  });

  function boot() { init(document.getElementById("chart-viewport")); }
  window.SNChart = { boot: boot };
  if (document.readyState !== "loading") boot(); else document.addEventListener("DOMContentLoaded", boot);
  document.addEventListener("htmx:load", boot);
})();
