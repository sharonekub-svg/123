"""Deterministic checks for the heuristic event/stats engine.

Hand-built tiny matches with a known ground truth, so the engine logic is
verified independently of the simulator. Run: python3 analyzer/tests/test_engine.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model import (  # noqa: E402
    EventType, Frame, MatchData, MatchMeta, Pitch, Player, Position, Team,
)
from engine import analyze  # noqa: E402


def _match(players):
    meta = MatchMeta(id="t", date="2026-01-01", home_team="A", away_team="B",
                     fps=10.0, duration_s=0.0, pitch=Pitch())
    return MatchData(match=meta, players=players, frames=[])


def _hold(md, pid, x, y, t, n=6, dt=0.1):
    """Append n frames where `pid` holds the ball at (x,y)."""
    for k in range(n):
        tt = t + k * dt
        md.frames.append(Frame(t=tt, ball=(x, y),
                               positions=[Position(player=pid, x=x, y=y)]))


def test_pass_between_teammates():
    players = [Player("H1", Team.HOME, "h1", "#00f"), Player("H2", Team.HOME, "h2", "#00f")]
    md = _match(players)
    _hold(md, "H1", 30, 34, t=0.0)
    _hold(md, "H2", 50, 34, t=1.0)
    analyze(md)
    passes = [e for e in md.events if e.type == EventType.PASS]
    assert len(passes) == 1, md.events
    assert passes[0].player == "H1" and passes[0].target == "H2"
    assert md.stats["H1"].passes_completed == 1
    print("  pass between teammates: OK")


def test_turnover_is_loss_plus_tackle():
    players = [Player("H1", Team.HOME, "h1", "#00f"), Player("A1", Team.AWAY, "a1", "#f00")]
    md = _match(players)
    _hold(md, "H1", 40, 34, t=0.0)
    _hold(md, "A1", 60, 34, t=1.0)
    analyze(md)
    assert any(e.type == EventType.LOSS and e.player == "H1" for e in md.events)
    assert any(e.type == EventType.TACKLE and e.player == "A1" for e in md.events)
    assert md.stats["H1"].losses == 1 and md.stats["A1"].tackles == 1
    print("  turnover -> loss + tackle: OK")


def test_goal_with_assist():
    players = [Player("H1", Team.HOME, "h1", "#00f"), Player("H2", Team.HOME, "h2", "#00f")]
    md = _match(players)
    _hold(md, "H1", 90, 34, t=0.0)          # H1 has it
    _hold(md, "H2", 100, 34, t=1.0)         # pass to H2 near goal
    # H2 shoots: ball crosses the right goal line at y center
    md.frames.append(Frame(t=2.0, ball=(105.0, 34.0),
                           positions=[Position(player="H2", x=103, y=34)]))
    analyze(md)
    assert any(e.type == EventType.GOAL and e.player == "H2" for e in md.events), md.events
    assert md.stats["H2"].goals == 1
    assert md.stats["H1"].assists == 1 and md.stats["H1"].key_passes == 1
    print("  goal with assist + key pass: OK")


def test_distance_and_speed():
    players = [Player("H1", Team.HOME, "h1", "#00f")]
    md = _match(players)
    # move 1 m every 0.1 s along x = 10 m/s = 36 km/h, for 10 frames (~9 m)
    for k in range(10):
        md.frames.append(Frame(t=k * 0.1, ball=None,
                               positions=[Position(player="H1", x=float(k), y=0.0)]))
    analyze(md)
    s = md.stats["H1"]
    assert 8.5 <= s.distance_m <= 9.5, s.distance_m
    assert 30 <= s.top_speed_kmh <= 40, s.top_speed_kmh
    print(f"  distance/speed: OK (dist={s.distance_m:.1f}m top={s.top_speed_kmh:.1f}km/h)")


if __name__ == "__main__":
    test_pass_between_teammates()
    test_turnover_is_loss_plus_tackle()
    test_goal_with_assist()
    test_distance_and_speed()
    print("engine tests OK")
