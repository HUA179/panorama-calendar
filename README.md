# 个人日历项目（个人全景日历 · ICS）

把国内调休、广西假期、国家纪念日、F1 赛历与战报，做成五类可在线订阅的
`.ics` 日历，由云端定时自动更新。

> **接手先读两份文件**：`AGENTS.md`（怎么干 + 硬约束）和
> `交接说明-进度与续接.md`（做到哪了 + 下一步）。

---

## 快速开始

```bash
python bootstrap.py
```

建虚拟环境、装依赖、跑测试、跑 lint、生成演示 ICS，一步到位。
最后一行显示 `RESULT: READY` 即可开工。要求 Python 3.12+。

不想装依赖只想验证：

```bash
python bootstrap.py --verify      # 复用已有环境
python bootstrap.py --offline     # 完全不联网
```

手动方式（等价）：

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"    # Windows
.venv/bin/python    -m pip install -e ".[dev]"     # macOS / Linux
.venv/Scripts/python -m pytest tests
```

## 五类订阅

| 订阅 | iOS 颜色 | 内容 |
|---|---|---|
| 全国假期 | 红 | 法定节假日 + 独立「调休上班」事件（前一晚 20:00 提醒） |
| 广西假期 | 绿 | 自治区级地方假期 |
| 国家纪念日 | — | 国家正式设立、有明确日期；非放假日，不提醒 |
| F1 赛历 | 黑 | 排位赛、冲刺排位赛、冲刺赛、正赛（不含练习赛） |
| F1 战报 | — | 赛后中文短摘要 + 发车顺位 + 最终排名 |

## 目录结构

```
├── bootstrap.py                  # 一键环境恢复 + 验证
├── AGENTS.md                     # 接手作业手册（代理必读）
├── README.md                     # 本文件
├── 交接说明-进度与续接.md         # 唯一状态源：进度、中断点、待办
├── 个人全景日历-技术设计方案.md    # 完整设计（架构/数据源/伪代码/边界）
├── pyproject.toml
├── src/panorama_calendar/
│   ├── data/                     # 人工转录的官方数据（假期、纪念日）
│   ├── models/                   # 统一事件模型、来源记录、枚举
│   ├── services/                 # 稳定 UID、语义修订、发布门禁
│   ├── ics/                      # 转义、字节折行、VALARM、组装、校验
│   ├── sources/                  # 数据源适配器与数据集校验
│   ├── pipelines/                # 官方数据 → 统一事件
│   ├── publishing.py             # 原子写出 + 字节校验
│   └── cli.py                    # Typer 命令
├── tests/                        # unit / property / integration
├── scripts/build_snapshot.py     # 重新打包（交付前必跑）
├── scripts/preflight_sources.py  # 云端数据源可达性探测
├── deploy/                       # Pages 部署物：_headers（钉 MIME）+ 入口页
├── .github/workflows/            # calendar.yml（发布）/ keepalive.yml（保活）
└── dist/                         # 生成物（ICS、state.json、压缩包）
```

## 常用命令

```bash
python -m pytest tests                              # 全部测试
python -m ruff check src tests                      # 静态检查
python -m panorama_calendar build --year 2026        # 生成三类静态订阅
python -m panorama_calendar f1-schedule --year 2026  # 从 F1 官方页面生成赛历
python -m panorama_calendar f1-report --year 2026    # 生成已完赛分站的战报
python -m panorama_calendar demo --in-days 1 --in-days 2 --output dist/valarm-ios-test.ics
python scripts/build_snapshot.py                    # 重新打包接手包
```

`demo` 生成的是 **iPhone 真机验证事件**：全天事件，日期用 `--in-days` 取相对今天的天数
（可重复，给多次听到提醒的机会），或用 `--workday` 指定固定日期。
预期在**前一晚 20:00** 弹出提醒（`TRIGGER;RELATED=START:-PT4H`）。

`bootstrap.py --verify` 的自检产物写到 `dist/valarm-selfcheck.ics`，固定 2026-12-15，
不会覆盖 `dist/valarm-ios-test.ics`。

`f1-report` 只处理**已经跑完**的分站（按赛道当地日期判断），未开赛的自动跳过；
成绩最终性由 FIA 文件决定（暂定 / 最终 / 改判）。战报是**全天事件、不带提醒**，
UID 与赛历完全独立。`dist/f1-reports-{year}.state.json` 保存上次发布的事件，
用于让 `SEQUENCE` 只在内容真的变化时递增——**不要手工删它**，否则改判会被当成新事件。

## 当前进度

里程碑 A（ICS 内核）、B（全国假期 / 广西 / 纪念日三类订阅）、C（F1 官方赛历 + 战报）、
D（云端自动更新闭环）均已完成，iPhone 真机 VALARM 验证已通过。
2026 赛季真实构建：赛历 23 站 / 58 个 Session，战报 19 个已完赛分站。
当前共 158 项测试全绿。

云端链路：GitHub Actions 每 6 小时构建 → Cloudflare Pages 发布 →
`calendar-state` 分支持久化修订状态（线上 ICS 作为 `SEQUENCE` 兜底下限）。
订阅地址形如 `https://panorama-calendar.pages.dev/f1-schedule-2026.ics`。
入口页：`https://panorama-calendar.pages.dev/`。内容未变时云端不会产生空提交。
部署与回滚步骤见 `交接说明-进度与续接.md` 第 7.5 节。
