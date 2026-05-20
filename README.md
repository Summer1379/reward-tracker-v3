# 奖励追踪器 v3

把日常电脑操作（鼠标移动、点击、打字）转化成轻量 RPG 反馈的桌面工具。

## 运行

```bash
pip install numpy
./run_reward_tracker.command
```

macOS 上不要使用 `/usr/bin/python3` 启动：CommandLineTools 自带 Python 3.9
在当前系统 Tk 组合下会崩溃。启动脚本会优先选择可用的 Python.org
3.13（例如 `/usr/local/bin/python3`）。

也可以在 Finder 里双击 `run_reward_tracker.command` 试玩。

不打开窗口的核心闭环检查：

```bash
python3 reward_tracker.py --self-test
```

这个命令使用临时存档，验证升级、掉落、称号装备、主题装备和保存，不会写入你的真实进度。

## 玩法进度

- 经验达到 25%、50%、75% 时会触发三段小音效和提示。
- 升级会触发更大的胜利音效，并掉落称号、光效主题或碎片。
- “身份”页可以装备称号；装备后的称号会出现在顶部身份徽章和关键反馈里。
- 光效主题会改变经验槽、接近升级闪烁和高价值反馈的主色。
- 3 个同名碎片可以在“身份”页锻造成指定称号或光效主题。
- 打字、点击、移动分别推进“梦境铭文师 / 连击破阵者 / 原野巡游者”熟练度，统计页可查看职业等级。
- “旅记”页会记录升级、职业突破、碎片锻造等长期记忆，让桌面反馈有个人故事线。
- 存档会自动保存到 `~/.reward_tracker_v3.json`，关闭窗口时也会强制保存。

## 音效

在 `assets/` 目录放入以下文件可使用自定义音效：
- `sfx_move.wav`
- `sfx_click.wav`
- `sfx_type_burst.wav`
- `sfx_xp_milestone.wav`
- `sfx_xp_milestone_25.wav`
- `sfx_xp_milestone_50.wav`
- `sfx_xp_milestone_75.wav`
- `sfx_level_victory.wav`
- `sfx_level_up.wav`

没有文件时自动使用更柔和的田园风合成音效。
三段经验奖励点会分别使用 25%、50%、75% 的风铃感音效文件；缺失时回退到通用 `sfx_xp_milestone.wav`。
`sfx_level_victory.wav` 不存在时会回退使用旧的 `sfx_level_up.wav`。

## 快捷键

- 底部输入框打字触发打字奖励（每 10 个字符）
- 点击窗口内任意位置触发点击奖励
- 移动鼠标超过 180px 触发移动奖励
