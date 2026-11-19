/* Accountability Chart canvas: zoom, pan, fit, collapse, titles-only, print, drag to re-parent. */
document.addEventListener("alpine:init", function () {
  "use strict";
  window.Alpine.data("orgChart", function (opts) {
    opts = opts || {};
    const key = "sn-chart:" + (opts.team || "");
    return {
      scale: 1,
      x: 0,
      y: 0,
      titles: false,
      collapsed: [],
      dragId: null,
      dropId: null,
      moving: false,
      _pan: null,
      init() {
        try {
          const saved = JSON.parse(localStorage.getItem(key) || "{}");
          this.titles = !!saved.titles;
          this.collapsed = saved.collapsed || [];
        } catch (e) { /* ignore */ }
        this.$nextTick(() => {
          this.applyCollapsed();
          this.fit();
        });
        document.body.addEventListener("chart:refresh", () => this.refresh());
        window.addEventListener("beforeprint", () => this.printFit(true));
        window.addEventListener("afterprint", () => this.printFit(false));
      },
      save() {
        localStorage.setItem(key, JSON.stringify({ titles: this.titles, collapsed: this.collapsed }));
      },
      get stage() { return this.$refs.stage; },
      get transform() {
        return `translate(${this.x}px, ${this.y}px) scale(${this.scale})`;
      },
      get pct() { return Math.round(this.scale * 100) + "%"; },
      clamp(s) { return Math.min(2, Math.max(0.15, s)); },
      zoomAt(factor, cx, cy) {
        const vp = this.$refs.viewport.getBoundingClientRect();
        cx = cx === undefined ? vp.width / 2 : cx - vp.left;
        cy = cy === undefined ? vp.height / 2 : cy - vp.top;
        const next = this.clamp(this.scale * factor);
        const k = next / this.scale;
        this.x = cx - (cx - this.x) * k;
        this.y = cy - (cy - this.y) * k;
        this.scale = next;
      },
      zoomIn() { this.zoomAt(1.4); },
      zoomOut() { this.zoomAt(1 / 1.4); },
      reset() {
        const vp = this.$refs.viewport;
        this.scale = 1;
        this.x = Math.max(16, (vp.clientWidth - this.stage.offsetWidth) / 2);
        this.y = 24;
      },
      fit() {
        const vp = this.$refs.viewport;
        const w = this.stage.offsetWidth, h = this.stage.offsetHeight;
        if (!w || !h) return;
        const s = this.clamp(Math.min((vp.clientWidth - 48) / w, (vp.clientHeight - 48) / h, 1));
        this.scale = s;
        this.x = (vp.clientWidth - w * s) / 2;
        this.y = Math.max(24, (vp.clientHeight - h * s) / 2);
      },
      wheel(e) {
        if (e.ctrlKey || e.metaKey) {
          // Continuous in the wheel delta, not a fixed step. A trackpad pinch arrives as a
          // ctrl+wheel with small pixel deltas, so it gets a higher factor than a mouse notch.
          const pinch = e.ctrlKey && !e.metaKey && e.deltaMode === 0 && Math.abs(e.deltaY) < 50;
          const dy = e.deltaMode === 1 ? e.deltaY * 40 : e.deltaMode === 2 ? e.deltaY * this.$refs.viewport.clientHeight : e.deltaY;
          this.zoomAt(Math.exp(-dy * (pinch ? 0.015 : 0.005)), e.clientX, e.clientY);
        } else {
          this.x -= e.deltaX;
          this.y -= e.deltaY;
        }
      },
      down(e) {
        if (e.button !== 0 || e.target.closest(".seat, button, a, input, select")) return;
        this._pan = { sx: e.clientX, sy: e.clientY, x: this.x, y: this.y };
        this.$refs.viewport.setPointerCapture(e.pointerId);
      },
      move(e) {
        if (!this._pan) return;
        this.x = this._pan.x + (e.clientX - this._pan.sx);
        this.y = this._pan.y + (e.clientY - this._pan.sy);
      },
      up() { this._pan = null; },
      key(e) {
        if (e.target.closest("input, textarea, select")) return;
        if (e.key === "+" || e.key === "=") { e.preventDefault(); this.zoomIn(); }
        else if (e.key === "-") { e.preventDefault(); this.zoomOut(); }
        else if (e.key === "0") { e.preventDefault(); this.reset(); }
        else if (e.key === "f") { e.preventDefault(); this.fit(); }
        else if (e.key === "t") { e.preventDefault(); this.toggleTitles(); }
      },
      toggleTitles() {
        this.titles = !this.titles;
        this.save();
        this.$nextTick(() => this.fit());
      },
      toggle(id) {
        id = String(id);
        const i = this.collapsed.indexOf(id);
        if (i >= 0) this.collapsed.splice(i, 1);
        else this.collapsed.push(id);
        this.save();
        this.applyCollapsed();
      },
      isCollapsed(id) { return this.collapsed.includes(String(id)); },
      applyCollapsed() {
        this.stage.querySelectorAll("li[data-node]").forEach((li) => {
          li.classList.toggle("collapsed", this.collapsed.includes(li.dataset.node));
        });
      },
      expandAll() {
        this.collapsed = [];
        this.save();
        this.applyCollapsed();
        this.$nextTick(() => this.fit());
      },
      collapseAll() {
        this.collapsed = Array.from(this.stage.querySelectorAll("li[data-node][data-depth='1'][data-has-children]")).map((li) => li.dataset.node);
        this.save();
        this.applyCollapsed();
        this.$nextTick(() => this.fit());
      },
      refresh() {
        const url = new URL(window.location.href);
        url.searchParams.set("part", "tree");
        window.htmx.ajax("GET", url.pathname + url.search, { target: "#chart-tree", swap: "outerHTML", select: "#chart-tree" })
          .then(() => this.$nextTick(() => this.applyCollapsed()));
      },
      printFit(on) {
        const st = this.stage;
        if (on) {
          this._saved = st.style.transform;
          const width = 1000;
          st.style.transform = `scale(${Math.min(1, width / st.offsetWidth)})`;
        } else if (this._saved !== undefined) {
          st.style.transform = this._saved;
        }
      },
      print() { window.print(); },
      dragStart(e, id) {
        if (!opts.canEdit) return;
        this.dragId = String(id);
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", this.dragId);
      },
      dragOver(e, id) {
        if (!this.dragId || String(id) === this.dragId) return;
        e.preventDefault();
        this.dropId = String(id);
      },
      dragLeave(id) { if (this.dropId === String(id)) this.dropId = null; },
      dragEnd() { this.dragId = null; this.dropId = null; },
      async drop(e, parentId) {
        e.preventDefault();
        const seat = this.dragId;
        this.dragEnd();
        if (!seat || String(parentId) === seat) return;
        const body = new URLSearchParams({ parent: parentId || "" });
        window.snSave && window.snSave("saving");
        const r = await fetch(`/chart/seats/${seat}/move/`, {
          method: "POST",
          headers: { "X-CSRFToken": opts.csrf, "Content-Type": "application/x-www-form-urlencoded" },
          body: body,
        });
        if (r.ok) {
          window.snSave && window.snSave("saved");
          this.refresh();
        } else {
          window.snSave && window.snSave("error");
          const data = await r.json().catch(() => ({}));
          if (data.error) alert(data.error);
        }
      },
    };
  });
});
