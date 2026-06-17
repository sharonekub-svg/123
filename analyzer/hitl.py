"""Human-in-the-loop corrections (Stage 3).

The CV pipeline emits *tracks* (T1, T2, ...). Under camera motion a single real
player fragments into many short tracks (the Re-ID problem). HITL is the fix: a
human maps each track to a real roster player (name + number), confirms/edits the
critical events, and we recompute per-player statistics from the corrected data.

This module is the authoritative re-aggregation: given a MatchData of tracks plus
a Corrections object (produced by the /review web screen), it returns a new
MatchData keyed by real players, with merged trajectories, curated events, and
recomputed stats. Merging also removes the phantom "self pass" that an id switch
creates when one player's possession appears to change hands to themselves.

CLI:
    python analyzer/hitl.py --in web/public/clip-match.json \
        --corrections corrections.json --out web/public/clip-confirmed.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from model import (  # noqa: E402
    Event, EventType, Frame, MatchData, Player, Position, Team,
)
from engine import compute_stats  # noqa: E402

HOME_COLOR = "#2563eb"
AWAY_COLOR = "#dc2626"


@dataclass
class RosterPlayer:
    id: str
    name: str
    team: str            # "home" | "away"
    number: int | None = None

    @staticmethod
    def from_dict(d: dict) -> "RosterPlayer":
        return RosterPlayer(id=str(d["id"]), name=str(d["name"]),
                            team=str(d["team"]), number=d.get("number"))


@dataclass
class Corrections:
    roster: list[RosterPlayer] = field(default_factory=list)
    track_to_player: dict[str, str] = field(default_factory=dict)
    deleted_events: list[int] = field(default_factory=list)        # indices into md.events
    event_edits: dict[int, dict] = field(default_factory=dict)     # index -> field overrides
    added_events: list[Event] = field(default_factory=list)

    @staticmethod
    def from_dict(d: dict) -> "Corrections":
        return Corrections(
            roster=[RosterPlayer.from_dict(r) for r in d.get("roster", [])],
            track_to_player={str(k): str(v) for k, v in d.get("track_to_player", {}).items()},
            deleted_events=[int(i) for i in d.get("deleted_events", [])],
            event_edits={int(k): v for k, v in d.get("event_edits", {}).items()},
            added_events=[Event.from_dict(e) for e in d.get("added_events", [])],
        )

    @staticmethod
    def load(path: str) -> "Corrections":
        with open(path, encoding="utf-8") as fh:
            return Corrections.from_dict(json.load(fh))


def apply_corrections(md: MatchData, corr: Corrections,
                      possession_radius: float = 2.5) -> MatchData:
    roster_ids = {r.id for r in corr.roster}
    players = [
        Player(id=r.id, team=Team(r.team), label=r.name,
               color=HOME_COLOR if r.team == "home" else AWAY_COLOR, number=r.number)
        for r in corr.roster
    ]
    m = corr.track_to_player

    # remap frame positions: track id -> roster player id, dropping unmapped
    # tracks and de-duplicating if two tracks of one player coexist in a frame.
    new_frames: list[Frame] = []
    for f in md.frames:
        seen: set[str] = set()
        positions: list[Position] = []
        for p in f.positions:
            pid = m.get(p.player)
            if pid is None or pid in seen:
                continue
            seen.add(pid)
            positions.append(Position(player=pid, x=p.x, y=p.y))
        new_frames.append(Frame(t=f.t, ball=f.ball, positions=positions))

    # remap + curate events
    events: list[Event] = []
    for i, e in enumerate(md.events):
        if i in corr.deleted_events:
            continue
        player = m.get(e.player, e.player)
        target = m.get(e.target, e.target) if e.target else None
        etype = e.type
        outcome = e.outcome
        edit = corr.event_edits.get(i)
        if edit:
            player = edit.get("player", player)
            target = edit.get("target", target)
            etype = EventType(edit["type"]) if "type" in edit else etype
            outcome = edit.get("outcome", outcome)
        # drop events that don't resolve to a real player, and phantom self-events
        # (an id switch making a player "pass to themselves")
        if player not in roster_ids:
            continue
        if target == player and etype in (EventType.PASS, EventType.KEY_PASS,
                                          EventType.ASSIST, EventType.TACKLE, EventType.LOSS):
            continue
        events.append(Event(t=e.t, type=etype, player=player, target=target,
                            outcome=outcome, confidence=e.confidence, confirmed=True))

    for e in corr.added_events:
        if e.player in roster_ids:
            events.append(Event(t=e.t, type=e.type, player=e.player, target=e.target,
                                outcome=e.outcome, confidence=e.confidence, confirmed=True))

    events.sort(key=lambda e: (e.t, e.type.value))
    md2 = MatchData(match=md.match, players=players, frames=new_frames, events=events)
    # event tallies come from the curated events; physical + possession from frames
    md2.stats = compute_stats(md2, md2.events, possession_radius)
    return md2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Apply HITL corrections and recompute stats.")
    ap.add_argument("--in", dest="inp", required=True, help="tracks MatchData json")
    ap.add_argument("--corrections", required=True, help="corrections json from /review")
    ap.add_argument("--out", required=True, help="output confirmed MatchData json")
    ap.add_argument("--radius", type=float, default=2.5)
    args = ap.parse_args(argv)

    md = MatchData.load(args.inp)
    corr = Corrections.load(args.corrections)
    md2 = apply_corrections(md, corr, args.radius)
    md2.save(args.out)

    print(f"wrote {args.out}")
    print(f"  players={len(md2.players)} (from {len(md.players)} tracks) events={len(md2.events)}")
    for s in sorted(md2.stats.values(), key=lambda s: s.goals * 10 + s.passes_completed, reverse=True)[:8]:
        p = md2.player(s.player)
        print(f"  {p.label:14s} #{p.number}  G={s.goals} A={s.assists} "
              f"passes={s.passes_completed}/{s.passes} tck={s.tackles} loss={s.losses}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
