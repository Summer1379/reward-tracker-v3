# 奖励追踪器 v3

把日常电脑操作（鼠标移动、点击、打字）转化成轻量 RPG 反馈的桌面工具。

## 运行

```bash
pip install numpy
python3 reward_tracker.py
```

## 音效

在 `assets/` 目录放入以下文件可使用自定义音效：
- `sfx_move.wav`
- `sfx_click.wav`
- `sfx_type_burst.wav`
- `sfx_level_up.wav`

没有文件时自动使用合成音效。

## 快捷键

- 底部输入框打字触发打字奖励（每 10 个字符）
- 点击窗口内任意位置触发点击奖励
- 移动鼠标超过 180px 触发移动奖励
