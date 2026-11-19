/* SN EOS UI layer: side panel, save indicator, keyboard shortcuts, command palette, drag reorder. */
(function () {
  "use strict";

  if (window.htmx) {
    window.htmx.config.responseHandling = [
      { code: "204", swap: false },
      { code: "[23]..", swap: true },
      { code: "422", swap: true, error: true },
      { code: "[45]..", swap: false, error: true },
      { code: "...", swap: false },
    ];
  }

  function csrf() {
    try {
      return JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRFToken"] || "";
    } catch (e) {
      return "";
    }
  }

  function navData() {
    const el = document.getElementById("sn-nav");
    return el ? JSON.parse(el.textContent) : { nav: {}, palette: [] };
  }

  document.addEventListener("alpine:init", function () {
    window.Alpine.store("ui", {
      panel: false,
      panelWide: false,
      help: false,
      palette: false,
      openPanel(wide) {
        this.panelWide = !!wide;
        this.panel = true;
      },
      closePanel() {
        this.panel = false;
        const body = document.getElementById("panel-body");
        if (body) setTimeout(() => { if (!this.panel) body.innerHTML = ""; }, 200);
      },
    });

    window.Alpine.data("palette", function () {
      return {
        q: "",
        active: 0,
        get items() {
          const all = navData().palette || [];
          const q = this.q.trim().toLowerCase();
          if (!q) return all;
          return all.filter((i) => (i.label + " " + (i.group || "") + " " + (i.keywords || "")).toLowerCase().includes(q));
        },
        move(d) {
          const n = this.items.length;
          if (n) this.active = (this.active + d + n) % n;
          this.$nextTick(() => {
            const el = this.$root.querySelector('[data-active="true"]');
            if (el) el.scrollIntoView({ block: "nearest" });
          });
        },
        go(item) {
          item = item || this.items[this.active];
          if (!item) return;
          this.$store.ui.palette = false;
          this.q = "";
          window.location.href = item.url;
        },
      };
    });
  });

  /* ---- Side panel: <a data-panel href="..."> loads the URL into the drawer. ---- */
  document.addEventListener("click", function (e) {
    const a = e.target.closest("[data-panel]");
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.target.closest("[data-no-panel]")) return;
    e.preventDefault();
    const url = a.dataset.panel || a.getAttribute("href");
    window.htmx.ajax("GET", url, { target: "#panel-body", swap: "innerHTML" }).then(function () {
      window.Alpine.store("ui").openPanel(a.hasAttribute("data-panel-wide"));
      const first = document.querySelector("#panel-body [autofocus]");
      if (first) first.focus();
    });
  });
  document.body.addEventListener("panel:close", function () {
    window.Alpine.store("ui").closePanel();
  });

  /* ---- Save indicator: any non-GET htmx request. ---- */
  const LABELS = { saving: "Saving…", saved: "Saved", error: "Couldn't save. Try again." };
  function setSave(state) {
    const el = document.getElementById("save-indicator");
    if (!el) return;
    el.dataset.state = state;
    el.querySelector("[data-label]").textContent = LABELS[state] || "";
    clearTimeout(el._t);
    if (state === "saved") el._t = setTimeout(() => { el.dataset.state = "idle"; }, 1600);
    if (state === "error") el._t = setTimeout(() => { el.dataset.state = "idle"; }, 4000);
  }
  window.snSave = setSave;
  function verb(e) {
    return ((e.detail.requestConfig && e.detail.requestConfig.verb) || "get").toLowerCase();
  }
  document.addEventListener("htmx:beforeRequest", function (e) {
    if (verb(e) !== "get" && !e.detail.boosted) setSave("saving");
  });
  document.addEventListener("htmx:afterRequest", function (e) {
    if (verb(e) === "get" || e.detail.boosted) return;
    setSave(e.detail.successful ? "saved" : "error");
  });

  /* ---- Keyboard shortcuts ---- */
  let pending = null;
  document.addEventListener("keydown", function (e) {
    const ui = window.Alpine && window.Alpine.store("ui");
    if (!ui) return;
    const t = e.target;
    const typing = t.closest && t.closest("input, textarea, select, [contenteditable=true]");
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      ui.palette = !ui.palette;
      return;
    }
    if (e.key === "Escape") {
      if (ui.palette || ui.help || ui.panel) {
        ui.palette = false;
        ui.help = false;
        ui.closePanel();
        e.preventDefault();
      } else if (typing) {
        t.blur();
      }
      return;
    }
    if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
    if (pending === "g") {
      pending = null;
      const url = (navData().nav || {})[e.key];
      if (url) {
        e.preventDefault();
        window.location.href = url;
      }
      return;
    }
    if (e.key === "g") {
      pending = "g";
      setTimeout(() => { pending = null; }, 1200);
      return;
    }
    if (e.key === "?") {
      e.preventDefault();
      ui.help = !ui.help;
    } else if (e.key === "/") {
      e.preventDefault();
      ui.palette = true;
    } else if (e.key === "n" || e.key === "c") {
      const el = document.querySelector('[data-shortcut="new"]');
      if (el) {
        e.preventDefault();
        if (el.matches("input, textarea, select")) el.focus();
        else el.click();
      }
    }
  });

  /* ---- Drag reorder: <ul data-sortable="/url/"> with children [data-id] and a .drag-handle. ---- */
  function initSortable(root) {
    root.querySelectorAll("[data-sortable]").forEach(function (list) {
      if (list._snSortable) return;
      list._snSortable = true;
      let dragging = null;
      const items = () => Array.from(list.children).filter((c) => c.dataset && c.dataset.id);
      list.addEventListener("mousedown", function (e) {
        const handle = e.target.closest(".drag-handle");
        const item = handle && handle.closest("[data-id]");
        if (item && item.parentElement === list) item.setAttribute("draggable", "true");
      });
      list.addEventListener("dragstart", function (e) {
        const item = e.target.closest && e.target.closest("[data-id]");
        if (!item || item.parentElement !== list) return;
        dragging = item;
        item.classList.add("is-dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", item.dataset.id);
      });
      list.addEventListener("dragover", function (e) {
        if (!dragging) return;
        e.preventDefault();
        const others = items().filter((c) => c !== dragging);
        const after = others.find((c) => e.clientY < c.getBoundingClientRect().top + c.offsetHeight / 2);
        if (after) list.insertBefore(dragging, after);
        else if (others.length) others[others.length - 1].after(dragging);
      });
      list.addEventListener("dragend", function () {
        if (!dragging) return;
        dragging.classList.remove("is-dragging");
        dragging.removeAttribute("draggable");
        dragging = null;
        const body = new URLSearchParams({ ids: items().map((c) => c.dataset.id).join(",") });
        setSave("saving");
        fetch(list.dataset.sortable, {
          method: "POST",
          headers: { "X-CSRFToken": csrf(), "Content-Type": "application/x-www-form-urlencoded" },
          body: body,
        }).then((r) => setSave(r.ok ? "saved" : "error")).catch(() => setSave("error"));
      });
    });
  }
  document.addEventListener("DOMContentLoaded", () => initSortable(document));
  document.addEventListener("htmx:afterSettle", (e) => initSortable(e.target));
})();
