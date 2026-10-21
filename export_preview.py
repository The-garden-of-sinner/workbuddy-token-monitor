#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把当前用量数据导出为单文件静态面板（preview.html），便于分享或存档。"""

import base64
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")

sys.path.insert(0, BASE_DIR)
import server  # noqa: E402


def main():
    positional = [a for a in sys.argv[1:] if not a.startswith("-")]
    out = positional[0] if positional else os.path.join(BASE_DIR, "preview.html")

    if "--demo" in sys.argv:
        import demo_data
        collector = demo_data.DemoSource()
    else:
        collector = server.Collector()
        collector.born()
    snap = collector.snapshot("all")

    def read(name):
        with open(os.path.join(WEB_DIR, name), "r", encoding="utf-8") as f:
            return f.read()

    html = read("index.html")
    css = read("style.css")
    js = read("app.js")

    icon = os.path.join(WEB_DIR, "icon.png")
    if os.path.exists(icon):
        with open(icon, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        html = html.replace('href="icon.png"', 'href="data:image/png;base64,%s"' % b64)

    html = html.replace('<link rel="stylesheet" href="style.css">',
                        "<style>\n%s\n</style>" % css)

    data = json.dumps(snap, ensure_ascii=False).replace("</", "<\\/")
    inject = ('<script>window.__WB_SNAPSHOT__ = %s;</script>\n<script>\n%s\n</script>'
              % (data, js))
    html = html.replace('<script src="app.js"></script>', inject)

    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("已生成快照：%s（%.1f KB，%d 条调用记录）"
          % (out, os.path.getsize(out) / 1024.0, snap["status"]["records"]))


if __name__ == "__main__":
    main()
