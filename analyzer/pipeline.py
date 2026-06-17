"""Stage-1/2 real CV pipeline.

Takes a real football clip and produces the SAME canonical MatchData the
simulator produced, so the engine and web viewer work unchanged.

Pipeline:
    YOLO11 (COCO: person + sports ball)            -> detections
      [optional] InferenceSlicer / SAHI            -> recover the small ball
    ByteTrack (tuned lost_track_buffer)            -> stable track ids
    KMeans on jersey colour                        -> team A / team B
    homography (+ camera-motion propagation)        -> positions in METERS

Two coordinate regimes:
  * No calibration  -> positions are a naive image->pitch *scaling* (Stage 1).
    Possession logic uses a loosened radius; metric stats are approximate.
  * --homography cal.json -> positions are real meters (Stage 2). For a static
    camera one homography is exact; for a moving camera we propagate it with
    global motion compensation (approximate but metric).

Honest residual limits without a GPU / football-tuned model: on a *moving
broadcast* camera, Re-ID still fragments and propagated homography drifts, so
per-player event counts remain approximate. On a *static wide* camera (the MVP
target) the chain yields trustworthy numbers. Track->player naming is the HITL
step (Stage 3).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from model import (  # noqa: E402
    Frame, MatchData, MatchMeta, Pitch, Player, Position, Team,
)
from engine import analyze  # noqa: E402
import homography as hg  # noqa: E402

PERSON_CLASS = 0
BALL_CLASS = 32  # COCO "sports ball"
HOME_COLOR = "#2563eb"
AWAY_COLOR = "#dc2626"


def _kmeans2(feats: np.ndarray, iters: int = 25, seed: int = 0) -> np.ndarray:
    """Minimal k=2 KMeans (avoids a scikit-learn dependency)."""
    rng = np.random.default_rng(seed)
    if len(feats) < 2:
        return np.zeros(len(feats), dtype=int)
    c = feats[rng.choice(len(feats), 2, replace=False)].astype(float)
    labels = np.zeros(len(feats), dtype=int)
    for _ in range(iters):
        d0 = np.linalg.norm(feats - c[0], axis=1)
        d1 = np.linalg.norm(feats - c[1], axis=1)
        new = (d1 < d0).astype(int)
        if np.array_equal(new, labels):
            break
        labels = new
        for k in (0, 1):
            if np.any(labels == k):
                c[k] = feats[labels == k].mean(axis=0)
    return labels


def _jersey_feature(frame_bgr, box) -> np.ndarray:
    """Mean RGB of the upper-body (jersey) region of a detection box."""
    x1, y1, x2, y2 = [int(v) for v in box]
    h = y2 - y1
    jy2 = y1 + max(1, int(h * 0.5))  # upper half = torso
    crop = frame_bgr[max(0, y1):max(1, jy2), max(0, x1):max(1, x2)]
    if crop.size == 0:
        return np.zeros(3)
    return crop.reshape(-1, 3).mean(axis=0)[::-1]  # BGR -> RGB


def run(source: str, out_json: str, annotated: str | None,
        stride: int, max_seconds: float, model_name: str = "yolo11n.pt",
        conf: float = 0.25, imgsz: int = 1280, use_slicing: bool = False,
        calib_path: str | None = None) -> MatchData:
    import cv2
    import supervision as sv
    from ultralytics import YOLO

    model = YOLO(model_name)
    # a generous lost-track buffer keeps an id alive across short occlusions /
    # missed detections, which is the main weapon against id fragmentation.
    tracker = sv.ByteTrack(lost_track_buffer=90, minimum_matching_threshold=0.85)

    def detect(image):
        result = model(image, verbose=False, conf=conf, imgsz=imgsz)[0]
        return sv.Detections.from_ultralytics(result)

    slicer = None
    if use_slicing:
        def _cb(tile):
            r = model(tile, verbose=False, conf=conf, imgsz=640)[0]
            return sv.Detections.from_ultralytics(r)
        slicer = sv.InferenceSlicer(
            callback=_cb, slice_wh=(640, 640), overlap_wh=(128, 128),
        )

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"could not open video: {source}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    eff_fps = src_fps / stride

    pitch = Pitch()
    sx, sy = pitch.length_m / W, pitch.width_m / H  # image-scale fallback

    # ---- calibration / homography -----------------------------------------
    calib = hg.Calibration.load(calib_path) if calib_path else None
    H0 = (hg.homography_from_correspondences(calib.image_points, calib.pitch_points)
          if calib else None)
    cum_motion = np.eye(3)
    prev_gray = None
    metric = H0 is not None

    writer = None
    if annotated:
        os.makedirs(os.path.dirname(os.path.abspath(annotated)), exist_ok=True)
        writer = cv2.VideoWriter(annotated, cv2.VideoWriter_fourcc(*"mp4v"),
                                 eff_fps, (W, H))
    box_ann = sv.BoxAnnotator() if annotated else None
    label_ann = sv.LabelAnnotator() if annotated else None

    frames: list[Frame] = []
    track_colors: dict[int, list[np.ndarray]] = defaultdict(list)
    ball_frames = 0
    raw_idx = 0
    kept = 0

    def to_pitch(x_px, y_px):
        """Map an image point to pitch meters (homography) or scaled fallback."""
        if metric:
            Ht = hg.propagate(H0, cum_motion)
            X, Y = hg.project_point(Ht, x_px, y_px)
            return X, Y
        return x_px * sx, y_px * sy

    def on_pitch(X, Y):
        return -6.0 <= X <= pitch.length_m + 6.0 and -6.0 <= Y <= pitch.width_m + 6.0

    while True:
        ok, image = cap.read()
        if not ok:
            break
        if raw_idx % stride != 0:
            raw_idx += 1
            continue
        t = kept / eff_fps
        if max_seconds and t > max_seconds:
            break

        # camera-motion propagation for metric projection on moving cameras
        if metric:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            if prev_gray is not None:
                A = hg.estimate_motion(prev_gray, gray)  # prev -> cur
                cum_motion = A @ cum_motion              # ref -> cur
            prev_gray = gray

        det = slicer(image) if slicer is not None else detect(image)

        ball_xy = None
        ball_mask = det.class_id == BALL_CLASS
        if ball_mask.any():
            bx = det.xyxy[ball_mask]
            cx = float((bx[0, 0] + bx[0, 2]) / 2)
            cy = float((bx[0, 1] + bx[0, 3]) / 2)
            X, Y = to_pitch(cx, cy)
            if not metric or on_pitch(X, Y):
                ball_xy = (X, Y)
                ball_frames += 1

        people = det[det.class_id == PERSON_CLASS]
        tracked = tracker.update_with_detections(people)

        positions: list[Position] = []
        for i in range(len(tracked)):
            tid = int(tracked.tracker_id[i])
            x1, y1, x2, y2 = tracked.xyxy[i]
            feet_x = float((x1 + x2) / 2.0)
            feet_y = float(y2)  # bottom-center = player's feet on the ground
            X, Y = to_pitch(feet_x, feet_y)
            if metric and not on_pitch(X, Y):
                continue  # drop crowd / sideline false positives
            positions.append(Position(player=f"T{tid}", x=X, y=Y))
            track_colors[tid].append(_jersey_feature(image, tracked.xyxy[i]))

        frames.append(Frame(t=t, ball=ball_xy, positions=positions))

        if writer is not None:
            labels = [f"#{int(tracked.tracker_id[i])}" for i in range(len(tracked))]
            img2 = box_ann.annotate(image.copy(), tracked)
            img2 = label_ann.annotate(img2, tracked, labels)
            writer.write(img2)

        kept += 1
        raw_idx += 1

    cap.release()
    if writer is not None:
        writer.release()

    # team clustering on mean jersey colour per track
    tids = [t for t in track_colors if track_colors[t]]
    team_of: dict[int, int] = {}
    if len(tids) >= 2:
        feats = np.array([np.mean(track_colors[t], axis=0) for t in tids])
        labels = _kmeans2(feats)
        team_of = {tid: int(lbl) for tid, lbl in zip(tids, labels)}

    players: list[Player] = []
    for tid in sorted(tids):
        cluster = team_of.get(tid, 0)
        players.append(Player(
            id=f"T{tid}", team=Team.HOME if cluster == 0 else Team.AWAY,
            label=f"Track #{tid}",
            color=HOME_COLOR if cluster == 0 else AWAY_COLOR, number=tid,
        ))

    meta = MatchMeta(
        id="clip-001", date="2026-06-17",
        home_team="Team A (cluster 0)", away_team="Team B (cluster 1)",
        fps=eff_fps, duration_s=(kept / eff_fps) if kept else 0.0, pitch=pitch,
    )
    md = MatchData(match=meta, players=players, frames=frames)
    # metric data uses the real ~2.5 m possession radius; the uncalibrated
    # image-projected fallback needs a looser one (see DESIGN.md).
    analyze(md, possession_radius=2.5 if metric else 4.5)
    md._ball_frames = ball_frames  # type: ignore[attr-defined]

    os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
    md.save(out_json)
    return md


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Real CV pipeline (YOLO11 + ByteTrack + homography).")
    ap.add_argument("--source", required=True, help="input video path")
    ap.add_argument("--out", default="web/public/clip-match.json")
    ap.add_argument("--annotated", default="clips/clip-annotated.mp4")
    ap.add_argument("--stride", type=int, default=3, help="process every Nth frame (CPU speed)")
    ap.add_argument("--max-seconds", type=float, default=8.0)
    ap.add_argument("--model", default="yolo11n.pt")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--slice", action="store_true", help="SAHI slicing for the small ball")
    ap.add_argument("--homography", default=None, help="calibration json -> metric meters")
    args = ap.parse_args(argv)

    md = run(args.source, args.out, args.annotated, args.stride, args.max_seconds,
             args.model, args.conf, args.imgsz, args.slice, args.homography)

    ball_n = getattr(md, "_ball_frames", 0)
    metric = args.homography is not None
    print(f"wrote {args.out}  ({'METRIC' if metric else 'image-scaled'})")
    print(f"  frames={len(md.frames)} tracks={len(md.players)} "
          f"ball_frames={ball_n} events={len(md.events)} fps={md.match.fps:.1f}")
    top = sorted(md.stats.values(), key=lambda s: s.passes_completed, reverse=True)[:6]
    for s in top:
        p = md.player(s.player)
        print(f"  {p.label:10s} {p.team.value:4s} passes={s.passes_completed}/{s.passes} "
              f"tackles={s.tackles} losses={s.losses} poss={s.possession_pct:.0f}% "
              f"dist={s.distance_m:.0f}m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
