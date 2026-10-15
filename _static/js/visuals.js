/* The two coverage visuals of the site: the capability map (.capmap) and the rosette (.rosette).
 *
 * The capability map is drawn on the server with every tool's list and the comparison table in the page; this script only
 * switches tools: the chip row is a single-select picker (arrow keys move it), the dots slide to the stop of the chosen tool
 * (CSS transition, none under reduced motion), and the chosen tool's sentence and list are shown. The rosette is drawn for
 * every device and this script shows the one the page's switch selects; a tool's chip or band isolates it, a feature shows
 * its readings, a sector can be focused (on a phone-width column the sector picker shows one sector fanned).
 * Cross-highlight: anything carrying data-feature lights every other element of the same feature on the page while it is
 * hovered or focused. Nothing is hover-only: every fact is in the tables, and a tap does what hover does. Vanilla JS. */
(function () {
  "use strict";

  function mk(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined) { e.textContent = text; }
    return e;
  }

  /* ---- cross-highlight: delegated, so the radar's own elements take part without knowing about this file ---- */
  var xhKey = null;
  function setXh(key) {
    if (key === xhKey) { return; }
    var old = document.querySelectorAll(".xh");
    for (var i = 0; i < old.length; i++) { old[i].classList.remove("xh"); }
    xhKey = key;
    if (!key) { return; }
    var sel = '[data-feature="' + key + '"], [data-axis="' + key + '"]';
    var hit = document.querySelectorAll(sel);
    for (var j = 0; j < hit.length; j++) { hit[j].classList.add("xh"); }
  }
  function featureOf(target) {
    if (!target.closest) { return null; }
    var n = target.closest("[data-feature], .radar-axis[data-axis], .radar-icon[data-axis]");
    return n ? (n.getAttribute("data-feature") || n.getAttribute("data-axis")) : null;
  }
  document.addEventListener("mouseover", function (ev) { setXh(featureOf(ev.target)); });
  document.addEventListener("mouseout", function (ev) { if (!ev.relatedTarget || !featureOf(ev.relatedTarget)) { setXh(null); } });
  document.addEventListener("focusin", function (ev) { setXh(featureOf(ev.target)); });
  document.addEventListener("focusout", function () { setXh(null); });

  function mount(root) {
    var data = JSON.parse(root.querySelector(".worlds-json").textContent);
    var side = data.side;
    var stage = root.querySelector(".worlds-stage");
    var pop = root.querySelector(".worlds-pop");
    var status = root.querySelector(".worlds-status");
    var legend = root.querySelectorAll(".worlds-leg");
    var devSlug = null, hl = null, pinned = null;

    /* ---- the device ---- */
    function showDevice(slug) {
      var devs = root.querySelectorAll(".worlds-dev");
      var any = false;
      for (var i = 0; i < devs.length; i++) {
        var on = devs[i].getAttribute("data-slug") === slug;
        devs[i].hidden = !on;
        any = any || on;
      }
      if (!any && devs.length) { devs[0].hidden = false; slug = devs[0].getAttribute("data-slug"); }
      devSlug = slug;
      closePop();
      setHl(null);
    }
    function followSwitch() {
      var r = document.querySelector('.perf-switch input[name="perf-' + side + '"]:checked');
      var slug = r ? r.getAttribute("data-slug") : null;
      if (slug && slug !== devSlug) { showDevice(slug); }
    }
    var sw = document.querySelector(".perf-switch");
    if (sw) { sw.addEventListener("perf-device-change", followSwitch); }
    var first = root.querySelector(".worlds-dev:not([hidden])");
    devSlug = first ? first.getAttribute("data-slug") : null;
    followSwitch();

    /* ---- a tool: chip and blob share one handler ---- */
    function setHl(tool) {
      if (hl === tool) { return; }
      hl = tool;
      root.classList.toggle("has-hl", !!tool);
      var els = root.querySelectorAll("[data-tool]");
      for (var i = 0; i < els.length; i++) { els[i].classList.toggle("is-hl", !!tool && els[i].getAttribute("data-tool") === tool); }
      for (var j = 0; j < legend.length; j++) { legend[j].setAttribute("aria-pressed", tool && legend[j].getAttribute("data-tool") === tool ? "true" : "false"); }
      if (status) { status.textContent = tool ? tool : ""; }
    }
    function bindTool(el) {
      var tool = el.getAttribute("data-tool");
      el.addEventListener("mouseenter", function () { setHl(tool); });
      el.addEventListener("mouseleave", function () { if (pinned !== tool) { setHl(null); } });
      el.addEventListener("focus", function () { setHl(tool); });
      el.addEventListener("blur", function () { if (pinned !== tool) { setHl(null); } });
      el.addEventListener("click", function (ev) {
        ev.stopPropagation();
        pinned = pinned === tool ? null : tool;
        setHl(pinned);
      });
    }
    var tools = root.querySelectorAll(".worlds-leg, path.blob[data-tool]");
    for (var t = 0; t < tools.length; t++) { bindTool(tools[t]); }

    /* ---- the evidence popover of a block or a feature ---- */
    var popTimer = null;
    function closePop() { if (popTimer) { clearTimeout(popTimer); popTimer = null; } if (pop) { pop.hidden = true; pop.textContent = ""; } }
    /* leaving a node closes its popover a moment later, so the pointer can reach the links inside it */
    function closeSoon() { if (popTimer) { clearTimeout(popTimer); } popTimer = setTimeout(closePop, 250); }
    if (pop) {
      pop.addEventListener("mouseenter", function () { if (popTimer) { clearTimeout(popTimer); popTimer = null; } });
      pop.addEventListener("mouseleave", closeSoon);
    }
    function evidence(key, kind) {
      var d = data.devices[devSlug];
      var feats, title, who = null, dropped = [];
      if (kind === "block") {
        var b = d.blocks[key];
        title = b.l; feats = b.f.map(function (f) { return f[0]; }); who = b.w; dropped = b.x || [];
      } else {
        title = null; feats = [key];
      }
      var box = mk("div", "wp");
      var toolNames = Object.keys(d.vals[feats[0]] || {});
      var labelOf = function (f) { var r = root.querySelector('.worlds-features tr[data-feature="' + f + '"] th, .worlds-dev:not([hidden]) tr[data-feature="' + f + '"] th'); return r ? r.textContent : f; };
      if (title) { box.appendChild(mk("div", "wp-h", title)); }
      else { box.appendChild(mk("div", "wp-h", labelOf(key))); }
      if (kind === "block") { box.appendChild(mk("div", "wp-s", "Needs " + feats.map(labelOf).join(", ") + ".")); }
      var tb = mk("table", "wp-t");
      var head = mk("tr");
      head.appendChild(mk("th", "", ""));
      toolNames.forEach(function (n) { head.appendChild(mk("th", "", n)); });
      tb.appendChild(head);
      feats.forEach(function (f) {
        var tr = mk("tr");
        var th = mk("th", "", labelOf(f));
        th.setAttribute("data-feature", f);
        tr.appendChild(th);
        toolNames.forEach(function (n) {
          var v = d.vals[f] && d.vals[f][n], td = mk("td");
          if (!v) { td.className = "miss"; td.textContent = "no reading"; }
          else {
            td.className = v[2] ? "ok" : "no";
            td.appendChild(mk("span", "v", v[0] + (v[2] ? " ✓" : "")));
            if (v[1]) { td.appendChild(mk("span", "r", v[1].replace(/ the best$/, ""))); }
          }
          tr.appendChild(td);
        });
        tb.appendChild(tr);
      });
      box.appendChild(tb);
      if (who) { box.appendChild(mk("div", "wp-s", who.length ? "Covered by " + who.join(", ") + "." : "No tool covers this block on this device.")); }
      if (dropped.length) { box.appendChild(mk("div", "wp-s", "No reading on this device for " + dropped.map(labelOf).join(", ") + ": left out of the block's needs.")); }
      return box;
    }
    function placePop(anchor) {
      pop.hidden = false;
      var narrow = root.clientWidth < 640;
      pop.classList.toggle("inflow", narrow);
      if (narrow) { pop.style.left = ""; pop.style.top = ""; return; }
      var st = stage.getBoundingClientRect(), ar = anchor.getBoundingClientRect();
      var w = pop.offsetWidth, h = pop.offsetHeight;
      var left = Math.max(0, Math.min(st.width - w, ar.left - st.left + ar.width + 10));
      if (left + w > ar.left - st.left && ar.left - st.left > w + 10 && ar.left - st.left + ar.width + 10 + w > st.width) { left = ar.left - st.left - w - 10; }
      var top = Math.max(0, Math.min(st.height - h, ar.top - st.top - 8));
      pop.style.left = left + "px";
      pop.style.top = top + "px";
    }
    function showNode(n) {
      if (!pop) { return; }
      if (popTimer) { clearTimeout(popTimer); popTimer = null; }
      var block = n.getAttribute("data-block"), feature = n.getAttribute("data-feature");
      pop.textContent = "";
      pop.appendChild(evidence(block || feature, block ? "block" : "feature"));
      placePop(n);
    }
    var nodes = root.querySelectorAll(".rnode");
    for (var k = 0; k < nodes.length; k++) {
      (function (n) {
        n.addEventListener("mouseenter", function () { showNode(n); });
        n.addEventListener("mouseleave", closeSoon);
        n.addEventListener("focus", function () { showNode(n); });
        n.addEventListener("blur", closeSoon);
        n.addEventListener("click", function (ev) { ev.stopPropagation(); showNode(n); });
        n.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); showNode(n); } });
      })(nodes[k]);
    }
    /* ---- rosette: a sector is focus (wide) or the picker's choice (phone width) ---- */
    function focusSector(sk) {
      root.classList.toggle("has-focus", !!sk);
      var els = root.querySelectorAll("[data-sector]");
      for (var i = 0; i < els.length; i++) { els[i].classList.toggle("is-focus", !!sk && els[i].getAttribute("data-sector") === sk); }
    }
    var sectors = root.querySelectorAll(".rsector");
    for (var s = 0; s < sectors.length; s++) {
      (function (g) {
        var sk = g.getAttribute("data-sector");
        g.addEventListener("mouseenter", function () { focusSector(sk); });
        g.addEventListener("mouseleave", function () { focusSector(null); });
        g.addEventListener("focus", function () { focusSector(sk); });
        g.addEventListener("blur", function () { focusSector(null); });
        g.addEventListener("click", function (ev) { ev.stopPropagation(); focusSector(sk); });
      })(sectors[s]);
    }
    var picks = root.querySelectorAll(".pick");
    function pick(sk) {
      for (var i = 0; i < picks.length; i++) {
        var on = picks[i].getAttribute("data-sector") === sk;
        picks[i].classList.toggle("on", on);
        picks[i].setAttribute("aria-pressed", on ? "true" : "false");
      }
      var panes = root.querySelectorAll(".rosette-sector");
      for (var j = 0; j < panes.length; j++) { panes[j].hidden = panes[j].getAttribute("data-sector") !== sk; }
      closePop();
    }
    for (var p = 0; p < picks.length; p++) {
      (function (b) { b.addEventListener("click", function () { pick(b.getAttribute("data-sector")); }); })(picks[p]);
    }

    root.addEventListener("keydown", function (ev) { if (ev.key === "Escape") { pinned = null; setHl(null); closePop(); focusSector(null); } });
    document.addEventListener("pointerdown", function (ev) {
      if (!ev.target.closest || !ev.target.closest(".worlds-leg, .blob, .rnode, .rsector, .worlds-pop, .pick")) {
        pinned = null; setHl(null); closePop(); focusSector(null);
      }
    });
  }

  /* ---- the Radar | Rosette toggle of the detailed view ---- */
  var VIEW_KEY = "raptor-detail-view";
  function initToggle() {
    var roots = document.querySelectorAll(".perf-detailed");
    for (var r = 0; r < roots.length; r++) {
      (function (root) {
        var opts = root.querySelectorAll(".view-opt");
        if (!opts.length) { return; }
        function show(view) {
          root.setAttribute("data-view", view);
          for (var i = 0; i < opts.length; i++) { opts[i].setAttribute("aria-pressed", opts[i].getAttribute("data-view") === view ? "true" : "false"); }
        }
        var saved = null;
        try { saved = window.localStorage.getItem(VIEW_KEY); } catch (e) { /* private window */ }
        root.classList.add("view-js");
        show(saved === "radar" ? "radar" : "rosette");
        root.addEventListener("click", function (ev) {
          var b = ev.target.closest ? ev.target.closest(".view-opt") : null;
          if (!b) { return; }
          var v = b.getAttribute("data-view") === "radar" ? "radar" : "rosette";
          show(v);
          try { window.localStorage.setItem(VIEW_KEY, v); } catch (e) { /* not remembered */ }
        });
      })(roots[r]);
    }
  }

  /* ---- the capability map: one tool at a time; tapping the chosen chip again picks none ---- */
  function mountCapmap(root) {
    var chips = Array.prototype.slice.call(root.querySelectorAll(".cm-chip"));
    var rows = root.querySelectorAll(".cm-row");
    var panes = root.querySelectorAll(".cm-tool");
    var summary = root.querySelector(".cm-summary");
    var data = JSON.parse(root.querySelector(".cm-json").textContent);
    var WORDS = { cpu: "CPU only", both: "CPU and GPU", gpu: "GPU only", none: "not first-class" };
    function choose(tool, focus) {
      root.setAttribute("data-tool", tool);
      root.classList.toggle("is-neutral", !tool);
      chips.forEach(function (c) {
        var on = c.getAttribute("data-tool") === tool;
        c.classList.toggle("is-on", on);
        c.setAttribute("aria-pressed", on ? "true" : "false");
        if (on) { root.style.setProperty("--c", c.style.getPropertyValue("--c")); }
        if (on && focus) { c.focus(); }
      });
      for (var i = 0; i < rows.length; i++) {
        var key = rows[i].getAttribute("data-block");
        var stop = tool ? data.stops[key][tool] : "none";
        rows[i].setAttribute("data-stop", tool ? stop : "neutral");
        rows[i].classList.toggle("is-off", !!tool && stop === "none");
        var sr = rows[i].querySelector(".cm-sr");
        if (sr) { sr.textContent = rows[i].querySelector(".cm-name").textContent + ": " + (tool ? WORDS[stop] : "no tool selected"); }
      }
      for (var j = 0; j < panes.length; j++) { panes[j].hidden = panes[j].getAttribute("data-tool") !== tool; }
      if (summary) { summary.textContent = tool ? data.summaries[tool] : data.none; }
    }
    chips.forEach(function (c, idx) {
      c.addEventListener("click", function () {
        var t = c.getAttribute("data-tool");
        choose(root.getAttribute("data-tool") === t ? "" : t, false);
      });
      c.addEventListener("keydown", function (ev) {
        var d = ev.key === "ArrowRight" || ev.key === "ArrowDown" ? 1 : ev.key === "ArrowLeft" || ev.key === "ArrowUp" ? -1 : 0;
        if (!d) { return; }
        ev.preventDefault();
        choose(chips[(idx + d + chips.length) % chips.length].getAttribute("data-tool"), true);
      });
    });
    root.classList.add("cm-js");
    /* entrance: the first time the chart is seen, the dots start on the centre line and slide out to the chosen tool, once */
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var chart = root.querySelector(".cm-chart");
    if (reduce || !chart || !("IntersectionObserver" in window)) { return; }
    var io = new IntersectionObserver(function (es) {
      if (!es.some(function (e) { return e.isIntersecting; })) { return; }
      io.disconnect();
      if (root.classList.contains("is-neutral")) { return; }
      root.classList.add("is-neutral", "cm-enter");
      void root.offsetWidth;
      for (var i = 0; i < rows.length; i++) { rows[i].querySelector(".cm-dot").style.transitionDelay = (i * 22) + "ms"; }
      root.classList.remove("is-neutral");
      setTimeout(function () {
        root.classList.remove("cm-enter");
        for (var k = 0; k < rows.length; k++) { rows[k].querySelector(".cm-dot").style.transitionDelay = ""; }
      }, 1200);
    }, { threshold: 0.35 });
    io.observe(chart);
  }

  function start() {
    var roots = document.querySelectorAll(".worlds, .rosette");
    for (var i = 0; i < roots.length; i++) { mount(roots[i]); }
    var maps = document.querySelectorAll(".capmap");
    for (var m = 0; m < maps.length; m++) { mountCapmap(maps[m]); }
    initToggle();
  }
  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", start); }
  else { start(); }
})();
