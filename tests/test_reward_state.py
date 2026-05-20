import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

if "tkinter" not in sys.modules:
    tk_stub = types.ModuleType("tkinter")
    ttk_stub = types.ModuleType("tkinter.ttk")
    tk_stub.ttk = ttk_stub
    tk_stub.TclError = Exception
    sys.modules["tkinter"] = tk_stub
    sys.modules["tkinter.ttk"] = ttk_stub

import reward_tracker


class RewardStateTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.old_save_file = reward_tracker.SAVE_FILE
        reward_tracker.SAVE_FILE = os.path.join(self.tmpdir.name, "save.json")

    def tearDown(self):
        reward_tracker.SAVE_FILE = self.old_save_file
        self.tmpdir.cleanup()

    def make_state(self):
        return reward_tracker.RewardState()

    def test_xp_crosses_single_milestone_once_per_level(self):
        state = self.make_state()
        result = state._add_xp(52)

        self.assertEqual([25], result["milestones"])
        self.assertFalse(result["leveled"])

        repeat = state._add_xp(0)

        self.assertEqual([], repeat["milestones"])

    def test_xp_crosses_multiple_milestones(self):
        state = self.make_state()
        state.xp = 40

        result = state._add_xp(120)

        self.assertEqual([25, 50, 75], result["milestones"])
        self.assertEqual(["xp_milestone_25", "xp_milestone_50", "xp_milestone_75"], result["milestone_sounds"])
        self.assertEqual(160, result["xp_after"])

    def test_milestones_reset_after_level_up(self):
        state = self.make_state()
        state._add_xp(160)

        level_up = state._add_xp(60)

        self.assertTrue(level_up["leveled"])
        self.assertEqual(set(), state.xp_milestones_triggered)
        self.assertGreaterEqual(len(level_up["drops"]), 1)

        next_level = state._add_xp(70)

        self.assertEqual([25], next_level["milestones"])

    def test_equipped_title_survives_save_and_load(self):
        state = self.make_state()
        state.owned_titles.add("水晶铭文师")
        self.assertTrue(state.equip_title("水晶铭文师"))
        state.save()

        loaded = self.make_state()

        self.assertEqual("水晶铭文师", loaded.equipped_title)
        self.assertIn("水晶铭文师", loaded.owned_titles)
        self.assertIn("水晶铭文师", loaded.inventory["titles"])

    def test_equipped_theme_survives_save_and_load(self):
        state = self.make_state()
        state.inventory["themes"].append("ember_heart")

        self.assertTrue(state.equip_theme("ember_heart"))
        ok, err = state.save()

        self.assertTrue(ok, err)
        loaded = self.make_state()
        self.assertEqual("ember_heart", loaded.equipped_theme)
        self.assertEqual("金红胜利感", loaded.theme_profile()["label"])

    def test_equip_theme_rejects_unowned_theme(self):
        state = self.make_state()

        self.assertFalse(state.equip_theme("starlit_oath"))
        self.assertIsNone(state.equipped_theme)

    def test_theme_drop_message_uses_player_facing_label(self):
        state = self.make_state()

        with mock.patch.object(state, "_weighted_choice", side_effect=["silver", "theme"]):
            with mock.patch.object(reward_tracker.random, "choice", return_value=reward_tracker.THEME_DROPS[1]):
                drops = state.generate_drops("level_up")

        self.assertEqual("ember_heart", drops[0]["name"])
        self.assertEqual("金红胜利感", drops[0]["label"])
        self.assertIn("金红胜利感", drops[0]["message"])

    def test_fragments_can_be_forged_into_title(self):
        state = self.make_state()
        state.inventory["fragments"]["梦晶碎片"] = 3

        result = state.forge_fragment_reward("梦晶碎片")

        self.assertTrue(result["success"])
        self.assertEqual("title", result["type"])
        self.assertEqual(0, state.inventory["fragments"].get("梦晶碎片", 0))
        self.assertIn(result["name"], state.owned_titles)

    def test_fragments_can_be_forged_into_theme(self):
        state = self.make_state()
        state.inventory["fragments"]["星尘羽片"] = 3

        result = state.forge_fragment_reward("星尘羽片")

        self.assertTrue(result["success"])
        self.assertEqual("theme", result["type"])
        self.assertEqual("ember_heart", result["name"])
        self.assertIn("ember_heart", state.inventory["themes"])

    def test_fragment_forge_rejects_insufficient_quantity(self):
        state = self.make_state()
        state.inventory["fragments"]["月光残页"] = 2

        result = state.forge_fragment_reward("月光残页")

        self.assertFalse(result["success"])
        self.assertEqual(2, state.inventory["fragments"]["月光残页"])

    def test_click_rewards_advance_chainbreaker_mastery(self):
        state = self.make_state()

        result = state.on_click()

        self.assertIn("mastery", result)
        self.assertEqual("chainbreaker", result["mastery"]["id"])
        self.assertGreater(state.masteries["chainbreaker"]["xp"], 0)

    def test_type_rewards_advance_scribe_mastery(self):
        state = self.make_state()

        result = None
        for _ in range(reward_tracker.TYPE_BURST_CHARS):
            result = state.on_type_char()

        self.assertIsNotNone(result)
        self.assertEqual("dream_scribe", result["mastery"]["id"])
        self.assertGreater(state.masteries["dream_scribe"]["xp"], 0)

    def test_move_rewards_advance_wanderer_mastery(self):
        state = self.make_state()
        state.on_move(0, 0)

        result = state.on_move(reward_tracker.MOUSE_PX_THRESHOLD + 1, 0)

        self.assertIsNotNone(result)
        self.assertEqual("meadow_wanderer", result["mastery"]["id"])
        self.assertGreater(state.masteries["meadow_wanderer"]["xp"], 0)

    def test_mastery_level_survives_save_and_load(self):
        state = self.make_state()
        result = state._add_mastery_xp("dream_scribe", 120)

        self.assertTrue(result["leveled"])
        state.save()
        loaded = self.make_state()

        self.assertEqual(2, loaded.masteries["dream_scribe"]["level"])
        self.assertEqual(state.masteries["dream_scribe"]["xp"], loaded.masteries["dream_scribe"]["xp"])

    def test_chronicle_records_level_up_and_survives_save(self):
        state = self.make_state()

        state._add_xp(220)
        state.save()
        loaded = self.make_state()

        self.assertTrue(any("丰收升级" in entry["text"] for entry in loaded.chronicle))

    def test_chronicle_keeps_recent_entries(self):
        state = self.make_state()

        for i in range(reward_tracker.CHRONICLE_LIMIT + 5):
            state.add_chronicle("测试旅记", f"第 {i} 条")

        self.assertEqual(reward_tracker.CHRONICLE_LIMIT, len(state.chronicle))
        self.assertEqual("第 5 条", state.chronicle[0]["text"])

    def test_forging_fragment_records_chronicle_entry(self):
        state = self.make_state()
        state.inventory["fragments"]["梦晶碎片"] = 3

        state.forge_fragment_reward("梦晶碎片")

        self.assertTrue(any("碎片锻造" in entry["title"] for entry in state.chronicle))

    def test_self_test_runs_core_reward_loop_without_gui(self):
        buf = StringIO()
        with redirect_stdout(buf):
            self.assertEqual(0, reward_tracker.run_self_test(verbose=False))

        self.assertEqual("", buf.getvalue())

    def test_old_save_loads_without_inventory_fields(self):
        with open(reward_tracker.SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump({"level": 3, "xp": 12, "xp_needed": 200}, f)

        state = self.make_state()

        self.assertEqual(3, state.level)
        self.assertEqual({"titles": [], "themes": [], "fragments": {}}, state.inventory)
        self.assertEqual(set(), state.owned_titles)
        self.assertIsNone(state.equipped_title)
        self.assertIsNone(state.equipped_theme)
        self.assertEqual(1, state.masteries["dream_scribe"]["level"])
        self.assertEqual([], state.chronicle)

    def test_command_line_tools_python_is_tk_unsafe(self):
        path = "/Library/Developer/CommandLineTools/usr/bin/python3"

        self.assertTrue(reward_tracker._is_unsafe_tk_python_path(path))

    def test_homebrew_python_without_tk_is_not_preferred_launcher(self):
        path = "/opt/homebrew/bin/python3"

        self.assertTrue(reward_tracker._is_homebrew_python_path(path))

    def test_print_launcher_exits_before_loading_tk(self):
        with mock.patch.object(reward_tracker.sys, "argv", ["reward_tracker.py", "--print-tk-launcher"]):
            with mock.patch.object(reward_tracker, "_find_safe_tk_python", return_value="/usr/local/bin/python3"):
                with self.assertRaises(SystemExit) as cm:
                    reward_tracker._reexec_if_needed_for_tk()

        self.assertEqual(0, cm.exception.code)

    def test_reward_flavor_text_uses_pastoral_style(self):
        state = self.make_state()

        text, critical = state.reward_flavor_text("click", combo=23, points=42)

        self.assertNotIn("CHAIN", text)
        self.assertNotIn("CRITICAL", text)
        self.assertTrue(any(word in text for word in ("花田", "溪畔", "丰收", "春风", "小芽")))
        self.assertFalse(critical)

    def test_level_reward_feedback_avoids_toplevel_windows(self):
        class FakeAudio:
            muted = False
            sound_files = {}

            def __init__(self):
                self.calls = []

            def play(self, name, priority=False):
                self.calls.append((name, priority))

        class FakeEffects:
            def __init__(self):
                self.calls = []

            def floating_text(self, *args, **kwargs):
                self.calls.append(("floating_text", args, kwargs))

            def show_passive_toast(self, *args, **kwargs):
                self.calls.append(("show_passive_toast", args, kwargs))

            def show_toast(self, *args, **kwargs):
                self.calls.append(("show_toast", args, kwargs))

            def show_achievement(self, *args, **kwargs):
                self.calls.append(("show_achievement", args, kwargs))

        class FakeState:
            combo = 0
            equipped_title = None
            level = 2

            def reward_flavor_text(self, event_type, combo, points):
                return ("tap", False)

            def theme_profile(self):
                return {"accent": "#FFD700", "accent_alt": "#C8A2C8", "dim": "#111111", "label": "test"}

            def check_achievements(self):
                return [("first bloom", "star")]

            def check_challenges(self):
                return []

        app = object.__new__(reward_tracker.App)
        app.state = FakeState()
        app.audio = FakeAudio()
        app.effects = FakeEffects()
        app.overlay = None
        app._log = lambda message: None
        app._refresh_identity_panel = lambda: None
        app.title_badge = types.SimpleNamespace(configure=lambda **kwargs: None)

        result = {
            "type": "click",
            "points": 42,
            "leveled": True,
            "milestones": [25],
            "milestone_sounds": ["xp_milestone_25"],
            "drops": [
                {
                    "type": "title",
                    "name": "first bloom",
                    "message": "first bloom dropped",
                    "rarity": "star",
                }
            ],
            "mastery": {
                "id": "chainbreaker",
                "label": "Chainbreaker",
                "level_after": 2,
                "color": "#FFD700",
                "leveled": True,
            },
        }

        reward_tracker.App._on_reward(app, result, label="click")

        effect_calls = [call[0] for call in app.effects.calls]
        self.assertNotIn("show_toast", effect_calls)
        self.assertNotIn("show_achievement", effect_calls)
        self.assertIn("show_passive_toast", effect_calls)


if __name__ == "__main__":
    unittest.main()
