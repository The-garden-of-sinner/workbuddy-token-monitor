# WorkBuddy Usage Monitor for Linux

[简体中文](README.md) | English

![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20x86__64%20%2F%20ARM64-0f172a?logo=linux&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.8%2B-3776ab?logo=python&logoColor=white)
![PyQt5](https://img.shields.io/badge/PyQt5-5.14-41cd52)
![Release](https://img.shields.io/github/v/release/The-garden-of-sinner/workbuddy-token-monitor?color=6366f1&label=release)
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
- **Per-model usage & credit tracking** — breakdown token and credit shares with one-click toggling between tokens and credits; filter by single model across all charts; adaptive single-model view displays cache hits, misses, and outputs, with estimated unit prices (`cents/M tokens`) and overall weighted rate
- **Model usage leaderboard** — dual-tab table switching between session ranking and model-level breakdown (total tokens, prompt/completion split, cache hit rate, calls, speed, credits and credit share)
- **Flexible time queries & custom ranges** — quick presets for Today, Yesterday, Last 7 days, Last 30 days, All, plus a custom date range picker; automatic hourly (≤40h) and daily (>40h) bucket sizing
- **Incremental parsing** — reads only newly appended bytes, at whatever pace the refresh interval sets; tens of thousands of calls stay smooth
- **Four UI scale presets** — small / standard / large / extra large, DPI-aware and remembered
- **Switchable throughput window** — 15 min / 1 h / 6 h / 24 h, with automatic bucket sizing
- **Adjustable refresh interval** — 0.1 s (turbo) / 0.3 / 0.8 / 1.6 / 3 s; the fast presets go through a snapshot cache and still cost milliseconds
- **Floating mini window** — collapse to an always-on-top card with just the key numbers; drag it anywhere, double-click to restore
- **Snapshot export** — one command produces a self-contained HTML file you can share

## Install

### Option 1: .deb package (recommended)

Grab the latest `workbuddy-token-monitor_<version>_all.deb` from
[Releases](https://github.com/The-garden-of-sinner/workbuddy-token-monitor/releases):

```bash
sudo dpkg -i workbuddy-token-monitor_1.0.0_all.deb
sudo apt -f install          # if dependencies are missing
```

Launch it from the application menu, or run `workbuddy-token-monitor` in a terminal.
Uninstall with `sudo apt remove workbuddy-token-monitor`.

### Option 2: run from source

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
| Five KPI cards | Total tokens, cache hit rate, average generation speed, credits, call count (linked to model and time filters) |
| Throughput | tokens/s curve over 15 min – 24 h (switchable top-right), with a large 5-minute weighted average |
| Model breakdown / composition | Model share by token or credit (switchable); when a single model is selected, shows internal hit/miss/output shares, component price estimates (cents/M tokens), and average price |
| Token volume | Hourly / daily stacked bars: cache hits, misses, output (auto-bucketed by selected duration) |
| Cache hit rate | Per-bucket hit-rate line with an 80% reference |
| Sessions & models | Dual tabs: switch between "Session ranking" and "Model breakdown & credits" |
| Live calls | The latest 6 calls with input/output, measured speed and credits |
| Mini window | The "悬浮" button collapses everything into a 326×158 always-on-top card: the latest call's speed, today's tokens, a mini throughput curve, hit rate and credits |

Use the top bar to switch between **Today / Yesterday / Last 7 days / Last 30 days / All / Custom ▾**, or filter by **Model: All ▾**. Charts show details on hover.

<img src="screenshot-mini.png" width="374" alt="Mini window">

The mini window stays on top and can be dragged anywhere. Double-click it (or hit the arrow) to
restore the full panel; `×` quits.

The "刷新" menu switches the refresh interval. At 0.1 s, collection scans for new bytes every
100 ms (~1.7 ms), aggregation hits the snapshot cache (~0.04 ms), and repaints are throttled to
once per 200 ms — roughly 2% CPU.
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
├── build_deb.sh        Builds the .deb package
├── CHANGELOG.md        Release notes
├── screenshot.png      Dashboard screenshot (demo data)
├── screenshot-mini.png Mini window screenshot
├── README.md           简体中文
└── LICENSE             MIT
```

## Customisation

```bash
WB_MONITOR_PORT=9000 ./run.sh --web            # different port
WB_HOME=/path/to/.workbuddy ./run.sh           # different data directory
python3 qt_app.py --demo                       # open with demo data
python3 qt_app.py --model DeepSeek-V4.1-Flash  # launch with a model filter
python3 qt_app.py --range 7d                   # launch with a time range (today/yesterday/7d/30d/all/custom)
python3 qt_app.py --shot out.png --range all   # offscreen render
```

UI preferences live in `.runtime/ui.json` (scale and refresh interval). Delete it to reset.

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

## Versioning

See [CHANGELOG.md](CHANGELOG.md) for the current version. Release flow:

```bash
./build_deb.sh 1.0.1        # build
git tag v1.0.1 && git push origin v1.0.1
./release.sh 1.0.1          # create the release and upload the .deb
```

`release.sh` reads the GitHub token from `~/.config/github/token` (or `GH_TOKEN`).
Run `./setup_token.sh` once to store it interactively — the token is never echoed
and never lands in your shell history.

## License

[MIT](LICENSE)
