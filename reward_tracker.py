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
import tkinter as tk
import wave
from collections import deque
from tkinter import ttk

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

try:
    from effects_overlay import make_overlay
    HAS_OVERLAY = True
except ImportError:
    HAS_OVERLAY = False
    def make_overlay():
        return None


APP_NAME = "奖励追踪器 v3"
SAVE_FILE = os.path.expanduser("~/.reward_tracker_v3.json")
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

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
            "achievement": "sfx_level_up.wav",
        }
        resolved = {}
        for key, fname in mapping.items():
            path = os.path.join(ASSETS_DIR, fname)
            if os.path.exists(path):
                resolved[key] = path
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
        freqs = {
            "move": [(660, 0.05)],
            "click": [(880, 0.08)],
            "type": [(523, 0.04), (784, 0.06)],
            "level_up": [(523, 0.08), (659, 0.08), (784, 0.1), (1047, 0.15)],
            "achievement": [(523, 0.08), (784, 0.1), (1047, 0.12)],
        }
        seq = freqs.get(category, [(440, 0.08)])
        samples = []
        sample_rate = 22050
        for f, dur in seq:
            t = np.linspace(0, dur, int(sample_rate * dur), endpoint=False)
            envelope = np.exp(-3 * t / dur)
            wave_samples = np.sin(2 * np.pi * f * t) * 0.15 * envelope
            samples.extend(wave_samples)
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

    # ── Toast（右上角，无焦点）─────────────────────────────────────────────
    def show_toast(self, title, subtitle="", color=None, category=None):
        color = color or COLORS["GOLD"]
        now = time.time()
        key = category or title
        if now - self._toast_last.get(key, 0) < 5.0:
            return
        self._toast_last[key] = now
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

    # ── 升级弹窗 CRYSTAL AWAKENED ──────────────────────────────────────────
    def show_level_up(self, level):
        self._modal_queue.append(("level", level, None))
        if not self._modal_active:
            self._show_next_modal()

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

            tk.Label(inner, text="✦  CRYSTAL AWAKENED  ✦",
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
        # 历史趋势（每日积分）
        self.daily_history = {}
        self.load()
        self._roll_daily_if_needed()

    @staticmethod
    def _today_str():
        return time.strftime("%Y-%m-%d")

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

    def _add_xp(self, amount):
        leveled = False
        self.xp += amount
        while self.xp >= self.xp_needed:
            self.xp -= self.xp_needed
            self.level += 1
            self.xp_needed = int(self.xp_needed * XP_GROWTH)
            leveled = True
        return leveled

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
        leveled = self._add_xp(points)
        return {"type": "move", "points": points, "leveled": leveled}

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
        leveled = self._add_xp(actual)
        return {"type": "click", "points": actual, "leveled": leveled}

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
        leveled = self._add_xp(actual)
        return {"type": "type", "points": actual, "leveled": leveled}

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
                self._add_xp(bonus)
                newly.append((title, bonus))
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
        data = {
            "total_score": self.total_score,
            "level": self.level,
            "xp": self.xp,
            "xp_needed": self.xp_needed,
            "max_combo": self.max_combo,
            "chars_total": self.chars_total,
            "event_counts": self.event_counts,
            "unlocked_achievements": list(self.unlocked_achievements),
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
        except Exception:
            pass

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
            self.max_combo = data.get("max_combo", 0)
            self.chars_total = data.get("chars_total", 0)
            self.event_counts = data.get("event_counts", {"move": 0, "click": 0, "type": 0})
            self.unlocked_achievements = set(data.get("unlocked_achievements", []))
            self.today = data.get("today", self._today_str())
            self.chars_today = data.get("chars_today", 0)
            self.clicks_today = data.get("clicks_today", 0)
            self.score_today = data.get("score_today", 0)
            self.completed_challenges = set(data.get("completed_challenges", []))
            self.daily_history = data.get("daily_history", {})
        except Exception:
            pass


class App:
    def __init__(self, root):
        self.root = root
        self.state = RewardState()
        self.audio = AudioStateMachine()
        self.effects = DesktopEffects(root)
        self.overlay = make_overlay()  # 全屏特效层（PyObjC + WKWebView）
        self.log_entries = deque(maxlen=20)
        self._xp_visual = 0.0  # 用于 XP 进度条动画过渡

        root.title(APP_NAME)
        root.geometry("900x650")
        root.configure(bg=COLORS["BG"])
        root.minsize(720, 540)

        self._build_ui()
        self._bind_events()
        self._tick()
        self._slow_tick()

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

        # 标签页：日志 / 成就 / 挑战 / 统计
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

        # 飘字：根据连击和积分选择
        if result["type"] in ("click", "type"):
            combo = self.state.combo
            pts = result["points"]
            critical = False
            if combo >= 30:
                text = f"CHAIN ×{combo}  +{pts}"
                critical = True
                color = COLORS["STAR"]
            elif combo >= 15:
                text = f"CHAIN ×{combo}  +{pts}"
                color = COLORS["GOLD"]
            elif pts >= 50:
                text = f"CRITICAL!  +{pts}"
                critical = True
                color = COLORS["STAR"]
            elif pts >= 30:
                text = f"PERFECT  +{pts}"
                color = COLORS["GOLD"]
            else:
                text = f"+{pts} EXP"

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

        if result.get("leveled"):
            self.audio.play("level_up", priority=True)
            self._log(f"★ 升级到 LV.{self.state.level}")
            if self.overlay:
                self.overlay.level_up(self.state.level)
            else:
                self.effects.show_level_up(self.state.level)
                self.effects.floating_text(f"LEVEL UP  LV.{self.state.level}", color=COLORS["STAR"], big=True)

        for title, rarity in self.state.check_achievements():
            self.audio.play("achievement", priority=True)
            self._log(f"🏆 {title}")
            if self.overlay:
                self.overlay.achievement(title, rarity)
            else:
                self.effects.show_achievement(title, rarity)

        for title, bonus in self.state.check_challenges():
            self.audio.play("achievement", priority=True)
            self._log(f"🎯 挑战完成：{title} +{bonus}")
            self.effects.show_toast(
                "🎯 试炼完成",
                subtitle=f"{title}  +{bonus} EXP",
                color=COLORS["CYAN"],
                category=f"ch_{title}",
            )

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
            flash_color = COLORS["STAR"] if self._xp_flash else COLORS["CRYSTAL"]
            self.xp_canvas.itemconfigure(self.xp_bar, fill=flash_color)
        else:
            self.xp_canvas.itemconfigure(self.xp_bar, fill=COLORS["CRYSTAL"])

        self.root.after(120, self._tick)

    def _slow_tick(self):
        """低频刷新：成就/挑战/统计面板，2s 一次"""
        self._refresh_achievements_panel()
        self.root.after(2000, self._slow_tick)

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
            self.state.save()
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
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
