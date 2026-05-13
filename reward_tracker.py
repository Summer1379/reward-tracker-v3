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


APP_NAME = "奖励追踪器 v3"
SAVE_FILE = os.path.expanduser("~/.reward_tracker_v3.json")
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

COLORS = {
    "BG": "#171614",
    "SURFACE": "#1C1B19",
    "SURFACE2": "#252321",
    "BORDER": "#393836",
    "TEXT": "#E8E6E3",
    "TEXT_MUTED": "#9C9A97",
    "ORANGE": "#FF6B2C",
    "CYAN": "#00E5CC",
    "GOLD": "#E8AF34",
    "PURPLE": "#A86FDF",
    "SUCCESS": "#6DAA45",
}

MOUSE_PX_THRESHOLD = 180
COMBO_TIMEOUT_SEC = 3.0
CLICK_BASE_POINTS = 12
TYPE_BURST_CHARS = 10
TYPE_BURST_POINTS = 40
MOUSE_MOVE_POINTS = 2
INITIAL_XP_NEEDED = 200
XP_GROWTH = 1.35

ACHIEVEMENTS = [
    # (key, title, current_fn, target)
    ("first_click", "初次点击", lambda s: s["event_counts"]["click"], 1),
    ("type_100", "百字达人", lambda s: s["chars_total"], 100),
    ("click_50", "点击新手", lambda s: s["event_counts"]["click"], 50),
    ("level_5", "达到 5 级", lambda s: s["level"], 5),
    ("combo_15", "银段连击", lambda s: s["max_combo"], 15),
    ("score_5000", "积分5000", lambda s: s["total_score"], 5000),
    ("level_10", "达到 10 级", lambda s: s["level"], 10),
    ("combo_30", "金段连击", lambda s: s["max_combo"], 30),
    ("type_1000", "千字大师", lambda s: s["chars_total"], 1000),
    ("click_500", "点击达人", lambda s: s["event_counts"]["click"], 500),
    ("score_50000", "积分5万", lambda s: s["total_score"], 50000),
    ("level_20", "达到 20 级", lambda s: s["level"], 20),
]

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
            if not priority and (now - last) < self.cooldown.get(category, 0.5):
                return
            if self.current_proc and self.current_proc.poll() is None:
                if self.current_category == category and not priority:
                    return
                self._stop_current()
            self.last_play_time[category] = now
            path = self.sound_files.get(category)
            try:
                if path and platform.system() == "Darwin":
                    self.current_proc = subprocess.Popen(
                        ["afplay", path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self.current_category = category
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
    """桌面悬浮特效：toast 通知 + 飘字"""

    def __init__(self, root):
        self.root = root
        self.toast_queue = deque()
        self.active_toast = None
        self.float_windows = []
        self.last_float_time = 0

    def show_toast(self, title, subtitle="", color=None):
        """右上角弹出半透明 toast，3秒淡出"""
        color = color or COLORS["GOLD"]
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
            try:
                tw.attributes("-alpha", 0.0)
            except tk.TclError:
                pass

            screen_w = tw.winfo_screenwidth()
            w, h = 320, 80 if subtitle else 56
            x = screen_w - w - 24
            y = 60 + (len([f for f in self.float_windows if f.winfo_exists()]) * 0)
            tw.geometry(f"{w}x{h}+{x}+{y}")
            tw.configure(bg=COLORS["SURFACE"])

            border = tk.Frame(tw, bg=color, width=4)
            border.pack(side=tk.LEFT, fill=tk.Y)

            content = tk.Frame(tw, bg=COLORS["SURFACE"])
            content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=8)

            tk.Label(content, text=title, bg=COLORS["SURFACE"], fg=color,
                     font=("Helvetica", 14, "bold")).pack(anchor=tk.W)
            if subtitle:
                tk.Label(content, text=subtitle, bg=COLORS["SURFACE"],
                         fg=COLORS["TEXT_MUTED"],
                         font=("Helvetica", 11)).pack(anchor=tk.W)

            self.active_toast = tw
            self._animate_toast(tw, fade_in=True, alpha=0.0)
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
                alpha += 0.08
                tw.attributes("-alpha", min(alpha, 0.95))
                if alpha < 0.95:
                    self.root.after(20, lambda: self._animate_toast(tw, True, alpha))
                else:
                    self.root.after(2200, lambda: self._animate_toast(tw, False, 0.95))
            else:
                alpha -= 0.05
                tw.attributes("-alpha", max(alpha, 0.0))
                if alpha > 0:
                    self.root.after(25, lambda: self._animate_toast(tw, False, alpha))
                else:
                    tw.destroy()
                    self.active_toast = None
                    self.root.after(150, self._show_next_toast)
        except tk.TclError:
            self.active_toast = None
            self.root.after(100, self._show_next_toast)

    def floating_text(self, text, color=None, x=None, y=None):
        """在屏幕指定位置（默认鼠标附近）飘字向上淡出"""
        # 限流：避免同一秒太多飘字卡顿
        now = time.time()
        if now - self.last_float_time < 0.05:
            return
        self.last_float_time = now
        # 清理失效窗口引用
        self.float_windows = [w for w in self.float_windows if w.winfo_exists()]
        if len(self.float_windows) > 8:
            return
        try:
            if x is None or y is None:
                x = self.root.winfo_pointerx()
                y = self.root.winfo_pointery() - 30
            color = color or COLORS["GOLD"]
            fw = tk.Toplevel(self.root)
            fw.overrideredirect(True)
            fw.attributes("-topmost", True)
            try:
                fw.attributes("-alpha", 0.95)
            except tk.TclError:
                pass
            try:
                fw.attributes("-transparent", True)
                fw.configure(bg="systemTransparent")
                bg_color = "systemTransparent"
            except tk.TclError:
                bg_color = COLORS["BG"]
                fw.configure(bg=bg_color)

            label = tk.Label(fw, text=text, bg=bg_color, fg=color,
                             font=("Helvetica", 16, "bold"))
            label.pack()
            fw.update_idletasks()
            w = fw.winfo_reqwidth()
            h = fw.winfo_reqheight()
            fw.geometry(f"{w}x{h}+{int(x - w/2)}+{int(y)}")
            self.float_windows.append(fw)
            self._animate_float(fw, x, y, 0)
        except Exception:
            pass

    def _animate_float(self, fw, x, y, step):
        if not fw.winfo_exists():
            return
        try:
            new_y = int(y - step * 1.5)
            alpha = max(0.0, 0.95 - step * 0.04)
            w = fw.winfo_width()
            fw.geometry(f"+{int(x - w/2)}+{new_y}")
            try:
                fw.attributes("-alpha", alpha)
            except tk.TclError:
                pass
            if step < 24:
                self.root.after(30, lambda: self._animate_float(fw, x, y, step + 1))
            else:
                fw.destroy()
        except tk.TclError:
            pass

    def shutdown(self):
        for w in list(self.float_windows):
            try:
                w.destroy()
            except Exception:
                pass
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
        for key, title, fn, target in ACHIEVEMENTS:
            if key in self.unlocked_achievements:
                continue
            try:
                if fn(snapshot) >= target:
                    self.unlocked_achievements.add(key)
                    newly.append(title)
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
        """返回所有成就的进度列表：[(title, current, target, unlocked)]"""
        snapshot = self._achievement_snapshot()
        out = []
        for key, title, fn, target in ACHIEVEMENTS:
            try:
                current = min(fn(snapshot), target)
            except Exception:
                current = 0
            out.append((title, current, target, key in self.unlocked_achievements))
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
        self.log_entries = deque(maxlen=20)
        self._xp_visual = 0.0  # 用于 XP 进度条动画过渡

        root.title(APP_NAME)
        root.geometry("900x650")
        root.configure(bg=COLORS["BG"])
        root.minsize(720, 540)

        self._build_ui()
        self._bind_events()
        self._tick()

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
        tk.Label(
            xp_frame,
            text="XP",
            bg=COLORS["BG"],
            fg=COLORS["TEXT_MUTED"],
            font=("Helvetica", 10),
        ).pack(anchor=tk.W)
        self.xp_canvas = tk.Canvas(
            xp_frame,
            height=8,
            bg=COLORS["SURFACE2"],
            highlightthickness=0,
        )
        self.xp_canvas.pack(fill=tk.X)
        self.xp_bar = self.xp_canvas.create_rectangle(0, 0, 0, 8, fill=COLORS["ORANGE"], width=0)

        body = tk.Frame(self.root, bg=COLORS["BG"])
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

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
        # 飘字：点击/打字才飘（移动太频繁）
        if result["type"] in ("click", "type"):
            self.effects.floating_text(f"+{result['points']}", color=color)
        if not quiet:
            self._log(f"+{result['points']} {label}")
        if result.get("leveled"):
            self.audio.play("level_up", priority=True)
            self._log(f"★ 升级到 LV.{self.state.level}")
            self.effects.show_toast(
                f"★ 升级到 LV.{self.state.level}",
                subtitle=f"下一级需 {self.state.xp_needed} XP",
                color=COLORS["GOLD"],
            )
        for title in self.state.check_achievements():
            self.audio.play("achievement", priority=True)
            self._log(f"🏆 {title}")
            self.effects.show_toast(
                f"🏆 成就解锁",
                subtitle=title,
                color=COLORS["ORANGE"],
            )
        for title, bonus in self.state.check_challenges():
            self.audio.play("achievement", priority=True)
            self._log(f"🎯 挑战完成：{title} +{bonus}")
            self.effects.show_toast(
                f"🎯 挑战完成",
                subtitle=f"{title} +{bonus} 积分",
                color=COLORS["CYAN"],
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
        for title, current, target, unlocked in progress:
            if title not in self._ach_widgets:
                row = tk.Frame(self.ach_inner, bg=COLORS["SURFACE"])
                row.pack(fill=tk.X, padx=6, pady=4)
                name = tk.Label(
                    row, text="", bg=COLORS["SURFACE"], fg=COLORS["TEXT"],
                    font=("Helvetica", 11, "bold"), anchor="w",
                )
                name.pack(fill=tk.X)
                bar = tk.Canvas(row, height=6, bg=COLORS["SURFACE2"], highlightthickness=0)
                bar.pack(fill=tk.X, pady=(2, 0))
                rect = bar.create_rectangle(0, 0, 0, 6, fill=COLORS["CYAN"], width=0)
                hint = tk.Label(
                    row, text="", bg=COLORS["SURFACE"], fg=COLORS["TEXT_MUTED"],
                    font=("Helvetica", 9), anchor="w",
                )
                hint.pack(fill=tk.X)
                self._ach_widgets[title] = (name, bar, rect, hint)
            name, bar, rect, hint = self._ach_widgets[title]
            if unlocked:
                name.configure(text=f"✓ {title}", fg=COLORS["GOLD"])
                hint.configure(text="已解锁")
                w = max(bar.winfo_width(), 1)
                bar.coords(rect, 0, 0, w, 6)
                bar.itemconfigure(rect, fill=COLORS["GOLD"])
            else:
                name.configure(text=title, fg=COLORS["TEXT"])
                pct = current / target if target else 0
                w = max(bar.winfo_width(), 1)
                bar.coords(rect, 0, 0, w * pct, 6)
                bar.itemconfigure(rect, fill=COLORS["CYAN"])
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

        # XP 动画过渡：向目标值缓慢逼近
        target = self.state.xp / max(self.state.xp_needed, 1)
        diff = target - self._xp_visual
        self._xp_visual += diff * 0.25
        if abs(diff) < 0.002:
            self._xp_visual = target
        width = max(self.xp_canvas.winfo_width(), 1)
        self.xp_canvas.coords(self.xp_bar, 0, 0, width * self._xp_visual, 8)

        # 更新成就/挑战面板
        self._refresh_achievements_panel()

        self.root.after(80, self._tick)

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
