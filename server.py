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
CACHE_TTL_MS = 400           # 聚合结果缓存时长（毫秒）


# ---------------------------------------------------------------- 工具函数

def ms_now():
    return int(time.time() * 1000)


def day_start_ms(ts_ms):
    lt = time.localtime(ts_ms / 1000.0)
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)) * 1000)


def hour_start_ms(ts_ms):
    lt = time.localtime(ts_ms / 1000.0)
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, lt.tm_hour, 0, 0, 0, 0, -1)) * 1000)


def day_end_ms(ts_ms):
    lt = time.localtime(ts_ms / 1000.0)
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 23, 59, 59, 0, 0, -1)) * 1000) + 999


def parse_ts_ms(v, default=None):
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return int(v)
    v = str(v).strip()
    if not v:
        return default
    if v.isdigit():
        return int(v)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            st = time.strptime(v, fmt)
            return int(time.mktime(st) * 1000)
        except ValueError:
            pass
    return default


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
        self.version = 0          # 每新增一条记录自增
        self._cache = None
        self._cache_key = None
        self._cache_at = 0

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
                    self.version += 1

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
    def snapshot(self, range_key, speed_min=60, start_ms=None, end_ms=None, model=None):
        now = ms_now()
        start_ms = parse_ts_ms(start_ms)
        end_ms = parse_ts_ms(end_ms)
        if model:
            model = model.strip() or None

        today = day_start_ms(now)

        if range_key == "today":
            actual_start = today
            actual_end = now
        elif range_key == "yesterday":
            yesterday_0 = day_start_ms(now - 86400000)
            actual_start = yesterday_0
            actual_end = day_end_ms(yesterday_0)
        elif range_key == "7d":
            actual_start = day_start_ms(now - 6 * 86400000)
            actual_end = now
        elif range_key == "30d":
            actual_start = day_start_ms(now - 29 * 86400000)
            actual_end = now
        elif range_key == "custom":
            actual_start = start_ms if start_ms is not None else today
            actual_end = end_ms if end_ms is not None else now
            if actual_end < actual_start:
                actual_start, actual_end = actual_end, actual_start
        else:
            range_key = "all"
            actual_start = None
            actual_end = now

        ck = (self.version, range_key, actual_start, actual_end,
              model.lower() if model else None, speed_min)

        # 记录未变化时复用上次聚合结果，让高频轮询只付出扫描成本
        with self.lock:
            if self._cache_key == ck and (now - self._cache_at) < CACHE_TTL_MS:
                return self._cache
            recs = sorted(self.records, key=lambda r: r["t"])
            sessions = dict(self.sessions)
            ctx = dict(self.ctx_usage)

        if actual_start is None:
            actual_start = recs[0]["t"] if recs else now

        if range_key == "all":
            time_sel = list(recs)
        else:
            time_sel = [r for r in recs if actual_start <= r["t"] <= actual_end]

        # 模型全量统计（在选定时间范围内各模型的消耗与占比）
        all_models = self._models(time_sel)

        # 若指定了具体模型，则其余视图按该模型过滤
        if model:
            sel = [r for r in time_sel if (r["model"] or "").lower() == model.lower()]
            models = self._models(sel)
        else:
            sel = time_sel
            models = all_models

        kpi = self._kpi(sel)
        today_sel = [r for r in recs if r["t"] >= today]
        if model:
            today_sel = [r for r in today_sel if (r["model"] or "").lower() == model.lower()]
        tk = self._kpi(today_sel)
        kpi["today_tokens"] = tk["tokens"]
        kpi["today_credit"] = tk["credit"]
        kpi["today_calls"] = tk["calls"]

        all_sel = recs if not model else [r for r in recs if (r["model"] or "").lower() == model.lower()]
        ak = self._kpi(all_sel)
        kpi["all_tokens"] = ak["tokens"]
        kpi["all_credit"] = ak["credit"]

        # 当选定单一模型时，计算其内部 Token 与积分构成（缓存命中 / 未命中输入 / 生成输出）
        breakdown = None
        if model:
            tot_tok = max(1, kpi["tokens"])
            tot_crd = kpi["credit"]
            hit = kpi["cache_hit"]
            miss = kpi["cache_miss"]
            out = kpi["output"]
            denom = (hit * 0.1) + (miss * 1.0) + (out * 4.0)
            if denom > 0:
                hit_crd = round(tot_crd * (hit * 0.1) / denom, 2)
                miss_crd = round(tot_crd * (miss * 1.0) / denom, 2)
                out_crd = round(tot_crd - hit_crd - miss_crd, 2)
                if out_crd < 0:
                    out_crd = 0.0
            else:
                hit_crd = miss_crd = out_crd = 0.0

            breakdown = {
                "model": model,
                "tokens": kpi["tokens"],
                "credit": tot_crd,
                "token_parts": [
                    {"name": "缓存命中", "val": hit, "share": hit / float(tot_tok), "color": "#06b6d4"},
                    {"name": "未命中输入", "val": miss, "share": miss / float(tot_tok), "color": "#f59e0b"},
                    {"name": "生成输出", "val": out, "share": out / float(tot_tok), "color": "#7c3aed"},
                ],
                "credit_parts": [
                    {"name": "缓存命中", "val": hit_crd, "share": (hit_crd / tot_crd) if tot_crd > 0 else 0, "color": "#06b6d4"},
                    {"name": "未命中输入", "val": miss_crd, "share": (miss_crd / tot_crd) if tot_crd > 0 else 0, "color": "#f59e0b"},
                    {"name": "生成输出", "val": out_crd, "share": (out_crd / tot_crd) if tot_crd > 0 else 0, "color": "#7c3aed"},
                ],
            }

        series = self._series(sel, actual_start, actual_end, range_key)
        speeds = self._speeds(sel if model else recs, actual_end, speed_min)
        sess_rows = self._sessions(sel, sessions, ctx, now)
        recent = self._recent(sel, sessions)

        result = {
            "generated_at": now,
            "range": range_key,
            "start": actual_start,
            "end": actual_end,
            "selected_model": model,
            "kpi": kpi,
            "series": series,
            "speeds": speeds,
            "models": models,
            "all_models": all_models,
            "breakdown": breakdown,
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

        with self.lock:
            self._cache = result
            self._cache_key = ck
            self._cache_at = now
        return result

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

    def _series(self, rows, start, end, range_key):
        buckets = []
        span_ms = max(0, end - start)

        # 判断是否按小时分桶：单日、昨日、今日，或跨度不超过 40 小时
        if range_key in ("today", "yesterday") or (range_key == "custom" and span_ms <= 40 * 3600000):
            base = hour_start_ms(start)
            h_count = max(1, int((hour_start_ms(end) - base) / 3600000) + 1)
            h_count = min(h_count, 48)

            single_day = time.localtime(start / 1000.0).tm_yday == time.localtime(end / 1000.0).tm_yday

            idx = {}
            for h in range(h_count):
                ts = base + h * 3600000
                lt = time.localtime(ts / 1000.0)
                lbl = "%02d:00" % lt.tm_hour if single_day else "%d/%d %02d:00" % (lt.tm_mon, lt.tm_mday, lt.tm_hour)
                b = {"label": lbl, "hit": 0, "miss": 0, "out": 0,
                     "credit": 0.0, "calls": 0, "t": ts}
                buckets.append(b)
                idx[ts] = b
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

        # 按天分桶
        if range_key == "7d":
            days = 7
            base = day_start_ms(end - (days - 1) * 86400000)
            count = days
        elif range_key == "30d":
            days = 30
            base = day_start_ms(end - (days - 1) * 86400000)
            count = days
        else:
            base = day_start_ms(start)
            span = int((day_start_ms(end) - base) / 86400000) + 1
            count = max(1, min(span, MAX_DAY_BUCKETS))
            base = day_start_ms(end) - (count - 1) * 86400000

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
    def _speeds(rows, end_time, minutes=60):
        """指定时间前 N 分钟，按粒度分桶的生成速度（tokens/s）。"""
        minutes = max(5, int(minutes or 60))
        if minutes <= 60:
            bucket = 1
        elif minutes <= 360:
            bucket = 5
        else:
            bucket = 15

        n = max(1, minutes // bucket)
        span_ms = bucket * 60000
        start = end_time - n * span_ms

        out = []
        for i in range(n):
            out.append({"t": start + i * span_ms, "v": 0.0, "out": 0, "calls": 0, "_d": 0})

        for r in rows:
            if r["t"] < start or r["t"] > end_time:
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
                     "calls": 0, "hit": 0, "miss": 0, "credit": 0.0,
                     "gen_ms": 0, "gen_out": 0}
                agg[k] = a
                display[k] = {}
            display[k][raw] = display[k].get(raw, 0) + 1
            a["in"] += r["in"]
            a["out"] += r["out"]
            a["tokens"] += r["in"] + r["out"]
            a["calls"] += 1
            a["hit"] += r["hit"]
            a["miss"] += r["miss"]
            a["credit"] += r["credit"]
            if r["dur"] and r["dur"] > 200:
                a["gen_ms"] += r["dur"]
                a["gen_out"] += r["out"]
        for k, a in agg.items():
            spellings = display.get(k) or {}
            if spellings:
                a["name"] = max(spellings.items(), key=lambda kv: kv[1])[0]
        items = sorted(agg.values(), key=lambda x: -x["tokens"])
        total_tokens = sum(i["tokens"] for i in items) or 1
        total_credit = sum(i["credit"] for i in items) or 0.0
        for i in items:
            i["share"] = round(i["tokens"] / float(total_tokens), 4)
            i["credit"] = round(i["credit"], 2)
            i["credit_share"] = round((i["credit"] / total_credit), 4) if total_credit > 0 else 0.0
            i["hit_rate"] = round((i["hit"] / float(i["in"])), 4) if i["in"] else 0.0
            i["speed"] = round((i["gen_out"] / (i["gen_ms"] / 1000.0)), 1) if i["gen_ms"] else 0.0
            i.pop("gen_ms", None)
            i.pop("gen_out", None)
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
            if rng not in ("today", "yesterday", "7d", "30d", "all", "custom"):
                rng = "today"
            try:
                span = int((q.get("span") or ["60"])[0])
            except (TypeError, ValueError):
                span = 60
            start_val = (q.get("start") or [None])[0]
            end_val = (q.get("end") or [None])[0]
            model_val = (q.get("model") or [None])[0]
            try:
                data = COLLECTOR.snapshot(rng, speed_min=span, start_ms=start_val, end_ms=end_val, model=model_val)
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
