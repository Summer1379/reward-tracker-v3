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
    ("first_click", "初次点击", lambda s: s["event_counts"]["click"] >= 1),
    ("type_100", "百字达人", lambda s: s["chars_total"] >= 100),
    ("click_50", "点击新手", lambda s: s["event_counts"]["click"] >= 50),
    ("level_5", "达到 5 级", lambda s: s["level"] >= 5),
    ("combo_15", "银段连击", lambda s: s["max_combo"] >= 15),
    ("score_5000", "积分5000", lambda s: s["total_score"] >= 5000),
    ("level_10", "达到 10 级", lambda s: s["level"] >= 10),
    ("combo_30", "金段连击", lambda s: s["max_combo"] >= 30),
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
        self.load()

    def _reset_combo(self):
        self.combo = 0
        self._combo_timer = None

    def _bump_combo_timer(self, root=None):
        if self._combo_timer and root:
            try:
                root.after_cancel(self._combo_timer)
            except Exception:
                pass
        if root:
            self._combo_timer = root.after(int(COMBO_TIMEOUT_SEC * 1000), self._reset_combo)

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
        points = CLICK_BASE_POINTS + random.randint(0, 8)
        _, _, mult, _ = self.combo_info()
        actual = int(points * mult)
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        self._bump_combo_timer(root)
        self.score += actual
        self.total_score += actual
        self.event_counts["click"] += 1
        self.last_event_time = time.time()
        leveled = self._add_xp(actual)
        return {"type": "click", "points": actual, "leveled": leveled}

    def on_type_char(self, root=None):
        self.chars_buffer += 1
        self.chars_total += 1
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
        self.event_counts["type"] += 1
        self.last_event_time = time.time()
        leveled = self._add_xp(actual)
        return {"type": "type", "points": actual, "leveled": leveled}

    def check_achievements(self):
        snapshot = {
            "total_score": self.total_score,
            "level": self.level,
            "max_combo": self.max_combo,
            "chars_total": self.chars_total,
            "event_counts": self.event_counts,
        }
        newly = []
        for key, title, predicate in ACHIEVEMENTS:
            if key in self.unlocked_achievements:
                continue
            try:
                if predicate(snapshot):
                    self.unlocked_achievements.add(key)
                    newly.append(title)
            except Exception:
                pass
        return newly

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
        except Exception:
            pass


class App:
    def __init__(self, root):
        self.root = root
        self.state = RewardState()
        self.audio = AudioStateMachine()
        self.log_entries = deque(maxlen=20)

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

        right = tk.Frame(body, bg=COLORS["SURFACE"], width=280)
        right.pack(side=tk.RIGHT, fill=tk.BOTH)
        right.pack_propagate(False)

        tk.Label(
            right,
            text="奖励日志",
            bg=COLORS["SURFACE"],
            fg=COLORS["TEXT"],
            font=("Helvetica", 12, "bold"),
        ).pack(anchor=tk.W, padx=12, pady=(12, 6))

        self.log_text = tk.Text(
            right,
            bg=COLORS["SURFACE2"],
            fg=COLORS["TEXT"],
            relief=tk.FLAT,
            font=("Helvetica", 10),
            state=tk.DISABLED,
            wrap=tk.WORD,
            padx=8,
            pady=8,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

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

    def _on_reward(self, result, label, quiet=False):
        self.audio.play(result["type"])
        if not quiet:
            self._log(f"+{result['points']} {label}")
        if result.get("leveled"):
            self.audio.play("level_up", priority=True)
            self._log(f"★ 升级到 LV.{self.state.level}")
        new_achievements = self.state.check_achievements()
        for title in new_achievements:
            self.audio.play("achievement", priority=True)
            self._log(f"🏆 {title}")

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

        width = max(self.xp_canvas.winfo_width(), 1)
        progress = self.state.xp / max(self.state.xp_needed, 1)
        self.xp_canvas.coords(self.xp_bar, 0, 0, width * progress, 8)

        self.root.after(400, self._tick)

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
