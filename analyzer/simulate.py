"""Synthetic match generator (Stage-0 "simulation mode").

Produces a fully-formed MatchData with realistic per-frame positions and ball
movement, WITHOUT any video or GPU. This lets us exercise the whole pipeline
end-to-end (engine -> stats -> web viewer) and is also the fixture the web app
ships with so it renders something real on first load.

The output is intentionally raw: only `frames` (positions + ball) are produced
here. Events and stats are then derived by `engine.analyze`, exactly as they
will be for real CV output.
"""

from __future__ import annotations

import random

from model import (
    DEFAULT_PITCH_LENGTH_M,
    DEFAULT_PITCH_WIDTH_M,
    Frame,
    MatchData,
    MatchMeta,
    Pitch,
    Player,
    Position,
    Team,
)

# 4-3-3 as (x_fraction_of_own_half, y_fraction_of_width). x measured from own goal.
FORMATION = [
    (0.05, 0.50),  # GK
    (0.22, 0.18), (0.22, 0.40), (0.22, 0.60), (0.22, 0.82),  # defenders
    (0.45, 0.28), (0.45, 0.50), (0.45, 0.72),                # midfielders
    (0.72, 0.25), (0.72, 0.50), (0.72, 0.75),                # forwards
]

HOME_COLORS = "#2563eb"   # blue
AWAY_COLORS = "#dc2626"   # red


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _build_players() -> tuple[list[Player], dict[str, tuple[float, float]]]:
    """Create both squads and their formation anchors (in meters)."""
    L, W = DEFAULT_PITCH_LENGTH_M, DEFAULT_PITCH_WIDTH_M
    players: list[Player] = []
    anchors: dict[str, tuple[float, float]] = {}

    for i, (fx, fy) in enumerate(FORMATION):
        # home attacks +x: spread from its own goal up into the opponent half
        hid = f"H{i + 1}"
        ax, ay = fx * L, fy * W
        players.append(Player(id=hid, team=Team.HOME, label=f"Home #{i + 1}",
                              color=HOME_COLORS, number=i + 1))
        anchors[hid] = (ax, ay)

        # away mirrors across the half line, attacks -x
        aid = f"A{i + 1}"
        bx, by = L - fx * L, W - fy * W
        players.append(Player(id=aid, team=Team.AWAY, label=f"Away #{i + 1}",
                              color=AWAY_COLORS, number=i + 1))
        anchors[aid] = (bx, by)

    return players, anchors


def simulate(
    duration_s: float = 120.0,
    fps: float = 10.0,
    seed: int = 7,
    match_id: str = "sim-001",
) -> MatchData:
    rng = random.Random(seed)
    L, W = DEFAULT_PITCH_LENGTH_M, DEFAULT_PITCH_WIDTH_M
    cy = W / 2.0

    players, anchors = _build_players()
    by_id = {p.id: p for p in players}
    outfield = [p.id for p in players]  # everyone may touch the ball in this toy sim

    # current player positions start at anchors
    pos = {pid: list(anchors[pid]) for pid in by_id}

    dt = 1.0 / fps
    n_frames = int(duration_s * fps)

    # ball / possession state machine
    holder = "H7"                 # central mid kicks off
    ball = list(pos[holder])
    mode = "hold"
    timer = rng.uniform(1.0, 2.5)
    travel_from = (0.0, 0.0)
    travel_to = (0.0, 0.0)
    travel_total = 0.0
    travel_left = 0.0
    pending_holder = None

    frames: list[Frame] = []

    def choose_action():
        """Decide what the holder does next; set up travel target."""
        nonlocal mode, travel_from, travel_to, travel_total, travel_left, pending_holder
        team = by_id[holder].team
        teammates = [p.id for p in players if p.team == team and p.id != holder]
        opponents = [p.id for p in players if p.team != team]
        roll = rng.random()

        attack_goal_x = L if team == Team.HOME else 0.0
        near_goal = abs(ball[0] - attack_goal_x) < 40.0

        if near_goal and roll < 0.30:
            # shot on goal (mostly on target)
            target_y = cy + rng.uniform(-3.5, 3.5)
            travel_to = (attack_goal_x, _clamp(target_y, 2.0, W - 2.0))
            pending_holder = None  # goal / loose ball
        elif roll < 0.80:
            # pass to a teammate, biased toward whoever is further up the pitch
            def advance(pid):
                return pos[pid][0] if team == Team.HOME else (L - pos[pid][0])
            weights = [max(advance(p) - advance(holder) + 12.0, 1.0) for p in teammates]
            tgt = rng.choices(teammates, weights=weights, k=1)[0]
            travel_to = tuple(pos[tgt])
            pending_holder = tgt
        else:
            # turnover to a nearby opponent
            opp = min(opponents, key=lambda o: (pos[o][0] - ball[0]) ** 2 + (pos[o][1] - ball[1]) ** 2)
            travel_to = tuple(pos[opp])
            pending_holder = opp

        travel_from = (ball[0], ball[1])
        travel_total = travel_left = rng.uniform(0.4, 1.1)
        mode = "travel"

    for k in range(n_frames):
        t = k * dt

        if mode == "hold":
            timer -= dt
            # glue ball to holder with slight jitter
            ball[0] = _clamp(pos[holder][0] + rng.uniform(-0.5, 0.5), 0, L)
            ball[1] = _clamp(pos[holder][1] + rng.uniform(-0.5, 0.5), 0, W)
            if timer <= 0:
                choose_action()
        else:  # travel
            travel_left -= dt
            frac = 1.0 - max(travel_left, 0.0) / travel_total
            ball[0] = _clamp(travel_from[0] + (travel_to[0] - travel_from[0]) * frac, 0, L)
            ball[1] = _clamp(travel_from[1] + (travel_to[1] - travel_from[1]) * frac, 0, W)
            if travel_left <= 0:
                if pending_holder is None:
                    # shot resolved: goal frame is emitted (ball at goal line); then reset
                    frames.append(_make_frame(t, tuple(ball), pos, by_id))
                    holder = rng.choice(outfield)
                    pos[holder] = [L / 2.0, cy]
                    ball = [L / 2.0, cy]
                    mode = "hold"
                    timer = rng.uniform(1.0, 2.5)
                    _drift_players(pos, anchors, ball, by_id, rng, dt, L, W)
                    continue
                holder = pending_holder
                ball = list(pos[holder])
                mode = "hold"
                timer = rng.uniform(0.8, 2.2)

        _drift_players(pos, anchors, ball, by_id, rng, dt, L, W, exclude=holder if mode == "hold" else None)
        frames.append(_make_frame(t, tuple(ball), pos, by_id))

    meta = MatchMeta(
        id=match_id,
        date="2026-06-17",
        home_team="PitchVision FC",
        away_team="Rivals United",
        fps=fps,
        duration_s=duration_s,
        pitch=Pitch(),
    )
    return MatchData(match=meta, players=players, frames=frames)


def _drift_players(pos, anchors, ball, by_id, rng, dt, L, W, exclude=None):
    """Move every player a little toward their anchor + a pull toward the ball."""
    for pid, p in by_id.items():
        if pid == exclude:
            continue
        ax, ay = anchors[pid]
        # bias the anchor toward the ball's x (team shape shifts with play)
        pull = 0.15
        tx = ax + (ball[0] - ax) * pull
        ty = ay + (ball[1] - ay) * pull
        speed = rng.uniform(1.5, 6.5)  # m/s
        step = speed * dt
        dx, dy = tx - pos[pid][0], ty - pos[pid][1]
        d = (dx * dx + dy * dy) ** 0.5
        if d > 1e-6:
            pos[pid][0] += dx / d * min(step, d) + rng.uniform(-0.15, 0.15)
            pos[pid][1] += dy / d * min(step, d) + rng.uniform(-0.15, 0.15)
        pos[pid][0] = _clamp(pos[pid][0], 0, L)
        pos[pid][1] = _clamp(pos[pid][1], 0, W)


def _make_frame(t, ball, pos, by_id) -> Frame:
    return Frame(
        t=t,
        ball=ball,
        positions=[Position(player=pid, x=pos[pid][0], y=pos[pid][1]) for pid in by_id],
    )
