"""Heuristic event + statistics engine.

Stage-0 logic that turns per-frame tracks (positions + ball) into events and
per-player statistics. No ML here yet — pure heuristics on the trajectories,
exactly the approach in the design doc:

    nearest player to the ball  -> possession
    change of possession        -> pass / loss / tackle
    ball inside the goal mouth   -> goal (with assist/key_pass credit)

Because everything operates on the canonical MatchData (meters on the pitch),
the very same engine will run later on real CV output — only the *source* of
the frames changes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from model import (
    EventType,
    Event,
    MatchData,
    PlayerStats,
)

# Tuning knobs (meters / seconds).
POSSESSION_RADIUS_M = 2.5        # ball must be within this of a player to count
MIN_SPELL_S = 0.3               # ignore possession spells shorter than this (noise)
MAX_GAP_S = 0.6                 # carry possession across ball-not-detected gaps
GOAL_DEPTH_M = 0.6              # how far past the goal line counts as a goal
SPEED_SMOOTH_S = 0.5           # window for speed estimation
MAX_PLAUSIBLE_SPEED_KMH = 40.0  # clamp tracking jitter


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


@dataclass
class Spell:
    """A continuous stretch where one player holds the ball."""
    player: str
    start_t: float
    end_t: float


def _nearest_player(frame, players_by_id, radius: float) -> Optional[str]:
    """Return the id of the player closest to the ball, within `radius`."""
    if frame.ball is None:
        return None
    bx, by = frame.ball
    best, best_d = None, radius
    for pos in frame.positions:
        d = _dist(pos.x, pos.y, bx, by)
        if d <= best_d:
            best, best_d = pos.player, d
    return best


def _build_spells(md: MatchData, radius: float = POSSESSION_RADIUS_M) -> list[Spell]:
    """Collapse the per-frame possession signal into clean possession spells."""
    players_by_id = {p.id: p for p in md.players}
    raw: list[tuple[float, Optional[str]]] = [
        (f.t, _nearest_player(f, players_by_id, radius)) for f in md.frames
    ]

    spells: list[Spell] = []
    cur_player: Optional[str] = None
    cur_start = 0.0
    last_t = 0.0
    last_seen_t = 0.0

    for t, holder in raw:
        if holder is None:
            # tolerate short gaps without ending the spell
            if cur_player is not None and (t - last_seen_t) > MAX_GAP_S:
                spells.append(Spell(cur_player, cur_start, last_seen_t))
                cur_player = None
            last_t = t
            continue
        if holder != cur_player:
            if cur_player is not None:
                spells.append(Spell(cur_player, cur_start, last_t))
            cur_player = holder
            cur_start = t
        last_seen_t = t
        last_t = t

    if cur_player is not None:
        spells.append(Spell(cur_player, cur_start, last_t))

    # drop noise spells
    return [s for s in spells if (s.end_t - s.start_t) >= MIN_SPELL_S or len(spells) == 1]


def _ball_in_goal(md: MatchData, frame) -> Optional[str]:
    """If the ball is inside a goal mouth, return which goal ('left'/'right')."""
    if frame.ball is None:
        return None
    bx, by = frame.ball
    pitch = md.match.pitch
    cy = pitch.width_m / 2.0
    half_goal = pitch.goal_width_m / 2.0
    if abs(by - cy) > half_goal:
        return None
    if bx <= GOAL_DEPTH_M:
        return "left"
    if bx >= pitch.length_m - GOAL_DEPTH_M:
        return "right"
    return None


def detect_events(md: MatchData, radius: float = POSSESSION_RADIUS_M) -> list[Event]:
    """Derive pass / loss / tackle / goal / assist / key_pass events."""
    players_by_id = {p.id: p for p in md.players}
    spells = _build_spells(md, radius)
    events: list[Event] = []

    # possession transitions -> pass / loss / tackle
    for prev, nxt in zip(spells, spells[1:]):
        a, b = players_by_id.get(prev.player), players_by_id.get(nxt.player)
        if a is None or b is None:
            continue
        t = nxt.start_t
        if a.team == b.team:
            events.append(Event(t=t, type=EventType.PASS, player=a.id,
                                target=b.id, outcome="completed", confidence=0.9))
        else:
            events.append(Event(t=t, type=EventType.LOSS, player=a.id,
                                target=b.id, outcome="lost", confidence=0.75))
            events.append(Event(t=t, type=EventType.TACKLE, player=b.id,
                                target=a.id, outcome="won", confidence=0.7))

    # goals: scan frames; credit last holder + assist/key_pass to prior teammate pass
    goal_cooldown_until = -1.0
    for frame in md.frames:
        side = _ball_in_goal(md, frame)
        if side is None or frame.t < goal_cooldown_until:
            continue
        scorer = _last_holder_before(spells, frame.t)
        if scorer is None:
            continue
        events.append(Event(t=frame.t, type=EventType.GOAL, player=scorer,
                            outcome=side, confidence=0.85))
        # assist + key pass: the completed pass to the scorer immediately before
        assist = _last_pass_to(events, scorer, frame.t)
        if assist is not None:
            events.append(Event(t=assist.t, type=EventType.ASSIST, player=assist.player,
                                target=scorer, outcome="goal", confidence=0.7))
            events.append(Event(t=assist.t, type=EventType.KEY_PASS, player=assist.player,
                                target=scorer, outcome="goal", confidence=0.6))
        goal_cooldown_until = frame.t + 3.0

    events.sort(key=lambda e: (e.t, e.type.value))
    return events


def _last_holder_before(spells: list[Spell], t: float) -> Optional[str]:
    holder = None
    for s in spells:
        if s.start_t <= t:
            holder = s.player
        else:
            break
    return holder


def _last_pass_to(events: list[Event], receiver: str, t: float) -> Optional[Event]:
    """The most recent completed pass whose target is `receiver`, before time t."""
    best = None
    for e in events:
        if e.type == EventType.PASS and e.target == receiver and e.t <= t:
            best = e
    return best


def compute_stats(md: MatchData, events: list[Event],
                  radius: float = POSSESSION_RADIUS_M) -> dict[str, PlayerStats]:
    stats = {p.id: PlayerStats(player=p.id) for p in md.players}

    # event-based tallies
    for e in events:
        s = stats.get(e.player)
        if s is None:
            continue
        if e.type == EventType.PASS:
            s.passes += 1
            if e.outcome == "completed":
                s.passes_completed += 1
        elif e.type == EventType.LOSS:
            s.passes += 1            # a loss is also a (failed) attempt to keep the ball
            s.losses += 1
        elif e.type == EventType.TACKLE:
            s.tackles += 1
        elif e.type == EventType.GOAL:
            s.goals += 1
        elif e.type == EventType.ASSIST:
            s.assists += 1
        elif e.type == EventType.KEY_PASS:
            s.key_passes += 1

    _add_physical_stats(md, stats)
    _add_possession(md, stats, radius)
    return stats


def _add_physical_stats(md: MatchData, stats: dict[str, PlayerStats]) -> None:
    """Distance covered + top speed from consecutive frame positions."""
    last_pos: dict[str, tuple[float, float, float]] = {}  # pid -> (t, x, y)
    speed_window: dict[str, list[tuple[float, float, float]]] = {}  # pid -> [(t, step_m, dt)]

    for frame in md.frames:
        for pos in frame.positions:
            s = stats.get(pos.player)
            if s is None:
                continue
            prev = last_pos.get(pos.player)
            if prev is not None:
                pt, px, py = prev
                dt = frame.t - pt
                if dt > 0:
                    step = _dist(px, py, pos.x, pos.y)
                    s.distance_m += step
                    win = speed_window.setdefault(pos.player, [])
                    win.append((frame.t, step, dt))
                    # trim window
                    while win and win[0][0] < frame.t - SPEED_SMOOTH_S:
                        win.pop(0)
                    # speed = total distance / total elapsed time over the window
                    dist_sum = sum(d for _, d, _ in win)
                    time_sum = sum(ddt for _, _, ddt in win)
                    if time_sum > 0:
                        v_kmh = (dist_sum / time_sum) * 3.6
                        if v_kmh <= MAX_PLAUSIBLE_SPEED_KMH:
                            s.top_speed_kmh = max(s.top_speed_kmh, v_kmh)
            last_pos[pos.player] = (frame.t, pos.x, pos.y)


def _add_possession(md: MatchData, stats: dict[str, PlayerStats],
                    radius: float = POSSESSION_RADIUS_M) -> None:
    spells = _build_spells(md, radius)
    total = 0.0
    for sp in spells:
        dur = sp.end_t - sp.start_t
        s = stats.get(sp.player)
        if s is not None:
            s.possession_s += dur
            total += dur
    if total > 0:
        for s in stats.values():
            s.possession_pct = 100.0 * s.possession_s / total


def analyze(md: MatchData, possession_radius: float = POSSESSION_RADIUS_M) -> MatchData:
    """Full analysis: fill md.events and md.stats in place, return md.

    `possession_radius` is in the same units as the frame coordinates. For
    metric (homography-calibrated or simulated) data the default ~2.5 m is
    right; for the Stage-1 image-projected pipeline a looser value compensates
    for the uncalibrated projection.
    """
    md.events = detect_events(md, possession_radius)
    md.stats = compute_stats(md, md.events, possession_radius)
    return md
