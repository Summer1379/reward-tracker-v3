#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桌面奖励追踪器 v3 — 稳定版单文件 MVP"""

import json
import math
import os
import platform
import random
import subprocess
import sys
import tempfile
import threading
import time
import wave
from collections import deque

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    from pynput import mouse as pynput_mouse, keyboard as pynput_keyboard
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False


APP_NAME = "奖励追踪器 v3"
SAVE_FILE = os.path.expanduser("~/.reward_tracker_v3.json")
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

tk = None
ttk = None


def _is_unsafe_tk_python_path(path):
    real = os.path.realpath(path)
    return "/Library/Developer/CommandLineTools/" in real


def _is_homebrew_python_path(path):
    real = os.path.realpath(path)
    return real.startswith("/opt/homebrew/")


def _candidate_tk_pythons():
    return [
        "/usr/local/bin/python3",
        "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3",
        "/usr/local/bin/python3.13",
    ]


def _find_safe_tk_python():
    current = os.path.realpath(sys.executable)
    for candidate in _candidate_tk_pythons():
        if not os.path.exists(candidate):
            continue
        real_candidate = os.path.realpath(candidate)
        if real_candidate == current:
            continue
        if _is_unsafe_tk_python_path(real_candidate) or _is_homebrew_python_path(real_candidate):
            continue
        result = subprocess.run(
            [candidate, "-c", "import tkinter"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return candidate
    return None


def _should_reexec_for_tk():
    return (
        not os.environ.get("REWARD_TRACKER_NO_REEXEC")
        and (
            _is_unsafe_tk_python_path(sys.executable)
            or _is_homebrew_python_path(sys.executable)
        )
    )


def _reexec_if_needed_for_tk():
    if not _should_reexec_for_tk():
        return
    safe_python = _find_safe_tk_python()
    if safe_python:
        if "--print-tk-launcher" in sys.argv:
            print(safe_python)
            raise SystemExit(0)
        os.execv(safe_python, [safe_python, os.path.abspath(__file__), *sys.argv[1:]])


def _load_gui_modules():
    global tk, ttk, make_overlay, HAS_OVERLAY
    _reexec_if_needed_for_tk()
    import tkinter as tk_module
    from tkinter import ttk as ttk_module

    tk = tk_module
    ttk = ttk_module
    try:
        from effects_overlay import make_overlay as overlay_factory
        HAS_OVERLAY = True
        make_overlay = overlay_factory
    except ImportError:
        HAS_OVERLAY = False

        def make_overlay():
            return None


HAS_OVERLAY = False


def make_overlay():
    return None

COLORS = {
    "BG":           "#0D0E14",
    "SURFACE":      "#13141C",
    "SURFACE2":     "#1A1C27",
    "BORDER":       "#2A2D3E",
    "TEXT":         "#D8D8E8",
    "TEXT_MUTED":   "#6A6C82",
    "ORANGE":       "#FF6B2C",
    "CYAN":         "#00E5CC",
    "GOLD":         "#E8C84A",
    "PURPLE":       "#A86FDF",
    "SUCCESS":      "#5DBB63",
    # FF 水晶风格
    "CRYSTAL":      "#4FC3F7",   # 水晶蓝
    "CRYSTAL_DIM":  "#1A3A4A",   # 水晶暗底
    "STAR":         "#FFD700",   # 星辉金
    "RELIC":        "#9B59B6",   # 史诗紫
    "SILVER":       "#BDC3C7",   # 银白
    "BRONZE":       "#CD7F32",   # 铜色
}

MOUSE_PX_THRESHOLD = 180
COMBO_TIMEOUT_SEC = 3.0
CLICK_BASE_POINTS = 12
TYPE_BURST_CHARS = 10
TYPE_BURST_POINTS = 40
MOUSE_MOVE_POINTS = 2
INITIAL_XP_NEEDED = 200
XP_GROWTH = 1.35


def _blend_color(hex_a, hex_b, t):
    """在两个 #RRGGBB 颜色之间插值，t=0 返回 a，t=1 返回 b"""
    t = max(0.0, min(1.0, t))
    try:
        ra, ga, ba = int(hex_a[1:3], 16), int(hex_a[3:5], 16), int(hex_a[5:7], 16)
        rb, gb, bb = int(hex_b[1:3], 16), int(hex_b[3:5], 16), int(hex_b[5:7], 16)
        r = int(ra + (rb - ra) * t)
        g = int(ga + (gb - ga) * t)
        b = int(ba + (bb - ba) * t)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_a


ACHIEVEMENTS = [
    # (key, title, rarity, current_fn, target)
    # rarity: "bronze" | "silver" | "crystal" | "star"
    ("first_click",   "初次点击",       "bronze",  lambda s: s["event_counts"]["click"],  1),
    ("first_type",    "初次铭刻",       "bronze",  lambda s: s["chars_total"],             1),
    ("type_50",       "见习铭刻者",     "bronze",  lambda s: s["chars_total"],             50),
    ("click_10",      "初学点击者",     "bronze",  lambda s: s["event_counts"]["click"],   10),
    ("combo_5",       "初段共鸣",       "bronze",  lambda s: s["max_combo"],               5),
    ("score_500",     "积分初醒",       "bronze",  lambda s: s["total_score"],             500),
    ("type_100",      "百字铭刻",       "silver",  lambda s: s["chars_total"],             100),
    ("click_50",      "点击见习者",     "silver",  lambda s: s["event_counts"]["click"],   50),
    ("level_5",       "Lv.5 觉醒",      "silver",  lambda s: s["level"],                   5),
    ("combo_15",      "银段共鸣",       "silver",  lambda s: s["max_combo"],               15),
    ("score_5000",    "星尘 5000",      "silver",  lambda s: s["total_score"],             5000),
    ("type_500",      "五百字行者",     "silver",  lambda s: s["chars_total"],             500),
    ("type_1000",     "千字大师",       "crystal", lambda s: s["chars_total"],             1000),
    ("click_200",     "点击行者",       "crystal", lambda s: s["event_counts"]["click"],   200),
    ("level_10",      "Lv.10 水晶觉醒", "crystal", lambda s: s["level"],                   10),
    ("combo_30",      "金段共鸣",       "crystal", lambda s: s["max_combo"],               30),
    ("score_20000",   "星尘 2万",       "crystal", lambda s: s["total_score"],             20000),
    ("type_5000",     "五千字远征",     "crystal", lambda s: s["chars_total"],             5000),
    ("click_500",     "点击达人",       "crystal", lambda s: s["event_counts"]["click"],   500),
    ("combo_60",      "钻石共鸣",       "star",    lambda s: s["max_combo"],               60),
    ("level_20",      "Lv.20 星辉觉醒", "star",    lambda s: s["level"],                   20),
    ("score_50000",   "星尘 5万",       "star",    lambda s: s["total_score"],             50000),
    ("type_10000",    "万字史诗",       "star",    lambda s: s["chars_total"],             10000),
    ("click_1000",    "千击传说",       "star",    lambda s: s["event_counts"]["click"],   1000),
    ("level_30",      "Lv.30 命运之主", "star",    lambda s: s["level"],                   30),
]

# 稀有度配置
RARITY_CONFIG = {
    "bronze":  ("青铜印记", COLORS["BRONZE"]),
    "silver":  ("白银纹章", COLORS["SILVER"]),
    "crystal": ("水晶遗物", COLORS["CRYSTAL"]),
    "star":    ("星辉王冠", COLORS["STAR"]),
}

DAILY_CHALLENGES = [
    ("daily_type", "今日打字", "chars_today", 500, 300),
    ("daily_click", "今日点击", "clicks_today", 100, 200),
    ("daily_score", "今日积分", "score_today", 2000, 500),
]

XP_MILESTONES = (25, 50, 75)
XP_MILESTONE_SOUNDS = {
    25: "xp_milestone_25",
    50: "xp_milestone_50",
    75: "xp_milestone_75",
}
XP_MILESTONE_LABELS = {
    25: "晨露铃",
    50: "溪畔风铃",
    75: "麦浪回声",
}

PASTORAL_REWARD_LINES = [
    (30, 0, "花田连奏"),
    (15, 0, "溪畔连奏"),
    (0, 50, "丰收一击"),
    (0, 30, "春风回应"),
    (0, 0, "小芽生长"),
]

TITLE_DROPS = [
    {"name": "微光拾荒者", "rarity": "bronze"},
    {"name": "键盘旅人", "rarity": "bronze"},
    {"name": "晨雾见习生", "rarity": "bronze"},
    {"name": "月下记录者", "rarity": "silver"},
    {"name": "星尘收信人", "rarity": "silver"},
    {"name": "温柔连击者", "rarity": "silver"},
    {"name": "水晶铭文师", "rarity": "crystal"},
    {"name": "梦境观测者", "rarity": "crystal"},
    {"name": "遗迹守灯人", "rarity": "crystal"},
    {"name": "命运之诗咏者", "rarity": "star"},
    {"name": "终末幻想旅人", "rarity": "star"},
    {"name": "群星回声", "rarity": "star"},
]

THEME_DROPS = [
    {"id": "crystal_dawn", "name": "crystal_dawn", "label": "水晶蓝", "rarity": "bronze"},
    {"id": "ember_heart", "name": "ember_heart", "label": "金红胜利感", "rarity": "silver"},
    {"id": "violet_dream", "name": "violet_dream", "label": "紫色梦境", "rarity": "crystal"},
    {"id": "starlit_oath", "name": "starlit_oath", "label": "星辉金", "rarity": "star"},
]

DEFAULT_THEME_ID = "crystal_dawn"
THEME_PROFILES = {
    "crystal_dawn": {
        "id": "crystal_dawn",
        "label": "水晶蓝",
        "accent": COLORS["CRYSTAL"],
        "accent_alt": COLORS["CYAN"],
        "dim": COLORS["CRYSTAL_DIM"],
        "reward_word": "水晶回响",
    },
    "ember_heart": {
        "id": "ember_heart",
        "label": "金红胜利感",
        "accent": COLORS["ORANGE"],
        "accent_alt": COLORS["STAR"],
        "dim": "#3A2318",
        "reward_word": "炉心跃迁",
    },
    "violet_dream": {
        "id": "violet_dream",
        "label": "紫色梦境",
        "accent": COLORS["RELIC"],
        "accent_alt": "#D7A8FF",
        "dim": "#271A36",
        "reward_word": "梦境涟漪",
    },
    "starlit_oath": {
        "id": "starlit_oath",
        "label": "星辉金",
        "accent": COLORS["STAR"],
        "accent_alt": "#FFF0A6",
        "dim": "#332A12",
        "reward_word": "星誓辉光",
    },
}

FRAGMENT_DROPS = [
    {"name": "梦晶碎片", "rarity": "bronze"},
    {"name": "星尘羽片", "rarity": "silver"},
    {"name": "旧日回声", "rarity": "crystal"},
    {"name": "月光残页", "rarity": "star"},
]

FRAGMENT_FORGE_COST = 3
FRAGMENT_FORGE_REWARDS = {
    "梦晶碎片": {"type": "title", "name": "晨雾见习生", "rarity": "bronze"},
    "星尘羽片": {"type": "theme", "name": "ember_heart", "rarity": "silver"},
    "旧日回声": {"type": "title", "name": "遗迹守灯人", "rarity": "crystal"},
    "月光残页": {"type": "theme", "name": "starlit_oath", "rarity": "star"},
}

MASTERY_INITIAL_XP_NEEDED = 100
MASTERY_GROWTH = 1.42
MASTERY_DEFS = {
    "dream_scribe": {
        "label": "梦境铭文师",
        "event": "type",
        "color": COLORS["CYAN"],
        "xp_scale": 1.0,
    },
    "chainbreaker": {
        "label": "连击破阵者",
        "event": "click",
        "color": COLORS["GOLD"],
        "xp_scale": 0.82,
    },
    "meadow_wanderer": {
        "label": "原野巡游者",
        "event": "move",
        "color": COLORS["SUCCESS"],
        "xp_scale": 2.4,
    },
}
EVENT_MASTERY = {
    config["event"]: key
    for key, config in MASTERY_DEFS.items()
}

CHRONICLE_LIMIT = 40

DROP_RARITY_WEIGHTS = {
    "level_up": {"bronze": 45, "silver": 30, "crystal": 18, "star": 7},
    "daily_challenge": {"bronze": 50, "silver": 30, "crystal": 16, "star": 4},
    "critical": {"bronze": 60, "silver": 26, "crystal": 12, "star": 2},
}

DROP_TYPE_WEIGHTS = {
    "level_up": {"title": 45, "theme": 25, "fragment": 30},
    "daily_challenge": {"title": 30, "theme": 20, "fragment": 50},
    "critical": {"title": 20, "theme": 15, "fragment": 65},
}


class AudioStateMachine:
    """音频状态机：同类输入持续时只播放一次，类别切换可中断"""

    def __init__(self):
        self.muted = False
        self.current_category = None
        self.current_proc = None
        self.last_play_time = {}
        self.cooldown = {
            "move": 0.8,
            "click": 0.15,
            "type": 0.4,
            "level_up": 0.0,
            "xp_milestone": 0.0,
            "xp_milestone_25": 0.0,
            "xp_milestone_50": 0.0,
            "xp_milestone_75": 0.0,
            "level_victory": 0.0,
            "achievement": 0.0,
        }
        self.sound_files = self._resolve_sounds()
        self.lock = threading.Lock()

    def _resolve_sounds(self):
        mapping = {
            "move": "sfx_move.wav",
            "click": "sfx_click.wav",
            "type": "sfx_type_burst.wav",
            "level_up": "sfx_level_up.wav",
            "xp_milestone": "sfx_xp_milestone.wav",
            "xp_milestone_25": "sfx_xp_milestone_25.wav",
            "xp_milestone_50": "sfx_xp_milestone_50.wav",
            "xp_milestone_75": "sfx_xp_milestone_75.wav",
            "level_victory": "sfx_level_victory.wav",
            "achievement": "sfx_level_up.wav",
        }
        fallback = {
            "xp_milestone_25": "sfx_xp_milestone.wav",
            "xp_milestone_50": "sfx_xp_milestone.wav",
            "xp_milestone_75": "sfx_xp_milestone.wav",
            "level_victory": "sfx_level_up.wav",
        }
        resolved = {}
        for key, fname in mapping.items():
            path = os.path.join(ASSETS_DIR, fname)
            if os.path.exists(path):
                resolved[key] = path
                continue
            fallback_name = fallback.get(key)
            if fallback_name:
                fallback_path = os.path.join(ASSETS_DIR, fallback_name)
                if os.path.exists(fallback_path):
                    resolved[key] = fallback_path
        return resolved

    def toggle_mute(self):
        self.muted = not self.muted
        if self.muted:
            self._stop_current()
        return self.muted

    def _stop_current(self):
        if self.current_proc and self.current_proc.poll() is None:
            try:
                self.current_proc.terminate()
            except Exception:
                pass
        self.current_proc = None
        self.current_category = None

    def play(self, category, priority=False):
        if self.muted:
            return
        now = time.time()
        with self.lock:
            last = self.last_play_time.get(category, 0)
            cd = self.cooldown.get(category, 0.5)
            if not priority and (now - last) < cd:
                return
            self.last_play_time[category] = now
            path = self.sound_files.get(category)
        # 在后台线程播放，不阻塞主线程
        threading.Thread(target=self._play_bg, args=(category, path, priority), daemon=True).start()

    def _play_bg(self, category, path, priority):
        try:
            if path and platform.system() == "Darwin":
                proc = subprocess.Popen(
                    ["afplay", "-v", "0.7", path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                proc.wait()
            elif HAS_NUMPY:
                self._play_synth(category)
        except Exception:
            pass

    def _play_synth(self, category):
        voices = {
            "move": [((523, 659), 0.085, 0.018, 0.032)],
            "click": [((784, 1175), 0.095, 0.018, 0.04)],
            "type": [((587, 880), 0.07, 0.02, 0.035), ((659, 988), 0.09, 0.0, 0.032)],
            "level_up": [
                ((392, 523), 0.105, 0.025, 0.05),
                ((523, 659), 0.105, 0.025, 0.05),
                ((659, 784, 988), 0.18, 0.0, 0.046),
            ],
            "xp_milestone": [((659, 988), 0.11, 0.026, 0.042), ((784, 1175), 0.13, 0.0, 0.038)],
            "xp_milestone_25": [
                ((587, 880), 0.12, 0.032, 0.04),
                ((659, 988), 0.16, 0.0, 0.036),
            ],
            "xp_milestone_50": [
                ((523, 784), 0.105, 0.024, 0.038),
                ((659, 988), 0.12, 0.028, 0.04),
                ((784, 1175), 0.16, 0.0, 0.035),
            ],
            "xp_milestone_75": [
                ((440, 659), 0.11, 0.022, 0.038),
                ((587, 880), 0.12, 0.026, 0.04),
                ((740, 1109), 0.13, 0.028, 0.04),
                ((880, 1319), 0.18, 0.0, 0.034),
            ],
            "level_victory": [
                ((392, 523), 0.14, 0.035, 0.052),
                ((523, 659), 0.14, 0.035, 0.052),
                ((659, 784, 988), 0.18, 0.04, 0.05),
                ((523, 659, 784, 1047), 0.36, 0.0, 0.044),
            ],
            "achievement": [
                ((523, 784), 0.12, 0.028, 0.045),
                ((659, 988), 0.15, 0.0, 0.04),
            ],
        }
        seq = voices.get(category, [((440, 660), 0.12, 0.0, 0.04)])
        samples = []
        sample_rate = 22050
        for freqs, dur, pause, volume in seq:
            t = np.linspace(0, dur, int(sample_rate * dur), endpoint=False)
            attack = min(0.018, dur * 0.22)
            attack_env = np.clip(t / attack, 0, 1) if attack > 0 else 1
            decay_env = np.exp(-4.2 * t / dur)
            envelope = np.minimum(attack_env, 1) * decay_env
            wave_samples = np.zeros_like(t)
            for i, f in enumerate(freqs):
                partial = np.sin(2 * np.pi * f * t)
                partial += 0.22 * np.sin(2 * np.pi * f * 2.01 * t)
                wave_samples += partial / (i + 1)
            wave_samples = wave_samples / max(len(freqs), 1) * volume * envelope
            samples.extend(wave_samples)
            if pause:
                samples.extend(np.zeros(int(sample_rate * pause)))
        pcm = (np.array(samples) * 32767).astype(np.int16)
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                path = f.name
            with wave.open(path, "w") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm.tobytes())
            if platform.system() == "Darwin":
                self.current_proc = subprocess.Popen(
                    ["afplay", path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.current_category = category
                threading.Timer(2.0, lambda: self._cleanup(path)).start()
        except Exception:
            pass

    def _cleanup(self, path):
        try:
            os.unlink(path)
        except Exception:
            pass

    def shutdown(self):
        self._stop_current()


class DesktopEffects:
    """特效系统：飘字 / Toast / 升级弹窗 / 成就弹窗"""

    def __init__(self, root):
        self.root = root
        self.toast_queue = deque()
        self.active_toast = None
        self._toast_last = {}
        self._float_canvas = None
        self._float_items = []   # [item_id, step, x, y, color, font_size]
        self._modal_queue = deque()
        self._modal_active = False

    # ── 飘字 Canvas ────────────────────────────────────────────────────────
    def _widget_lift(self, w):
        """Canvas.lift() 在 tkinter 里被重写为 tag 操作，用 tk.call 绕过"""
        try:
            w.tk.call("raise", w._w)
        except Exception:
            pass

    def setup_float_canvas(self, parent):
        self._float_canvas = tk.Canvas(
            parent, highlightthickness=0, bg=COLORS["BG"],
        )
        self._float_canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        self._widget_lift(self._float_canvas)
        self._keep_float_lifted()
        self._tick_floats()

    def _keep_float_lifted(self):
        if self._float_canvas and self._float_canvas.winfo_exists():
            self._widget_lift(self._float_canvas)
            self._float_canvas.after(500, self._keep_float_lifted)

    def floating_text(self, text, color=None, big=False):
        if not self._float_canvas:
            return
        try:
            color = color or COLORS["GOLD"]
            cw = max(self._float_canvas.winfo_width(), 300)
            ch = max(self._float_canvas.winfo_height(), 300)
            x = random.randint(int(cw * 0.2), int(cw * 0.8))
            y = random.randint(int(ch * 0.35), int(ch * 0.65))
            size = 22 if big else 16
            # 描边（黑色偏移）增加可读性
            shadow = self._float_canvas.create_text(
                x + 2, y + 2, text=text, fill="#000000",
                font=("Helvetica", size, "bold"),
            )
            item_id = self._float_canvas.create_text(
                x, y, text=text, fill=color,
                font=("Helvetica", size, "bold"),
            )
            self._widget_lift(self._float_canvas)
            self._float_items.append([item_id, shadow, 0, x, y, color])
        except Exception:
            pass

    def _tick_floats(self):
        if not self._float_canvas or not self._float_canvas.winfo_exists():
            return
        done = []
        for entry in self._float_items:
            item_id, shadow, step, x, y, color = entry
            step += 1
            entry[2] = step
            ny = y - step * 2.2
            try:
                self._float_canvas.coords(item_id, x, ny)
                self._float_canvas.coords(shadow, x + 2, ny + 2)
                t = step / 20.0
                blended = _blend_color(color, COLORS["BG"], t)
                self._float_canvas.itemconfigure(item_id, fill=blended)
                self._float_canvas.itemconfigure(shadow, fill=_blend_color("#000000", COLORS["BG"], t))
            except Exception:
                pass
            if step >= 20:
                done.append(entry)
                try:
                    self._float_canvas.delete(item_id)
                    self._float_canvas.delete(shadow)
                except Exception:
                    pass
        for d in done:
            self._float_items.remove(d)
        self._float_canvas.after(30, self._tick_floats)

    def _notice_allowed(self, title, category=None):
        now = time.time()
        key = category or title
        if now - self._toast_last.get(key, 0) < 5.0:
            return False
        self._toast_last[key] = now
        return True

    # ── Toast（Tk 顶层窗；奖励流程默认走 passive，避免抢焦点）──────────────
    def show_toast(self, title, subtitle="", color=None, category=None):
        color = color or COLORS["GOLD"]
        if not self._notice_allowed(title, category):
            return
        self.toast_queue.append((title, subtitle, color))
        if not self.active_toast:
            self._show_next_toast()

    def _show_next_toast(self):
        if not self.toast_queue:
            self.active_toast = None
            return
        title, subtitle, color = self.toast_queue.popleft()
        try:
            tw = tk.Toplevel(self.root)
            tw.overrideredirect(True)
            tw.attributes("-topmost", True)
            tw.attributes("-alpha", 0.0)
            try:
                tw.tk.call("::tk::unsupported::MacWindowStyle", "style", tw._w, "help", "noActivates")
            except Exception:
                pass
            sw = tw.winfo_screenwidth()
            w, h = 300, 76 if subtitle else 52
            tw.geometry(f"{w}x{h}+{sw - w - 20}+60")
            tw.configure(bg=COLORS["SURFACE"])
            tk.Frame(tw, bg=color, width=4).pack(side=tk.LEFT, fill=tk.Y)
            c = tk.Frame(tw, bg=COLORS["SURFACE"])
            c.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=8)
            tk.Label(c, text=title, bg=COLORS["SURFACE"], fg=color,
                     font=("Helvetica", 12, "bold")).pack(anchor=tk.W)
            if subtitle:
                tk.Label(c, text=subtitle, bg=COLORS["SURFACE"],
                         fg=COLORS["TEXT_MUTED"], font=("Helvetica", 10)).pack(anchor=tk.W)
            self.active_toast = tw
            self._animate_toast(tw, True, 0.0)
        except Exception:
            self.active_toast = None
            self.root.after(50, self._show_next_toast)

    def _animate_toast(self, tw, fade_in, alpha):
        if not tw.winfo_exists():
            self.active_toast = None
            self.root.after(100, self._show_next_toast)
            return
        try:
            if fade_in:
                alpha = min(alpha + 0.12, 0.92)
                tw.attributes("-alpha", alpha)
                if alpha < 0.92:
                    self.root.after(18, lambda: self._animate_toast(tw, True, alpha))
                else:
                    self.root.after(2200, lambda: self._animate_toast(tw, False, 0.92))
            else:
                alpha = max(alpha - 0.08, 0.0)
                tw.attributes("-alpha", alpha)
                if alpha > 0:
                    self.root.after(22, lambda: self._animate_toast(tw, False, alpha))
                else:
                    tw.destroy()
                    self.active_toast = None
                    self.root.after(80, self._show_next_toast)
        except tk.TclError:
            self.active_toast = None
            self.root.after(100, self._show_next_toast)

    def show_passive_toast(self, title, subtitle="", color=None, category=None, big=False):
        color = color or COLORS["GOLD"]
        if not self._notice_allowed(title, category):
            return
        text = title if not subtitle else f"{title} · {subtitle}"
        self.floating_text(text, color=color, big=big)

    # ── 升级反馈：轻量田园结算，不弹阻塞式大窗口 ──────────────────────────
    def show_level_up(self, level):
        self.show_passive_toast(
            "丰收升级",
            subtitle=f"LV.{level} · 新的小路亮起",
            color=COLORS["STAR"],
            category=f"level_{level}",
            big=True,
        )
        self.floating_text(f"丰收升级  LV.{level}", color=COLORS["STAR"], big=True)

    # ── 成就弹窗 ──────────────────────────────────────────────────────────
    def show_achievement(self, title, rarity):
        self._modal_queue.append(("achievement", title, rarity))
        if not self._modal_active:
            self._show_next_modal()

    def _show_next_modal(self):
        if not self._modal_queue:
            self._modal_active = False
            return
        self._modal_active = True
        kind, data, extra = self._modal_queue.popleft()
        if kind == "level":
            self._build_level_modal(data)
        else:
            self._build_achievement_modal(data, extra)

    def _build_level_modal(self, level):
        try:
            m = tk.Toplevel(self.root)
            m.overrideredirect(True)
            m.attributes("-topmost", True)
            m.attributes("-alpha", 0.0)
            try:
                m.tk.call("::tk::unsupported::MacWindowStyle", "style", m._w, "help", "noActivates")
            except Exception:
                pass
            sw, sh = m.winfo_screenwidth(), m.winfo_screenheight()
            w, h = 380, 200
            m.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2 - 60}")
            m.configure(bg=COLORS["SURFACE"])

            # 水晶色边框
            border = tk.Frame(m, bg=COLORS["CRYSTAL"], padx=2, pady=2)
            border.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
            inner = tk.Frame(border, bg=COLORS["SURFACE"])
            inner.pack(fill=tk.BOTH, expand=True)

            tk.Label(inner, text="✦  HARVEST BLOOM  ✦",
                     bg=COLORS["SURFACE"], fg=COLORS["CRYSTAL"],
                     font=("Helvetica", 11, "bold")).pack(pady=(18, 4))
            tk.Label(inner, text=f"LV. {level}",
                     bg=COLORS["SURFACE"], fg=COLORS["STAR"],
                     font=("Helvetica", 42, "bold")).pack()
            tk.Label(inner, text="新的力量正在苏醒",
                     bg=COLORS["SURFACE"], fg=COLORS["TEXT_MUTED"],
                     font=("Helvetica", 11)).pack(pady=(4, 16))

            # 粒子动画（canvas 上随机星点）
            pc = tk.Canvas(inner, height=6, bg=COLORS["SURFACE"], highlightthickness=0)
            pc.pack(fill=tk.X, padx=20)
            self._animate_particles(pc, 0)

            self._animate_modal(m, True, 0.0, auto_close_ms=2200)
        except Exception:
            self._modal_active = False
            self.root.after(100, self._show_next_modal)

    def _build_achievement_modal(self, title, rarity):
        rarity_label, rarity_color = RARITY_CONFIG.get(rarity, ("成就", COLORS["GOLD"]))
        try:
            m = tk.Toplevel(self.root)
            m.overrideredirect(True)
            m.attributes("-topmost", True)
            m.attributes("-alpha", 0.0)
            try:
                m.tk.call("::tk::unsupported::MacWindowStyle", "style", m._w, "help", "noActivates")
            except Exception:
                pass
            sw, sh = m.winfo_screenwidth(), m.winfo_screenheight()
            w, h = 360, 160
            m.geometry(f"{w}x{h}+{(sw-w)//2}+{sh//2 + 40}")
            m.configure(bg=COLORS["SURFACE"])

            border = tk.Frame(m, bg=rarity_color, padx=2, pady=2)
            border.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
            inner = tk.Frame(border, bg=COLORS["SURFACE"])
            inner.pack(fill=tk.BOTH, expand=True)

            tk.Label(inner, text="命运铭文已刻下",
                     bg=COLORS["SURFACE"], fg=COLORS["TEXT_MUTED"],
                     font=("Helvetica", 10)).pack(pady=(14, 2))
            tk.Label(inner, text=f"【{title}】",
                     bg=COLORS["SURFACE"], fg=rarity_color,
                     font=("Helvetica", 18, "bold")).pack()
            tk.Label(inner, text=rarity_label,
                     bg=COLORS["SURFACE"], fg=rarity_color,
                     font=("Helvetica", 10)).pack(pady=(4, 14))

            self._animate_modal(m, True, 0.0, auto_close_ms=2000)
        except Exception:
            self._modal_active = False
            self.root.after(100, self._show_next_modal)

    def _animate_particles(self, canvas, step):
        if not canvas.winfo_exists():
            return
        canvas.delete("all")
        w = max(canvas.winfo_width(), 340)
        for _ in range(12):
            x = random.randint(0, w)
            r = random.randint(1, 3)
            c = random.choice([COLORS["CRYSTAL"], COLORS["STAR"], COLORS["TEXT_MUTED"]])
            canvas.create_oval(x-r, 0, x+r, 6, fill=c, width=0)
        if step < 60:
            canvas.after(80, lambda: self._animate_particles(canvas, step + 1))

    def _animate_modal(self, m, fade_in, alpha, auto_close_ms=2000):
        if not m.winfo_exists():
            self.root.after(120, self._show_next_modal)
            return
        try:
            if fade_in:
                alpha = min(alpha + 0.12, 0.96)
                m.attributes("-alpha", alpha)
                if alpha < 0.96:
                    self.root.after(18, lambda: self._animate_modal(m, True, alpha, auto_close_ms))
                else:
                    self.root.after(auto_close_ms, lambda: self._animate_modal(m, False, 0.96, 0))
            else:
                alpha = max(alpha - 0.1, 0.0)
                m.attributes("-alpha", alpha)
                if alpha > 0:
                    self.root.after(20, lambda: self._animate_modal(m, False, alpha, 0))
                else:
                    m.destroy()
                    self.root.after(200, self._show_next_modal)
        except tk.TclError:
            self.root.after(100, self._show_next_modal)

    def shutdown(self):
        if self.active_toast:
            try:
                self.active_toast.destroy()
            except Exception:
                pass


class RewardState:
    """核心奖励逻辑 + 数据持久化"""

    COMBO_TIERS = [
        (0, "无", 1.0, COLORS["TEXT_MUTED"]),
        (5, "铜", 1.3, "#B87333"),
        (15, "银", 1.6, "#C0C0C0"),
        (30, "金", 2.0, COLORS["GOLD"]),
        (60, "钻", 3.0, COLORS["CYAN"]),
    ]

    def __init__(self):
        self.score = 0
        self.total_score = 0
        self.combo = 0
        self.max_combo = 0
        self.level = 1
        self.xp = 0
        self.xp_needed = INITIAL_XP_NEEDED
        self.last_mouse_pos = None
        self.mouse_pixels = 0.0
        self.chars_buffer = 0
        self.chars_total = 0
        self.event_counts = {"move": 0, "click": 0, "type": 0}
        self.unlocked_achievements = set()
        self.session_start = time.time()
        self.last_event_time = 0
        self._combo_timer = None
        self._combo_decay_after = 0.0
        # 每日数据
        self.today = self._today_str()
        self.chars_today = 0
        self.clicks_today = 0
        self.score_today = 0
        self.completed_challenges = set()
        self.xp_milestones_triggered = set()
        self.inventory = {"titles": [], "themes": [], "fragments": {}}
        self.owned_titles = set()
        self.equipped_title = None
        self.equipped_theme = None
        self.masteries = self._default_masteries()
        self.chronicle = []
        self.dirty = False
        # 历史趋势（每日积分）
        self.daily_history = {}
        self.load()
        self._normalize_inventory()
        self._normalize_masteries()
        self._normalize_chronicle()
        self._roll_daily_if_needed()

    @staticmethod
    def _today_str():
        return time.strftime("%Y-%m-%d")

    def _default_masteries(self):
        return {
            key: {
                "level": 1,
                "xp": 0,
                "xp_needed": MASTERY_INITIAL_XP_NEEDED,
            }
            for key in MASTERY_DEFS
        }

    def _roll_daily_if_needed(self):
        today = self._today_str()
        if self.today != today:
            # 把昨天的数据归档
            self.daily_history[self.today] = {
                "chars": self.chars_today,
                "clicks": self.clicks_today,
                "score": self.score_today,
            }
            # 只保留最近 30 天
            if len(self.daily_history) > 30:
                oldest = sorted(self.daily_history.keys())[:-30]
                for k in oldest:
                    del self.daily_history[k]
            self.today = today
            self.chars_today = 0
            self.clicks_today = 0
            self.score_today = 0
            self.completed_challenges = set()
            self.mark_dirty()

    def mark_dirty(self):
        self.dirty = True

    def _reset_combo(self):
        self.combo = 0
        self._combo_timer = None

    def _bump_combo_timer(self, root=None):
        """连击在 COMBO_TIMEOUT_SEC 后开始每秒 -1 衰减"""
        self._combo_decay_after = time.time() + COMBO_TIMEOUT_SEC
        if root and not self._combo_timer:
            self._combo_timer = root.after(1000, lambda: self._tick_combo_decay(root))

    def _tick_combo_decay(self, root):
        self._combo_timer = None
        if self.combo <= 0:
            return
        if time.time() >= self._combo_decay_after:
            self.combo = max(0, self.combo - 1)
        if self.combo > 0:
            self._combo_timer = root.after(1000, lambda: self._tick_combo_decay(root))

    def combo_info(self):
        current = self.COMBO_TIERS[0]
        for tier in self.COMBO_TIERS:
            if self.combo >= tier[0]:
                current = tier
        return current

    def reward_flavor_text(self, event_type, combo, points):
        for min_combo, min_points, label in PASTORAL_REWARD_LINES:
            if combo >= min_combo and points >= min_points:
                critical = min_combo >= 30 or min_points >= 50
                return f"{label}  +{points}", critical
        return f"小芽生长  +{points}", False

    def _normalize_masteries(self):
        clean = self._default_masteries()
        source = self.masteries if isinstance(self.masteries, dict) else {}
        for key, defaults in clean.items():
            data = source.get(key, {})
            try:
                defaults["level"] = max(1, int(data.get("level", defaults["level"])))
                defaults["xp"] = max(0, int(data.get("xp", defaults["xp"])))
                defaults["xp_needed"] = max(1, int(data.get("xp_needed", defaults["xp_needed"])))
            except (TypeError, ValueError):
                pass
        self.masteries = clean

    def _normalize_chronicle(self):
        clean = []
        source = self.chronicle if isinstance(self.chronicle, list) else []
        for item in source:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            text = str(item.get("text", "")).strip()
            if not title or not text:
                continue
            clean.append({
                "time": str(item.get("time", self._today_str())),
                "title": title,
                "text": text,
            })
        self.chronicle = clean[-CHRONICLE_LIMIT:]

    def add_chronicle(self, title, text):
        self._normalize_chronicle()
        self.chronicle.append({
            "time": time.strftime("%Y-%m-%d %H:%M"),
            "title": title,
            "text": text,
        })
        self.chronicle = self.chronicle[-CHRONICLE_LIMIT:]
        self.mark_dirty()

    def _add_mastery_xp(self, mastery_id, base_points):
        self._normalize_masteries()
        if mastery_id not in self.masteries:
            return None
        config = MASTERY_DEFS[mastery_id]
        data = self.masteries[mastery_id]
        gained = max(1, int(base_points * config["xp_scale"]))
        before_level = data["level"]
        data["xp"] += gained
        levels_gained = 0
        while data["xp"] >= data["xp_needed"]:
            data["xp"] -= data["xp_needed"]
            data["level"] += 1
            data["xp_needed"] = int(data["xp_needed"] * MASTERY_GROWTH)
            levels_gained += 1
        if levels_gained:
            self.add_chronicle(
                "职业突破",
                f"{config['label']} 抵达 Lv.{data['level']}，新的日常技艺被点亮。",
            )
        self.mark_dirty()
        return {
            "id": mastery_id,
            "label": config["label"],
            "color": config["color"],
            "gained": gained,
            "level_before": before_level,
            "level_after": data["level"],
            "level": data["level"],
            "xp": data["xp"],
            "xp_needed": data["xp_needed"],
            "leveled": levels_gained > 0,
            "levels_gained": levels_gained,
        }

    def _mastery_for_event(self, event_type, points):
        mastery_id = EVENT_MASTERY.get(event_type)
        if not mastery_id:
            return None
        return self._add_mastery_xp(mastery_id, points)

    def _add_xp(self, amount):
        before_level = self.level
        before_xp = self.xp
        before_needed = self.xp_needed
        milestones = []
        milestone_sounds = []
        drops = []
        levels_gained = 0
        self.xp += amount

        if amount >= 0 and self.xp < self.xp_needed:
            start_pct = int((before_xp / max(before_needed, 1)) * 100)
            end_pct = int((self.xp / max(self.xp_needed, 1)) * 100)
            for milestone in XP_MILESTONES:
                if start_pct < milestone <= end_pct and milestone not in self.xp_milestones_triggered:
                    self.xp_milestones_triggered.add(milestone)
                    milestones.append(milestone)
                    milestone_sounds.append(XP_MILESTONE_SOUNDS[milestone])

        while self.xp >= self.xp_needed:
            self.xp -= self.xp_needed
            self.level += 1
            self.xp_needed = int(self.xp_needed * XP_GROWTH)
            self.xp_milestones_triggered = set()
            levels_gained += 1
            drops.extend(self.generate_drops("level_up", count=1))
            self.add_chronicle("丰收升级", f"丰收升级到 LV.{self.level}，小路向更远处延伸。")

        if amount or milestones or drops:
            self.mark_dirty()

        return {
            "leveled": levels_gained > 0,
            "levels_gained": levels_gained,
            "level_before": before_level,
            "level_after": self.level,
            "xp_before": before_xp,
            "xp_after": self.xp,
            "xp_needed_before": before_needed,
            "xp_needed_after": self.xp_needed,
            "pct_before": before_xp / max(before_needed, 1),
            "pct_after": self.xp / max(self.xp_needed, 1),
            "milestones": milestones,
            "milestone_sounds": milestone_sounds,
            "drops": drops,
        }

    def _weighted_choice(self, weights):
        names = list(weights.keys())
        values = [weights[name] for name in names]
        return random.choices(names, weights=values, k=1)[0]

    def _items_for_rarity(self, items, rarity):
        matched = [item for item in items if item.get("rarity") == rarity]
        return matched or items

    def _normalize_inventory(self):
        inv = self.inventory if isinstance(self.inventory, dict) else {}
        titles = inv.get("titles", [])
        themes = inv.get("themes", [])
        fragments = inv.get("fragments", {})
        if not isinstance(titles, list):
            titles = []
        if not isinstance(themes, list):
            themes = []
        if not isinstance(fragments, dict):
            fragments = {}

        self.owned_titles = set(self.owned_titles) | set(titles)
        if self.equipped_title and self.equipped_title not in self.owned_titles:
            self.owned_titles.add(self.equipped_title)

        clean_fragments = {}
        for k, v in fragments.items():
            try:
                count = int(v)
            except (TypeError, ValueError):
                continue
            if count > 0:
                clean_fragments[str(k)] = count

        self.inventory = {
            "titles": sorted(self.owned_titles),
            "themes": sorted(set(themes)),
            "fragments": clean_fragments,
        }
        if self.equipped_title not in self.owned_titles:
            self.equipped_title = None
        if self.equipped_theme not in self.inventory["themes"]:
            self.equipped_theme = None

    def theme_profile(self, theme_id=None):
        key = theme_id or self.equipped_theme or DEFAULT_THEME_ID
        return THEME_PROFILES.get(key, THEME_PROFILES[DEFAULT_THEME_ID])

    def generate_drops(self, source, count=1, chance=1.0):
        drops = []
        for _ in range(count):
            if random.random() > chance:
                continue
            rarity = self._weighted_choice(DROP_RARITY_WEIGHTS.get(source, DROP_RARITY_WEIGHTS["critical"]))
            drop_type = self._weighted_choice(DROP_TYPE_WEIGHTS.get(source, DROP_TYPE_WEIGHTS["critical"]))
            if drop_type == "title":
                item = random.choice(self._items_for_rarity(TITLE_DROPS, rarity))
                title = item["name"]
                already_owned = title in self.owned_titles
                self.owned_titles.add(title)
                self.inventory["titles"] = sorted(self.owned_titles)
                self.mark_dirty()
                drops.append({
                    "type": "title",
                    "name": title,
                    "rarity": item["rarity"],
                    "new": not already_owned,
                    "message": f"获得称号：{title}" if not already_owned else f"命运回声重复：{title}",
                })
            elif drop_type == "theme":
                item = random.choice(self._items_for_rarity(THEME_DROPS, rarity))
                theme_id = item["id"]
                already_owned = theme_id in self.inventory["themes"]
                if not already_owned:
                    self.inventory["themes"].append(theme_id)
                    self.inventory["themes"].sort()
                self.mark_dirty()
                drops.append({
                    "type": "theme",
                    "name": theme_id,
                    "label": item["label"],
                    "rarity": item["rarity"],
                    "new": not already_owned,
                    "message": f"新的光效主题已苏醒：{item['label']}" if not already_owned else f"命运回声重复：{item['label']}",
                })
            else:
                item = random.choice(self._items_for_rarity(FRAGMENT_DROPS, rarity))
                name = item["name"]
                fragments = self.inventory["fragments"]
                fragments[name] = fragments.get(name, 0) + 1
                self.mark_dirty()
                drops.append({
                    "type": "fragment",
                    "name": name,
                    "rarity": item["rarity"],
                    "quantity": fragments[name],
                    "new": fragments[name] == 1,
                    "message": f"命运回声掉落：{name} ×1",
                })
        return drops

    def equip_title(self, title):
        if not title:
            self.equipped_title = None
            return True
        if title not in self.owned_titles:
            return False
        self.equipped_title = title
        self.mark_dirty()
        return True

    def equip_theme(self, theme_id):
        if not theme_id:
            self.equipped_theme = None
            self.mark_dirty()
            return True
        if theme_id not in self.inventory.get("themes", []):
            return False
        if theme_id not in THEME_PROFILES:
            return False
        self.equipped_theme = theme_id
        self.mark_dirty()
        return True

    def forge_fragment_reward(self, fragment_name):
        self._normalize_inventory()
        reward = FRAGMENT_FORGE_REWARDS.get(fragment_name)
        fragments = self.inventory["fragments"]
        quantity = fragments.get(fragment_name, 0)
        if not reward:
            return {
                "success": False,
                "message": f"未知碎片：{fragment_name}",
                "needed": FRAGMENT_FORGE_COST,
                "have": quantity,
            }
        if quantity < FRAGMENT_FORGE_COST:
            return {
                "success": False,
                "message": f"{fragment_name} 还需要 {FRAGMENT_FORGE_COST - quantity} 个",
                "needed": FRAGMENT_FORGE_COST,
                "have": quantity,
            }

        remaining = quantity - FRAGMENT_FORGE_COST
        if remaining > 0:
            fragments[fragment_name] = remaining
        else:
            fragments.pop(fragment_name, None)

        if reward["type"] == "theme":
            theme_id = reward["name"]
            if theme_id not in self.inventory["themes"]:
                self.inventory["themes"].append(theme_id)
                self.inventory["themes"].sort()
            profile = self.theme_profile(theme_id)
            message = f"碎片锻造成光效主题：{profile['label']}"
            label = profile["label"]
        else:
            title = reward["name"]
            self.owned_titles.add(title)
            self.inventory["titles"] = sorted(self.owned_titles)
            message = f"碎片锻造成称号：{title}"
            label = title

        self.mark_dirty()
        self.add_chronicle("碎片锻造", message)
        return {
            "success": True,
            "type": reward["type"],
            "name": reward["name"],
            "label": label,
            "rarity": reward["rarity"],
            "message": message,
            "remaining": remaining,
        }

    def on_move(self, x, y, root=None):
        if self.last_mouse_pos is None:
            self.last_mouse_pos = (x, y)
            return None
        dx = x - self.last_mouse_pos[0]
        dy = y - self.last_mouse_pos[1]
        self.last_mouse_pos = (x, y)
        self.mouse_pixels += math.sqrt(dx * dx + dy * dy)
        if self.mouse_pixels < MOUSE_PX_THRESHOLD:
            return None
        self.mouse_pixels = 0.0
        points = MOUSE_MOVE_POINTS
        self.score += points
        self.total_score += points
        self.event_counts["move"] += 1
        self.last_event_time = time.time()
        xp_result = self._add_xp(points)
        mastery_result = self._mastery_for_event("move", points)
        self.mark_dirty()
        return {"type": "move", "points": points, **xp_result, "drops": xp_result["drops"], "mastery": mastery_result}

    def on_click(self, root=None):
        self._roll_daily_if_needed()
        points = CLICK_BASE_POINTS + random.randint(0, 8)
        _, _, mult, _ = self.combo_info()
        actual = int(points * mult)
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        self._bump_combo_timer(root)
        self.score += actual
        self.total_score += actual
        self.score_today += actual
        self.clicks_today += 1
        self.event_counts["click"] += 1
        self.last_event_time = time.time()
        xp_result = self._add_xp(actual)
        mastery_result = self._mastery_for_event("click", actual)
        drops = list(xp_result["drops"])
        if self.combo >= 30 or actual >= 50:
            drops.extend(self.generate_drops("critical", chance=0.08))
        self.mark_dirty()
        return {"type": "click", "points": actual, **xp_result, "drops": drops, "mastery": mastery_result}

    def on_type_char(self, root=None):
        self._roll_daily_if_needed()
        self.chars_buffer += 1
        self.chars_total += 1
        self.chars_today += 1
        if self.chars_buffer < TYPE_BURST_CHARS:
            return None
        self.chars_buffer = 0
        points = TYPE_BURST_POINTS + random.randint(0, 20)
        _, _, mult, _ = self.combo_info()
        actual = int(points * mult)
        self.combo += 2
        self.max_combo = max(self.max_combo, self.combo)
        self._bump_combo_timer(root)
        self.score += actual
        self.total_score += actual
        self.score_today += actual
        self.event_counts["type"] += 1
        self.last_event_time = time.time()
        xp_result = self._add_xp(actual)
        mastery_result = self._mastery_for_event("type", actual)
        drops = list(xp_result["drops"])
        if self.combo >= 30 or actual >= 50:
            drops.extend(self.generate_drops("critical", chance=0.08))
        self.mark_dirty()
        return {"type": "type", "points": actual, **xp_result, "drops": drops, "mastery": mastery_result}

    def check_achievements(self):
        snapshot = self._achievement_snapshot()
        newly = []
        for key, title, rarity, fn, target in ACHIEVEMENTS:
            if key in self.unlocked_achievements:
                continue
            try:
                if fn(snapshot) >= target:
                    self.unlocked_achievements.add(key)
                    newly.append((title, rarity))
                    self.mark_dirty()
            except Exception:
                pass
        return newly

    def check_challenges(self):
        """检查每日挑战完成情况，返回新完成的挑战列表 [(title, bonus_score)]"""
        self._roll_daily_if_needed()
        newly = []
        for key, title, attr, target, bonus in DAILY_CHALLENGES:
            if key in self.completed_challenges:
                continue
            current = getattr(self, attr, 0)
            if current >= target:
                self.completed_challenges.add(key)
                self.total_score += bonus
                self.score_today += bonus
                xp_result = self._add_xp(bonus)
                drops = list(xp_result["drops"])
                drops.extend(self.generate_drops("daily_challenge", chance=0.75))
                newly.append((title, bonus, xp_result, drops))
                self.mark_dirty()
        return newly

    def challenge_progress(self):
        """返回所有挑战进度：[(title, current, target, bonus, completed)]"""
        self._roll_daily_if_needed()
        out = []
        for key, title, attr, target, bonus in DAILY_CHALLENGES:
            current = min(getattr(self, attr, 0), target)
            out.append((title, current, target, bonus, key in self.completed_challenges))
        return out

    def _achievement_snapshot(self):
        return {
            "total_score": self.total_score,
            "level": self.level,
            "max_combo": self.max_combo,
            "chars_total": self.chars_total,
            "event_counts": self.event_counts,
        }

    def achievement_progress(self):
        """返回所有成就的进度列表：[(title, rarity, current, target, unlocked)]"""
        snapshot = self._achievement_snapshot()
        out = []
        for key, title, rarity, fn, target in ACHIEVEMENTS:
            try:
                current = min(fn(snapshot), target)
            except Exception:
                current = 0
            out.append((title, rarity, current, target, key in self.unlocked_achievements))
        return out

    def save(self):
        self._normalize_inventory()
        self._normalize_masteries()
        self._normalize_chronicle()
        data = {
            "total_score": self.total_score,
            "level": self.level,
            "xp": self.xp,
            "xp_needed": self.xp_needed,
            "xp_milestones_triggered": sorted(self.xp_milestones_triggered),
            "max_combo": self.max_combo,
            "chars_total": self.chars_total,
            "event_counts": self.event_counts,
            "unlocked_achievements": list(self.unlocked_achievements),
            "inventory": self.inventory,
            "owned_titles": sorted(self.owned_titles),
            "equipped_title": self.equipped_title,
            "equipped_theme": self.equipped_theme,
            "masteries": self.masteries,
            "chronicle": self.chronicle,
            "today": self.today,
            "chars_today": self.chars_today,
            "clicks_today": self.clicks_today,
            "score_today": self.score_today,
            "completed_challenges": list(self.completed_challenges),
            "daily_history": self.daily_history,
        }
        try:
            with open(SAVE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.dirty = False
            return True, None
        except Exception as exc:
            return False, str(exc)

    def load(self):
        if not os.path.exists(SAVE_FILE):
            return
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.total_score = data.get("total_score", 0)
            self.level = data.get("level", 1)
            self.xp = data.get("xp", 0)
            self.xp_needed = data.get("xp_needed", INITIAL_XP_NEEDED)
            milestones = set()
            for milestone in data.get("xp_milestones_triggered", []):
                try:
                    milestones.add(int(milestone))
                except (TypeError, ValueError):
                    pass
            self.xp_milestones_triggered = milestones
            self.max_combo = data.get("max_combo", 0)
            self.chars_total = data.get("chars_total", 0)
            self.event_counts = data.get("event_counts", {"move": 0, "click": 0, "type": 0})
            self.unlocked_achievements = set(data.get("unlocked_achievements", []))
            self.inventory = data.get("inventory", {"titles": [], "themes": [], "fragments": {}})
            self.owned_titles = set(data.get("owned_titles", self.inventory.get("titles", [])))
            self.equipped_title = data.get("equipped_title")
            self.equipped_theme = data.get("equipped_theme")
            self.masteries = data.get("masteries", self._default_masteries())
            self.chronicle = data.get("chronicle", [])
            self.today = data.get("today", self._today_str())
            self.chars_today = data.get("chars_today", 0)
            self.clicks_today = data.get("clicks_today", 0)
            self.score_today = data.get("score_today", 0)
            self.completed_challenges = set(data.get("completed_challenges", []))
            self.daily_history = data.get("daily_history", {})
            self.dirty = False
        except Exception:
            pass


class App:
    def __init__(self, root):
        if tk is None or ttk is None:
            _load_gui_modules()
        self.root = root
        self.state = RewardState()
        self.audio = AudioStateMachine()
        self.effects = DesktopEffects(root)
        self.overlay = make_overlay()  # 全屏特效层（PyObjC + WKWebView）
        self.log_entries = deque(maxlen=20)
        self._xp_visual = 0.0  # 用于 XP 进度条动画过渡
        self._last_save_error = 0

        root.title(APP_NAME)
        root.geometry("900x650")
        root.configure(bg=COLORS["BG"])
        root.minsize(720, 540)

        self._build_ui()
        self._apply_theme()
        self._bind_events()
        self._tick()
        self._slow_tick()
        self._autosave_tick()

        root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        header = tk.Frame(self.root, bg=COLORS["BG"])
        header.pack(fill=tk.X, padx=20, pady=(18, 10))

        title = tk.Label(
            header,
            text="奖励追踪器",
            font=("Helvetica", 22, "bold"),
            bg=COLORS["BG"],
            fg=COLORS["TEXT"],
        )
        title.pack(side=tk.LEFT)

        self.mute_btn = tk.Button(
            header,
            text="🔊 音效开",
            command=self._toggle_mute,
            bg=COLORS["SURFACE2"],
            fg=COLORS["TEXT"],
            activebackground=COLORS["SURFACE"],
            activeforeground=COLORS["ORANGE"],
            relief=tk.FLAT,
            padx=14,
            pady=6,
            font=("Helvetica", 11),
            cursor="hand2",
            highlightthickness=0,
            borderwidth=0,
        )
        self.mute_btn.pack(side=tk.RIGHT)

        self.lv_badge = tk.Label(
            header,
            text=f"LV.{self.state.level}",
            font=("Helvetica", 14, "bold"),
            bg=COLORS["ORANGE"],
            fg="white",
            padx=12,
            pady=4,
        )
        self.lv_badge.pack(side=tk.RIGHT, padx=12)

        self.title_badge = tk.Label(
            header,
            text=self._title_badge_text(),
            font=("Helvetica", 12, "bold"),
            bg=COLORS["SURFACE2"],
            fg=COLORS["CRYSTAL"],
            padx=10,
            pady=4,
        )
        self.title_badge.pack(side=tk.RIGHT)

        kpi = tk.Frame(self.root, bg=COLORS["BG"])
        kpi.pack(fill=tk.X, padx=20, pady=6)

        self.kpi_labels = {}
        for key, label, color in [
            ("total", "总积分", COLORS["CYAN"]),
            ("combo", "连击 ×1.0", COLORS["GOLD"]),
            ("move", "移动", COLORS["SUCCESS"]),
            ("click", "点击", COLORS["PURPLE"]),
            ("type", "打字", COLORS["ORANGE"]),
        ]:
            card = tk.Frame(kpi, bg=COLORS["SURFACE"], padx=14, pady=10)
            card.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
            tk.Label(
                card,
                text=label,
                bg=COLORS["SURFACE"],
                fg=COLORS["TEXT_MUTED"],
                font=("Helvetica", 10),
            ).pack(anchor=tk.W)
            value = tk.Label(
                card,
                text="0",
                bg=COLORS["SURFACE"],
                fg=color,
                font=("Helvetica", 18, "bold"),
            )
            value.pack(anchor=tk.W)
            self.kpi_labels[key] = (card, value)

        xp_frame = tk.Frame(self.root, bg=COLORS["BG"])
        xp_frame.pack(fill=tk.X, padx=20, pady=(10, 4))
        xp_header = tk.Frame(xp_frame, bg=COLORS["BG"])
        xp_header.pack(fill=tk.X)
        tk.Label(xp_header, text="CRYSTAL RESONANCE",
                 bg=COLORS["BG"], fg=COLORS["CRYSTAL"],
                 font=("Helvetica", 9, "bold")).pack(side=tk.LEFT)
        self.xp_pct_label = tk.Label(xp_header, text="0%",
                 bg=COLORS["BG"], fg=COLORS["TEXT_MUTED"],
                 font=("Helvetica", 9))
        self.xp_pct_label.pack(side=tk.RIGHT)
        self.xp_canvas = tk.Canvas(
            xp_frame, height=10, bg=COLORS["CRYSTAL_DIM"], highlightthickness=1,
            highlightbackground=COLORS["CRYSTAL"],
        )
        self.xp_canvas.pack(fill=tk.X, pady=(2, 0))
        self.xp_bar = self.xp_canvas.create_rectangle(0, 0, 0, 10, fill=COLORS["CRYSTAL"], width=0)
        self._xp_flash = False

        body = tk.Frame(self.root, bg=COLORS["BG"])
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        # 飘字 canvas overlay（沉底，不拦截输入）
        self.effects.setup_float_canvas(body)

        left = tk.Frame(body, bg=COLORS["SURFACE"])
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        tk.Label(
            left,
            text="在此打字触发奖励（每 10 字一次爆发）",
            bg=COLORS["SURFACE"],
            fg=COLORS["TEXT_MUTED"],
            font=("Helvetica", 10),
        ).pack(anchor=tk.W, padx=12, pady=(12, 4))

        self.text_input = tk.Text(
            left,
            height=10,
            bg=COLORS["SURFACE2"],
            fg=COLORS["TEXT"],
            insertbackground=COLORS["ORANGE"],
            relief=tk.FLAT,
            font=("Helvetica", 12),
            wrap=tk.WORD,
            padx=10,
            pady=10,
        )
        self.text_input.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        tk.Label(
            left,
            text="在此区域移动/点击也会触发奖励",
            bg=COLORS["SURFACE"],
            fg=COLORS["TEXT_MUTED"],
            font=("Helvetica", 10),
        ).pack(anchor=tk.W, padx=12, pady=(0, 6))

        self.play_area = tk.Canvas(
            left,
            bg=COLORS["SURFACE2"],
            height=100,
            highlightthickness=0,
        )
        self.play_area.pack(fill=tk.BOTH, expand=False, padx=12, pady=(0, 12))

        right = tk.Frame(body, bg=COLORS["SURFACE"], width=320)
        right.pack(side=tk.RIGHT, fill=tk.BOTH)
        right.pack_propagate(False)

        # 标签页：日志 / 成就 / 挑战 / 身份 / 统计
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TNotebook", background=COLORS["SURFACE"], borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=COLORS["SURFACE2"],
            foreground=COLORS["TEXT_MUTED"],
            padding=(10, 6),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLORS["SURFACE"])],
            foreground=[("selected", COLORS["ORANGE"])],
        )

        nb = ttk.Notebook(right)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # 日志
        log_tab = tk.Frame(nb, bg=COLORS["SURFACE"])
        nb.add(log_tab, text="日志")
        self.log_text = tk.Text(
            log_tab,
            bg=COLORS["SURFACE2"],
            fg=COLORS["TEXT"],
            relief=tk.FLAT,
            font=("Helvetica", 10),
            state=tk.DISABLED,
            wrap=tk.WORD,
            padx=8,
            pady=8,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # 成就
        ach_tab = tk.Frame(nb, bg=COLORS["SURFACE"])
        nb.add(ach_tab, text="成就")
        ach_canvas = tk.Canvas(ach_tab, bg=COLORS["SURFACE"], highlightthickness=0)
        ach_scroll = tk.Scrollbar(ach_tab, orient="vertical", command=ach_canvas.yview)
        self.ach_inner = tk.Frame(ach_canvas, bg=COLORS["SURFACE"])
        self.ach_inner.bind(
            "<Configure>",
            lambda e: ach_canvas.configure(scrollregion=ach_canvas.bbox("all")),
        )
        ach_canvas.create_window((0, 0), window=self.ach_inner, anchor="nw")
        ach_canvas.configure(yscrollcommand=ach_scroll.set)
        ach_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ach_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._ach_widgets = {}

        # 挑战
        ch_tab = tk.Frame(nb, bg=COLORS["SURFACE"])
        nb.add(ch_tab, text="挑战")
        self.ch_inner = tk.Frame(ch_tab, bg=COLORS["SURFACE"])
        self.ch_inner.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._ch_widgets = {}

        # 身份 / 背包
        identity_tab = tk.Frame(nb, bg=COLORS["SURFACE"])
        nb.add(identity_tab, text="身份")
        id_canvas = tk.Canvas(identity_tab, bg=COLORS["SURFACE"], highlightthickness=0)
        id_scroll = tk.Scrollbar(identity_tab, orient="vertical", command=id_canvas.yview)
        self.identity_inner = tk.Frame(id_canvas, bg=COLORS["SURFACE"])
        self.identity_inner.bind(
            "<Configure>",
            lambda e: id_canvas.configure(scrollregion=id_canvas.bbox("all")),
        )
        id_canvas.create_window((0, 0), window=self.identity_inner, anchor="nw")
        id_canvas.configure(yscrollcommand=id_scroll.set)
        id_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        id_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._identity_built = False
        self._title_buttons = {}
        self._theme_buttons = {}
        self._forge_buttons = {}
        self._identity_summary_labels = {}

        # 旅记
        chronicle_tab = tk.Frame(nb, bg=COLORS["SURFACE"])
        nb.add(chronicle_tab, text="旅记")
        chronicle_canvas = tk.Canvas(chronicle_tab, bg=COLORS["SURFACE"], highlightthickness=0)
        chronicle_scroll = tk.Scrollbar(chronicle_tab, orient="vertical", command=chronicle_canvas.yview)
        self.chronicle_inner = tk.Frame(chronicle_canvas, bg=COLORS["SURFACE"])
        self.chronicle_inner.bind(
            "<Configure>",
            lambda e: chronicle_canvas.configure(scrollregion=chronicle_canvas.bbox("all")),
        )
        chronicle_canvas.create_window((0, 0), window=self.chronicle_inner, anchor="nw")
        chronicle_canvas.configure(yscrollcommand=chronicle_scroll.set)
        chronicle_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        chronicle_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._chronicle_rows = []

        # 统计
        st_tab = tk.Frame(nb, bg=COLORS["SURFACE"])
        nb.add(st_tab, text="统计")
        self.st_inner = tk.Frame(st_tab, bg=COLORS["SURFACE"])
        self.st_inner.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.status_label = tk.Label(
            self.root,
            text=self._status_text(),
            bg=COLORS["BG"],
            fg=COLORS["TEXT_MUTED"],
            font=("Helvetica", 9),
            anchor=tk.W,
        )
        self.status_label.pack(fill=tk.X, padx=20, pady=(0, 10))

    def _status_text(self):
        sound_status = "静音" if self.audio.muted else "音效开"
        sfx_info = f"{len(self.audio.sound_files)} 个音效文件" if self.audio.sound_files else "使用合成音"
        return f"{sound_status} · {sfx_info} · 存档：{SAVE_FILE}"

    def _title_badge_text(self):
        title = self.state.equipped_title
        profile = self.state.theme_profile()
        identity = title if title else "未装备称号"
        return f"LV.{self.state.level} · {identity} · {profile['label']}"

    def _theme_colors(self):
        return self.state.theme_profile()

    def _show_passive_notice(self, title, subtitle="", color=None, category=None, big=False):
        color = color or COLORS["GOLD"]
        text = title if not subtitle else f"{title} · {subtitle}"
        if self.overlay:
            if not self.effects._notice_allowed(title, category):
                return
            try:
                self.overlay.float_text(text, color=color)
                return
            except Exception:
                self.effects.floating_text(text, color=color, big=big)
                return
        self.effects.show_passive_toast(
            title,
            subtitle=subtitle,
            color=color,
            category=category,
            big=big,
        )

    def _show_reward_notice(self, title, subtitle="", color=None, category=None, passive=False, big=False):
        if passive:
            self._show_passive_notice(
                title,
                subtitle=subtitle,
                color=color,
                category=category,
                big=big,
            )
            return
        self.effects.show_toast(
            title,
            subtitle=subtitle,
            color=color,
            category=category,
        )

    def _show_reward_achievement(self, title, rarity, passive=False):
        if passive:
            _, color = RARITY_CONFIG.get(rarity, ("成就", COLORS["GOLD"]))
            self._show_passive_notice(
                "命运铭文已刻下",
                subtitle=title,
                color=color,
                category=f"achievement_{title}",
                big=True,
            )
            return
        self.effects.show_achievement(title, rarity)

    def _apply_theme(self):
        profile = self._theme_colors()
        accent = profile["accent"]
        dim = profile["dim"]
        try:
            self.title_badge.configure(fg=accent)
            self.xp_canvas.configure(bg=dim, highlightbackground=accent)
            self.xp_canvas.itemconfigure(self.xp_bar, fill=accent)
        except Exception:
            pass

    def _bind_events(self):
        self.text_input.bind("<KeyPress>", self._on_key)
        self.root.bind("<Control-m>", lambda e: self._toggle_mute())
        self._global_listeners = []
        if HAS_PYNPUT:
            self._start_global_listeners()
        else:
            # fallback: 窗口内监听
            self.play_area.bind("<Motion>", self._on_mouse_move)
            self.play_area.bind("<Button-1>", self._on_click)

    def _start_global_listeners(self):
        def on_move(x, y):
            self.root.after(0, lambda: self._on_mouse_move_global(x, y))

        def on_click(x, y, button, pressed):
            if pressed:
                self.root.after(0, lambda: self._on_click_global())

        ml = pynput_mouse.Listener(on_move=on_move, on_click=on_click)
        ml.daemon = True
        ml.start()
        self._global_listeners.append(ml)

        def on_press(key):
            try:
                if hasattr(key, 'char') and key.char and key.char.isprintable():
                    self.root.after(0, self._on_key_global)
            except Exception:
                pass

        kl = pynput_keyboard.Listener(on_press=on_press)
        kl.daemon = True
        kl.start()
        self._global_listeners.append(kl)

    def _on_key(self, event):
        if event.char and event.char.isprintable():
            result = self.state.on_type_char(self.root)
            if result:
                self._on_reward(result, label="打字爆发")
        return None

    def _on_mouse_move(self, event):
        result = self.state.on_move(event.x, event.y, self.root)
        if result:
            self._on_reward(result, label="移动", quiet=True)

    def _on_mouse_move_global(self, x, y):
        result = self.state.on_move(x, y, self.root)
        if result:
            self._on_reward(result, label="移动", quiet=True)

    def _on_click(self, event):
        result = self.state.on_click(self.root)
        if result:
            self._on_reward(result, label="点击")

    def _on_click_global(self):
        result = self.state.on_click(self.root)
        if result:
            self._on_reward(result, label="点击")

    def _on_key_global(self):
        result = self.state.on_type_char(self.root)
        if result:
            self._on_reward(result, label="打字爆发")

    def _on_reward(self, result, label, quiet=False):
        self.audio.play(result["type"])
        color = {
            "click": COLORS["PURPLE"],
            "type": COLORS["CYAN"],
            "move": COLORS["SUCCESS"],
        }.get(result["type"], COLORS["GOLD"])
        theme = self._theme_colors()

        # 飘字：根据连击和积分选择
        if result["type"] in ("click", "type"):
            combo = self.state.combo
            pts = result["points"]
            text, critical = self.state.reward_flavor_text(result["type"], combo, pts)
            if critical:
                color = theme["accent_alt"]
            elif combo >= 15 or pts >= 30:
                color = theme["accent"]
            else:
                color = COLORS["SUCCESS"]
            if critical and self.state.equipped_title:
                text = f"{self.state.equipped_title} · {text}"

            # 全屏 overlay 优先（在鼠标位置触发）
            if self.overlay:
                try:
                    px = self.root.winfo_pointerx()
                    py = self.root.winfo_pointery()
                    if critical:
                        self.overlay.critical(text, x=px, y=py, color=color)
                    else:
                        self.overlay.float_text(text, x=px, y=py, color=color)
                except Exception:
                    pass
            else:
                self.effects.floating_text(text, color=color, big=critical)

        if not quiet:
            self._log(f"+{result['points']} {label}")

        mastery = result.get("mastery")
        if mastery:
            if mastery.get("leveled"):
                self.audio.play("achievement", priority=True)
                self._log(f"✧ {mastery['label']} 升到 Lv.{mastery['level_after']}")
                self._show_reward_notice(
                    "职业熟练度提升",
                    subtitle=f"{mastery['label']}  Lv.{mastery['level_after']}",
                    color=mastery["color"],
                    category=f"mastery_{mastery['id']}_{mastery['level_after']}",
                    passive=True,
                    big=True,
                )
            elif result["type"] in ("click", "type"):
                self._show_reward_notice(
                    mastery["label"],
                    subtitle=f"+{mastery['gained']} 熟练度",
                    color=mastery["color"],
                    category=f"mastery_tick_{mastery['id']}",
                    passive=True,
                )

        milestone_sounds = result.get("milestone_sounds", [])
        for i, milestone in enumerate(result.get("milestones", [])):
            sound = milestone_sounds[i] if i < len(milestone_sounds) else "xp_milestone"
            self.audio.play(sound, priority=True)
            label = XP_MILESTONE_LABELS.get(milestone, "田野回声")
            self._show_reward_notice(
                label,
                subtitle=f"经验 {milestone}% · 小路又亮了一段",
                color=COLORS["SUCCESS"] if milestone == 25 else COLORS["GOLD"] if milestone == 50 else COLORS["STAR"],
                category=f"xp_{self.state.level}_{milestone}",
                passive=True,
                big=milestone == 75,
            )

        if result.get("leveled"):
            self.audio.play("level_victory", priority=True)
            self._log(f"★ 牧场升级到 LV.{self.state.level}")
            if self.overlay:
                self.overlay.level_up(self.state.level)
                if self.state.equipped_title:
                    self.overlay.float_text(
                        f"{self.state.equipped_title} · 丰收升级",
                        color=COLORS["STAR"],
                    )
            else:
                level_text = f"丰收升级  LV.{self.state.level}"
                if self.state.equipped_title:
                    level_text = f"{self.state.equipped_title} · {level_text}"
                self.effects.floating_text(level_text, color=COLORS["STAR"], big=True)

        self._handle_drops(result.get("drops", []), passive=True)

        for title, rarity in self.state.check_achievements():
            self.audio.play("achievement", priority=True)
            self._log(f"🏆 {title}")
            if self.overlay:
                self.overlay.achievement(title, rarity)
            else:
                self._show_reward_achievement(title, rarity, passive=True)

        for title, bonus, xp_result, drops in self.state.check_challenges():
            self.audio.play("achievement", priority=True)
            self._log(f"🎯 挑战完成：{title} +{bonus}")
            challenge_sounds = xp_result.get("milestone_sounds", [])
            for i, milestone in enumerate(xp_result.get("milestones", [])):
                sound = challenge_sounds[i] if i < len(challenge_sounds) else "xp_milestone"
                self.audio.play(sound, priority=True)
            self._show_reward_notice(
                "🎯 试炼完成",
                subtitle=f"{title}  +{bonus} EXP",
                color=COLORS["CYAN"],
                category=f"ch_{title}",
                passive=True,
                big=True,
            )
            self._handle_drops(drops, passive=True)

    def _drop_color(self, drop):
        _, color = RARITY_CONFIG.get(drop.get("rarity"), ("", COLORS["GOLD"]))
        return color

    def _handle_drops(self, drops, passive=False):
        for drop in drops:
            message = drop.get("message") or drop.get("name", "命运回声掉落")
            color = self._drop_color(drop)
            self._log(f"✦ {message}")
            self._show_reward_notice(
                "命运回声",
                subtitle=message,
                color=color,
                category=f"drop_{drop.get('type')}_{drop.get('name')}_{time.time()}",
                passive=passive,
                big=drop.get("rarity") in ("crystal", "star"),
            )
            if not passive:
                if self.overlay:
                    try:
                        self.overlay.float_text(message, color=color)
                    except Exception:
                        pass
                else:
                    self.effects.floating_text(message, color=color, big=drop.get("rarity") in ("crystal", "star"))
        if drops:
            self._refresh_identity_panel()
            self.title_badge.configure(text=self._title_badge_text())

    def _toggle_mute(self):
        muted = self.audio.toggle_mute()
        self.mute_btn.configure(text="🔇 已静音" if muted else "🔊 音效开")
        self.status_label.configure(text=self._status_text())

    def _log(self, message):
        ts = time.strftime("%H:%M:%S")
        self.log_entries.appendleft(f"[{ts}] {message}")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.insert("1.0", "\n".join(self.log_entries))
        self.log_text.configure(state=tk.DISABLED)

    def _equip_title(self, title):
        if self.state.equip_title(title):
            self._log(f"称号已装备：{title}")
            self.effects.show_toast(
                "身份更新",
                subtitle=f"LV.{self.state.level} · {title}",
                color=COLORS["CRYSTAL"],
                category=f"equip_{title}_{time.time()}",
            )
            self._refresh_identity_panel()
            self.title_badge.configure(text=self._title_badge_text())
        else:
            self._log(f"无法装备未拥有称号：{title}")

    def _equip_theme(self, theme_id):
        profile = self.state.theme_profile(theme_id)
        if self.state.equip_theme(theme_id):
            self._apply_theme()
            self._log(f"光效主题已装备：{profile['label']}")
            self.effects.show_toast(
                "光效更新",
                subtitle=profile["label"],
                color=profile["accent"],
                category=f"theme_{theme_id}_{time.time()}",
            )
            self._refresh_identity_panel()
            self.title_badge.configure(text=self._title_badge_text())
        else:
            self._log(f"无法装备未拥有主题：{profile['label']}")

    def _forge_fragment(self, fragment_name):
        result = self.state.forge_fragment_reward(fragment_name)
        color = self._drop_color(result) if result.get("success") else COLORS["TEXT_MUTED"]
        self._log(result["message"])
        self.effects.show_toast(
            "碎片锻造" if result.get("success") else "碎片不足",
            subtitle=result["message"],
            color=color,
            category=f"forge_{fragment_name}_{time.time()}",
        )
        if result.get("success"):
            self.effects.floating_text(result["message"], color=color, big=result.get("rarity") in ("crystal", "star"))
        self._refresh_identity_panel()

    def _build_identity_panel(self):
        self._identity_built = True
        header = tk.Label(
            self.identity_inner,
            text="当前身份",
            bg=COLORS["SURFACE"],
            fg=COLORS["TEXT_MUTED"],
            font=("Helvetica", 10, "bold"),
            anchor="w",
        )
        header.pack(fill=tk.X, padx=8, pady=(8, 2))

        current = tk.Label(
            self.identity_inner,
            text="",
            bg=COLORS["SURFACE"],
            fg=COLORS["CRYSTAL"],
            font=("Helvetica", 13, "bold"),
            anchor="w",
            wraplength=250,
            justify=tk.LEFT,
        )
        current.pack(fill=tk.X, padx=8, pady=(0, 8))
        self._identity_summary_labels["current"] = current

        theme_current = tk.Label(
            self.identity_inner,
            text="",
            bg=COLORS["SURFACE"],
            fg=COLORS["GOLD"],
            font=("Helvetica", 11, "bold"),
            anchor="w",
            wraplength=250,
            justify=tk.LEFT,
        )
        theme_current.pack(fill=tk.X, padx=8, pady=(0, 10))
        self._identity_summary_labels["theme_current"] = theme_current

        tk.Label(
            self.identity_inner,
            text="称号",
            bg=COLORS["SURFACE"],
            fg=COLORS["TEXT_MUTED"],
            font=("Helvetica", 10, "bold"),
            anchor="w",
        ).pack(fill=tk.X, padx=8, pady=(4, 2))

        self.titles_frame = tk.Frame(self.identity_inner, bg=COLORS["SURFACE"])
        self.titles_frame.pack(fill=tk.X, padx=8)

        tk.Label(
            self.identity_inner,
            text="光效主题",
            bg=COLORS["SURFACE"],
            fg=COLORS["TEXT_MUTED"],
            font=("Helvetica", 10, "bold"),
            anchor="w",
        ).pack(fill=tk.X, padx=8, pady=(12, 2))

        self.themes_frame = tk.Frame(self.identity_inner, bg=COLORS["SURFACE"])
        self.themes_frame.pack(fill=tk.X, padx=8)

        tk.Label(
            self.identity_inner,
            text="背包摘要",
            bg=COLORS["SURFACE"],
            fg=COLORS["TEXT_MUTED"],
            font=("Helvetica", 10, "bold"),
            anchor="w",
        ).pack(fill=tk.X, padx=8, pady=(12, 2))

        for key in ("themes", "fragments"):
            label = tk.Label(
                self.identity_inner,
                text="",
                bg=COLORS["SURFACE"],
                fg=COLORS["TEXT"],
                font=("Helvetica", 10),
                anchor="w",
                wraplength=250,
                justify=tk.LEFT,
            )
            label.pack(fill=tk.X, padx=8, pady=3)
            self._identity_summary_labels[key] = label

        tk.Label(
            self.identity_inner,
            text="碎片锻造",
            bg=COLORS["SURFACE"],
            fg=COLORS["TEXT_MUTED"],
            font=("Helvetica", 10, "bold"),
            anchor="w",
        ).pack(fill=tk.X, padx=8, pady=(12, 2))

        self.forge_frame = tk.Frame(self.identity_inner, bg=COLORS["SURFACE"])
        self.forge_frame.pack(fill=tk.X, padx=8)

    def _title_rarity(self, title):
        for item in TITLE_DROPS:
            if item["name"] == title:
                return item["rarity"]
        return "bronze"

    def _refresh_identity_panel(self):
        if not self._identity_built:
            self._build_identity_panel()

        equipped = self.state.equipped_title
        current = f"LV.{self.state.level} · {equipped}" if equipped else "尚未装备称号"
        self._identity_summary_labels["current"].configure(text=current)
        profile = self.state.theme_profile()
        self._identity_summary_labels["theme_current"].configure(
            text=f"当前光效：{profile['label']}",
            fg=profile["accent"],
        )

        owned = sorted(self.state.owned_titles)
        visible_titles = set(owned)
        stale = set(self._title_buttons) - visible_titles
        for title in stale:
            self._title_buttons[title].destroy()
            del self._title_buttons[title]

        for title in owned:
            rarity = self._title_rarity(title)
            _, color = RARITY_CONFIG.get(rarity, ("", COLORS["CRYSTAL"]))
            if title not in self._title_buttons:
                btn = tk.Button(
                    self.titles_frame,
                    text=title,
                    command=lambda t=title: self._equip_title(t),
                    bg=COLORS["SURFACE2"],
                    fg=color,
                    activebackground=COLORS["SURFACE"],
                    activeforeground=color,
                    relief=tk.FLAT,
                    padx=8,
                    pady=5,
                    font=("Helvetica", 10, "bold"),
                    cursor="hand2",
                    highlightthickness=0,
                    borderwidth=0,
                    anchor="w",
                )
                btn.pack(fill=tk.X, pady=3)
                self._title_buttons[title] = btn
            prefix = "✓ " if title == equipped else ""
            self._title_buttons[title].configure(text=f"{prefix}{title}", fg=color)

        if not owned and not hasattr(self, "_empty_title_label"):
            self._empty_title_label = tk.Label(
                self.titles_frame,
                text="尚未获得称号",
                bg=COLORS["SURFACE"],
                fg=COLORS["TEXT_MUTED"],
                font=("Helvetica", 10),
                anchor="w",
            )
            self._empty_title_label.pack(fill=tk.X, pady=3)
        elif owned and hasattr(self, "_empty_title_label"):
            self._empty_title_label.destroy()
            del self._empty_title_label

        themes = self.state.inventory.get("themes", [])
        visible_themes = set(themes)
        stale_themes = set(self._theme_buttons) - visible_themes
        for theme_id in stale_themes:
            self._theme_buttons[theme_id].destroy()
            del self._theme_buttons[theme_id]

        for theme_id in sorted(themes):
            profile = self.state.theme_profile(theme_id)
            if theme_id not in self._theme_buttons:
                btn = tk.Button(
                    self.themes_frame,
                    text=profile["label"],
                    command=lambda t=theme_id: self._equip_theme(t),
                    bg=COLORS["SURFACE2"],
                    fg=profile["accent"],
                    activebackground=COLORS["SURFACE"],
                    activeforeground=profile["accent_alt"],
                    relief=tk.FLAT,
                    padx=8,
                    pady=5,
                    font=("Helvetica", 10, "bold"),
                    cursor="hand2",
                    highlightthickness=0,
                    borderwidth=0,
                    anchor="w",
                )
                btn.pack(fill=tk.X, pady=3)
                self._theme_buttons[theme_id] = btn
            prefix = "✓ " if theme_id == self.state.equipped_theme else ""
            self._theme_buttons[theme_id].configure(
                text=f"{prefix}{profile['label']}",
                fg=profile["accent"],
            )

        if not themes and not hasattr(self, "_empty_theme_label"):
            self._empty_theme_label = tk.Label(
                self.themes_frame,
                text="尚未获得光效主题",
                bg=COLORS["SURFACE"],
                fg=COLORS["TEXT_MUTED"],
                font=("Helvetica", 10),
                anchor="w",
            )
            self._empty_theme_label.pack(fill=tk.X, pady=3)
        elif themes and hasattr(self, "_empty_theme_label"):
            self._empty_theme_label.destroy()
            del self._empty_theme_label

        theme_labels = [self.state.theme_profile(theme_id)["label"] for theme_id in themes]
        theme_text = "光效主题：" + ("、".join(theme_labels) if theme_labels else "尚未苏醒")
        fragments = self.state.inventory.get("fragments", {})
        if fragments:
            fragment_text = "碎片：" + "、".join(f"{name} ×{count}" for name, count in sorted(fragments.items()))
        else:
            fragment_text = "碎片：空"
        self._identity_summary_labels["themes"].configure(text=theme_text)
        self._identity_summary_labels["fragments"].configure(text=fragment_text)

        visible_fragments = set(FRAGMENT_FORGE_REWARDS)
        stale_forge = set(self._forge_buttons) - visible_fragments
        for name in stale_forge:
            self._forge_buttons[name].destroy()
            del self._forge_buttons[name]

        for fragment_name, reward in FRAGMENT_FORGE_REWARDS.items():
            quantity = fragments.get(fragment_name, 0)
            if reward["type"] == "theme":
                reward_label = self.state.theme_profile(reward["name"])["label"]
                action_text = f"{fragment_name} {quantity}/{FRAGMENT_FORGE_COST} -> {reward_label}"
            else:
                action_text = f"{fragment_name} {quantity}/{FRAGMENT_FORGE_COST} -> {reward['name']}"
            enabled = quantity >= FRAGMENT_FORGE_COST
            if fragment_name not in self._forge_buttons:
                btn = tk.Button(
                    self.forge_frame,
                    command=lambda name=fragment_name: self._forge_fragment(name),
                    bg=COLORS["SURFACE2"],
                    activebackground=COLORS["SURFACE"],
                    relief=tk.FLAT,
                    padx=8,
                    pady=5,
                    font=("Helvetica", 10),
                    cursor="hand2",
                    highlightthickness=0,
                    borderwidth=0,
                    anchor="w",
                )
                btn.pack(fill=tk.X, pady=3)
                self._forge_buttons[fragment_name] = btn
            self._forge_buttons[fragment_name].configure(
                text=action_text,
                fg=COLORS["STAR"] if enabled else COLORS["TEXT_MUTED"],
                state=tk.NORMAL if enabled else tk.DISABLED,
            )

    def _refresh_achievements_panel(self):
        # 成就面板
        progress = self.state.achievement_progress()
        for title, rarity, current, target, unlocked in progress:
            _, rarity_color = RARITY_CONFIG.get(rarity, ("", COLORS["CYAN"]))
            if title not in self._ach_widgets:
                row = tk.Frame(self.ach_inner, bg=COLORS["SURFACE"])
                row.pack(fill=tk.X, padx=6, pady=4)
                name = tk.Label(row, text="", bg=COLORS["SURFACE"], fg=COLORS["TEXT"],
                    font=("Helvetica", 11, "bold"), anchor="w")
                name.pack(fill=tk.X)
                bar = tk.Canvas(row, height=6, bg=COLORS["SURFACE2"], highlightthickness=0)
                bar.pack(fill=tk.X, pady=(2, 0))
                rect = bar.create_rectangle(0, 0, 0, 6, fill=rarity_color, width=0)
                hint = tk.Label(row, text="", bg=COLORS["SURFACE"], fg=COLORS["TEXT_MUTED"],
                    font=("Helvetica", 9), anchor="w")
                hint.pack(fill=tk.X)
                self._ach_widgets[title] = (name, bar, rect, hint)
            name, bar, rect, hint = self._ach_widgets[title]
            if unlocked:
                name.configure(text=f"✦ {title}", fg=rarity_color)
                hint.configure(text=RARITY_CONFIG.get(rarity, ("已解锁",))[0])
                w = max(bar.winfo_width(), 1)
                bar.coords(rect, 0, 0, w, 6)
                bar.itemconfigure(rect, fill=rarity_color)
            else:
                name.configure(text=title, fg=COLORS["TEXT_MUTED"])
                pct = current / target if target else 0
                w = max(bar.winfo_width(), 1)
                bar.coords(rect, 0, 0, w * pct, 6)
                bar.itemconfigure(rect, fill=rarity_color)
                hint.configure(text=f"{current} / {target}")

        # 挑战面板
        for title, current, target, bonus, completed in self.state.challenge_progress():
            if title not in self._ch_widgets:
                row = tk.Frame(self.ch_inner, bg=COLORS["SURFACE"])
                row.pack(fill=tk.X, padx=6, pady=6)
                name = tk.Label(
                    row, text="", bg=COLORS["SURFACE"], fg=COLORS["TEXT"],
                    font=("Helvetica", 11, "bold"), anchor="w",
                )
                name.pack(fill=tk.X)
                bar = tk.Canvas(row, height=8, bg=COLORS["SURFACE2"], highlightthickness=0)
                bar.pack(fill=tk.X, pady=(2, 0))
                rect = bar.create_rectangle(0, 0, 0, 8, fill=COLORS["ORANGE"], width=0)
                hint = tk.Label(
                    row, text="", bg=COLORS["SURFACE"], fg=COLORS["TEXT_MUTED"],
                    font=("Helvetica", 9), anchor="w",
                )
                hint.pack(fill=tk.X)
                self._ch_widgets[title] = (name, bar, rect, hint)
            name, bar, rect, hint = self._ch_widgets[title]
            if completed:
                name.configure(text=f"✓ {title}", fg=COLORS["CYAN"])
                hint.configure(text=f"已完成 +{bonus}")
                w = max(bar.winfo_width(), 1)
                bar.coords(rect, 0, 0, w, 8)
                bar.itemconfigure(rect, fill=COLORS["CYAN"])
            else:
                name.configure(text=f"🎯 {title}", fg=COLORS["TEXT"])
                pct = current / target if target else 0
                w = max(bar.winfo_width(), 1)
                bar.coords(rect, 0, 0, w * pct, 8)
                bar.itemconfigure(rect, fill=COLORS["ORANGE"])
                hint.configure(text=f"{current} / {target}  ·  奖励 +{bonus}")

        # 统计面板
        if not hasattr(self, "_st_built"):
            self._build_stats_panel()
            self._st_built = True
        self._update_stats_panel()
        self._refresh_identity_panel()
        self._refresh_chronicle_panel()

    def _refresh_chronicle_panel(self):
        for row in self._chronicle_rows:
            row.destroy()
        self._chronicle_rows = []
        entries = list(reversed(self.state.chronicle[-18:]))
        if not entries:
            empty = tk.Label(
                self.chronicle_inner,
                text="旅记尚未展开",
                bg=COLORS["SURFACE"],
                fg=COLORS["TEXT_MUTED"],
                font=("Helvetica", 10),
                anchor="w",
            )
            empty.pack(fill=tk.X, padx=8, pady=8)
            self._chronicle_rows.append(empty)
            return
        for entry in entries:
            row = tk.Frame(self.chronicle_inner, bg=COLORS["SURFACE"])
            row.pack(fill=tk.X, padx=8, pady=6)
            tk.Label(
                row,
                text=f"{entry['title']} · {entry['time']}",
                bg=COLORS["SURFACE"],
                fg=COLORS["GOLD"],
                font=("Helvetica", 10, "bold"),
                anchor="w",
                wraplength=250,
                justify=tk.LEFT,
            ).pack(fill=tk.X)
            tk.Label(
                row,
                text=entry["text"],
                bg=COLORS["SURFACE"],
                fg=COLORS["TEXT"],
                font=("Helvetica", 10),
                anchor="w",
                wraplength=250,
                justify=tk.LEFT,
            ).pack(fill=tk.X, pady=(2, 0))
            self._chronicle_rows.append(row)

    def _tick(self):
        self.kpi_labels["total"][1].configure(text=f"{self.state.total_score}")
        _, tier_name, mult, tier_color = self.state.combo_info()
        self.kpi_labels["combo"][1].configure(
            text=f"×{mult:.1f} {tier_name}({self.state.combo})",
            fg=tier_color,
        )
        self.kpi_labels["move"][1].configure(text=f"{self.state.event_counts['move']}")
        self.kpi_labels["click"][1].configure(text=f"{self.state.event_counts['click']}")
        self.kpi_labels["type"][1].configure(text=f"{self.state.event_counts['type']}")
        self.lv_badge.configure(text=f"LV.{self.state.level}")
        self.title_badge.configure(text=self._title_badge_text())

        # XP 水晶槽动画
        target = self.state.xp / max(self.state.xp_needed, 1)
        diff = target - self._xp_visual
        self._xp_visual += diff * 0.22
        if abs(diff) < 0.002:
            self._xp_visual = target
        width = max(self.xp_canvas.winfo_width(), 1)
        self.xp_canvas.coords(self.xp_bar, 0, 0, width * self._xp_visual, 10)
        self.xp_pct_label.configure(text=f"{int(self._xp_visual * 100)}%")

        # 接近升级（>80%）时闪烁
        if self._xp_visual >= 0.8:
            self._xp_flash = not self._xp_flash
            theme = self._theme_colors()
            flash_color = theme["accent_alt"] if self._xp_flash else theme["accent"]
            self.xp_canvas.itemconfigure(self.xp_bar, fill=flash_color)
        else:
            self.xp_canvas.itemconfigure(self.xp_bar, fill=self._theme_colors()["accent"])

        self.root.after(120, self._tick)

    def _slow_tick(self):
        """低频刷新：成就/挑战/统计面板，2s 一次"""
        self._refresh_achievements_panel()
        self.root.after(2000, self._slow_tick)

    def _save_if_dirty(self, force=False):
        if not force and not self.state.dirty:
            return True
        ok, err = self.state.save()
        if not ok:
            now = time.time()
            if now - self._last_save_error > 10:
                self._last_save_error = now
                self._log(f"存档失败：{err}")
        return ok

    def _autosave_tick(self):
        self._save_if_dirty()
        self.root.after(10000, self._autosave_tick)

    def _build_stats_panel(self):
        self._stat_labels = {}
        rows = [
            ("today_score", "今日积分"),
            ("today_clicks", "今日点击"),
            ("today_chars", "今日打字"),
            ("week_score", "本周积分"),
            ("session_minutes", "本次时长"),
            ("max_combo", "历史最高连击"),
        ]
        for key, label in rows:
            row = tk.Frame(self.st_inner, bg=COLORS["SURFACE"])
            row.pack(fill=tk.X, pady=4)
            tk.Label(row, text=label, bg=COLORS["SURFACE"], fg=COLORS["TEXT_MUTED"],
                     font=("Helvetica", 10), anchor="w").pack(side=tk.LEFT)
            v = tk.Label(row, text="0", bg=COLORS["SURFACE"], fg=COLORS["TEXT"],
                         font=("Helvetica", 12, "bold"), anchor="e")
            v.pack(side=tk.RIGHT)
            self._stat_labels[key] = v
        tk.Label(self.st_inner, text="职业熟练度", bg=COLORS["SURFACE"],
                 fg=COLORS["TEXT_MUTED"], font=("Helvetica", 10, "bold"), anchor="w").pack(fill=tk.X, pady=(14, 4))
        self._mastery_widgets = {}
        for key, config in MASTERY_DEFS.items():
            row = tk.Frame(self.st_inner, bg=COLORS["SURFACE"])
            row.pack(fill=tk.X, pady=4)
            name = tk.Label(
                row,
                text=config["label"],
                bg=COLORS["SURFACE"],
                fg=config["color"],
                font=("Helvetica", 10, "bold"),
                anchor="w",
            )
            name.pack(fill=tk.X)
            bar = tk.Canvas(row, height=7, bg=COLORS["SURFACE2"], highlightthickness=0)
            bar.pack(fill=tk.X, pady=(2, 0))
            rect = bar.create_rectangle(0, 0, 0, 7, fill=config["color"], width=0)
            hint = tk.Label(row, text="", bg=COLORS["SURFACE"], fg=COLORS["TEXT_MUTED"],
                            font=("Helvetica", 9), anchor="w")
            hint.pack(fill=tk.X)
            self._mastery_widgets[key] = (bar, rect, hint)
        tk.Label(self.st_inner, text="近 7 日积分趋势", bg=COLORS["SURFACE"],
                 fg=COLORS["TEXT_MUTED"], font=("Helvetica", 10), anchor="w").pack(fill=tk.X, pady=(14, 4))
        self.trend_canvas = tk.Canvas(self.st_inner, height=120, bg=COLORS["SURFACE2"], highlightthickness=0)
        self.trend_canvas.pack(fill=tk.X)

    def _update_stats_panel(self):
        s = self.state
        self._stat_labels["today_score"].configure(text=f"{s.score_today}")
        self._stat_labels["today_clicks"].configure(text=f"{s.clicks_today}")
        self._stat_labels["today_chars"].configure(text=f"{s.chars_today}")
        week_score = s.score_today
        for i in range(1, 7):
            d = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
            week_score += s.daily_history.get(d, {}).get("score", 0)
        self._stat_labels["week_score"].configure(text=f"{week_score}")
        elapsed = int((time.time() - s.session_start) / 60)
        self._stat_labels["session_minutes"].configure(text=f"{elapsed} 分钟")
        self._stat_labels["max_combo"].configure(text=f"{s.max_combo}")
        s._normalize_masteries()
        for key, (bar, rect, hint) in self._mastery_widgets.items():
            data = s.masteries[key]
            config = MASTERY_DEFS[key]
            pct = data["xp"] / max(data["xp_needed"], 1)
            w = max(bar.winfo_width(), 1)
            bar.coords(rect, 0, 0, w * pct, 7)
            bar.itemconfigure(rect, fill=config["color"])
            hint.configure(text=f"Lv.{data['level']}  {data['xp']} / {data['xp_needed']}")
        # 趋势图
        c = self.trend_canvas
        c.delete("all")
        days = []
        for i in range(6, -1, -1):
            d = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
            days.append(s.score_today if i == 0 else s.daily_history.get(d, {}).get("score", 0))
        max_v = max(days) or 1
        c.update_idletasks()
        w = max(c.winfo_width(), 200)
        h, n = 120, len(days)
        bar_w = w / n - 4
        for i, v in enumerate(days):
            bh = int((v / max_v) * (h - 24))
            x0 = i * (bar_w + 4) + 2
            y0 = h - bh - 14
            x1 = x0 + bar_w
            color = COLORS["ORANGE"] if i == n - 1 else COLORS["CYAN"]
            c.create_rectangle(x0, y0, x1, h - 14, fill=color, width=0)
            if v > 0:
                c.create_text((x0 + x1) / 2, y0 - 6, text=str(v),
                               fill=COLORS["TEXT_MUTED"], font=("Helvetica", 8))

    def _on_close(self):
        try:
            self._save_if_dirty(force=True)
            self.audio.shutdown()
            if self.overlay:
                try:
                    self.overlay.shutdown()
                except Exception:
                    pass
            for l in getattr(self, "_global_listeners", []):
                try:
                    l.stop()
                except Exception:
                    pass
        finally:
            self.root.destroy()


def main():
    if "--print-tk-launcher" in sys.argv:
        safe_python = _find_safe_tk_python()
        print(safe_python or sys.executable)
        return
    if "--self-test" in sys.argv:
        raise SystemExit(run_self_test())
    _load_gui_modules()
    root = tk.Tk()
    App(root)
    root.mainloop()


def run_self_test(verbose=True):
    def report(message):
        if verbose:
            print(message)

    global SAVE_FILE
    old_save_file = SAVE_FILE
    with tempfile.TemporaryDirectory() as tmpdir:
        SAVE_FILE = os.path.join(tmpdir, "self-test-save.json")
        try:
            state = RewardState()
            click = state.on_click()
            if not click.get("mastery") or click["mastery"]["id"] != "chainbreaker":
                report("self-test failed: expected click mastery")
                return 1
            result = state._add_xp(220)
            if not result["leveled"]:
                report("self-test failed: expected level-up")
                return 1
            if not result["drops"]:
                report("self-test failed: expected level-up drop")
                return 1
            state.inventory["themes"].append("ember_heart")
            if not state.equip_theme("ember_heart"):
                report("self-test failed: expected theme equip")
                return 1
            state.owned_titles.add("水晶铭文师")
            if not state.equip_title("水晶铭文师"):
                report("self-test failed: expected title equip")
                return 1
            state.inventory["fragments"]["梦晶碎片"] = FRAGMENT_FORGE_COST
            forged = state.forge_fragment_reward("梦晶碎片")
            if not forged.get("success") or forged["name"] not in state.owned_titles:
                report("self-test failed: expected fragment forge")
                return 1
            if not state.chronicle:
                report("self-test failed: expected chronicle entry")
                return 1
            ok, err = state.save()
            if not ok:
                report(f"self-test failed: save error: {err}")
                return 1
            report(
                "self-test ok: "
                f"LV.{state.level}, drops={len(result['drops'])}, "
                f"title={state.equipped_title}, theme={state.theme_profile()['label']}, "
                f"forge={forged['label']}"
            )
            return 0
        finally:
            SAVE_FILE = old_save_file


if __name__ == "__main__":
    main()
