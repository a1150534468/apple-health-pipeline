# iPhone 快捷指令

## 文件

| 文件 | 说明 |
|---|---|
| `Health Export.shortcut` | 导入到 iPhone 即可使用 |

> ⚠️ **待补**：该文件需要从 iPhone 导出——快捷指令 App → 长按「Health Export」→ 分享 → 存储到文件。

## 导入

也可以直接用 iCloud 链接导入：

`https://www.icloud.com/shortcuts/f7ad8c2d7baa42f88d08a30cf1c7e391`

**必须用 Safari 打开**，微信 / QQ 的内置浏览器打不开。

## 必做设置

**设置 → 快捷指令 → 高级 → 允许共享大量数据**（打开）

不开这一项，运行时直接报 `XPC error`。

## 挂上自动运行

快捷指令 App → 自动化 → 新建 → **特定时间** → 每天 **22:00** → 关闭「运行前询问」。

时间要固定：步数、能量这类累计值随一天推移不断增长，只有固定时点采集，跨天的数据才可比。

## 采集字段

见仓库根目录 README 的「采集字段」表。

## 出处

本快捷指令在开源项目 [OpenClaw with Apple](https://github.com/rtjowo/Openclaw-With-Apple)（MIT）的
`Health Daily Export` 基础上改造，补齐了 HRV / 静息心率 / 锻炼分钟数 / 静息能量四个字段。
