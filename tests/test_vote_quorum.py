"""投票门槛：防止"一票出局"。"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import game, rules  # noqa: E402
from engine.events import EventLog  # noqa: E402
from engine.scenario import Scenario  # noqa: E402
from engine.state import GameState  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO12 = os.path.join(ROOT, "scenarios", "werewolf12.yaml")


class TestTally(unittest.TestCase):
    def test_counts_abstain(self):
        result = rules.tally_votes({1: 3, 2: None, 3: None, 4: 3})
        self.assertEqual(result["tally"], {3: 2})
        self.assertEqual(result["abstain"], 2)
        self.assertEqual(result["voters"], 4)


class TestQuorum(unittest.TestCase):
    def test_above_abstain_blocks_single_vote(self):
        result = rules.tally_votes({1: 5, 2: None, 3: None, 4: None, 5: None})
        ok, detail = rules.quorum_check(result, "above_abstain", 12)
        self.assertFalse(ok)
        self.assertIn("弃权", detail)

    def test_above_abstain_allows_clear_majority(self):
        votes = {1: 5, 2: 5, 3: 5, 4: 5, 5: 7, 6: None}
        result = rules.tally_votes(votes)
        ok, _ = rules.quorum_check(result, "above_abstain", 12)
        self.assertTrue(ok)

    def test_majority_requires_half(self):
        result = rules.tally_votes({1: 5, 2: 5, 3: 7, 4: None})
        ok, detail = rules.quorum_check(result, "majority", 12)
        self.assertFalse(ok)
        self.assertIn("过半", detail)

    def test_plurality_keeps_old_behavior(self):
        result = rules.tally_votes({1: 5, 2: None})
        ok, _ = rules.quorum_check(result, "plurality", 12)
        self.assertTrue(ok)


class TestVoteGateInGame(unittest.TestCase):
    def _state(self):
        return GameState.new(Scenario.load(SCENARIO12), 2)

    def _fake_round(self, votes):
        def fake(state_, log_, players_, candidates, tag):
            result = rules.tally_votes(votes)
            log_.emit(tag, day=state_.day, votes={str(k): v for k, v in votes.items()},
                      tally={str(k): v for k, v in result["tally"].items()},
                      abstain=result["abstain"], tie=result["tie"],
                      top=result["top"], eliminated=result["eliminated"])
            return result
        return fake

    def test_single_vote_does_not_eliminate(self):
        state = self._state()
        alive = sorted(state.alive)
        votes = {s: (alive[1] if s == alive[0] else None) for s in alive}
        log = EventLog()
        with mock.patch.object(game, "_vote_round", side_effect=self._fake_round(votes)):
            eliminated = game._resolve_vote(state, log, {})
        self.assertIsNone(eliminated, "只有一票时不应有人被投出")
        self.assertTrue(any(e["event"] == "vote_quorum_failed" for e in log.events))

    def test_clear_majority_eliminates(self):
        state = self._state()
        alive = sorted(state.alive)
        target = alive[1]
        votes = {}
        for i, seat in enumerate(alive):
            votes[seat] = alive[0] if i == 0 else target
        log = EventLog()
        with mock.patch.object(game, "_vote_round", side_effect=self._fake_round(votes)):
            eliminated = game._resolve_vote(state, log, {})
        self.assertEqual(eliminated, target)


if __name__ == "__main__":
    unittest.main(verbosity=2)
