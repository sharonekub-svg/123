"""End-to-end proof that the METRIC pipeline is correct.

We take a ground-truth match in meters, render it through a known perspective
camera into "pixels", then run the exact projection the real pipeline uses
(calibrate from 4 corner correspondences -> homography -> project back). The
recovered meter positions, and every derived statistic, must match the ground
truth. This shows that *given a correct calibration* the system produces correct
per-player metric statistics — the part a real static-camera deployment relies on.

Run: python3 analyzer/tests/test_metric_pipeline.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model import Frame, MatchData, Position  # noqa: E402
from engine import analyze  # noqa: E402
from simulate import simulate  # noqa: E402
import homography as hg  # noqa: E402


def _render_to_pixels(md: MatchData, H_pitch_to_img) -> MatchData:
    """Project a meters-MatchData into a synthetic camera's pixel space."""
    frames = []
    for f in md.frames:
        ball_px = None
        if f.ball is not None:
            ball_px = tuple(hg.project(H_pitch_to_img, [list(f.ball)])[0])
        pos_px = []
        if f.positions:
            pts = [[p.x, p.y] for p in f.positions]
            proj = hg.project(H_pitch_to_img, pts)
            pos_px = [Position(p.player, float(q[0]), float(q[1]))
                      for p, q in zip(f.positions, proj)]
        frames.append(Frame(t=f.t, ball=ball_px, positions=pos_px))
    return MatchData(match=md.match, players=md.players, frames=frames)


def _project_back(md_px: MatchData, H_img_to_pitch) -> MatchData:
    frames = []
    for f in md_px.frames:
        ball_m = None
        if f.ball is not None:
            ball_m = tuple(hg.project(H_img_to_pitch, [list(f.ball)])[0])
        pos_m = []
        if f.positions:
            pts = [[p.x, p.y] for p in f.positions]
            proj = hg.project(H_img_to_pitch, pts)
            pos_m = [Position(p.player, float(q[0]), float(q[1]))
                     for p, q in zip(f.positions, proj)]
        frames.append(Frame(t=f.t, ball=ball_m, positions=pos_m))
    return MatchData(match=md_px.match, players=md_px.players, frames=frames)


def main():
    # 1. ground truth in meters
    md_true = simulate(duration_s=30.0, fps=10.0, seed=3)
    analyze(md_true)

    # 2. a known perspective camera: pitch corners -> a plausible image quad
    pitch_corners = np.array([[0, 0], [105, 0], [105, 68], [0, 68]], dtype=np.float64)
    img_quad = np.array([[280, 880], [1640, 870], [1905, 1050], [40, 1065]], dtype=np.float64)

    # the calibration the pipeline is given: image -> pitch
    H_img2pitch = hg.homography_from_correspondences(img_quad, pitch_corners)
    H_pitch2img = np.linalg.inv(H_img2pitch)

    # 3. render meters -> pixels, then recover pixels -> meters
    md_px = _render_to_pixels(md_true, H_pitch2img)
    md_rec = _project_back(md_px, H_img2pitch)
    analyze(md_rec)

    # 4a. positions recovered to sub-millimeter
    max_err = 0.0
    for ft, fr in zip(md_true.frames, md_rec.frames):
        for pt, pr in zip(ft.positions, fr.positions):
            max_err = max(max_err, abs(pt.x - pr.x), abs(pt.y - pr.y))
    assert max_err < 1e-6, f"position recovery error {max_err} m"
    print(f"  position recovery: OK (max error {max_err:.2e} m)")

    # 4b. every per-player stat is identical to ground truth
    for pid in md_true.stats:
        a, b = md_true.stats[pid], md_rec.stats[pid]
        assert (a.passes, a.passes_completed, a.goals, a.assists, a.tackles,
                a.losses) == (b.passes, b.passes_completed, b.goals, b.assists,
                              b.tackles, b.losses), pid
        assert abs(a.distance_m - b.distance_m) < 1e-3, pid
    n_goals = sum(s.goals for s in md_rec.stats.values())
    n_pass = sum(s.passes_completed for s in md_rec.stats.values())
    print(f"  per-player stats match ground truth: OK "
          f"(goals={n_goals} completed_passes={n_pass})")
    print("metric pipeline test OK")


if __name__ == "__main__":
    main()
