# iPhone 快捷指令

> ℹ️ **这是旧采集方案**。主推方案是 health-sync 仓库（iPhone 导出 App → GitHub 私有仓库 → `git pull`），
> 字段更全、数据更干净，见主 README 的「数据来源」。本方案仍可用，适合不想装额外 App 的场景。

## 文件

| 文件 | 说明 |
|---|---|
| `Health Export.shortcut` | 导入到 iPhone 即可使用 |

## 导入

**方式一（用仓库里的文件）**：把 `Health Export.shortcut` AirDrop 到 iPhone，点击并确认导入。

**方式二（iCloud 链接）**：用 iPhone 打开——

`https://www.icloud.com/shortcuts/f7ad8c2d7baa42f88d08a30cf1c7e391`

两种方式都**必须用 Safari 打开**，微信 / QQ 的内置浏览器打不开。

## 必做设置

**设置 → 快捷指令 → 高级 → 允许共享大量数据**（打开）

不开这一项，运行时直接报 `XPC error`。

## 挂上自动运行

快捷指令 App → 自动化 → 新建 → **特定时间** → 每天 **22:00** → 关闭「运行前询问」。

时间要固定：步数、能量这类累计值随一天推移不断增长，只有固定时点采集，跨天的数据才可比。

## 采集字段

见仓库根目录 README 的「采集字段」表。

## 可选：加上运动记录

默认的快捷指令不采集运动明细（只知道当天锻炼了多少分钟，不知道是跑步还是游泳）。
加上之后，仪表盘会多一张「运动记录」图，AI 也能回答「这周练了几次」。

做法是在导出的 JSON 顶层补一个 `workouts` 数组：

```json
"workouts": [
  {"type":"跑步","start":"18:32","end":"19:05","duration_min":33.2,"calories":320.5,"distance_km":5.12}
]
```

| 键 | 必需 | 说明 |
|---|---|---|
| `type` | ✅ | 运动类型，中英文都行 |
| `start` / `end` | 建议 | `HH:mm`，没有就省略 |
| `duration_min` | ✅ | 时长（分钟） |
| `calories` | 建议 | 活动能量 kcal |
| `distance_km` | 可选 | 距离 km |
| `avg_hr` | 可选 | 平均心率 bpm |

拼装方式：新增「查找体能训练」→「重复（对每个项目）」里拼单条 JSON →「结合文本」（分隔符 `,`）→ 套上 `[ ]`。

> 你现有的 JSON 里 `sleep` 就是一个用「重复」拼出来的数组，**照抄那段改键名最省事**。

几个注意点：

- 引号用英文半角，最后一条后面不要留逗号
- 日期用「格式化日期」动作，格式填 `HH:mm`（24 小时制）
- 「时长」在部分 iOS 版本给的是**秒**，需要 `÷ 60`。跑一次看数值，几十倍就是秒
- 没有运动的日子输出 `"workouts": []` 即可

字段名有容错：`workout_type` 会被当成 `type`，数字写成字符串也会被转换。

## 出处

本快捷指令在开源项目 [OpenClaw with Apple](https://github.com/rtjowo/Openclaw-With-Apple)（MIT）的
`Health Daily Export` 基础上改造，补齐了 HRV / 静息心率 / 锻炼分钟数 / 静息能量四个字段。
