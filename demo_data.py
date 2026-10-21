#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""演示数据：生成一份完全虚构的用量记录，用于截图与文档示例。

不读取任何本地文件，也不接触真实会话。同一随机种子下结果稳定。
"""

import random
import time

import server

# (标题, 工作目录, 模型)
SESSIONS = [
    ("重构日志采集模块", "~/WorkBuddy/log-pipeline", "DeepSeek-V4.1-Flash"),
    ("为 REST API 增加分页与限流", "~/WorkBuddy/api-service", "DeepSeek-V4.1-Flash"),
    ("排查 CI 构建超时", "~/WorkBuddy/ci-tools", "Claude-4.5-Sonnet"),
    ("补充缓存层单元测试", "~/WorkBuddy/api-service", "Claude-4.5-Sonnet"),
    ("整理组件库文档", "~/WorkBuddy/ui-kit", "Step-5-Preview"),
    ("优化订单查询慢 SQL", "~/WorkBuddy/order-center", "DeepSeek-V4.1-Flash"),
]

TOOLS = ["Bash", "Read", "Edit", "Write", "Grep", "Glob", "TaskCreate"]


def _weighted_model(rnd):
    r = rnd.random()
    if r < 0.62:
        return SESSIONS[0][2]
    if r < 0.85:
        return SESSIONS[2][2]
    return SESSIONS[4][2]


def collector():
    """构造一个带演示记录的 Collector（复用其聚合逻辑）。"""
    rnd = random.Random(20261021)
    now = int(time.time() * 1000)
    today0 = server.day_start_ms(now)

    sessions = {}
    ctx = {}
    for i, (title, cwd, model) in enumerate(SESSIONS):
        sid = "demo-%02d" % (i + 1)
        sessions[sid] = {
            "title": title,
            "model": model,
            "ctx_window": 1000000,
            "cwd": cwd,
            "updated": now,
        }
        ctx[sid] = {"used": rnd.randint(58000, 462000), "size": 1000000}

    records = []
    step = dict((k, 0) for k in sessions)

    # 最近 7 天（含今天）：每小时 1~4 次调用
    for d in range(6, -1, -1):
        day0 = today0 - d * 86400000
        for hour in range(8, 21):
            if d == 0 and day0 + hour * 3600000 > now:
                break
            if d > 0 and hour > 19:
                continue
            # 中午与傍晚更活跃
            base = {8: 3, 9: 6, 10: 4, 11: 6, 12: 2, 13: 4, 14: 6,
                    15: 4, 16: 7, 17: 6, 18: 4, 19: 3, 20: 2}.get(hour, 4)
            cnt = max(2, base + rnd.choice([-1, 0, 1, 2]))
            for _ in range(cnt):
                sid = rnd.choice(list(sessions.keys()))
                meta = sessions[sid]
                step[sid] += 1
                inp = rnd.randint(28000, 112000) + step[sid] * 3000
                hit = int(inp * rnd.uniform(0.92, 0.995))
                out = max(140, min(4200, int(rnd.gauss(880, 520))))
                dur = int(out / rnd.uniform(85, 235) * 1000 + rnd.uniform(700, 3400))
                ts = day0 + hour * 3600000 + rnd.randint(0, 3500000)
                if ts > now:
                    ts = now - rnd.randint(60000, 3000000)
                records.append({
                    "id": "demo-%s-%d" % (sid, step[sid]),
                    "t": int(ts),
                    "sid": sid,
                    "cwd": meta["cwd"],
                    "model": meta["model"],
                    "in": int(inp),
                    "out": int(out),
                    "hit": int(hit),
                    "miss": int(inp - hit),
                    "reason": int(out * 0.35),
                    "credit": round(out / 10000.0 * 0.62 + 0.01, 3),
                    "dur": int(dur),
                    "tool": rnd.choice(TOOLS),
                })

    records.sort(key=lambda r: r["t"])
    # 让最近一次调用落在 1 分钟内，实时速度才有读数
    if records:
        last = records[-1]
        last["t"] = now - 52000
        last["dur"] = 3200
        records.sort(key=lambda r: r["t"])

    c = server.Collector()
    c.records = records
    c.rids = set(r["id"] for r in records)
    c.sessions = sessions
    c.ctx_usage = ctx
    c.files = dict(("demo/%02d.jsonl" % i, None) for i in range(len(SESSIONS)))
    c.last_scan = now
    return c


def snapshot(range_key="today"):
    c = collector()
    data = c.snapshot(range_key)
    data["status"]["source"] = "~/.workbuddy/projects（演示数据）"
    return data


class DemoSource(object):
    """与 Collector 同接口，但只返回固定的演示数据，不读磁盘。"""

    def __init__(self):
        self._c = collector()

    def scan(self):
        pass

    def snapshot(self, range_key):
        data = self._c.snapshot(range_key)
        data["status"]["source"] = "~/.workbuddy/projects（演示数据）"
        return data


if __name__ == "__main__":
    import json
    print(json.dumps(snapshot("today")["kpi"], ensure_ascii=False, indent=2))
