# healthpipe

> 把 Apple Health 的导出数据变成本地可分析的时序数据，并生成一张单文件可视化仪表盘。
> 全程 0 元，数据不出本机。

替代那些「要么付费、要么把健康数据上传到别人服务器」的导出 App。核心是一个**容错解析器**——
iPhone 快捷指令拼出来的 JSON 几乎一定是坏的，而现有工具都假设它是合法的。

---

## 特性

- **容错解析** —— 自动修复快捷指令导出的三类固定语法错误，坏文件不会中断整条链路
- **多源合并** —— 快捷指令导出 + 第三方 App 导出，同一日期自动去重合并
- **数据质量守门** —— 自动标注「疑似未佩戴手表」「步数异常」等日子，只标注不删数据
- **单文件仪表盘** —— 图表库内联，产物是一张可离线打开、可直接发出去的 HTML
- **一键脱敏** —— 生成公开版本时按比例缩放真实值，保留趋势形态

---

## 快速开始

```bash
git clone https://github.com/<用户名>/apple-health-pipeline.git
cd apple-health-pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp config.example.toml config.toml
```

打开 `config.toml`，把 `shortcut_dir` 指向你的快捷指令导出目录，然后：

```bash
healthpipe sync
healthpipe dashboard
```

用浏览器打开 `output/health-dashboard.html`。

> iPhone 端的快捷指令配置步骤见 [`shortcuts/README.md`](shortcuts/README.md)。

---

## 命令

| 命令 | 作用 |
|---|---|
| `healthpipe doctor` | 体检：路径是否可达、文件是否损坏、数据质量如何 |
| `healthpipe sync` | 解析所有导出文件，合并成统一时序 → `output/series.json` |
| `healthpipe dashboard` | 生成单文件 HTML 仪表盘 |
| `healthpipe report --days 30` | 生成 Markdown 汇总表 |

---

## 仪表盘包含

| 图表 | 说明 |
|---|---|
| KPI 卡片 ×6 | 睡眠时长、HRV、静息心率、步数、活动消耗、运动时间，并与区间均值对比 |
| 睡眠结构 | 深睡 / 核心 / REM / 清醒的每日堆叠 |
| 每日步数 | 带均值虚线，离群日自动变色 |
| 心率趋势 | 日均 / 日最高 / 静息 三条线 |
| 活动消耗 | 主动运动产生的热量 |
| 心率曲线 | 全天逐点心率，标出最低 / 最高 |
| 睡眠分期时间轴 | 每段睡眠按分期画在对应行上 |

<!-- 📷 截图占位：仪表盘全貌 -->
> *（此处放仪表盘整页截图）*

---

## 数据来源

项目支持两个来源，也可只用其中一个：

| 来源 | 字段完整度 | 说明 |
|---|---|---|
| **iPhone 快捷指令** | 完整 | 含 HRV、静息心率等 HealthKit 原生指标 |
| 第三方 App 导出（如 HealthExport） | 较少 | 通常缺 HRV，但可以提供历史存量数据 |

两者按日期合并，**快捷指令的数据优先**。

### 采集字段

| 字段 | 含义 | 统计方式 | 单位 |
|---|---|---|---|
| `steps` | 步数 | 求和 | 步 |
| `distance_km` | 步行 + 跑步距离 | 求和 | km |
| `active_energy_kcal` | 活动能量 | 求和 | kcal |
| `exercise_min` | 锻炼分钟数 | 求和 | min |
| `basal_energy_kcal` | 静息（基础）能量 | 求和 | kcal |
| `hrv_ms` | 心率变异性（HealthKit 原生 SDNN） | 平均 | ms |
| `resting_hr` | 静息心率（HealthKit 原生） | 平均 | bpm |
| `heart_rate` | 全天逐条心率 | 逐条 | bpm |
| `sleep` | 睡眠分期分段 | 逐段 | — |

> 累计型指标（步数、能量、距离）随一天推移不断增长，**必须每天固定同一时间点采集**，跨天的数据才可比。

---

## 项目结构

```
src/healthpipe/
├── repair.py      ★ 容错解析器（本项目的核心）
├── sources.py     数据源适配与合并
├── metrics.py     派生指标、质量守门、脱敏
├── report.py      Markdown 汇总
├── dashboard.py   单文件 HTML 生成
├── config.py      配置加载
└── cli.py         命令行入口
```

---

## 常见问题

**运行报 `XPC error`** → 去 iPhone「设置 → 快捷指令 → 高级」，打开「允许共享大量数据」。

**找不到导出文件** → 检查 `config.toml` 的 `shortcut_dir`。路径里如果带前导空格（例如 ` tmp`），空格要原样写上。

**某天没有数据** → iOS 锁屏时会限制健康数据访问，自动化运行时手机锁着可能取不到。连续观察几天。

**想发到公开场合** → 把 `config.toml` 里 `[privacy] anonymize` 设为 `true`，会按比例缩放真实数值。

---

## License

MIT
