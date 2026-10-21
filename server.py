#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy Token Monitor — 本地用量监视服务

数据来源（全部只读）:
  ~/.workbuddy/projects/**/*.jsonl   每次模型调用的 usage（含缓存命中、积分）
  ~/.workbuddy/workbuddy.db          sessions / session_usage（标题、上下文占用）

对外提供:
  GET /                 可视化面板
  GET /api/snapshot     聚合快照 (range=today|7d|all)
  GET /api/ping         健康检查

仅使用标准库，兼容 Python 3.8+。
"""

import argparse
import glob
import json
import os
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")

WB_HOME = os.path.abspath(os.environ.get("WB_HOME") or os.path.expanduser("~/.workbuddy"))
PROJECTS_DIR = os.path.join(WB_HOME, "projects")
DB_PATH = os.path.join(WB_HOME, "workbuddy.db")

SCAN_INTERVAL = 1.2          # 秒
CTX_TTL = 5.0                # 数据库缓存秒数
MAX_DAY_BUCKETS = 120        # 全部范围最多天数
SPEED_WINDOW_MIN = 60        # 实时吞吐曲线窗口（分钟）


# ---------------------------------------------------------------- 工具函数

def ms_now():
    return int(time.time() * 1000)


def day_start_ms(ts_ms):
    lt = time.localtime(ts_ms / 1000.0)
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)) * 1000)


def hour_start_ms(ts_ms):
    lt = time.localtime(ts_ms / 1000.0)
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, lt.tm_hour, 0, 0, 0, 0, -1)) * 1000)


def num(v):
    return v if isinstance(v, (int, float)) else 0


# ---------------------------------------------------------------- 数据采集

class FileState(object):
    __slots__ = ("ino", "off", "anchor", "sid", "cwd", "seen")

    def __init__(self):
        self.ino = None
        self.off = 0
        self.anchor = None      # 上一次"生成开始"的时间锚点
        self.sid = None
        self.cwd = None
        self.seen = set()


class Collector(object):
    """增量扫描 jsonl，抽取每次模型调用的用量记录。"""

    def __init__(self):
        self.lock = threading.RLock()
        self.files = {}
        self.records = []
        self.rids = set()
        self.sessions = {}      # sid -> {title, model, ctx_window, cwd, updated}
        self.ctx_usage = {}     # sid -> {used, size}
        self.last_scan = 0
        self.scanning = False
        self._ctx_loaded_at = 0

    # -- 数据库 --------------------------------------------------
    def load_db(self):
        now = time.time()
        if now - self._ctx_loaded_at < CTX_TTL:
            return
        self._ctx_loaded_at = now
        if not os.path.exists(DB_PATH):
            return
        try:
            con = sqlite3.connect("file:%s?mode=ro" % DB_PATH, uri=True, timeout=1.0)
            con.row_factory = sqlite3.Row
            try:
                for r in con.execute(
                    "select session_id, used, size from session_usage"
                ):
                    try:
                        self.ctx_usage[r["session_id"]] = {
                            "used": int(r["used"] or 0),
                            "size": int(r["size"] or 0),
                        }
                    except Exception:
                        pass
                for r in con.execute(
                    "select id, title, custom_title, model, context_window, cwd, updated_at "
                    "from sessions where deleted_at is null"
                ):
                    title = r["custom_title"] or r["title"] or ""
                    self.sessions[r["id"]] = {
                        "title": title,
                        "model": r["model"] or "",
                        "ctx_window": r["context_window"] or 0,
                        "cwd": r["cwd"] or "",
                        "updated": r["updated_at"] or 0,
                    }
            finally:
                con.close()
        except Exception:
            pass

    # -- 单行解析 ------------------------------------------------
    def feed(self, st, raw):
        raw = raw.strip()
        if not raw:
            return
        try:
            d = json.loads(raw)
        except Exception:
            return
        if not isinstance(d, dict):
            return

        if d.get("cwd"):
            st.cwd = d["cwd"]
        if d.get("sessionId"):
            st.sid = d["sessionId"]

        t = d.get("timestamp")
        if not isinstance(t, (int, float)):
            t = None
        typ = d.get("type")

        pd = d.get("providerData") or {}
        ru = pd.get("rawUsage") if isinstance(pd, dict) else None
        msg = d.get("message") if isinstance(d.get("message"), dict) else {}
        mu = msg.get("usage") if isinstance(msg, dict) else None

        if ru or mu:
            rec = self._build_record(st, d, pd, ru or {}, mu or {}, t)
            if rec is not None:
                rid = rec["id"]
                if rid and rid in self.rids:
                    pass
                else:
                    if rid:
                        self.rids.add(rid)
                    self.records.append(rec)

        if typ in ("function_call_result", "message") and t:
            st.anchor = t

    def _build_record(self, st, d, pd, ru, mu, t):
        if t is None:
            return None
        inp = ru.get("prompt_tokens")
        if inp is None:
            inp = mu.get("input_tokens") or 0
        out = ru.get("completion_tokens")
        if out is None:
            out = mu.get("output_tokens") or 0

        hit = ru.get("prompt_cache_hit_tokens")
        if hit is None:
            hit = mu.get("cache_read_input_tokens") or 0
        miss = ru.get("prompt_cache_miss_tokens")
        if miss is None:
            miss = max(0, num(inp) - num(hit))

        ctd = ru.get("completion_tokens_details") or {}
        reasoning = ctd.get("reasoning_tokens") or ru.get("completion_thinking_tokens") or 0

        credit = ru.get("credit")
        if credit is None:
            credit = pd.get("credit") or 0

        dur = None
        if st.anchor and t > st.anchor:
            dur = int(t - st.anchor)
            if dur > 30 * 60 * 1000:
                dur = None

        model = pd.get("requestModelName") or pd.get("model") or "unknown"
        tool = (d.get("name") or "").strip()

        return {
            "id": d.get("id") or (str(st.sid) + ":" + str(t)),
            "t": int(t),
            "sid": st.sid or d.get("sessionId") or "",
            "cwd": st.cwd or "",
            "model": model,
            "in": int(num(inp)),
            "out": int(num(out)),
            "hit": int(num(hit)),
            "miss": int(num(miss)),
            "reason": int(num(reasoning)),
            "credit": float(num(credit)),
            "dur": dur,
            "tool": tool,
        }

    # -- 文件扫描 ------------------------------------------------
    def scan(self):
        with self.lock:
            self.scanning = True
            try:
                self.load_db()
                paths = glob.glob(os.path.join(PROJECTS_DIR, "**", "*.jsonl"), recursive=True)
                for path in paths:
                    try:
                        stt = os.stat(path)
                    except OSError:
                        continue
                    st = self.files.get(path)
                    if st is None:
                        st = FileState()
                        self.files[path] = st
                    if st.ino != stt.st_ino:
                        st.ino = stt.st_ino
                        st.off = 0
                    if stt.st_size < st.off:
                        st.off = 0
                    if stt.st_size == st.off:
                        continue
                    try:
                        with open(path, "rb") as f:
                            f.seek(st.off)
                            while True:
                                pos = f.tell()
                                line = f.readline()
                                if not line:
                                    break
                                if not line.endswith(b"\n"):
                                    f.seek(pos)   # 半行，等下次
                                    break
                                self.feed(st, line.decode("utf-8", "replace"))
                            st.off = f.tell()
                    except OSError:
                        continue
            finally:
                self.scanning = False
                self.last_scan = ms_now()

    def born(self):
        # 首次全量扫描
        self.scan()

    # -- 聚合 ----------------------------------------------------
    def snapshot(self, range_key, speed_min=60):
        with self.lock:
            recs = sorted(self.records, key=lambda r: r["t"])
            sessions = dict(self.sessions)
            ctx = dict(self.ctx_usage)

        now = ms_now()
        today = day_start_ms(now)

        if range_key == "today":
            start = today
            sel = [r for r in recs if r["t"] >= start]
        elif range_key == "7d":
            start = day_start_ms(now - 6 * 86400000)
            sel = [r for r in recs if r["t"] >= start]
        else:
            start = recs[0]["t"] if recs else now
            sel = list(recs)

        kpi = self._kpi(sel)
        today_sel = [r for r in recs if r["t"] >= today]
        tk = self._kpi(today_sel)
        kpi["today_tokens"] = tk["tokens"]
        kpi["today_credit"] = tk["credit"]
        kpi["today_calls"] = tk["calls"]
        kpi["all_tokens"] = self._kpi(recs)["tokens"]

        series = self._series(sel, start, now, range_key)
        speeds = self._speeds(recs, now, speed_min)
        models = self._models(sel)
        sess_rows = self._sessions(sel, sessions, ctx, now)
        recent = self._recent(sel, sessions)

        return {
            "generated_at": now,
            "range": range_key,
            "kpi": kpi,
            "series": series,
            "speeds": speeds,
            "models": models,
            "sessions": sess_rows,
            "recent": recent,
            "status": {
                "files": len(self.files),
                "records": len(self.records),
                "last_scan": self.last_scan,
                "sessions": len(sessions),
                "source": PROJECTS_DIR,
            },
        }

    @staticmethod
    def _kpi(rows):
        tin = sum(r["in"] for r in rows)
        tout = sum(r["out"] for r in rows)
        hit = sum(r["hit"] for r in rows)
        miss = sum(r["miss"] for r in rows)
        credit = sum(r["credit"] for r in rows)
        durs = [(r["dur"], r["out"]) for r in rows if r["dur"] and r["dur"] > 200]
        gen_ms = sum(d for d, _ in durs)
        gen_out = sum(o for _, o in durs)
        speeds = [o / (d / 1000.0) for d, o in durs if d and o]
        return {
            "tokens": tin + tout,
            "input": tin,
            "output": tout,
            "cache_hit": hit,
            "cache_miss": miss,
            "hit_rate": (hit / float(tin)) if tin else 0.0,
            "credit": round(credit, 2),
            "calls": len(rows),
            "avg_speed": (gen_out / (gen_ms / 1000.0)) if gen_ms else 0.0,
            "peak_speed": max(speeds) if speeds else 0.0,
            "gen_seconds": round(gen_ms / 1000.0, 1),
        }

    def _series(self, rows, start, now, range_key):
        buckets = []
        if range_key == "today":
            base = day_start_ms(now)
            idx = {}
            for h in range(24):
                b = {"label": "%02d:00" % h, "hit": 0, "miss": 0, "out": 0,
                     "credit": 0.0, "calls": 0, "t": base + h * 3600000}
                buckets.append(b)
                idx[b["t"]] = b
            for r in rows:
                key = hour_start_ms(r["t"])
                b = idx.get(key)
                if not b:
                    continue
                b["hit"] += r["hit"]
                b["miss"] += r["miss"]
                b["out"] += r["out"]
                b["credit"] += r["credit"]
                b["calls"] += 1
            return {"granularity": "hour", "buckets": buckets}

        # 按天
        if range_key == "7d":
            days = 7
            base = day_start_ms(now - (days - 1) * 86400000)
            count = days
        else:
            base = day_start_ms(start)
            span = int((day_start_ms(now) - base) / 86400000) + 1
            count = max(1, min(span, MAX_DAY_BUCKETS))
            base = day_start_ms(now) - (count - 1) * 86400000

        idx = {}
        for i in range(count):
            ts = base + i * 86400000
            lt = time.localtime(ts / 1000.0)
            b = {"label": "%d/%d" % (lt.tm_mon, lt.tm_mday), "hit": 0, "miss": 0,
                 "out": 0, "credit": 0.0, "calls": 0, "t": ts}
            buckets.append(b)
            idx[ts] = b
        for r in rows:
            key = day_start_ms(r["t"])
            b = idx.get(key)
            if not b:
                continue
            b["hit"] += r["hit"]
            b["miss"] += r["miss"]
            b["out"] += r["out"]
            b["credit"] += r["credit"]
            b["calls"] += 1
        return {"granularity": "day", "buckets": buckets}

    @staticmethod
    def _speeds(rows, now, minutes=60):
        """最近 N 分钟，按粒度分桶的生成速度（tokens/s）。"""
        minutes = max(5, int(minutes or 60))
        if minutes <= 60:
            bucket = 1
        elif minutes <= 360:
            bucket = 5
        else:
            bucket = 15

        n = max(1, minutes // bucket)
        span_ms = bucket * 60000
        start = now - n * span_ms

        out = []
        for i in range(n):
            out.append({"t": start + i * span_ms, "v": 0.0, "out": 0, "calls": 0, "_d": 0})

        for r in rows:
            if r["t"] < start or r["t"] > now:
                continue
            i = int((r["t"] - start) // span_ms)
            if 0 <= i < n:
                b = out[i]
                b["out"] += r["out"]
                b["calls"] += 1
                if r["dur"] and r["dur"] > 200:
                    b["_d"] += r["dur"]

        for b in out:
            b["v"] = round(b["out"] / (b["_d"] / 1000.0), 1) if b["_d"] else 0.0
            b.pop("_d", None)
        return out

    @staticmethod
    def _models(rows):
        agg = {}
        display = {}
        for r in rows:
            raw = r["model"] or "unknown"
            k = raw.lower()
            a = agg.get(k)
            if a is None:
                a = {"name": raw, "tokens": 0, "in": 0, "out": 0,
                     "calls": 0, "hit": 0, "credit": 0.0}
                agg[k] = a
                display[k] = {}
            display[k][raw] = display[k].get(raw, 0) + 1
            a["in"] += r["in"]
            a["out"] += r["out"]
            a["tokens"] += r["in"] + r["out"]
            a["calls"] += 1
            a["hit"] += r["hit"]
            a["credit"] += r["credit"]
        for k, a in agg.items():
            spellings = display.get(k) or {}
            if spellings:
                a["name"] = max(spellings.items(), key=lambda kv: kv[1])[0]
        items = sorted(agg.values(), key=lambda x: -x["tokens"])
        total = sum(i["tokens"] for i in items) or 1
        for i in items:
            i["share"] = i["tokens"] / float(total)
            i["credit"] = round(i["credit"], 2)
        return items

    def _sessions(self, rows, sessions, ctx, now):
        agg = {}
        for r in rows:
            sid = r["sid"] or "?"
            a = agg.get(sid)
            if a is None:
                a = {"id": sid, "tokens": 0, "in": 0, "out": 0, "hit": 0,
                     "credit": 0.0, "calls": 0, "first": r["t"], "last": r["t"],
                     "model": r["model"], "cwd": r["cwd"], "gen_ms": 0, "gen_out": 0}
                agg[sid] = a
            a["in"] += r["in"]
            a["out"] += r["out"]
            a["tokens"] += r["in"] + r["out"]
            a["hit"] += r["hit"]
            a["credit"] += r["credit"]
            a["calls"] += 1
            a["last"] = max(a["last"], r["t"])
            a["first"] = min(a["first"], r["t"])
            if r["dur"] and r["dur"] > 200:
                a["gen_ms"] += r["dur"]
                a["gen_out"] += r["out"]

        out = []
        for sid, a in agg.items():
            meta = sessions.get(sid) or {}
            cu = ctx.get(sid) or {}
            title = meta.get("title") or ""
            cwd = meta.get("cwd") or a["cwd"] or ""
            name = os.path.basename(cwd.rstrip("/")) if cwd else ""
            out.append({
                "id": sid,
                "title": title or (name or "未命名会话"),
                "cwd": cwd,
                "model": meta.get("model") or a["model"],
                "tokens": a["tokens"],
                "in": a["in"],
                "out": a["out"],
                "calls": a["calls"],
                "hit_rate": (a["hit"] / float(a["in"])) if a["in"] else 0.0,
                "credit": round(a["credit"], 2),
                "speed": (a["gen_out"] / (a["gen_ms"] / 1000.0)) if a["gen_ms"] else 0.0,
                "last": a["last"],
                "used": cu.get("used") or 0,
                "size": cu.get("size") or meta.get("ctx_window") or 0,
                "active": (now - a["last"]) < 5 * 60000,
            })
        out.sort(key=lambda x: -x["tokens"])
        return out[:14]

    @staticmethod
    def _recent(rows, sessions):
        out = []
        for r in reversed(rows[-24:]):
            speed = (r["out"] / (r["dur"] / 1000.0)) if r["dur"] and r["dur"] > 200 else 0.0
            meta = sessions.get(r["sid"]) or {}
            out.append({
                "t": r["t"],
                "model": r["model"],
                "in": r["in"],
                "out": r["out"],
                "hit": r["hit"],
                "miss": r["miss"],
                "credit": round(r["credit"], 3),
                "dur": r["dur"] or 0,
                "speed": round(speed, 1),
                "tool": r["tool"],
                "title": meta.get("title") or "",
            })
        return out


COLLECTOR = Collector()


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "WBTokenMonitor/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path

        if path == "/api/ping":
            return self._send(200, json.dumps({"ok": True, "ts": ms_now()}))
        if path == "/api/snapshot":
            q = parse_qs(u.query)
            rng = (q.get("range") or ["today"])[0]
            if rng not in ("today", "7d", "all"):
                rng = "today"
            try:
                span = int((q.get("span") or ["60"])[0])
            except (TypeError, ValueError):
                span = 60
            try:
                data = COLLECTOR.snapshot(rng, span)
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)}))
            return self._send(200, json.dumps(data, ensure_ascii=False))

        # 静态文件
        if path in ("/", ""):
            path = "/index.html"
        rel = path.lstrip("/")
        full = os.path.abspath(os.path.join(WEB_DIR, rel))
        if not full.startswith(WEB_DIR):
            return self._send(403, "forbidden", "text/plain; charset=utf-8")
        if not os.path.isfile(full):
            return self._send(404, "not found", "text/plain; charset=utf-8")
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
        }.get(os.path.splitext(full)[1], "application/octet-stream")
        with open(full, "rb") as f:
            body = f.read()
        return self._send(200, body, ctype)


def scanner_loop():
    while True:
        try:
            COLLECTOR.scan()
        except Exception:
            pass
        time.sleep(SCAN_INTERVAL)


def main():
    ap = argparse.ArgumentParser(description="WorkBuddy Token Monitor")
    ap.add_argument("--port", type=int, default=int(os.environ.get("WB_MONITOR_PORT") or 8791))
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    COLLECTOR.born()
    t = threading.Thread(target=scanner_loop, name="scanner")
    t.daemon = True
    t.start()

    port = args.port
    httpd = None
    for p in range(port, port + 12):
        try:
            httpd = ThreadingHTTPServer((args.host, p), Handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        sys.stderr.write("无法绑定端口 %d 及后续端口\n" % port)
        sys.exit(1)

    httpd.daemon_threads = True
    sys.stderr.write("WorkBuddy Token Monitor  http://%s:%d  (source: %s)\n"
                     % (args.host, port, PROJECTS_DIR))
    sys.stderr.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
