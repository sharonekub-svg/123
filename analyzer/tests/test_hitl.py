"""HITL re-aggregation: merging fragmented tracks back into one player must
recover the correct per-player stats and drop the phantom self-pass created by
an id switch. Run: python3 analyzer/tests/test_hitl.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model import (  # noqa: E402
    EventType, Frame, MatchData, MatchMeta, Pitch, Player, Position, Team,
)
from engine import analyze  # noqa: E402
from hitl import Corrections, RosterPlayer, apply_corrections  # noqa: E402


def _match(players):
    meta = MatchMeta(id="t", date="2026-01-01", home_team="A", away_team="B",
                     fps=10.0, duration_s=0.0, pitch=Pitch())
    return MatchData(match=meta, players=players, frames=[])


def _hold(md, pid, x, y, t, n=6, dt=0.1):
    for k in range(n):
        md.frames.append(Frame(t=t + k * dt, ball=(x, y),
                               positions=[Position(player=pid, x=x, y=y)]))


def test_merge_fragments_recovers_passes():
    # ground truth: T_a (=player1) -> H2 -> T_b (=player1). Two real passes.
    md = _match([
        Player("Ta", Team.HOME, "ta", "#00f"),
        Player("Tb", Team.HOME, "tb", "#00f"),
        Player("H2", Team.HOME, "h2", "#00f"),
    ])
    _hold(md, "Ta", 30, 34, t=0.0)
    _hold(md, "H2", 50, 34, t=1.0)
    _hold(md, "Tb", 35, 34, t=2.0)
    analyze(md)
    # raw tracks: Ta->H2 and H2->Tb  => 2 passes spread over 2 "different" players
    assert sum(1 for e in md.events if e.type == EventType.PASS) == 2

    corr = Corrections(
        roster=[RosterPlayer("p1", "Player One", "home", 7),
                RosterPlayer("p2", "Player Two", "home", 9)],
        track_to_player={"Ta": "p1", "Tb": "p1", "H2": "p2"},
    )
    md2 = apply_corrections(md, corr)
    assert {p.id for p in md2.players} == {"p1", "p2"}
    s1, s2 = md2.stats["p1"], md2.stats["p2"]
    # p1 passed to p2 once; p2 passed to p1 once
    assert s1.passes_completed == 1, s1.passes_completed
    assert s2.passes_completed == 1, s2.passes_completed
    print("  merge fragments -> correct per-player passes: OK")


def test_id_switch_phantom_self_pass_removed():
    # one real player, id switches mid-possession: Ta then Tb, no real pass.
    md = _match([
        Player("Ta", Team.HOME, "ta", "#00f"),
        Player("Tb", Team.HOME, "tb", "#00f"),
    ])
    _hold(md, "Ta", 30, 34, t=0.0)
    _hold(md, "Tb", 31, 34, t=1.0)  # same player, new id => engine sees a "pass"
    analyze(md)
    assert sum(1 for e in md.events if e.type == EventType.PASS) == 1  # phantom

    corr = Corrections(
        roster=[RosterPlayer("p1", "Player One", "home", 7)],
        track_to_player={"Ta": "p1", "Tb": "p1"},
    )
    md2 = apply_corrections(md, corr)
    # after merge the phantom self-pass is gone
    assert md2.stats["p1"].passes == 0, md2.stats["p1"].passes
    assert sum(1 for e in md2.events if e.type == EventType.PASS) == 0
    print("  id-switch phantom self-pass removed: OK")


def test_event_edit_and_delete():
    md = _match([Player("Ta", Team.HOME, "ta", "#00f"),
                 Player("Tb", Team.HOME, "tb", "#00f")])
    _hold(md, "Ta", 30, 34, t=0.0)
    _hold(md, "Tb", 50, 34, t=1.0)
    analyze(md)
    assert len(md.events) == 1 and md.events[0].type == EventType.PASS

    # reclassify the single pass as a key_pass via an edit
    corr = Corrections(
        roster=[RosterPlayer("p1", "One", "home", 7), RosterPlayer("p2", "Two", "home", 9)],
        track_to_player={"Ta": "p1", "Tb": "p2"},
        event_edits={0: {"type": "key_pass"}},
    )
    md2 = apply_corrections(md, corr)
    assert md2.stats["p1"].key_passes == 1, md2.stats["p1"].key_passes
    assert all(e.confirmed for e in md2.events)
    print("  event edit (pass -> key_pass) + confirm flag: OK")


if __name__ == "__main__":
    test_merge_fragments_recovers_passes()
    test_id_switch_phantom_self_pass_removed()
    test_event_edit_and_delete()
    print("hitl tests OK")
