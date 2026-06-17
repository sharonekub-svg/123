"""PitchVision analyzer CLI.

Stage-0 entry point: generate a synthetic match, run the heuristic engine, and
write the unified JSON — both as a standalone artifact and (by default) straight
into the web app's public folder so the viewer has real data to render.

    python -m analyzer.cli                       # -> web/public/sample-match.json
    python analyzer/cli.py --out match.json      # custom path
    python analyzer/cli.py --duration 90 --fps 5 # tweak the sim
"""

from __future__ import annotations

import argparse
import os
import sys

# allow running both as `python -m analyzer.cli` and `python analyzer/cli.py`
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import analyze          # noqa: E402
from simulate import simulate       # noqa: E402

DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "web", "public", "sample-match.json",
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate + analyze a synthetic PitchVision match.")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output JSON path")
    ap.add_argument("--duration", type=float, default=120.0, help="match duration (s)")
    ap.add_argument("--fps", type=float, default=10.0, help="frames per second")
    ap.add_argument("--seed", type=int, default=7, help="random seed")
    args = ap.parse_args(argv)

    md = simulate(duration_s=args.duration, fps=args.fps, seed=args.seed)
    analyze(md)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    md.save(args.out)

    # quick summary so the run is self-verifying
    n_goals = sum(s.goals for s in md.stats.values())
    n_passes = sum(s.passes for s in md.stats.values())
    print(f"wrote {args.out}")
    print(f"  frames={len(md.frames)} players={len(md.players)} events={len(md.events)}")
    print(f"  goals={n_goals} pass_attempts={n_passes}")
    top = sorted(md.stats.values(), key=lambda s: s.distance_m, reverse=True)[:3]
    for s in top:
        p = md.player(s.player)
        print(f"  {p.label:12s} dist={s.distance_m:6.0f}m top={s.top_speed_kmh:4.1f}km/h "
              f"passes={s.passes_completed}/{s.passes} poss={s.possession_pct:.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
