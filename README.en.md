# WorkBuddy Usage Monitor for Linux

[简体中文](README.md) | English

![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20x86__64%20%2F%20ARM64-0f172a?logo=linux&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.8%2B-3776ab?logo=python&logoColor=white)
![PyQt5](https://img.shields.io/badge/PyQt5-5.14-41cd52)
![License](https://img.shields.io/badge/License-MIT-0f172a)

> **Platform**: Linux desktop (x86_64 / ARM64). Verified on Kylin, UOS and Zhaoxin-based machines.
> No Chromium or Electron required — the dashboard still runs where the browser engine refuses to start.

A local dashboard for WorkBuddy: token consumption, generation throughput and cache hit rate,
plus credit usage and a per-session breakdown. Everything is read-only, stays on your machine,
and never leaves it.

![Dashboard](screenshot.png)

## Features

- **Linux native** — PyQt5 with hand-drawn QPainter charts, no browser engine involved
- **No third-party dependencies** besides PyQt5 — collection and aggregation use only the standard library
- **Two frontends** — a native window (default) and a web panel (`--web`), sharing one aggregation layer
- **Incremental parsing** — reads only newly appended bytes every 1.2 s; tens of thousands of calls stay smooth
- **Four UI scale presets** — small / standard / large / extra large, DPI-aware and remembered
- **Switchable throughput window** — 15 min / 1 h / 6 h / 24 h, with automatic bucket sizing
- **Snapshot export** — one command produces a self-contained HTML file you can share

## Install

Requires Python 3.8+ and PyQt5:

```bash
# Debian / Ubuntu / Kylin / UOS
sudo apt install python3 python3-pyqt5

# Arch / Manjaro
sudo pacman -S python python-pyqt5
```

```bash
git clone git@github.com:The-garden-of-sinner/workbuddy-token-monitor.git
cd workbuddy-token-monitor

./run.sh          # open the native window
./install.sh      # add a desktop shortcut and menu entry
```

If PyQt5 is missing, the launcher falls back to `--web` instead of failing.

## Usage

| Command | What it does |
| --- | --- |
| `./run.sh` | Open the native desktop window (default) |
| `./run.sh --web` | Start the local server and open `http://127.0.0.1:8791` |
| `./stop.sh` | Stop the background server started by `--web` |
| `./install.sh` | Install desktop shortcut and menu entry |
| `./install.sh --uninstall` | Remove desktop entries |

## What's on screen

| Area | Description |
| --- | --- |
| Five KPI cards | Total tokens, cache hit rate, average generation speed, credits, call count |
| Throughput | tokens/s curve over 15 min – 24 h (switchable top-right), with a large live reading for the last 5 minutes |
| Model breakdown | Token share per model; spelling variants of the same model are merged |
| Token volume | Hourly / daily stacked bars: cache hits, misses, output |
| Cache hit rate | Per-bucket hit-rate line with an 80% reference |
| Sessions | Tokens, calls, hit rate, speed, credits and context usage per session |
| Live calls | The latest 6 calls with input/output, measured speed and credits |

Use the top bar to switch between **Today / Last 7 days / All**. Charts show details on hover.
The scale presets and throughput window are native-window features; the web panel is fixed to
the last 60 minutes and follows browser zoom.

## Where the data comes from

Everything is read-only — no WorkBuddy file is ever modified:

| Path | Content |
| --- | --- |
| `~/.workbuddy/projects/**/*.jsonl` | `providerData.rawUsage` for every model call: `prompt_tokens`, `completion_tokens`, `prompt_cache_hit_tokens`, `credit`, plus a millisecond timestamp |
| `~/.workbuddy/workbuddy.db` | `sessions` (title, model, context window) and `session_usage` (current context usage) |

Both are opened read-only. If the database is unavailable the dashboard degrades gracefully
and shows what the JSONL files alone can provide.

### How the numbers are calculated

- **Total tokens** = input + output. Input already includes the cached portion.
- **Cache hit rate** = cached tokens ÷ input tokens. WorkBuddy reports `prompt_tokens` as the
  full context length, so this ratio tells you how much of the context was reused as-is.
- **Generation speed** = output tokens ÷ time spent generating. The interval runs from the
  previous tool result (or user message) to this call's output, so it includes time-to-first-token;
  short replies therefore read low. The KPI average is weighted by duration, not a plain mean.
- **Credits** = sum of `rawUsage.credit`, covering only what exists in local records.

## Why the desktop window doesn't embed a browser engine

The project **does ship a web UI** (the `web/` directory, plain Canvas). It is simply an
alternative way to look at the same data. The desktop window is drawn with Qt instead, because:

- On platforms like Zhaoxin, Chromium / Firefox / Electron crash on startup (SIGTRAP), which
  rules out `chrome --app`-style wrappers entirely;
- These are exactly the environments where domestic hardware and OS replacements are deployed —
  a tool that won't open may as well not exist;
- Qt paints natively, with no GPU or browser sandbox to depend on.

The trade-off is hand-written charts (`QPainter`), so both frontends share the aggregation
results from `server.py` and therefore report identical numbers.

## Project layout

```
workbuddy-token-monitor/
├── qt_app.py           Desktop dashboard (PyQt5, hand-drawn charts)
├── server.py           Collection and aggregation (stdlib) + optional HTTP server
├── demo_data.py        Demo data for screenshots and docs (never reads disk)
├── web/                Web dashboard (plain Canvas, no CDN)
│   ├── index.html
│   ├── style.css
│   └── app.js
├── run.sh              Launcher (native window by default, --web for the browser)
├── stop.sh             Stops the background server
├── install.sh          Installs / removes desktop entries
├── export_preview.py   Exports a single-file snapshot
├── preview.html        Demo snapshot (open directly in a browser)
├── make_icon.py        Regenerates the icon
├── screenshot.png      Dashboard screenshot (demo data)
├── README.md           简体中文
└── LICENSE             MIT
```

## Customisation

```bash
WB_MONITOR_PORT=9000 ./run.sh --web            # different port
WB_HOME=/path/to/.workbuddy ./run.sh           # different data directory
python3 qt_app.py --demo                       # open with demo data
python3 qt_app.py --shot out.png --range all   # offscreen render
```

UI preferences live in `.runtime/ui.json` (currently just the scale). Delete it to reset.

## FAQ

**Text too small or too large?** Use the "字号" button in the top bar — four presets, remembered
across launches. The UI follows the system DPI by default (1.5× on a 144 dpi display); pick
"大" or "特大" if that is still not enough.

**Double-clicking the icon does nothing?** Make sure the `.desktop` file is executable
(`install.sh` handles this). Some desktop environments also require right-click → "Allow launching"
the first time. Errors are logged to `.runtime/qt.log`.

**PyQt5 is missing?** The launcher falls back to `--web` automatically, or install
`python3-pyqt5` and retry.

**The dashboard is empty?** Check that `~/.workbuddy/projects` contains `.jsonl` session files
and that the current user can read them.

**Does it use much memory?** The process exits when the window closes. Only `--web` stays
resident in the background (~30 MB).

## Development

```bash
python3 qt_app.py --demo                      # demo data, never touches real records
python3 qt_app.py --shot out.png --range all  # offscreen render
python3 export_preview.py demo.html --demo    # single-file snapshot
```

Demo data lives in `demo_data.py`: session names and numbers are entirely fictional and are used
only for screenshots and documentation.

## License

[MIT](LICENSE)
