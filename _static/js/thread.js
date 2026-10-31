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
  var P1 = 0.42;             // share of the loop spent on thread -> branches; the rest morphs them into the cases
  var NAMES = ["Ray tracing", "Spectra", "Linear algebra", "Particle statistics", "Trajectories"];
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
    var fid = "t-glow-" + (opts.seed || 0), fl = el("filter", { id: fid, x: "-10%", y: "-20%", width: "120%", height: "140%" }, el("defs", {}, svg));
    svg.__g = [el("feGaussianBlur", { "in": "SourceGraphic", stdDeviation: 1.5, result: "b" }, fl),
      el("feColorMatrix", { "in": "b", type: "matrix", values: "1 0 0 0 0 0 1 0 0 0 0 0 1 0 0 0 0 0 1 0", result: "c" }, fl)];   // coloured bloom: the blurred strokes themselves
    el("feMerge", {}, fl).innerHTML = '<feMergeNode in="c"/><feMergeNode in="SourceGraphic"/>';
    var lines = [], gm = el("g", { class: "t-glow", filter: "url(#" + fid + ")" }, svg), gl = el("g", {}, gm), gd = el("g", {}, gm);
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
      lines.push({ path: path, drop: drop, pts: pts, cum: cum, len: len, f: f, lane: lane, r: rnd(), r0: parseFloat(drop.getAttribute("r")), d0: path.getAttribute("d"), da: path.getAttribute("stroke-dasharray") });
    }


    var M = 60, K = 14, FT = K / (M - 1), NS = phone ? [6, 10, 6, 8, 6] : [10, 20, 10, 20, 12], HS = [1.57, 1.25, 1.6, 1.43, 1.35], OF = [-0.1, 0.22, 0, 0.16, -0.03], hb = (H - 2 * pad) / 5, hh = phone ? hb * 0.7 : (H - 2 * pad - 16) / 8, cum = phone ? pad : pad + 16, ord = [], grp = [[], [], [], [], []], extra = [], lab = [];
    var XA = phone ? [0.1, 0.1, 0.1, 0.1, 0.1] : [0.08, 0.24, 0.12, 0.36, 0.3], CW = phone ? [0.5, 0.5, 0.5, 0.5, 0.5] : [0.42, 0.32, 0.5, 0.32, 0.44], FK = [0.3, 0.34, 0, 0.34, 0], TA = [0.4, 0.35, 0, 0.4, 0];
    var YB = HS.map(function (h, c) { var y = cum + (h / 2 - OF[c]) * hh; cum += (h + 0.2) * hh; return y; }), yb = function (c) { return phone ? pad + hb * (c + 0.5) : YB[c]; }, xs = function (c) { return x0 + L * XA[c]; };
    var wv = 9.4 / (L * CW[0]), tl = phone ? 0 : 0.7 / (L * CW[0]), meshY = function (x) { return yb(0) + hh * 0.3 + hh * 0.09 * Math.sin((x - xs(0)) * wv) - hh * tl * (x - xs(0)); };
    var gau = function (f, m, sd, a) { return a * Math.exp(-Math.pow((f - m) / sd, 2)); };
    var pl = function (V) {
      var cu = [0], m;
      for (m = 1; m < V.length; m++) cu.push(cu[m - 1] + Math.hypot(V[m][0] - V[m - 1][0], V[m][1] - V[m - 1][1]));
      return function (f) {
        var d = f * cu[m - 1], i = 1, e;
        while (i < m - 1 && cu[i] < d) i++;
        e = (d - cu[i - 1]) / (cu[i] - cu[i - 1] || 1);
        return [V[i - 1][0] + (V[i][0] - V[i - 1][0]) * e, V[i - 1][1] + (V[i][1] - V[i - 1][1]) * e];
      };
    };
    for (i = 0; i < n; i++) ord.push(i);
    ord.sort(function (a, b) { return lines[a].lane - lines[b].lane; });
    ord.forEach(function (i, r) { grp[Math.floor(r * 5 / n)].push(lines[i]); });
    function shape(c, k, ln) {
      var ns = NS[c], xa = xs(c), cw = L * CW[c], y = yb(c), yB = y + hh * 0.4, u = (k + 0.5) / ns, x = xa + cw * u, h, V, w = 1, up = 0, tw = 0, per, nb, b;
      var B = [xa, (c === 0 ? y - hh * 0.4 : c === 1 || c === 3 ? yB : y) + (k - (ns - 1) / 2) * Math.min(2.2, 16 / ns)];
      if (c === 0) {
        var S = [xa + cw * 0.1, y - hh * 0.42], T = [xa + cw * (0.12 + 0.86 * u), 0]; T[1] = meshY(T[0]); V = [B, S, T];
        var dl = Math.hypot(T[0] - S[0], T[1] - S[1]), d = [(T[0] - S[0]) / dl, (T[1] - S[1]) / dl], sl = hh * (0.09 * wv * Math.cos((T[0] - xs(0)) * wv) - tl), nl = Math.hypot(sl, 1), nn = [sl / nl, -1 / nl], dt = d[0] * nn[0] + d[1] * nn[1], len = phone ? 75 + 30 * ln.r : 70 + 60 * ln.r, ry = d[1] - 2 * dt * nn[1];
        if (ry < 0) len = Math.min(len, (T[1] - pad - 4) / -ry);
        ln.rf = [T, [T[0] + (d[0] - 2 * dt * nn[0]) * len, Math.max(pad + 2, T[1] + (d[1] - 2 * dt * nn[1]) * len)]];
      }
      else if (c === 1) { h = hh * 0.95 * Math.min(1, (0.15 + gau(u, 0.19, 0.07, 0.8) + gau(u, 0.55, 0.06, 0.55) + gau(u, 0.82, 0.06, 0.7)) * (0.55 + 0.9 * ln.r)); V = [B, [x, yB], [x, yB - h]]; }
      else if (c === 3) {
        per = phone ? 2 : 4; nb = ns / per; b = Math.floor(k / per); x = xa + cw * (0.1 + 0.9 * (b + 0.5) / nb);
        h = hh * 0.95 * (0.25 + 0.75 * Math.exp(-Math.pow(((b + 0.5) / nb - 0.5) / 0.3, 2))); V = [B, [x, yB], [x, yB - h]]; w = 1.5; tw = phone ? 2.6 : 4.6; ln.p2 = (k % per) * 6.283 / per; }
      else if (c === 2) {
        var R = ns >> 1, qs = hh * (phone ? 1.4 : 1.6), qw = phone ? qs : cw * 0.66, qx = xa + cw * 0.08, qy = y - qs / 2, ex = xa + cw - qx - qw, yf = y + (k - (ns - 1) / 2) * hh * 0.15, j = k - R, ry = qy + (k + 0.5) * qs / R, cx = qx + (j + 0.5) * qw / (ns - R);
        V = k < R ? [B, [qx, ry], [qx + qw, ry]] : [B, [cx, qy], [cx, qy + qs], [qx + qw + ex * 0.1, qy + qs]];
        V.push([qx + qw + ex * 0.4, yf], [xa + cw, yf]); up = k >= R; w = 1.3; }
      else { var xe = xa + cw * (0.55 + 0.45 * ln.r), ye = y + (u - 0.5) * hh * 1.2, dr = k % 2 ? 1 : -1;
        return [B, function (f) { var r = hh * 0.32 * Math.sin(Math.PI * f), th = dr * 12.57 * f + k;
          return [B[0] + (xe - B[0]) * f + r * Math.cos(th) * 0.9, B[1] + (ye - B[1]) * smooth(f) + r * Math.sin(th)]; }, w, 0, 0]; }
      return [B, pl(V), w, up, tw];
    }
    var gid = "t-rf-" + (opts.seed || 0), gr = el("linearGradient", { id: gid }, el("defs", {}, svg));
    el("stop", { offset: 0, class: "t-rs0" }, gr); el("stop", { offset: 0.66, class: "t-rs0" }, gr); el("stop", { offset: 1, class: "t-rs1" }, gr);
    grp.forEach(function (G, c) {
      G.forEach(function (ln) { ln.m0 = P1 + 0.04 * c + (c === 4 && !phone ? -0.1 : 0) + 0.05 * ln.r; });
      for (var k = 0; k < NS[c]; k++) {
        var ln = G[Math.round((k + 0.5) * G.length / NS[c] - 0.5)], sh = shape(c, k, ln), A = sh[0], g = sh[1], P = ln.pts, p0 = P[0];
        ln.car = 1; ln.path.setAttribute("data-b", c); ln.drop.setAttribute("data-b", c); ln.w = sh[2]; ln.up = sh[3]; ln.src = []; ln.tgt = [];
        for (var j = 0; j < M; j++) {
          var f = j / (M - 1), fi = f * (P.length - 1), a = Math.floor(fi), b2 = Math.min(a + 1, P.length - 1), e = fi - a, t = Math.min(1, f / FT), pt;
          ln.src.push([P[a][0] + (P[b2][0] - P[a][0]) * e, P[a][1] + (P[b2][1] - P[a][1]) * e]);
          pt = f < FT ? [p0[0] + (A[0] - p0[0]) * t, p0[1] + (A[1] - p0[1]) * smooth(t)] : g((f - FT) / (1 - FT));
          pt[1] += hh * TA[c] * Math.exp(-Math.pow((f - FK[c]) / 0.09, 2)) * Math.sin(37.7 * f + k * 2.4 + c);
          if (sh[4]) pt[0] += sh[4] * Math.sin(55 * f + ln.p2) * smooth((f - 0.45) / 0.2);
          ln.tgt.push(pt);
        }
        if (ln.rf) {
          var q = el("path", { d: "M" + ln.rf[0].map(function (v) { return v.toFixed(1); }).join(" ") + "L" + ln.rf[1].map(function (v) { return v.toFixed(1); }).join(" "), class: "t-ref", stroke: "url(#" + gid + ")" }, svg), q2 = el("circle", { cx: ln.rf[1][0].toFixed(1), cy: ln.rf[1][1].toFixed(1), r: 1.5, class: "t-rd" }, svg);
          q.at = q2.at = P1 + 0.3; q.setAttribute("data-b", 0); q2.setAttribute("data-b", 0); q2.mx = 0.8; extra.push(q, q2);
        }
      }
      var t = el("text", { x: (xs(c) + L * CW[c] + 10).toFixed(1), y: (yb(c) + (c === 0 ? (phone ? hh * 0.4 + 14 : hh * 0.2) : 4)).toFixed(1), class: "t-label" }, svg);
      t.textContent = NAMES[c]; t.setAttribute("data-b", c); t.at = P1 + 0.04 * c + 0.2; lab.push(t);
    });
    var mp = []; for (i = 0; i <= 60; i++) mp.push((xs(0) + L * CW[0] * i / 60).toFixed(1) + " " + meshY(xs(0) + L * CW[0] * i / 60).toFixed(1));
    [["M" + mp.join("L"), 0], ["M" + xs(1) + " " + (yb(1) + hh * 0.4) + "h" + L * CW[1], 1], ["M" + xs(3) + " " + (yb(3) + hh * 0.4) + "h" + L * CW[3], 3]].forEach(function (e) {
      var p = el("path", { d: e[0], class: "t-mesh" }, svg); p.at = P1 + 0.04 * e[1] + 0.1; p.setAttribute("data-b", e[1]); extra.push(p);
    });

    svg.__b = { xs: xs, L: L, CW: CW };
    function frame(T) {
      var Tm = T;
      T = Math.min(1, T / P1);
      var ts = Math.min(1, T / STROKE_PHASE);
      clipRect.setAttribute("width", (x0 * ts + 1).toFixed(1));
      var tf = Math.max(0, (T - STROKE_PHASE) / (1 - STROKE_PHASE - FADE));
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
        if (Tm > P1 || ln.mo) morph(ln, Tm);
      }
      extra.forEach(function (p) { p.style.opacity = ((p.mx || 1) * smooth((Tm - p.at) / 0.15)).toFixed(2); });
      lab.forEach(function (t) { t.style.opacity = smooth((Tm - t.at) / 0.1).toFixed(2); });
    }
    function morph(ln, Tm) {
      var u = Math.max(0, Math.min(1, (Tm - ln.m0) / 0.3)), m = smooth(u), d = "", e;
      if (!ln.car) { ln.path.style.opacity = ln.drop.style.opacity = (1 - smooth((Tm - ln.m0) / 0.15)).toFixed(2); return; }
      if (u <= 0) { if (ln.mo) { ln.mo = 0; ln.path.setAttribute("d", ln.d0); ln.path.setAttribute("stroke-dasharray", ln.da); ln.path.style.strokeWidth = ""; ln.drop.setAttribute("r", ln.r0); } return; }
      ln.mo = 1;
      for (var j = 0; j < M; j++) {
        var a = ln.src[j], b = ln.tgt[j], q = smooth(Math.max(0, Math.min(1, u * 1.5 - 0.5 * (M - 1 - j) / (M - 1))));
        e = [a[0] + (b[0] - a[0]) * q, a[1] + (b[1] - a[1]) * q]; d += (j ? "L" : "M") + e[0].toFixed(1) + " " + e[1].toFixed(1);
      }
      ln.path.setAttribute("d", d); ln.path.setAttribute("stroke-dasharray", "none");
      ln.path.style.strokeWidth = (0.8 + (ln.w - 0.8) * m).toFixed(2);
      ln.path.style.setProperty("--grey", (ln.up ? 0.35 * m + 0.25 * (1 - m) : 1 - m).toFixed(3));
      ln.drop.setAttribute("cx", e[0].toFixed(1)); ln.drop.setAttribute("cy", e[1].toFixed(1)); ln.drop.setAttribute("r", (ln.r0 * (1 + 0.4 * m)).toFixed(2));
    }
    return frame;
  }

  function mount(svg, opts) {
    opts = opts || {};
    var q = new URLSearchParams(location.search), fixed = q.get("t");
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var frame = build(svg, opts), dur = opts.duration || 5500, per = 3500, on = false, t0 = null;
    function glow(ph) {                       // the finished figure breathes: a soft sinusoidal glow
      var b = 0.5 - 0.5 * Math.cos(6.2832 * ph);
      svg.__g[0].setAttribute("stdDeviation", (1.5 + 3 * b).toFixed(2));      // halo radius
      svg.__g[1].setAttribute("values", "1 0 0 0 0 0 1 0 0 0 0 0 1 0 0 0 0 0 " + (0.9 + 1.6 * b).toFixed(2) + " 0");   // halo intensity; the strokes stay opaque
    }
    if (fixed !== null) { frame(Math.max(0, Math.min(1, parseFloat(fixed)))); glow(parseFloat(q.get("glow") || 0)); return; }
    if (reduce) { frame(1); return; }
    function tick(now) {                      // plays once, then only the glow runs
      if (!on) return;
      var u = now - t0;
      frame(Math.min(1, u / dur));
      if (u > dur) glow((u - dur) / per);
      requestAnimationFrame(tick);
    }
    frame(0);
    new IntersectionObserver(function (e) {
      var v = e[0].isIntersecting;
      if (v && !on) { on = true; if (t0 === null) t0 = performance.now(); requestAnimationFrame(tick); } else if (!v) on = false;
    }).observe(svg);
    var lastW = svg.clientWidth;
    window.addEventListener("resize", function () {
      if (Math.abs(svg.clientWidth - lastW) < 40) return;
      lastW = svg.clientWidth; frame = build(svg, opts);
    });
  }
  window.RaptorThread = { mount: mount };
})();
