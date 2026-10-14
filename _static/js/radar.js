/* The landing radar: where each tool shines.
 *
 * The page carries, per side (GPU, CPU), one SVG for the default device plus a JSON
 * block with every device's vertex positions and tooltip texts, all computed by
 * tools/sync_cards.py. This script only draws and interacts:
 *   - redraws the tool shapes for the device the page's switch selects, morphing the
 *     shape over ~250 ms (no morph under prefers-reduced-motion);
 *   - hover or focus of a legend item or a shape brings that tool to the front and dims
 *     the others; a click on a legend item toggles the tool (at least one stays on);
 *   - hover or focus of an axis label, or hover of a vertex, shows a tooltip (in the detailed
 *     mode: fills the side panel with what the axis measures, its source and every tool's value);
 *   - touch: a tap acts as hover, a tap outside resets.
 * Vanilla JS, no library. Without script the server-drawn SVG and the data table remain.
 */
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var MORPH_MS = 250;

  function reduced() {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }
  function el(name, attrs, parent) {
    var e = document.createElementNS(NS, name);
    for (var k in attrs) { e.setAttribute(k, attrs[k]); }
    if (parent) { parent.appendChild(e); }
    return e;
  }

  function mount(root) {
    var data = JSON.parse(root.querySelector(".radar-json").textContent);
    var side = data.side;
    var svg = root.querySelector(".radar-svg");
    var layer = svg.querySelector(".radar-tools");
    var tip = root.querySelector(".radar-tip");
    var stage = root.querySelector(".radar-stage");
    var legend = root.querySelectorAll(".radar-leg");
    var panel = root.querySelector(".radar-panel");
    var detailed = data.mode === "detailed";
    var nAx = data.axes.length;
    var centre = data.centre;
    var groups = {}, order = [], shown = {};   // shown[tool] = [[x,y]|null per axis]
    var devSlug = null, raf = 0, hl = null;
    var on = {};

    while (layer.firstChild) { layer.removeChild(layer.firstChild); }
    data.tools.forEach(function (t) {
      var g = el("g", { "class": "radar-tool", "data-tool": t.id }, layer);
      g.style.setProperty("--c", "var(" + t.color + ")");
      var poly = el("polygon", { "class": "radar-area" }, g);
      var dots = [];
      for (var i = 0; i < nAx; i++) {
        var q = data.axes[i].qual;
        var c = el("circle", { "class": "radar-vertex" + (q ? " q" : ""), r: q ? 5 : 4, tabindex: -1,
                               "data-axis": data.axes[i].key, "data-i": i }, g);
        dots.push(c);
      }
      groups[t.id] = { g: g, poly: poly, dots: dots };
      order.push(t.id);
      on[t.id] = true;
      for (var b = 0; b < legend.length; b++) {
        if (legend[b].getAttribute("data-tool") === t.id && legend[b].getAttribute("aria-pressed") === "false") { on[t.id] = false; }
      }
      g.classList.toggle("is-off", !on[t.id]);
      shown[t.id] = [];
    });

    function applyHollow(slug) {
      var hol = data.devices[slug].hol || {};
      data.tools.forEach(function (t) {
        for (var i = 0; i < nAx; i++) {
          groups[t.id].dots[i].classList.toggle("q", !!data.axes[i].qual || (hol[t.id] || []).indexOf(i) >= 0);
        }
      });
    }

    function paint(tool, pos) {
      var gr = groups[tool], pts = [];
      for (var i = 0; i < nAx; i++) {
        var p = pos[i];
        if (p) {
          pts.push(p[0].toFixed(1) + "," + p[1].toFixed(1));
          gr.dots[i].setAttribute("cx", p[0]); gr.dots[i].setAttribute("cy", p[1]);
          gr.dots[i].style.display = "";
        } else { gr.dots[i].style.display = "none"; }
      }
      gr.poly.setAttribute("points", pts.join(" "));
      gr.poly.style.display = pts.length >= 2 ? "" : "none";
    }

    function target(slug, tool) {
      var src = (data.devices[slug].pts[tool]) || {}, out = [];
      for (var i = 0; i < nAx; i++) { out.push(src[i] || null); }
      return out;
    }

    function setDevice(slug, animate) {
      if (!data.devices[slug] || slug === devSlug) { return; }
      var from = {}, to = {};
      data.tools.forEach(function (t) { from[t.id] = shown[t.id].slice(); to[t.id] = target(slug, t.id); });
      devSlug = slug;
      var devs = root.querySelectorAll(".radar-dev");
      for (var d = 0; d < devs.length; d++) { devs[d].hidden = devs[d].getAttribute("data-slug") !== slug; }
      svg.setAttribute("aria-label", data.devices[slug].aria);
      applyHollow(slug);
      hideTip();
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
      var finish = function () {
        data.tools.forEach(function (t) { shown[t.id] = to[t.id]; paint(t.id, to[t.id]); });
      };
      if (!animate || reduced() || !from[data.tools[0].id].length) { finish(); return; }
      var t0 = null;
      var step = function (now) {
        if (t0 === null) { t0 = now; }
        var k = Math.min(1, (now - t0) / MORPH_MS);
        k = k * k * (3 - 2 * k);
        data.tools.forEach(function (t) {
          var pos = [];
          for (var i = 0; i < nAx; i++) {
            var a = from[t.id][i], b = to[t.id][i];
            if (!a && !b) { pos.push(null); continue; }
            a = a || centre; b = b || centre;
            pos.push([a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k]);
          }
          paint(t.id, pos);
        });
        if (k < 1) { raf = requestAnimationFrame(step); } else { raf = 0; finish(); }
      };
      raf = requestAnimationFrame(step);
    }

    /* ring units, drawn along the spoke of the axis being read (never on every axis at rest) */
    var ringLayer = el("g", { "class": "radar-hover-rings" }, svg);
    var RINGS = [1.0, 0.6, 0.2];
    function showBands(i) {
      var ax = data.axes[i], g = data.geom, a = ax.ang;
      if (!ax.bands || !ax.bands.length) { return; }
      var ca = Math.cos(a), sa = Math.sin(a), px = -sa, py = ca;
      if (py < 0) { px = -px; py = -py; }               // the lower side of the spoke: rings use the upper
      ax.bands.forEach(function (b) {
        var rr = g[4] * b.r, d = 0.09;
        var p0 = [g[2] + rr * Math.cos(a - d), g[3] + rr * Math.sin(a - d)];
        var p1 = [g[2] + rr * Math.cos(a + d), g[3] + rr * Math.sin(a + d)];
        el("path", { "class": "radar-band", d: "M" + p0[0].toFixed(1) + "," + p0[1].toFixed(1) + " A" + rr.toFixed(1) + "," + rr.toFixed(1) +
                     " 0 0 1 " + p1[0].toFixed(1) + "," + p1[1].toFixed(1) }, ringLayer);
        var t = el("text", { "class": "radar-hring radar-bandlabel", x: (g[2] + rr * ca + px * 14).toFixed(1), y: (g[3] + rr * sa + py * 14).toFixed(1),
                             "text-anchor": px >= 0 ? "start" : "end", "dominant-baseline": "central" }, ringLayer);
        t.textContent = b.t;
        var bb = t.getBBox();
        var pill = el("rect", { "class": "radar-pill", x: (bb.x - 4).toFixed(1), y: (bb.y - 2).toFixed(1), width: (bb.width + 8).toFixed(1),
                                height: (bb.height + 4).toFixed(1), rx: 4 }, ringLayer);
        ringLayer.insertBefore(pill, t);
      });
    }
    function showRings(key) {
      clearRings();
      var i = axisIndex(key), dev = data.devices[devSlug];
      if (i < 0 || !dev.rl[key]) { return; }
      showBands(i);
      var parts = dev.rl[key].split(" · "), g = data.geom, a = data.axes[i].ang;
      var ca = Math.cos(a), sa = Math.sin(a), px = -sa, py = ca;
      if (py > 0) { px = -px; py = -py; }               // offset to the upper side of the spoke
      for (var k = 0; k < RINGS.length && k < parts.length; k++) {
        var x = g[2] + g[4] * RINGS[k] * ca + px * 12, y = g[3] + g[4] * RINGS[k] * sa + py * 12;
        var t = el("text", { "class": "radar-hring", x: x.toFixed(1), y: y.toFixed(1), "text-anchor": "middle",
                             "dominant-baseline": "central" }, ringLayer);
        t.textContent = parts[k] + (k === 0 && data.axes[i].edge ? "" : "");
      }
    }
    function clearRings() { while (ringLayer.firstChild) { ringLayer.removeChild(ringLayer.firstChild); } }

    /* ---- highlight and toggle ---- */
    function applyHl() {
      root.classList.toggle("has-hl", !!hl);
      data.tools.forEach(function (t) {
        groups[t.id].g.classList.toggle("is-hl", hl === t.id);
      });
      for (var i = 0; i < legend.length; i++) {
        legend[i].classList.toggle("is-hl", legend[i].getAttribute("data-tool") === hl);
      }
      order.forEach(function (id) { layer.appendChild(groups[id].g); });
      if (hl) { layer.appendChild(groups[hl].g); }
    }
    function setHl(tool) { if (hl !== tool) { hl = tool; applyHl(); } }
    function toggle(tool) {
      var n = 0;
      for (var k in on) { if (on[k]) { n++; } }
      if (on[tool] && n === 1) { return; }
      on[tool] = !on[tool];
      groups[tool].g.classList.toggle("is-off", !on[tool]);
      for (var i = 0; i < legend.length; i++) {
        if (legend[i].getAttribute("data-tool") === tool) { legend[i].setAttribute("aria-pressed", on[tool] ? "true" : "false"); }
      }
      if (!on[tool] && hl === tool) { setHl(null); }
    }

    /* ---- tooltip ---- */
    function line(parent, text, cls) {
      var d = document.createElement("div");
      if (cls) { d.className = cls; }
      d.textContent = text;
      parent.appendChild(d);
    }
    function placeTip(x, y) {
      var w = stage.clientWidth;
      tip.hidden = false;
      var tw = tip.offsetWidth;
      var left = Math.max(0, Math.min(w - tw, x + 12));
      tip.style.left = left + "px";
      tip.style.top = Math.max(0, y - 8) + "px";
    }
    function hideTip() { tip.hidden = true; clearRings(); }
    function axisIndex(key) {
      for (var i = 0; i < nAx; i++) { if (data.axes[i].key === key) { return i; } }
      return -1;
    }
    function toolLabel(id) { return id; }
    function showPanel(key) {
      var dev = data.devices[devSlug], ax = data.axes[axisIndex(key)];
      panel.textContent = "";
      line(panel, ax.label, "radar-panel-h");
      if (ax.what) { line(panel, ax.what); }
      if (ax.edge) { line(panel, "Edge of the chart: " + ax.edge + " (" + ax.dir + ").", "radar-tip-s"); }
      line(panel, (ax.qual ? "Rubric: " : "Source: " + ax.src + "; ") + dev.desc[key], "radar-tip-s");
      showRings(key);
      var list = document.createElement("div");
      list.className = "radar-panel-list";
      panel.appendChild(list);
      data.tools.forEach(function (t) {
        var tt = dev.tips[t.id] && dev.tips[t.id][key];
        var row = document.createElement("div");
        row.className = "radar-panel-row" + (on[t.id] ? "" : " is-off");
        var chip = document.createElement("span");
        chip.className = "chip";
        chip.style.setProperty("--c", "var(" + t.color + ")");
        row.appendChild(chip);
        var txt = document.createElement("span");
        txt.textContent = t.id + ": " + (tt ? tt.v + (ax.qual ? "" : " (" + tt.r + ")") : "no reading");
        row.appendChild(txt);
        list.appendChild(row);
        if (tt && ax.qual) { line(list, tt.r, "radar-tip-s radar-panel-why"); }
        else if (tt && tt.a) { line(list, tt.a + (tt.d ? " · " + tt.d : ""), "radar-tip-s radar-panel-why"); }
      });
      if (!ax.qual) {
        var a = document.createElement("a");
        a.href = dev.link; a.textContent = "Open this device's card";
        panel.appendChild(a);
      }
      line(panel, dev.card, "radar-tip-s");
    }
    function showVertex(circle, tool) {
      var key = circle.getAttribute("data-axis"), dev = data.devices[devSlug];
      if (detailed) { showPanel(key); return; }
      var tt = dev.tips[tool] && dev.tips[tool][key];
      if (!tt) { return; }
      tip.textContent = "";
      line(tip, toolLabel(tool) + " · " + data.axes[axisIndex(key)].label, "radar-tip-h");
      line(tip, tt.v);
      line(tip, tt.r);
      if (tt.a) { line(tip, tt.a, "radar-tip-s"); }
      if (tt.d) { line(tip, tt.d, "radar-tip-s"); }
      line(tip, dev.desc[key], "radar-tip-s");
      var ax0 = data.axes[axisIndex(key)];
      if (ax0.edge) { line(tip, "Edge of the chart: " + ax0.edge + " (" + ax0.dir + ")", "radar-tip-s"); }
      line(tip, dev.card, "radar-tip-s");
      showRings(key);
      var sr = svg.getBoundingClientRect(), st = stage.getBoundingClientRect();
      var k = sr.width / svg.viewBox.baseVal.width;
      placeTip(sr.left - st.left + parseFloat(circle.getAttribute("cx")) * k,
               sr.top - st.top + parseFloat(circle.getAttribute("cy")) * k);
    }
    function showAxis(label) {
      var key = label.getAttribute("data-axis"), dev = data.devices[devSlug];
      if (detailed) { showPanel(key); return; }
      tip.textContent = "";
      line(tip, data.axes[axisIndex(key)].label, "radar-tip-h");
      line(tip, dev.desc[key], "radar-tip-s");
      var axx = data.axes[axisIndex(key)];
      if (axx.edge) { line(tip, "Edge of the chart: " + axx.edge + " (" + axx.dir + ")", "radar-tip-s"); }
      showRings(key);
      data.tools.forEach(function (t) {
        var tt = dev.tips[t.id] && dev.tips[t.id][key];
        if (on[t.id]) { line(tip, t.id + ": " + (tt ? tt.v + " (" + tt.r + ")" : "no reading")); }
      });
      line(tip, dev.card, "radar-tip-s");
      var anchor = label;
      if (label.tagName === "LI" || label.getBoundingClientRect().width === 0) {
        anchor = svg.querySelector('.radar-icon.disc[data-axis="' + key + '"]') || label;
      }
      var lr = anchor.getBoundingClientRect(), st = stage.getBoundingClientRect();
      placeTip(lr.right - st.left, lr.top - st.top);
    }

    /* ---- events ---- */
    for (var i = 0; i < legend.length; i++) {
      (function (b) {
        var tool = b.getAttribute("data-tool");
        b.addEventListener("mouseenter", function () { setHl(tool); });
        b.addEventListener("mouseleave", function () { setHl(null); });
        b.addEventListener("focus", function () { setHl(tool); });
        b.addEventListener("blur", function () { setHl(null); });
        b.addEventListener("click", function () { toggle(tool); });
      })(legend[i]);
    }
    data.tools.forEach(function (t) {
      var gr = groups[t.id];
      gr.poly.addEventListener("mouseenter", function () { if (on[t.id]) { setHl(t.id); } });
      gr.poly.addEventListener("mouseleave", function () { setHl(null); });
      gr.dots.forEach(function (c) {
        c.addEventListener("mouseenter", function () { setHl(t.id); showVertex(c, t.id); });
        c.addEventListener("mouseleave", function () { setHl(null); hideTip(); });
        c.addEventListener("focus", function () { setHl(t.id); showVertex(c, t.id); });
        c.addEventListener("blur", function () { setHl(null); hideTip(); });
      });
    });
    var icons = svg.querySelectorAll(".radar-icon.disc");
    for (var ic = 0; ic < icons.length; ic++) {
      (function (n) {
        n.addEventListener("mouseenter", function () { showAxis(n); });
        n.addEventListener("mouseleave", hideTip);
        n.addEventListener("focus", function () { showAxis(n); });
        n.addEventListener("blur", hideTip);
        n.addEventListener("click", function () { showAxis(n); });
        n.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); showAxis(n); } });
      })(icons[ic]);
    }
    var labels = svg.querySelectorAll(".radar-axis");
    for (var j = 0; j < labels.length; j++) {
      (function (l) {
        l.addEventListener("mouseenter", function () { showAxis(l); });
        l.addEventListener("mouseleave", hideTip);
        l.addEventListener("focus", function () { showAxis(l); });
        l.addEventListener("blur", hideTip);
      })(labels[j]);
    }
    var items = root.querySelectorAll(".radar-axlist li");
    for (var m = 0; m < items.length; m++) {
      (function (li) {
        li.addEventListener("mouseenter", function () { showAxis(li); });
        li.addEventListener("focus", function () { showAxis(li); });
        li.addEventListener("click", function () { showAxis(li); });
        li.addEventListener("blur", hideTip);
      })(items[m]);
    }
    root.addEventListener("keydown", function (ev) { if (ev.key === "Escape") { hideTip(); setHl(null); } });
    document.addEventListener("pointerdown", function (ev) {
      if (!ev.target.closest || !ev.target.closest(".radar-tool, .radar-leg, .radar-axis, .radar-axlist, .radar-icon")) { hideTip(); setHl(null); }
    });

    /* ---- icons beside the axis names: the name is placed by the server; the icon is set against the measured width ---- */
    var wideIcons = svg.querySelectorAll(".radar-icon.wide");
    function placeIcons() {
      for (var k = 0; k < wideIcons.length; k++) {
        var g = wideIcons[k], t = svg.querySelector('.radar-axis[data-axis="' + g.getAttribute("data-axis") + '"]'), bb = null;
        try { bb = t ? t.getBBox() : null; } catch (e) { bb = null; }
        if (!bb || !bb.width) { continue; }
        var u = g.firstChild, size = parseFloat(u.getAttribute("width")), gap = 6;
        var x = bb.x - gap - size;
        g.setAttribute("transform", "translate(" + x.toFixed(1) + " " + (bb.y + bb.height / 2 - size / 2).toFixed(1) + ")");
      }
    }
    placeIcons();
    if (document.fonts && document.fonts.ready) { document.fonts.ready.then(placeIcons); }

    /* ---- narrow column: crop the chart to its disc (the names give way to numbers) ---- */
    var full = svg.getAttribute("viewBox");
    function fit() {
      var g = data.geom, pad = 48;
      var narrow = root.clientWidth < (detailed ? 560 : 720);   /* the same widths as the CSS container queries */
      svg.setAttribute("viewBox", narrow ? [g[2] - g[4] - pad, g[3] - g[4] - pad, 2 * (g[4] + pad), 2 * (g[4] + pad)].join(" ") : full);
      placeIcons();
    }
    fit();
    if (window.ResizeObserver) { new ResizeObserver(fit).observe(root); } else { window.addEventListener("resize", fit); }

    /* ---- the page's device state ---- */
    function followSwitch(animate) {
      var r = document.querySelector('.perf-switch input[name="perf-' + side + '"]:checked');
      var slug = r ? r.getAttribute("data-slug") : null;
      if (slug) { setDevice(slug, animate); }
    }
    var sw = document.querySelector(".perf-switch");
    if (sw) { sw.addEventListener("perf-device-change", function () { followSwitch(true); }); }
    var first = root.querySelector(".radar-dev:not([hidden])");
    devSlug = first ? first.getAttribute("data-slug") : null;
    if (devSlug) {
      data.tools.forEach(function (t) { shown[t.id] = target(devSlug, t.id); paint(t.id, shown[t.id]); });
      svg.setAttribute("aria-label", data.devices[devSlug].aria);
      applyHollow(devSlug);
    }
    followSwitch(false);
  }

  function start() {
    var roots = document.querySelectorAll(".radar");
    for (var i = 0; i < roots.length; i++) { mount(roots[i]); }
  }
  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", start); }
  else { start(); }
})();
