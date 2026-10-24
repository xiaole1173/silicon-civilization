"""规则引擎单元测试：全部离线，不需要 API Key。

运行：python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import game, rules  # noqa: E402
from engine.prompts import parse_action  # noqa: E402
from engine.scenario import Scenario, ScenarioError  # noqa: E402
from engine.state import GameState  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "scenarios", "werewolf.yaml")


def make_state(seed: int = 1) -> GameState:
    scenario = Scenario.load(SCENARIO)
    return GameState.new(scenario, seed)


class TestScenario(unittest.TestCase):
    def test_load_and_counts(self):
        s = Scenario.load(SCENARIO)
        self.assertEqual(sum(s.roles.values()), s.players)

    def test_role_total_mismatch_rejected(self):
        s = Scenario.load(SCENARIO)
        s.roles["villager"] = 9
        with self.assertRaises(ScenarioError):
            s.validate()

    def test_layout_deterministic(self):
        s = Scenario.load(SCENARIO)
        self.assertEqual(s.role_layout(7), s.role_layout(7))
        layouts = {tuple(s.role_layout(seed)) for seed in range(6)}
        self.assertGreater(len(layouts), 1, "不同 seed 应给出不同座位分布")

    def test_layout_has_expected_counts(self):
        s = Scenario.load(SCENARIO)
        layout = s.role_layout(3)
        self.assertEqual(layout.count("werewolf"), s.roles["werewolf"])
        self.assertEqual(len(layout), s.players)


class TestWolfVotes(unittest.TestCase):
    def test_majority(self):
        target, detail = rules.resolve_wolf_votes({1: 5, 2: 5, 3: 7})
        self.assertEqual(target, 5)
        self.assertEqual(detail["rule"], "majority_lowest_seat")

    def test_tie_picks_lowest_seat(self):
        # 3 只狼：2 票投 6、2 票投 4，真正平票 -> 取座位号小的 4
        target, detail = rules.resolve_wolf_votes({1: 6, 2: 6, 3: 4, 4: 4})
        self.assertEqual(target, 4)
        self.assertTrue(detail["tied"])

    def test_all_pass(self):
        target, _ = rules.resolve_wolf_votes({1: None, 2: None})
        self.assertIsNone(target)


class TestNight(unittest.TestCase):
    def test_wolf_kill_applies(self):
        state = make_state()
        wolf = state.alive_wolves()[0]
        victim = [s for s in state.alive if s != wolf][0]
        night = rules.resolve_night(state, victim, {"kind": "pass"})
        self.assertEqual([d["seat"] for d in night["deaths"]], [victim])
        self.assertEqual(night["deaths"][0]["cause"], "wolf")

    def test_witch_save_cancels_death(self):
        state = make_state()
        witch = state.seats_of("witch")[0]
        victim = [s for s in state.alive if s != witch][0]
        night = rules.resolve_night(state, victim, {"kind": "save", "target": victim})
        self.assertEqual(night["deaths"], [])
        self.assertTrue(night["saved"])
        self.assertEqual(state.witch_stock["antidote"], 0)

    def test_witch_poison_adds_death(self):
        state = make_state()
        wolf = state.alive_wolves()[0]
        poison_target = [s for s in state.alive if s not in (wolf,)][0]
        night = rules.resolve_night(state, wolf, {"kind": "poison", "target": poison_target})
        causes = {d["seat"]: d["cause"] for d in night["deaths"]}
        self.assertIn(poison_target, causes)
        self.assertEqual(state.witch_stock["poison"], 0)

    def test_witch_cannot_reuse_potion(self):
        state = make_state()
        witch = state.seats_of("witch")[0]
        victim = [s for s in state.alive if s != witch][0]
        rules.resolve_night(state, victim, {"kind": "save", "target": victim})
        ok, msg = rules.validate_action(state, witch, {"kind": "save"}, context="night_witch")
        self.assertFalse(ok)
        self.assertIn("解药", msg)


class TestVotesAndWin(unittest.TestCase):
    def test_tally_tie(self):
        result = rules.tally_votes({1: 3, 2: 4, 3: 3, 4: 4})
        self.assertTrue(result["tie"])
        self.assertIsNone(result["eliminated"])

    def test_tally_winner(self):
        result = rules.tally_votes({1: 3, 2: 3, 3: 4})
        self.assertFalse(result["tie"])
        self.assertEqual(result["eliminated"], 3)

    def test_good_wins_when_all_wolves_dead(self):
        state = make_state()
        state.alive = {s for s in state.alive if state.role_of(s) != "werewolf"}
        self.assertEqual(rules.check_win(state), "good")

    def test_wolves_win_when_no_villagers(self):
        state = make_state()
        state.alive = {s for s in state.alive if state.role_of(s) != "villager"}
        self.assertEqual(rules.check_win(state), "werewolves")

    def test_wolves_win_when_no_gods(self):
        state = make_state()
        state.alive = {s for s in state.alive
                       if state.role_of(s) in ("werewolf", "villager")}
        self.assertEqual(rules.check_win(state), "werewolves")


class TestValidation(unittest.TestCase):
    def test_dead_target_rejected(self):
        state = make_state()
        seat = state.alive_wolves()[0]
        victim = [s for s in state.alive if s != seat][0]
        state.alive.discard(victim)
        ok, msg = rules.validate_action(state, seat, {"kind": "kill", "target": victim},
                                        context="night_wolf")
        self.assertFalse(ok)
        self.assertIn("已出局", msg)

    def test_self_vote_rejected(self):
        state = make_state()
        seat = sorted(state.alive)[0]
        ok, msg = rules.validate_action(state, seat, {"kind": "vote", "target": seat},
                                        context="day_vote")
        self.assertFalse(ok)

    def test_seer_cannot_kill(self):
        state = make_state()
        seer = state.seats_of("seer")[0]
        ok, _ = rules.validate_action(state, seer, {"kind": "kill", "target": 1},
                                      context="night_seer")
        self.assertFalse(ok)

    def test_hunter_allowed_after_death(self):
        state = make_state()
        hunter = state.seats_of("hunter")[0]
        state.alive.discard(hunter)
        ok, msg = rules.validate_action(state, hunter, {"kind": "pass"}, context="hunter")
        self.assertTrue(ok, msg)

    def test_poisoned_hunter_cannot_shoot(self):
        state = make_state()
        hunter = state.seats_of("hunter")[0]
        self.assertTrue(rules.can_hunter_shoot(state, hunter, "wolf"))
        self.assertTrue(rules.can_hunter_shoot(state, hunter, "vote"))
        self.assertFalse(rules.can_hunter_shoot(state, hunter, "poison"))


class TestFullGame(unittest.TestCase):
    def _run(self, seed: int):
        scenario = Scenario.load(SCENARIO)
        return game.run_game(scenario, players={}, seed=seed)

    def test_game_reaches_end(self):
        result = self._run(5)
        summary = result["summary"]
        self.assertIn(summary["winner"], ("good", "werewolves", "draw"))
        self.assertGreater(summary["days"], 0)
        events = result["log"].events
        self.assertEqual(events[-1]["event"], "game_end")
        self.assertEqual(events[0]["event"], "run_meta")

    def test_events_well_formed(self):
        result = self._run(3)
        for i, event in enumerate(result["log"].events, start=1):
            self.assertEqual(event["seq"], i)
            self.assertIn("event", event)

    def test_deterministic_same_seed(self):
        a = self._run(11)["log"].events
        b = self._run(11)["log"].events
        strip = lambda ev: json.dumps({k: v for k, v in ev.items() if k != "recorded_at"},
                                      ensure_ascii=False, sort_keys=True)
        self.assertEqual([strip(e) for e in a], [strip(e) for e in b])

    def test_alive_never_negative_and_deaths_consistent(self):
        result = self._run(9)
        state_alive = set(result["log"].events[-1]["alive"])
        seen_dead = set()
        for e in result["log"].events:
            if e["event"] in ("night_resolve",):
                for d in e["deaths"]:
                    seen_dead.add(d["seat"])
            if e["event"] == "elimination":
                seen_dead.add(e["seat"])
        self.assertFalse((seen_dead & state_alive), "死者不应仍存活")

    def test_multi_seed_coverage(self):
        winners = set()
        for seed in range(1, 12):
            winners.add(self._run(seed)["summary"]["winner"])
        self.assertTrue(winners, "至少跑出一种结局")


class TestLLMResilience(unittest.TestCase):
    """模型端完全不可用时，对局必须跑完并把非法动作记成降级，而不是崩掉。"""

    def test_game_survives_dead_provider(self):
        import providers as providers_mod
        scenario = Scenario.load(SCENARIO)
        state = GameState.new(scenario, 2)
        conf = {"name": "不可用", "api_base": "http://127.0.0.1:9/v1",
                "model": "none", "api_key": "", "temperature": 0.0,
                "max_tokens": 32, "timeout": 2.0}
        players = game.build_players(state, mode="llm", seed=2,
                                     models={seat: dict(conf) for seat in state.seat_roles})
        # 直接把网络调用打挂，验证"模型全挂时对局仍能跑完并全部降级"
        with mock.patch.object(providers_mod, "call_chat",
                               side_effect=providers_mod.ProviderError("模拟故障")):
            result = game.run_game(scenario, players=players, seed=2)
        summary = result["summary"]
        self.assertIn(summary["winner"], ("good", "werewolves", "draw"))
        kinds = [e["event"] for e in result["log"].events]
        self.assertIn("action_degraded", kinds)
        self.assertEqual(result["log"].events[-1]["event"], "game_end")


class TestParsing(unittest.TestCase):
    def test_parse_plain_json(self):
        self.assertEqual(parse_action('{"kind": "pass"}')["kind"], "pass")

    def test_parse_fenced_json(self):
        fence = chr(96) * 3
        raw = fence + "json\n{\"kind\": \"vote\", \"target\": 3}\n" + fence
        self.assertEqual(parse_action(raw)["target"], 3)

    def test_parse_with_chatter(self):
        raw = "好的，我决定：{\"kind\": \"kill\", \"target\": 4} 以上。"
        self.assertEqual(parse_action(raw)["kind"], "kill")

    def test_parse_garbage(self):
        self.assertEqual(parse_action("我不知道该投谁"), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
