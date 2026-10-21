# WorkBuddy 用量监视

一个本地运行的 WorkBuddy 用量面板：实时查看 **Token 消耗、生成吞吐、缓存命中率**，
附带积分统计与会话排行。数据全程只读留在本机，不联网、不上传。

![Python](https://img.shields.io/badge/Python-3.8%2B-3776ab?logo=python&logoColor=white)
![PyQt5](https://img.shields.io/badge/PyQt5-5.14-41cd52)
![License](https://img.shields.io/badge/License-MIT-0f172a)

![面板截图](screenshot.png)

## 特性

- **零第三方依赖**（除 PyQt5）：数据采集与聚合只用 Python 标准库
- **不依赖浏览器内核**：面板用 PyQt5 + QPainter 手绘，Chromium 起不来的机器也能正常显示
- **增量解析**：每 1.2 秒只读会话文件新增的字节，万级记录也不卡
- **两套界面共用一层聚合**：原生窗口与可选 Web 面板的数据口径完全一致
- **可导出快照**：一条命令生成单文件 HTML，发给别人不用装环境

## 快速开始

```bash
git clone <repo-url> && cd token-monitor

./run.sh                  # 打开原生桌面窗口
./install.sh              # 安装桌面快捷方式 + 应用菜单项
```

其他命令：

```bash
./run.sh --web            # 可选：本地服务 + 浏览器（http://127.0.0.1:8791）
./stop.sh                 # 停止 --web 模式的后台服务
./install.sh --uninstall  # 卸载桌面入口

python3 export_preview.py demo.html --demo   # 导出一份演示快照
python3 qt_app.py --demo                     # 用演示数据打开面板
```

依赖：Python 3.8+、PyQt5（Debian/Ubuntu 系 `apt install python3-pyqt5`）。
缺少 PyQt5 时启动器会自动退回 `--web` 模式。

## 界面

| 区域 | 说明 |
| --- | --- |
| 五张 KPI 卡 | 总 Token、缓存命中率、平均生成速度、积分消耗、调用次数 |
| 生成吞吐 | 近 60 分钟每分钟的 tokens/s 曲线，大字显示最近 5 分钟实时速度 |
| 模型分布 | 按模型拆分 token 占比（大小写不同的同名模型自动合并） |
| Token 用量 | 按小时 / 按天堆叠柱：缓存命中、未命中、输出 |
| 缓存命中率 | 按时间桶的命中率折线，80% 参考线 |
| 会话排行 | 各会话的 token、调用数、命中率、速度、积分、上下文占用 |
| 实时调用流 | 最新 6 次调用，含输入/输出、实测速度与积分 |

顶部可切换「今日 / 近 7 天 / 全部」，图表支持鼠标悬停查看明细。

## 数据来源

全部只读，不修改任何 WorkBuddy 文件：

| 路径 | 内容 |
| --- | --- |
| `~/.workbuddy/projects/**/*.jsonl` | 每次模型调用的 `providerData.rawUsage`：`prompt_tokens`、`completion_tokens`、`prompt_cache_hit_tokens`、`credit`，以及毫秒时间戳 |
| `~/.workbuddy/workbuddy.db` | `sessions`（会话标题、模型、上下文窗口）、`session_usage`（当前上下文占用） |

两者都用只读方式打开；数据库不可用时自动降级，只显示 jsonl 里的信息。

### 指标口径

- **Token 总量** = 输入 tokens + 输出 tokens。输入已包含缓存命中的部分。
- **缓存命中率** = 缓存命中 tokens ÷ 输入 tokens。WorkBuddy 的 `prompt_tokens`
  是完整上下文长度，因此该比例反映"上下文中有多少可直接复用"。
- **生成速度** = 输出 tokens ÷ 单次生成耗时。耗时以"上一条工具结果 / 用户消息"
  到"本轮调用产出"为区间，包含首 token 延迟，因此短请求数值会偏低；
  KPI 的平均值按耗时加权，不是简单平均。
- **积分** = 记录中 `rawUsage.credit` 的累加，仅统计本地有记录的部分。

## 文件结构

```
token-monitor/
├── qt_app.py           桌面面板（PyQt5，QPainter 手绘图表）
├── server.py           数据采集与聚合（标准库）+ 可选 HTTP 服务
├── demo_data.py        演示数据（截图与文档示例使用，不读磁盘）
├── web/                Web 面板（原生 Canvas，无 CDN）
│   ├── index.html
│   ├── style.css
│   └── app.js
├── run.sh              启动器（默认原生窗口，--web 走浏览器）
├── stop.sh             停止 --web 模式的后台服务
├── install.sh          安装 / 卸载桌面入口
├── export_preview.py   导出单文件静态快照
├── preview.html        演示快照（可直接用浏览器打开）
├── make_icon.py        重新生成图标
├── screenshot.png      面板截图（演示数据）
└── LICENSE             MIT
```

## 自定义

```bash
WB_MONITOR_PORT=9000 ./run.sh --web            # 换端口
WB_HOME=/path/to/.workbuddy ./run.sh           # 指向其他数据目录
python3 qt_app.py --shot out.png --range all   # 离屏渲染截图
```

## 为什么不用 Web 技术做窗口

在部分国产平台（如兆芯 + 麒麟）上，Chromium / Firefox / Electron 启动即崩溃，
`chrome --app` 这类方案直接失效。Qt 是原生 C++ 绘制，兼容性更好；
同时面板仍保留了 Web 实现，浏览器可用的机器上体验一致。

## 许可证

[MIT](LICENSE)
