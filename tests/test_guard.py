"""守卫规则测试（12 人局新增神职）。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import game, rules  # noqa: E402
from engine.scenario import Scenario  # noqa: E402
from engine.state import GameState  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO9 = os.path.join(ROOT, "scenarios", "werewolf.yaml")
SCENARIO12 = os.path.join(ROOT, "scenarios", "werewolf12.yaml")


def state12(seed: int = 3) -> GameState:
    return GameState.new(Scenario.load(SCENARIO12), seed)


class TestTwelvePlayerScenario(unittest.TestCase):
    def test_counts(self):
        s = Scenario.load(SCENARIO12)
        self.assertEqual(s.players, 12)
        self.assertEqual(s.roles["werewolf"], 4)
        self.assertEqual(s.roles["guard"], 1)
        self.assertEqual(sum(s.roles.values()), 12)
        self.assertTrue(s.guard.get("enabled"))

    def test_layout(self):
        s = Scenario.load(SCENARIO12)
        layout = s.role_layout(5)
        self.assertEqual(len(layout), 12)
        self.assertEqual(layout.count("guard"), 1)
        self.assertEqual(layout.count("werewolf"), 4)


class TestGuardRules(unittest.TestCase):
    def test_guard_blocks_wolf_kill(self):
        state = state12()
        guard = state.seats_of("guard")[0]
        victim = [s for s in state.alive if s != guard][0]
        night = rules.resolve_night(state, victim, {"kind": "pass"}, guard_target=victim)
        self.assertTrue(night["guarded"])
        self.assertEqual(night["deaths"], [])

    def test_same_night_rescue_kills(self):
        """同守同救：守卫守住 + 女巫救同一人 -> 仍然死亡。"""
        state = state12()
        guard = state.seats_of("guard")[0]
        victim = [s for s in state.alive if s != guard][0]
        night = rules.resolve_night(state, victim, {"kind": "save", "target": victim},
                                    guard_target=victim)
        self.assertTrue(night["guarded"])
        self.assertTrue(night["saved"])
        self.assertTrue(night["same_night_rescue"])
        self.assertEqual([d["seat"] for d in night["deaths"]], [victim])
        self.assertEqual(night["deaths"][0]["cause"], "guard_save_conflict")

    def test_same_night_rescue_can_be_configured_to_survive(self):
        """同守同救默认判死，但配置 survive 时应改为存活（规则可切换）。"""
        scenario = Scenario.load(SCENARIO12)
        scenario.guard["same_night_rescue"] = "survive"
        state = GameState.new(scenario, 3)
        guard = state.seats_of("guard")[0]
        victim = [s for s in state.alive if s != guard][0]
        night = rules.resolve_night(state, victim, {"kind": "save", "target": victim},
                                    guard_target=victim)
        self.assertTrue(night["same_night_rescue"])
        self.assertEqual(night["deaths"], [], "配置 survive 时应活下来")

    def test_default_policy_is_death(self):
        self.assertEqual(Scenario.load(SCENARIO12).guard["same_night_rescue"], "death")

    def test_save_only_blocks_kill(self):
        state = state12()
        guard = state.seats_of("guard")[0]
        victim = [s for s in state.alive if s != guard][0]
        night = rules.resolve_night(state, victim, {"kind": "save", "target": victim},
                                    guard_target=None)
        self.assertEqual(night["deaths"], [])
        self.assertFalse(night["same_night_rescue"])

    def test_poison_ignores_guard(self):
        state = state12()
        guard = state.seats_of("guard")[0]
        wolf_victim = [s for s in state.alive if s != guard][0]
        poison_target = [s for s in state.alive if s not in (guard, wolf_victim)][0]
        night = rules.resolve_night(state, wolf_victim, {"kind": "poison", "target": poison_target},
                                    guard_target=wolf_victim)
        seats = {d["seat"]: d["cause"] for d in night["deaths"]}
        self.assertNotIn(wolf_victim, seats)     # 被守住
        self.assertEqual(seats.get(poison_target), "poison")

    def test_cannot_guard_same_target_twice(self):
        state = state12()
        guard = state.seats_of("guard")[0]
        target = [s for s in state.alive if s != guard][0]
        state.guard_last = target
        ok, msg = rules.validate_action(state, guard, {"kind": "guard", "target": target},
                                        context="night_guard")
        self.assertFalse(ok)
        self.assertIn("连续", msg)

    def test_can_switch_target(self):
        state = state12()
        guard = state.seats_of("guard")[0]
        first, second = [s for s in sorted(state.alive) if s != guard][:2]
        state.guard_last = first
        ok, msg = rules.validate_action(state, guard, {"kind": "guard", "target": second},
                                        context="night_guard")
        self.assertTrue(ok, msg)

    def test_guard_cannot_target_dead(self):
        state = state12()
        guard = state.seats_of("guard")[0]
        target = [s for s in state.alive if s != guard][0]
        state.alive.discard(target)
        ok, msg = rules.validate_action(state, guard, {"kind": "guard", "target": target},
                                        context="night_guard")
        self.assertFalse(ok)
        self.assertIn("已出局", msg)

    def test_others_cannot_guard(self):
        state = state12()
        villager = state.seats_of("villager")[0]
        target = [s for s in state.alive if s != villager][0]
        ok, _ = rules.validate_action(state, villager, {"kind": "guard", "target": target},
                                      context="night_guard")
        self.assertFalse(ok)


class TestTwelvePlayerGame(unittest.TestCase):
    def test_full_game_runs_and_audits(self):
        scenario = Scenario.load(SCENARIO12)
        result = game.run_game(scenario, players={}, seed=7)
        summary = result["summary"]
        self.assertIn(summary["winner"], ("good", "werewolves", "draw"))
        self.assertTrue(summary["health"]["ok"], summary["health"]["errors"])
        self.assertEqual(summary["health"]["stats"]["players"], 12)
        guard_actions = [e for e in result["log"].events if e["event"] == "guard_action"]
        self.assertTrue(guard_actions, "12 人局应该有守卫行动")

    def test_guard_state_is_tracked(self):
        scenario = Scenario.load(SCENARIO12)
        result = game.run_game(scenario, players={}, seed=11)
        events = result["log"].events
        targets = [e["target"] for e in events if e["event"] == "guard_action"]
        for prev, cur in zip(targets, targets[1:]):
            if prev is not None and cur is not None:
                self.assertNotEqual(prev, cur, "守卫不能连守同一人")


if __name__ == "__main__":
    unittest.main(verbosity=2)
