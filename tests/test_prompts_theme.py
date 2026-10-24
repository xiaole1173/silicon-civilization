"""提示词情境化：不出现"游戏/狼人杀"，要有处境与生存压力。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import prompts  # noqa: E402
from engine.scenario import Scenario  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO12 = os.path.join(ROOT, "scenarios", "werewolf12.yaml")


def view_for(context: str, role: str = "villager", **extra) -> dict:
    scenario = Scenario.load(SCENARIO12)
    view = {
        "context": context, "seat": 3, "role": role, "day": 2, "players": 12,
        "alive": [1, 2, 3, 4, 5], "deaths": [], "transcript": [], "transcript_limit": -1,
        "max_chars": 220, "teammates": [7, 9] if role == "werewolf" else [],
        "theme": {
            "name": scenario.theme["name"],
            "premise": scenario.theme["premise"],
            "roles": scenario.theme["roles"],
            "phases": scenario.theme["phases"],
        },
    }
    view.update(extra)
    return view


class TestThemedPrompts(unittest.TestCase):
    def test_system_uses_theme_name_and_premise(self):
        messages = prompts.build_messages(view_for("day_speak"))
        system = messages[0]["content"]
        self.assertIn("黑森林村", system)
        self.assertIn("狼", system)

    def test_no_game_words(self):
        for ctx in ("day_speak", "day_vote", "night_wolf", "night_seer", "night_witch"):
            messages = prompts.build_messages(view_for(ctx, "werewolf" if "wolf" in ctx else "villager"))
            blob = messages[0]["content"] + messages[1]["content"]
            for word in ("狼人杀", "游戏", "玩家", "扮演", "实验", "规则说明"):
                self.assertNotIn(word, blob, "{} 里不应出现 {}".format(ctx, word))

    def test_survival_pressure_present(self):
        system = prompts.build_messages(view_for("day_speak"))[0]["content"]
        self.assertIn("活下来", system)
        self.assertIn("没有重来", system)

    def test_role_label_from_theme(self):
        system = prompts.build_messages(view_for("day_vote", "werewolf"))[0]["content"]
        self.assertIn("狼人", system)
        self.assertIn("同伴", system)

    def test_context_tag_present(self):
        for ctx, tag in prompts.CONTEXT_TAG.items():
            messages = prompts.build_messages(view_for(ctx))
            self.assertIn(tag, messages[1]["content"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
