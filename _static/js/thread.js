/* The thread: one ink stroke that fans into a batch of hairline samples.
   Each sample stops at its own step (log-uniform in [S/100, S], sample 0 runs all S,
   as in the perf card's "spread" workload); a drop marks where it finished, and the
   finished hairline fades to grey. Deterministic (seeded), no libraries.
   Usage: RaptorThread.mount(svgElement, {phoneSamples, desktopSamples, seed}).
   URL ?t=<0..1> renders a fixed frame; prefers-reduced-motion renders the last one. */
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";

  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6d2b79f5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function el(name, attrs, parent) {
    var e = document.createElementNS(NS, name);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function smooth(u) { u = Math.max(0, Math.min(1, u)); return u * u * (3 - 2 * u); }

  var STROKE_PHASE = 0.16;   // share of the play time spent drawing the single stroke
  var FADE = 0.06;           // share of the play time a finished hairline takes to grey

  function build(svg, opts) {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var W = Math.max(280, svg.clientWidth || svg.parentNode.clientWidth || 1200);
    var H = Math.max(150, svg.clientHeight || 240);
    var phone = W < 640;
    var n = phone ? (opts.phoneSamples || 60) : (opts.desktopSamples || 150);
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    var rnd = mulberry32(opts.seed || 20261001);

    var yc = H * 0.5, pad = phone ? 14 : 18;
    var x0 = phone ? W * 0.2 : W * 0.15;     // where the stroke opens into the batch
    var x1 = W - (phone ? 8 : 12);          // where sample 0 (the longest) finishes
    var L = x1 - x0, R = L * (phone ? 0.2 : 0.13);
    var wave = function (x) { return yc + Math.sin((x / x0) * Math.PI * 1.15 + 0.6) * H * 0.06 * (1 - x / x0); };

    // the single brush stroke: tapered fill along a gentle wave, entry dots like the marks
    var top = [], bot = [], steps = 40;
    for (var s = 0; s <= steps; s++) {
      var x = 6 + (x0 - 6) * s / steps, u = s / steps;
      var th = 0.4 + 3.2 * smooth(u / 0.7) - 0.7 * smooth((u - 0.75) / 0.25);
      top.push([x, wave(x) - th]); bot.push([x, wave(x) + th]);
    }
    var d = "M" + top.map(function (p) { return p[0].toFixed(1) + " " + p[1].toFixed(1); }).join(" L") +
      " L" + bot.reverse().map(function (p) { return p[0].toFixed(1) + " " + p[1].toFixed(1); }).join(" L") + " Z";
    var clip = el("clipPath", { id: "thread-clip-" + (opts.seed || 0) }, el("defs", {}, svg));
    var clipRect = el("rect", { x: 0, y: 0, width: 0, height: H }, clip);
    var g = el("g", { "clip-path": "url(#thread-clip-" + (opts.seed || 0) + ")" }, svg);
    el("path", { d: d, class: "t-stroke" }, g);
    [[0, 1.5], [-8, 1.15], [-15, 0.85]].forEach(function (p) {
      el("circle", { cx: 2 + p[0] + 14, cy: wave(6) + 4 - p[0] * 0.12, r: p[1], class: "t-drop t-entry" }, svg);
    });

    // the batch
    var lines = [], gl = el("g", {}, svg), gd = el("g", {}, svg);
    var order = []; for (var i = 0; i < n; i++) order.push(i);
    for (i = 0; i < n; i++) {                          // stratified lanes, shuffled
      var j = Math.floor(rnd() * (i + 1)); var tmp = order[i]; order[i] = order[j]; order[j] = tmp;
    }
    for (i = 0; i < n; i++) {
      var lane = pad + (H - 2 * pad) * (order[i] + 0.15 + 0.7 * rnd()) / n;
      var f = i === 0 ? 1 : Math.pow(10, -2 + 2 * rnd());    // log-uniform stop step / S
      var xe = x0 + L * f, y0 = yc + (rnd() - 0.5) * 5;
      var pts = [], len = 0, cum = [];
      var segs = Math.max(4, Math.ceil((xe - x0) / 6));
      for (s = 0; s <= segs; s++) {
        var xx = x0 + (xe - x0) * s / segs;
        var yy = y0 + (lane - y0) * smooth((xx - x0) / R);
        if (s) len += Math.hypot(xx - pts[s - 1][0], yy - pts[s - 1][1]);
        pts.push([xx, yy]); cum.push(len);
      }
      var path = el("path", {
        d: "M" + pts.map(function (p) { return p[0].toFixed(1) + " " + p[1].toFixed(1); }).join(" L"),
        class: "t-hair", "stroke-dasharray": len.toFixed(1) + " " + (len + 2).toFixed(1)
      }, gl);
      var end = pts[pts.length - 1];
      var drop = el("circle", { cx: end[0].toFixed(1), cy: end[1].toFixed(1), r: (phone ? 1.5 : 1.6) + rnd() * (phone ? 0.9 : 1.2), class: "t-drop" }, gd);
      lines.push({ path: path, drop: drop, pts: pts, cum: cum, len: len, f: f });
    }

    function frame(T) {                       // T in [0, 1] over the whole play
      var ts = Math.min(1, T / STROKE_PHASE);
      clipRect.setAttribute("width", (x0 * ts + 1).toFixed(1));
      var tf = Math.max(0, (T - STROKE_PHASE) / (1 - STROKE_PHASE - FADE)); // batch time = steps / S
      for (var k = 0; k < lines.length; k++) {
        var ln = lines[k], frac = Math.min(1, tf / ln.f), shown;
        var idx = Math.floor(frac * (ln.pts.length - 1));
        shown = frac >= 1 ? ln.len : ln.cum[idx];
        ln.path.setAttribute("stroke-dashoffset", (ln.len - shown).toFixed(1));
        ln.path.style.opacity = tf > 0 ? 1 : 0;
        var done = tf >= ln.f, grey = done ? Math.min(1, (tf - ln.f) / (FADE / (1 - STROKE_PHASE))) : 0;
        ln.path.style.setProperty("--grey", grey.toFixed(3));
        ln.path.classList.toggle("is-done", done);
        ln.drop.style.opacity = done ? 1 : 0;
      }
    }
    return frame;
  }

  function mount(svg, opts) {
    opts = opts || {};
    var q = new URLSearchParams(location.search), fixed = q.get("t");
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var frame = build(svg, opts), dur = opts.duration || 2500;
    if (fixed !== null) { frame(Math.max(0, Math.min(1, parseFloat(fixed)))); return; }
    if (reduce) { frame(1); return; }
    var t0 = null, finished = false;
    function tick(now) {
      if (t0 === null) t0 = now;
      var T = Math.min(1, (now - t0) / dur);
      frame(T);
      if (T < 1) requestAnimationFrame(tick); else finished = true;
    }
    frame(0); requestAnimationFrame(tick);
    var lastW = svg.clientWidth;
    window.addEventListener("resize", function () {     // re-layout to the final frame, never replay
      if (Math.abs(svg.clientWidth - lastW) < 40) return;
      lastW = svg.clientWidth; frame = build(svg, opts); frame(finished ? 1 : 1);
      finished = true; t0 = -1e9;
    });
  }
  window.RaptorThread = { mount: mount };
})();
