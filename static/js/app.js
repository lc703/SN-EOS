/* SN EOS client glue: side panel, toasts, save indicator, keyboard shortcuts, drag-reorder. */
(function () {
  "use strict";

  function csrf() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.content : "";
  }

  document.addEventListener("alpine:init", function () {
    window.Alpine.store("ui", {
      panel: false,
      help: false,
      save: "",
      _t: null,
      closePanel: function () {
        this.panel = false;
        var url = new URL(window.location);
        if (url.searchParams.has("open")) {
          url.searchParams.delete("open");
          history.replaceState(history.state, "", url);
        }
      },
      setSave: function (state) {
        var self = this;
        clearTimeout(self._t);
        self.save = state;
        if (state === "saved") self._t = setTimeout(function () { self.save = ""; }, 1800);
      },
    });
  });

  function ui() { return window.Alpine && window.Alpine.store("ui"); }

  /* ---------- toasts ---------- */
  function toast(text, kind) {
    var box = document.getElementById("toasts");
    if (!box) return;
    var el = document.createElement("div");
    el.className = "toast fade-in" + (kind === "error" ? " !bg-red-700" : "");
    el.setAttribute("data-toast", "");
    var dot = document.createElement("span");
    dot.className = "h-2 w-2 rounded-full " + (kind === "error" ? "bg-white" : "bg-bolt");
    el.appendChild(dot);
    el.appendChild(document.createTextNode(text));
    box.appendChild(el);
    dismiss(el);
  }
  function dismiss(el) {
    setTimeout(function () {
      el.style.transition = "opacity .3s, transform .3s";
      el.style.opacity = "0";
      el.style.transform = "translateY(6px)";
      setTimeout(function () { el.remove(); }, 320);
    }, 3200);
  }
  window.SN = { toast: toast, csrf: csrf };
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-toast]").forEach(dismiss);
  });
  document.addEventListener("toast", function (e) {
    toast((e.detail && (e.detail.value || e.detail.message)) || "Done", e.detail && e.detail.kind);
  });

  /* ---------- side panel ---------- */
  document.addEventListener("htmx:beforeRequest", function (e) {
    var t = e.detail.target;
    if (t && t.id === "panel-content" && ui()) ui().panel = true;
  });
  document.addEventListener("htmx:afterSwap", function (e) {
    if (e.detail.target && e.detail.target.id === "panel-content") {
      var first = e.detail.target.querySelector("[autofocus], input:not([type=hidden]), textarea, select");
      if (first && window.matchMedia("(min-width: 768px)").matches) first.focus();
    }
  });
  document.addEventListener("closePanel", function () { if (ui()) ui().closePanel(); });
  document.addEventListener("htmx:beforeHistorySave", function () {
    if (ui()) { ui().panel = false; ui().help = false; }
  });

  /* ---------- save indicator ---------- */
  function isSave(e) {
    var v = (e.detail.requestConfig && e.detail.requestConfig.verb) || "";
    var el = e.detail.elt;
    return v.toLowerCase() === "post" && !(el && el.closest && el.closest("[data-no-save]"));
  }
  document.addEventListener("htmx:beforeRequest", function (e) { if (isSave(e) && ui()) ui().setSave("saving"); });
  document.addEventListener("htmx:afterRequest", function (e) {
    if (!isSave(e) || !ui()) return;
    ui().setSave(e.detail.successful ? "saved" : "error");
  });
  document.addEventListener("htmx:responseError", function (e) {
    var xhr = e.detail.xhr;
    var msg = xhr && xhr.status === 403 ? "You don't have permission to change that." : "Something went wrong. Try again.";
    toast(msg, "error");
  });
  document.addEventListener("htmx:sendError", function () { toast("You're offline. Changes weren't saved.", "error"); });

  /* Autosave: inputs inside [data-autosave] forms post on change (debounced for text). */
  document.addEventListener("input", function (e) {
    var form = e.target.closest && e.target.closest("form[data-autosave]");
    if (!form || e.target.matches("select, [type=checkbox], [type=radio], [type=date]")) return;
    clearTimeout(form._sn);
    form._sn = setTimeout(function () { window.htmx.trigger(form, "autosave"); }, 700);
  });
  document.addEventListener("change", function (e) {
    var form = e.target.closest && e.target.closest("form[data-autosave]");
    if (!form) return;
    clearTimeout(form._sn);
    window.htmx.trigger(form, "autosave");
  });

  /* ---------- drag reorder (SortableJS) ---------- */
  function initSortables(root) {
    if (!window.Sortable) return;
    (root || document).querySelectorAll("[data-sortable]").forEach(function (list) {
      if (list._sortable) return;
      list._sortable = window.Sortable.create(list, {
        handle: list.dataset.handle || ".drag-handle",
        draggable: list.dataset.draggable || "[data-id]",
        group: list.dataset.group || undefined,
        animation: 160,
        ghostClass: "sortable-ghost",
        chosenClass: "sortable-chosen",
        dragClass: "sortable-drag",
        onEnd: function (evt) {
          var to = evt.to;
          var ids = Array.prototype.map.call(to.querySelectorAll(":scope > [data-id]"), function (n) { return n.dataset.id; });
          var body = new URLSearchParams();
          ids.forEach(function (id) { body.append("ids", id); });
          if (to.dataset.groupValue) body.append("group", to.dataset.groupValue);
          if (evt.item && evt.item.dataset.id) body.append("moved", evt.item.dataset.id);
          if (ui()) ui().setSave("saving");
          fetch(to.dataset.sortable, {
            method: "POST",
            headers: { "X-CSRFToken": csrf(), "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true" },
            body: body,
            credentials: "same-origin",
          }).then(function (r) {
            if (ui()) ui().setSave(r.ok ? "saved" : "error");
            if (!r.ok) toast("Couldn't save the new order.", "error");
            else if (to.dataset.refresh) window.htmx.trigger(document.body, to.dataset.refresh);
          }).catch(function () { if (ui()) ui().setSave("error"); });
        },
      });
    });
  }
  document.addEventListener("DOMContentLoaded", function () { initSortables(document); });
  document.addEventListener("htmx:load", function (e) { initSortables(e.detail.elt); });

  /* ---------- keyboard shortcuts ---------- */
  var GO = { h: "/", s: "/scorecard/", r: "/rocks/", t: "/todos/", i: "/issues/", l: "/meetings/", q: "/sessions/", v: "/vto/", c: "/chart/", p: "/people/" };
  var pendingG = 0;
  function typing(el) {
    return el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
  }
  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    var s = ui();
    if (e.key === "Escape") {
      if (s && s.help) { s.help = false; return; }
      if (s && s.panel) { s.closePanel(); return; }
      if (typing(document.activeElement)) document.activeElement.blur();
      return;
    }
    if (typing(e.target)) return;
    if (pendingG && Date.now() - pendingG < 1200) {
      pendingG = 0;
      var url = GO[e.key.toLowerCase()];
      if (url) { e.preventDefault(); window.location.href = url; }
      return;
    }
    if (e.key === "g" || e.key === "G") { pendingG = Date.now(); return; }
    if (e.key === "?") { e.preventDefault(); if (s) s.help = !s.help; return; }
    if (e.key === "n" || e.key === "N") {
      var btn = document.querySelector("[data-shortcut-new]");
      if (btn) { e.preventDefault(); btn.click(); }
      return;
    }
    if (e.key === "/") {
      var f = document.querySelector("main [data-shortcut-focus], main input[type=search], main input[type=text]");
      if (f) { e.preventDefault(); f.focus(); }
    }
  });
})();
