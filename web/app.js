/* WorkBuddy Token Monitor — 前端面板 */
(function () {
  "use strict";

  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.prototype.slice.call((r || document).querySelectorAll(s));

  const COLORS = {
    hit: "#06b6d4",
    miss: "#f59e0b",
    out: "#7c3aed",
    line: "#6366f1",
    grid: "#eef2f7",
    axis: "#94a3b8",
    ink: "#0f172a"
  };
  const MODEL_COLORS = ["#6366f1", "#06b6d4", "#f59e0b", "#10b981", "#8b5cf6", "#f43f5e", "#64748b"];
  const FONT = '11px -apple-system, "Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", sans-serif';
  const FONT_SM = '10px -apple-system, "Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", sans-serif';

  const state = {
    range: "today",
    customStart: "",
    customEnd: "",
    model: "",
    modelMetric: "tokens", // "tokens" | "credit"
    activeTab: "sessions", // "sessions" | "models"
    paused: false,
    data: null,
    lastUpdate: 0,
    animate: true,
    hover: null
  };

  /* ------------------------------------------------ 格式化 */

  function compact(n) {
    n = Number(n) || 0;
    if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
    if (n >= 1e4) return (n / 1e3).toFixed(1) + "K";
    if (n >= 1e3) return (n / 1e3).toFixed(2) + "K";
    return String(Math.round(n));
  }
  function intFmt(n) {
    return Math.round(Number(n) || 0).toLocaleString("zh-CN");
  }
  function pct(v) {
    return (Math.max(0, Math.min(1, Number(v) || 0)) * 100).toFixed(1) + "%";
  }
  function two(n) {
    return n < 10 ? "0" + n : String(n);
  }
  function hhmmss(ms) {
    const d = new Date(ms);
    return two(d.getHours()) + ":" + two(d.getMinutes()) + ":" + two(d.getSeconds());
  }
  function hhmm(ms) {
    const d = new Date(ms);
    return two(d.getHours()) + ":" + two(d.getMinutes());
  }
  function ago(ms) {
    const s = Math.max(0, (Date.now() - ms) / 1000);
    if (s < 60) return "刚刚";
    if (s < 3600) return Math.floor(s / 60) + " 分钟前";
    if (s < 86400) return Math.floor(s / 3600) + " 小时前";
    return Math.floor(s / 86400) + " 天前";
  }

  /* ------------------------------------------------ 数字动画 */

  const tweens = new Map();
  function setNum(el, to, fmt) {
    if (!el) return;
    const from = Number(el.dataset.v || 0);
    if (Math.abs(from - to) <= Math.max(0.4, Math.abs(to) * 0.0008)) {
      el.dataset.v = String(to);
      el.textContent = fmt(to);
      return;
    }
    el.dataset.v = String(to);
    const t0 = performance.now();
    const dur = 620;
    if (tweens.has(el)) cancelAnimationFrame(tweens.get(el));
    const step = (t) => {
      const p = Math.min(1, (t - t0) / dur);
      const e = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(from + (to - from) * e);
      if (p < 1) tweens.set(el, requestAnimationFrame(step));
    };
    tweens.set(el, requestAnimationFrame(step));
  }

  /* ------------------------------------------------ canvas 基础 */

  function fit(canvas) {
    const r = canvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(20, r.width);
    const h = Math.max(20, r.height);
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    return { ctx: ctx, w: w, h: h };
  }

  function roundTop(ctx, x, y, w, h, r) {
    r = Math.max(0, Math.min(r, w / 2, h));
    ctx.beginPath();
    ctx.moveTo(x, y + h);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h);
    ctx.closePath();
  }

  function smooth(ctx, pts) {
    if (!pts.length) return;
    ctx.moveTo(pts[0].x, pts[0].y);
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i - 1] || pts[i];
      const p1 = pts[i];
      const p2 = pts[i + 1];
      const p3 = pts[i + 2] || p2;
      ctx.bezierCurveTo(
        p1.x + (p2.x - p0.x) / 6, p1.y + (p2.y - p0.y) / 6,
        p2.x - (p3.x - p1.x) / 6, p2.y - (p3.y - p1.y) / 6,
        p2.x, p2.y
      );
    }
  }

  function niceMax(v) {
    if (!v || v < 1) return 10;
    const exp = Math.pow(10, Math.floor(Math.log10(v)));
    const f = v / exp;
    let m;
    if (f <= 1) m = 1;
    else if (f <= 2) m = 2;
    else if (f <= 2.5) m = 2.5;
    else if (f <= 5) m = 5;
    else m = 10;
    return m * exp;
  }

  /* ------------------------------------------------ tooltip */

  const tipEl = $("#tip");
  function showTip(html, x, y) {
    tipEl.innerHTML = html;
    tipEl.style.left = x + "px";
    tipEl.style.top = y + "px";
    tipEl.classList.add("show");
  }
  function hideTip() {
    tipEl.classList.remove("show");
  }

  /* ------------------------------------------------ 吞吐面积图 */

  function drawSpeed(canvas, series, animate) {
    const d = fit(canvas);
    const ctx = d.ctx, W = d.w, H = d.h;
    const padL = 0, padR = 6, padT = 12, padB = 20;
    const cw = W - padL - padR;
    const ch = H - padT - padB;
    if (!series.length) return;

    const vals = series.map((s) => s.v);
    const maxV = niceMax(Math.max.apply(null, vals.concat([10])));
    const n = vals.length;
    const prog = animate ? state._p || 0 : 1;

    // 网格
    ctx.strokeStyle = COLORS.grid;
    ctx.lineWidth = 1;
    for (let i = 0; i <= 3; i++) {
      const y = padT + (ch * i) / 3;
      ctx.beginPath();
      ctx.moveTo(padL, y + 0.5);
      ctx.lineTo(W - padR, y + 0.5);
      ctx.stroke();
    }
    // y 轴文字
    ctx.fillStyle = COLORS.axis;
    ctx.font = FONT_SM;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(compact(maxV), padL + 2, padT + 2);
    ctx.fillText("0", padL + 2, padT + ch - 2);

    const pts = vals.map((v, i) => ({
      x: padL + (cw * i) / Math.max(1, n - 1),
      y: padT + ch - (ch * Math.min(v, maxV) / maxV) * prog
    }));

    // 面积
    const grad = ctx.createLinearGradient(0, padT, 0, padT + ch);
    grad.addColorStop(0, "rgba(99,102,241,.26)");
    grad.addColorStop(0.55, "rgba(124,58,237,.10)");
    grad.addColorStop(1, "rgba(124,58,237,0)");
    ctx.beginPath();
    smooth(ctx, pts);
    ctx.lineTo(pts[pts.length - 1].x, padT + ch);
    ctx.lineTo(pts[0].x, padT + ch);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // 线
    const lg = ctx.createLinearGradient(padL, 0, W, 0);
    lg.addColorStop(0, "#6366f1");
    lg.addColorStop(1, "#a855f7");
    ctx.beginPath();
    smooth(ctx, pts);
    ctx.strokeStyle = lg;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();

    // 末端光点
    const last = pts[pts.length - 1];
    if (last) {
      const glow = ctx.createRadialGradient(last.x, last.y, 0, last.x, last.y, 12);
      glow.addColorStop(0, "rgba(139,92,246,.35)");
      glow.addColorStop(1, "rgba(139,92,246,0)");
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(last.x, last.y, 12, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#fff";
      ctx.strokeStyle = "#8b5cf6";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(last.x, last.y, 3.4, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }

    // x 轴
    ctx.fillStyle = COLORS.axis;
    ctx.font = FONT_SM;
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    ctx.fillText("-60 分钟", padL + 2, padT + ch + 6);
    ctx.textAlign = "right";
    ctx.fillText("现在", W - padR, padT + ch + 6);

    canvas._hit = { pts: pts, series: series, padT: padT, ch: ch, W: W, padR: padR };
  }

  /* ------------------------------------------------ 堆叠柱 */

  function drawUsage(canvas, buckets, animate) {
    const d = fit(canvas);
    const ctx = d.ctx, W = d.w, H = d.h;
    const padL = 38, padR = 4, padT = 10, padB = 20;
    const cw = W - padL - padR;
    const ch = H - padT - padB;
    const n = buckets.length;
    if (!n) return;

    const totals = buckets.map((b) => b.hit + b.miss + b.out);
    const maxV = niceMax(Math.max.apply(null, totals.concat([1])));
    const prog = animate ? state._p || 0 : 1;

    ctx.strokeStyle = COLORS.grid;
    ctx.lineWidth = 1;
    ctx.font = FONT_SM;
    ctx.textBaseline = "middle";
    for (let i = 0; i <= 3; i++) {
      const y = padT + (ch * i) / 3;
      ctx.beginPath();
      ctx.moveTo(padL, y + 0.5);
      ctx.lineTo(W - padR, y + 0.5);
      ctx.stroke();
      const val = maxV - (maxV * i) / 3;
      ctx.fillStyle = COLORS.axis;
      ctx.textAlign = "right";
      ctx.fillText(compact(val), padL - 6, y);
    }

    const slot = cw / n;
    const bw = Math.max(2.5, Math.min(26, slot * 0.62));
    const hitTop = [];
    const baseY = padT + ch;

    for (let i = 0; i < n; i++) {
      const b = buckets[i];
      const x = padL + slot * i + (slot - bw) / 2;
      const h1 = (ch * b.hit / maxV) * prog;
      const h2 = (ch * b.miss / maxV) * prog;
      const h3 = (ch * b.out / maxV) * prog;

      let y = baseY;
      if (h1 > 0.4) {
        ctx.fillStyle = "rgba(6,182,212,.78)";
        ctx.fillRect(x, y - h1, bw, h1);
        y -= h1;
      }
      if (h2 > 0.4) {
        ctx.fillStyle = "rgba(245,158,11,.85)";
        ctx.fillRect(x, y - h2, bw, h2);
        y -= h2;
      }
      if (h3 > 0.4) {
        ctx.fillStyle = "rgba(124,58,237,.9)";
        roundTop(ctx, x, y - h3, bw, h3, Math.min(3, bw / 2));
        ctx.fill();
        y -= h3;
      } else if (h1 + h2 > 0.4) {
        ctx.fillStyle = "rgba(6,182,212,.78)";
        roundTop(ctx, x, y, bw, 2, 1);
        ctx.fill();
      }
      hitTop.push({ x: x, w: bw, y: y, b: b, cx: padL + slot * i + slot / 2 });
    }

    // x 标签
    ctx.fillStyle = COLORS.axis;
    ctx.font = FONT_SM;
    ctx.textBaseline = "top";
    const step = Math.max(1, Math.ceil(n / 8));
    for (let i = 0; i < n; i += step) {
      const cx = padL + slot * i + slot / 2;
      ctx.textAlign = "center";
      ctx.fillText(buckets[i].label, cx, baseY + 6);
    }

    canvas._hit = { bars: hitTop, baseY: baseY, slot: slot };
  }

  /* ------------------------------------------------ 命中率折线 */

  function drawCache(canvas, buckets, animate) {
    const d = fit(canvas);
    const ctx = d.ctx, W = d.w, H = d.h;
    const padL = 30, padR = 8, padT = 12, padB = 20;
    const cw = W - padL - padR;
    const ch = H - padT - padB;
    const n = buckets.length;
    if (!n) return;

    const prog = animate ? state._p || 0 : 1;

    ctx.strokeStyle = COLORS.grid;
    ctx.lineWidth = 1;
    ctx.font = FONT_SM;
    ctx.textBaseline = "middle";
    for (let i = 0; i <= 4; i++) {
      const y = padT + (ch * i) / 4;
      ctx.beginPath();
      ctx.moveTo(padL, y + 0.5);
      ctx.lineTo(W - padR, y + 0.5);
      ctx.stroke();
      ctx.fillStyle = COLORS.axis;
      ctx.textAlign = "right";
      ctx.fillText((100 - i * 25) + "%", padL - 6, y);
    }

    // 80% 参考线
    const y80 = padT + ch * (1 - 0.8);
    ctx.save();
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = "rgba(16,185,129,.45)";
    ctx.beginPath();
    ctx.moveTo(padL, y80);
    ctx.lineTo(W - padR, y80);
    ctx.stroke();
    ctx.restore();

    const pts = [];
    for (let i = 0; i < n; i++) {
      const b = buckets[i];
      const denom = b.hit + b.miss;
      const x = padL + (cw * (i + 0.5)) / n;
      if (!denom) {
        pts.push(null);
        continue;
      }
      const r = b.hit / denom;
      const y = padT + ch - ch * r * prog;
      pts.push({ x: x, y: y, r: r, b: b });
    }

    // 分段绘制（空桶断开）
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.strokeStyle = "#10b981";
    let seg = [];
    const flush = () => {
      if (seg.length > 1) {
        ctx.beginPath();
        smooth(ctx, seg);
        ctx.stroke();

        const g = ctx.createLinearGradient(0, padT, 0, padT + ch);
        g.addColorStop(0, "rgba(16,185,129,.18)");
        g.addColorStop(1, "rgba(16,185,129,0)");
        ctx.beginPath();
        smooth(ctx, seg);
        ctx.lineTo(seg[seg.length - 1].x, padT + ch);
        ctx.lineTo(seg[0].x, padT + ch);
        ctx.closePath();
        ctx.fillStyle = g;
        ctx.fill();
      }
      seg = [];
    };
    for (let i = 0; i < pts.length; i++) {
      if (pts[i]) seg.push(pts[i]);
      else flush();
    }
    flush();

    // 数据点
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i];
      if (!p) continue;
      if (n > 40 && i % 3 !== 0) continue;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 2.2, 0, Math.PI * 2);
      ctx.fillStyle = "#fff";
      ctx.fill();
      ctx.strokeStyle = "#10b981";
      ctx.lineWidth = 1.6;
      ctx.stroke();
    }

    ctx.fillStyle = COLORS.axis;
    ctx.font = FONT_SM;
    ctx.textBaseline = "top";
    const step = Math.max(1, Math.ceil(n / 8));
    for (let i = 0; i < n; i += step) {
      const x = padL + (cw * (i + 0.5)) / n;
      ctx.textAlign = "center";
      ctx.fillText(buckets[i].label, x, padT + ch + 6);
    }

    canvas._hit = { pts: pts, padL: padL, cw: cw, n: n, padT: padT, ch: ch };
  }

  /* ------------------------------------------------ 环形图 */

  function drawDonut(canvas, models, animate) {
    const d = fit(canvas);
    const ctx = d.ctx, W = d.w, H = d.h;
    const cx = W / 2, cy = H / 2;
    const R = Math.min(W, H) / 2 - 6;
    const r = R * 0.66;
    const isCredit = state.modelMetric === "credit";
    const total = models.reduce((s, m) => s + (isCredit ? m.credit : m.tokens), 0);

    if (!total) {
      ctx.strokeStyle = "#eef2f7";
      ctx.lineWidth = 12;
      ctx.beginPath();
      ctx.arc(cx, cy, (R + r) / 2, 0, Math.PI * 2);
      ctx.stroke();
      return;
    }

    const prog = animate ? state._p || 0 : 1;
    let a0 = -Math.PI / 2;
    models.forEach((m, i) => {
      const val = isCredit ? m.credit : m.tokens;
      const frac = val / total;
      const a1 = a0 + frac * Math.PI * 2 * prog;
      ctx.beginPath();
      ctx.arc(cx, cy, R, a0, a1);
      ctx.arc(cx, cy, r, a1, a0, true);
      ctx.closePath();
      ctx.fillStyle = MODEL_COLORS[i % MODEL_COLORS.length];
      ctx.fill();
      a0 = a1;
    });

    // 内圈阴影
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = "#fff";
    ctx.fill();

    canvas._hit = { donut: true, cx: cx, cy: cy, R: R, r: r, models: models, total: total, isCredit: isCredit };
  }

  /* ------------------------------------------------ hover */

  function bindHover(canvas, kind) {
    canvas.addEventListener("mousemove", function (e) {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const hit = canvas._hit;
      if (!hit) return;
      const px = e.clientX, py = e.clientY;

      if (kind === "speed" && hit.pts) {
        let best = -1, bd = 1e9;
        hit.pts.forEach((p, i) => {
          const dd = Math.abs(p.x - x);
          if (dd < bd) { bd = dd; best = i; }
        });
        if (best >= 0) {
          const p = hit.pts[best];
          const s = hit.series[best];
          showTip(
            '<span class="k">' + hhmm(s.t) + '</span><br><b>' + s.v.toFixed(1) + '</b> tok/s' +
            (s.calls ? '<br><span class="k">' + s.calls + ' 次调用 · ' + compact(s.out) + ' tokens</span>' : '<br><span class="k">无调用</span>'),
            px, py
          );
          return;
        }
      }

      if (kind === "usage" && hit.bars) {
        const half = (hit.slot || 12) / 2;
        for (let i = 0; i < hit.bars.length; i++) {
          const b = hit.bars[i];
          if (Math.abs(x - b.cx) <= half) {
            const bb = b.b;
            showTip(
              '<b>' + bb.label + '</b><br>' +
              '<span class="k">缓存命中</span> ' + compact(bb.hit) + '<br>' +
              '<span class="k">未命中</span> ' + compact(bb.miss) + '<br>' +
              '<span class="k">输出</span> ' + compact(bb.out) + '<br>' +
              '<span class="k">' + bb.calls + ' 次调用 · ' + bb.credit.toFixed(2) + ' 积分</span>',
              b.cx + rect.left, py
            );
            return;
          }
        }
      }

      if (kind === "cache" && hit.pts) {
        let best = null, bd = 1e9;
        hit.pts.forEach((p) => {
          if (!p) return;
          const dd = Math.abs(p.x - x);
          if (dd < bd) { bd = dd; best = p; }
        });
        if (best && bd < 26) {
          showTip(
            '<b>' + best.b.label + '</b><br>命中率 <b>' + (best.r * 100).toFixed(1) + '%</b><br>' +
            '<span class="k">命中 ' + compact(best.b.hit) + ' / 未命中 ' + compact(best.b.miss) + '</span>',
            best.x + rect.left, py
          );
          return;
        }
      }

      if (kind === "donut" && hit.donut) {
        const dx = x - hit.donut.cx, dy = y - hit.donut.cy;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist >= hit.donut.r && dist <= hit.donut.R) {
          let ang = Math.atan2(dy, dx) + Math.PI / 2;
          if (ang < 0) ang += Math.PI * 2;
          let acc = 0;
          for (let i = 0; i < hit.donut.models.length; i++) {
            const m = hit.donut.models[i];
            const val = hit.donut.isCredit ? m.credit : m.tokens;
            const f = val / (hit.donut.total || 1);
            if (ang >= acc && ang < acc + f) {
              const cShare = (m.credit_share !== undefined ? m.credit_share * 100 : ((m.credit / (hit.donut.total || 1)) * 100)).toFixed(1);
              const tShare = (m.share !== undefined ? m.share * 100 : ((m.tokens / (hit.donut.total || 1)) * 100)).toFixed(1);
              showTip(
                '<b>' + esc(m.name) + '</b><br>' +
                '<span class="k">Token 用量</span> ' + compact(m.tokens) + ' (' + tShare + '%)<br>' +
                '<span class="k">积分消耗</span> ' + m.credit.toFixed(2) + ' 分 (' + cShare + '%)<br>' +
                '<span class="k">' + m.calls + ' 次调用 · 命中率 ' + pct(m.hit / (m.in || 1)) + '</span>',
                px, py
              );
              return;
            }
            acc += f;
          }
        }
      }

      hideTip();
    });

    canvas.addEventListener("mouseleave", hideTip);
  }

  /* ------------------------------------------------ 渲染 */

  function renderKpi(k) {
    setNum($('[data-k="tokens"]'), k.tokens, compact);
    $('[data-k="inout"]').textContent = "输入 " + compact(k.input) + " · 输出 " + compact(k.output);

    const hr = $('[data-k="hitrate"]');
    setNum(hr, k.hit_rate * 100, (v) => v.toFixed(1));
    $('[data-k="hitinfo"]').textContent =
      "命中 " + compact(k.cache_hit) + " / 未命中 " + compact(k.cache_miss);

    setNum($('[data-k="speed"]'), k.avg_speed, (v) => v.toFixed(0));
    $('[data-k="speedinfo"]').textContent = "峰值 " + k.peak_speed.toFixed(0) + " tok/s";

    setNum($('[data-k="credit"]'), k.credit, (v) => v.toFixed(2));
    $('[data-k="creditinfo"]').textContent = "今日 " + k.today_credit.toFixed(2) + " 分";

    setNum($('[data-k="calls"]'), k.calls, (v) => intFmt(v));
    const gs = k.gen_seconds || 0;
    $('[data-k="callinfo"]').textContent =
      "生成耗时 " + (gs >= 120 ? (gs / 60).toFixed(1) + " 分钟" : gs.toFixed(0) + " 秒");
  }

  function renderNowSpeed(data) {
    const now = Date.now();
    const recs = data.recent || [];
    const recent5 = recs.filter((r) => now - r.t < 300000 && r.dur > 200);
    let v = 0, sub = "";
    if (recent5.length) {
      let dsum = 0, osum = 0, c = 0;
      recent5.forEach((r) => { dsum += r.dur; osum += r.out; c++; });
      v = osum / (dsum / 1000);
      sub = "最近 5 分钟 · " + c + " 次调用";
    } else if (recs.length) {
      sub = "空闲 · 上次 " + ago(recs[0].t);
    } else {
      sub = "等待记录";
    }
    setNum($("#now-speed"), v, (n) => n.toFixed(0));
    $("#now-sub").textContent = sub;
  }

  function renderModels(models) {
    const box = $("#model-legend");
    const isCredit = state.modelMetric === "credit";
    const totalTokens = models.reduce((s, m) => s + m.tokens, 0);
    const totalCredit = models.reduce((s, m) => s + m.credit, 0);

    const totalEl = $("#model-total");
    const labelEl = $("#model-total-label");
    if (isCredit) {
      totalEl.textContent = totalCredit.toFixed(2);
      if (labelEl) labelEl.textContent = "总积分(分)";
    } else {
      totalEl.textContent = compact(totalTokens);
      if (labelEl) labelEl.textContent = "总 Token";
    }

    const items = isCredit
      ? [].concat(models).sort((a, b) => b.credit - a.credit)
      : [].concat(models).sort((a, b) => b.tokens - a.tokens);

    box.innerHTML = items.slice(0, 6).map((m, i) => {
      const color = MODEL_COLORS[i % MODEL_COLORS.length];
      const valTxt = isCredit
        ? m.credit.toFixed(2) + " 分 (" + (totalCredit ? ((m.credit / totalCredit) * 100).toFixed(1) : "0") + "%)"
        : compact(m.tokens) + " (" + (totalTokens ? ((m.tokens / totalTokens) * 100).toFixed(1) : "0") + "%)";
      return '<li><i style="background:' + color + '"></i>' +
        '<span class="lname" title="' + esc(m.name) + '">' + esc(m.name) + "</span>" +
        '<span class="lval">' + valTxt + "</span></li>";
    }).join("");
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  function renderSessions(rows) {
    const tb = $("#tbl-sessions tbody");
    if (!rows.length) {
      tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#94a3b8;padding:26px 0">当前范围还没有调用记录</td></tr>';
      return;
    }
    tb.innerHTML = rows.map((r, i) => {
      const path = r.cwd ? r.cwd.replace(/^\/home\/[^/]+/, "~") : "";
      const hr = r.hit_rate;
      const cls = hr >= 0.9 ? "good" : hr >= 0.6 ? "mid" : "bad";
      const hasCtx = r.used > 0 && r.size > 0;
      const ratio = hasCtx ? Math.min(1, r.used / r.size) : 0;
      const ctxTxt = hasCtx
        ? compact(r.used) + " / " + compact(r.size) + " · " + (ratio * 100).toFixed(0) + "%"
        : "—";
      const ctxCell = hasCtx
        ? '<div class="ctx-bar"><i style="width:' + (ratio * 100).toFixed(1) + '%"></i></div>'
        : '<div class="ctx-bar" style="opacity:.45"></div>';
      return '<tr>' +
        '<td class="col-title"><div class="title-cell"><span class="rank">' + (i + 1) + "</span>" +
        '<div style="min-width:0"><div class="t-name">' + esc(r.title) + "</div>" +
        '<div class="t-path">' + esc(path) + "</div></div></div></td>" +
        '<td><span class="model-chip" title="' + esc(r.model) + '">' + esc(shortModel(r.model)) + "</span></td>" +
        '<td class="num">' + compact(r.tokens) + "</td>" +
        '<td class="num">' + r.calls + "</td>" +
        '<td class="num"><span class="pill ' + cls + '">' + (hr * 100).toFixed(1) + "%</span></td>" +
        '<td class="num">' + (r.speed ? r.speed.toFixed(0) : "—") + "</td>" +
        '<td class="num">' + (r.credit ? r.credit.toFixed(2) : "—") + "</td>" +
        '<td class="col-ctx bar-cell">' + ctxCell +
        '<div class="ctx-txt">' + ctxTxt + "</div></td>" +
        "</tr>";
    }).join("");
  }

  function shortModel(m) {
    if (!m) return "unknown";
    return m.length > 18 ? m.slice(0, 17) + "…" : m;
  }

  let streamKey = "";
  function renderStream(rows) {
    const ul = $("#stream");
    const key = rows.map((r) => r.t + ":" + r.out + ":" + r.in).join("|");
    if (key === streamKey) return;
    streamKey = key;
    if (!rows.length) {
      ul.innerHTML = '<li style="display:block;color:#94a3b8;padding:18px 6px">等待新的模型调用…</li>';
      return;
    }
    const maxTok = Math.max.apply(null, rows.map((r) => r.in).concat([1]));
    ul.innerHTML = rows.map((r, i) => {
      const denom = r.hit + r.miss || 1;
      const hp = (r.hit / denom) * 100;
      const mp = (r.miss / denom) * 100;
      return '<li' + (i === 0 ? ' class="fresh"' : "") + ">" +
        '<span class="st-time">' + hhmmss(r.t) + "</span>" +
        '<span class="st-model" title="' + esc(r.model) + '">' + esc(shortModel(r.model)) + "</span>" +
        '<span class="st-bars"><span class="mini-bar" title="缓存命中 ' + pct(r.hit / denom) + '">' +
        '<i style="width:' + hp.toFixed(1) + "%;background:" + COLORS.hit + '"></i>' +
        '<i style="width:' + mp.toFixed(1) + "%;background:" + COLORS.miss + '"></i>' +
        "</span></span>" +
        '<span class="st-nums">' + compact(r.in) + " → " + compact(r.out) + "</span>" +
        '<span class="st-speed' + (r.speed ? "" : " zero") + '">' +
        (r.speed ? r.speed.toFixed(0) + " tok/s" : "—") + "</span>" +
        "</li>";
    }).join("");
  }

  function renderCacheNote(k) {
    const saved = k.cache_hit;
    const miss = k.cache_miss;
    if (!k.tokens) {
      $("#cache-note").textContent = "缓存让重复上下文无需重新计费";
      return;
    }
    const factor = miss > 0 ? (k.input / miss) : 0;
    $("#cache-note").textContent =
      "命中 " + compact(saved) + " tokens，约等于减少 " + (factor ? factor.toFixed(1) + "×" : "大量") + " 的重复计算";
  }

  function renderModelTable(models) {
    const tb = $("#tbl-models tbody");
    if (!tb) return;
    if (!models || !models.length) {
      tb.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#94a3b8;padding:26px 0">当前选定时间段内没有模型调用记录</td></tr>';
      return;
    }
    const maxCredit = Math.max.apply(null, models.map((m) => m.credit).concat([0.01]));
    const totalCredit = models.reduce((s, m) => s + m.credit, 0);

    tb.innerHTML = models.map((m, i) => {
      const hr = m.hit_rate !== undefined ? m.hit_rate : (m.hit / (m.in || 1));
      const cls = hr >= 0.9 ? "good" : hr >= 0.6 ? "mid" : "bad";
      const cRatio = maxCredit > 0 ? Math.min(100, Math.max(0, (m.credit / maxCredit) * 100)) : 0;
      const cShare = m.credit_share !== undefined
        ? (m.credit_share * 100).toFixed(1) + "%"
        : (totalCredit ? ((m.credit / totalCredit) * 100).toFixed(1) + "%" : "0.0%");
      const isSelected = state.model && state.model.toLowerCase() === m.name.toLowerCase();

      return '<tr' + (isSelected ? ' style="background:#f8faff"' : '') + '>' +
        '<td class="col-title">' +
        '<div class="title-cell"><span class="rank">' + (i + 1) + '</span>' +
        '<span class="model-chip" title="' + esc(m.name) + '">' + esc(m.name) + '</span>' +
        (isSelected ? ' <span class="pill good" style="font-size:10px;padding:2px 6px">已筛选</span>' : '') +
        '</div></td>' +
        '<td class="num"><b>' + compact(m.tokens) + '</b></td>' +
        '<td class="num">' + compact(m.in) + ' / ' + compact(m.out) + '</td>' +
        '<td class="num"><span class="pill ' + cls + '">' + (hr * 100).toFixed(1) + '%</span></td>' +
        '<td class="num">' + intFmt(m.calls) + '</td>' +
        '<td class="num">' + (m.speed ? m.speed.toFixed(0) : '—') + '</td>' +
        '<td class="num"><div class="credit-bar-cell"><b>' + m.credit.toFixed(2) + ' 分</b>' +
        '<span class="credit-mini-bar"><i style="width:' + cRatio.toFixed(1) + '%"></i></span></div></td>' +
        '<td class="num">' + cShare + '</td>' +
        '<td style="text-align:center">' +
        (isSelected
          ? '<button class="btn-filter-this" data-clear="1" style="background:#fee2e2;color:#dc2626;border-color:#fca5a5">清除</button>'
          : '<button class="btn-filter-this" data-model="' + esc(m.name) + '">筛选</button>') +
        '</td>' +
        '</tr>';
    }).join("");
  }

  function syncModelFilterSelect(models) {
    const sel = $("#model-filter");
    if (!sel) return;
    const current = (state.model || "").toLowerCase();
    const opts = ['<option value="">全部模型 (' + models.length + ' 种)</option>'];
    models.forEach((m) => {
      const isSel = m.name.toLowerCase() === current ? ' selected' : '';
      opts.push('<option value="' + esc(m.name) + '"' + isSel + '>' + esc(m.name) + ' (' + compact(m.tokens) + ' tok · ' + m.credit.toFixed(1) + '分)</option>');
    });
    sel.innerHTML = opts.join("");
    sel.classList.toggle("active", !!state.model);
    const clr = $("#model-filter-clear");
    if (clr) clr.style.display = state.model ? "block" : "none";
  }

  function render() {
    const data = state.data;
    if (!data) return;

    renderKpi(data.kpi);
    renderNowSpeed(data);
    renderModels(data.models);
    renderSessions(data.sessions);
    renderModelTable(data.models);
    renderStream(data.recent);
    renderCacheNote(data.kpi);
    syncModelFilterSelect(data.models);

    $("#usage-tag").textContent = data.series.granularity === "hour" ? "按小时" : "按天";
    $("#cache-tag").textContent = data.series.granularity === "hour" ? "按小时" : "按天";

    const animate = state.animate;
    if (animate) {
      state._p = 0;
      const t0 = performance.now();
      const tick = (t) => {
        const p = Math.min(1, (t - t0) / 520);
        state._p = 1 - Math.pow(1 - p, 3);
        paint();
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      state.animate = false;
    } else {
      paint();
    }

    $("#stream-tag").textContent = "最新 " + data.recent.length + " 次";
    $("#foot-stat").textContent =
      data.status.files + " 个会话文件 · " + intFmt(data.status.records) + " 条调用记录";
    const t = new Date(data.generated_at);
    $("#live-status").textContent = "最近更新 " + hhmmss(data.generated_at) + " · 每 2 秒自动刷新";
  }

  function paint() {
    const data = state.data;
    if (!data) return;
    drawSpeed($("#chart-speed"), data.speeds, state._p !== undefined && state._p < 1);
    drawUsage($("#chart-usage"), data.series.buckets, state._p !== undefined && state._p < 1);
    drawCache($("#chart-cache"), data.series.buckets, state._p !== undefined && state._p < 1);
    drawDonut($("#chart-models"), data.models, state._p !== undefined && state._p < 1);
  }

  /* ------------------------------------------------ 数据 */

  async function load() {
    if (state.paused) return;
    try {
      let url = "/api/snapshot?range=" + encodeURIComponent(state.range);
      if (state.range === "custom") {
        if (state.customStart) url += "&start=" + encodeURIComponent(state.customStart);
        if (state.customEnd) url += "&end=" + encodeURIComponent(state.customEnd);
      }
      if (state.model) {
        url += "&model=" + encodeURIComponent(state.model);
      }
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      state.data = data;
      state.lastUpdate = Date.now();
      $("#livebadge").classList.remove("off");
      render();
    } catch (err) {
      $("#livebadge").classList.add("off");
      $("#live-status").textContent = "连接中断，正在重试…";
    }
  }

  /* ------------------------------------------------ 事件 */

  const popover = $("#custom-date-popover");
  $("#range").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-range]");
    if (!b) return;
    const r = b.dataset.range;
    if (r === "custom") {
      if (popover) {
        popover.style.display = popover.style.display === "none" ? "block" : "none";
      }
      return;
    }
    if (popover) popover.style.display = "none";
    const custBtn = $("#btn-custom-range");
    if (custBtn) custBtn.textContent = "自定义 ▾";
    $$("#range button").forEach((x) => x.classList.toggle("on", x === b));
    state.range = r;
    state.customStart = "";
    state.customEnd = "";
    state.animate = true;
    load();
  });

  function fmtDateInput(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }

  $$(".preset-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const p = btn.dataset.preset;
      const now = new Date();
      let s = new Date(now), e = new Date(now);
      if (p === "today") {
        // today
      } else if (p === "yesterday") {
        s.setDate(s.getDate() - 1);
        e.setDate(e.getDate() - 1);
      } else if (p === "7d") {
        s.setDate(s.getDate() - 6);
      } else if (p === "30d") {
        s.setDate(s.getDate() - 29);
      } else if (p === "thismonth") {
        s.setDate(1);
      }
      $("#inp-start-date").value = fmtDateInput(s);
      $("#inp-end-date").value = fmtDateInput(e);
    });
  });

  const btnApply = $("#btn-custom-apply");
  if (btnApply) {
    btnApply.addEventListener("click", () => {
      const sVal = $("#inp-start-date").value;
      const eVal = $("#inp-end-date").value;
      if (!sVal && !eVal) {
        if (popover) popover.style.display = "none";
        return;
      }
      state.range = "custom";
      state.customStart = sVal ? sVal + " 00:00:00" : "";
      state.customEnd = eVal ? eVal + " 23:59:59" : "";
      $$("#range button").forEach((x) => x.classList.toggle("on", x.dataset.range === "custom"));
      const sShort = sVal ? sVal.slice(5) : "";
      const eShort = eVal ? eVal.slice(5) : "";
      const custBtn = $("#btn-custom-range");
      if (custBtn) custBtn.textContent = (sShort && eShort ? sShort + "~" + eShort : "已选时间") + " ▾";
      if (popover) popover.style.display = "none";
      state.animate = true;
      load();
    });
  }

  const btnCancel = $("#btn-custom-cancel");
  if (btnCancel) {
    btnCancel.addEventListener("click", () => {
      if (popover) popover.style.display = "none";
    });
  }

  document.addEventListener("click", (e) => {
    if (popover && popover.style.display !== "none") {
      if (!e.target.closest(".range-box")) {
        popover.style.display = "none";
      }
    }
  });

  const selModel = $("#model-filter");
  if (selModel) {
    selModel.addEventListener("change", (e) => {
      state.model = e.target.value;
      state.animate = true;
      load();
    });
  }
  const clrModel = $("#model-filter-clear");
  if (clrModel) {
    clrModel.addEventListener("click", () => {
      state.model = "";
      if (selModel) selModel.value = "";
      state.animate = true;
      load();
    });
  }

  const metricToggle = $("#model-metric-toggle");
  if (metricToggle) {
    metricToggle.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-metric]");
      if (!b) return;
      $$("#model-metric-toggle button").forEach((x) => x.classList.toggle("on", x === b));
      state.modelMetric = b.dataset.metric;
      if (state.data) {
        renderModels(state.data.models);
        drawDonut($("#chart-models"), state.data.models, false);
      }
    });
  }

  const tabHeader = $("#table-tabs");
  if (tabHeader) {
    tabHeader.addEventListener("click", (e) => {
      const b = e.target.closest("button.tbl-tab");
      if (!b) return;
      $$("#table-tabs button").forEach((x) => x.classList.toggle("on", x === b));
      state.activeTab = b.dataset.tab;
      const isSess = state.activeTab === "sessions";
      $("#wrap-sessions").style.display = isSess ? "" : "none";
      $("#wrap-models").style.display = isSess ? "none" : "";
      $("#table-tag").textContent = isSess ? "上下文占用为当前窗口" : "按模型查看累计消耗与积分";
    });
  }

  const tblModels = $("#tbl-models");
  if (tblModels) {
    tblModels.addEventListener("click", (e) => {
      const b = e.target.closest(".btn-filter-this");
      if (!b) return;
      if (b.dataset.clear) {
        state.model = "";
      } else if (b.dataset.model) {
        state.model = b.dataset.model;
      }
      state.animate = true;
      load();
    });
  }

  $("#pause").addEventListener("click", () => {
    state.paused = !state.paused;
    $("#pause").style.background = state.paused ? "#f1f5f9" : "";
    $("#livebadge").classList.toggle("off", state.paused);
    if (!state.paused) load();
  });

  let rt = null;
  window.addEventListener("resize", () => {
    clearTimeout(rt);
    rt = setTimeout(paint, 120);
  });

  bindHover($("#chart-speed"), "speed");
  bindHover($("#chart-usage"), "usage");
  bindHover($("#chart-cache"), "cache");
  bindHover($("#chart-models"), "donut");

  // 启动
  if (window.__WB_SNAPSHOT__) {
    state.data = window.__WB_SNAPSHOT__;
    state.animate = true;
    render();
    $("#live-status").textContent = "静态快照 · " + hhmmss(state.data.generated_at) + " 生成";
    const lb = $("#livebadge");
    lb.classList.add("off");
    if (lb.lastChild && lb.lastChild.nodeType === 3) lb.lastChild.textContent = "快照";
    $("#pause").style.display = "none";
    const rg = $("#range");
    if (rg) rg.style.display = "none";
  } else {
    load();
    setInterval(load, 2000);
  }
})();
