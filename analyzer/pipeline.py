"""Stage-1 real CV pipeline.

Takes a real football clip and produces the SAME canonical MatchData that the
simulator produced in Stage 0 — so the existing engine and web viewer light up
with real tracks instead of synthetic ones.

Pipeline:
    YOLO11 (COCO: person + sports ball)  ->  detections
    ByteTrack (supervision)              ->  stable track ids
    KMeans on jersey colour              ->  team A / team B
    image -> pitch projection            ->  positions (meters, UNcalibrated)

Honest limitations (Stage 1, no GPU / no pitch-keypoint model here):
  * Detection uses the generic COCO model (person/sports-ball), not a
    football-tuned model — referees/GK are not separated.
  * Positions are a plain image->pitch *scaling*, NOT a homography. Good enough
    for a top-down sketch and for possession logic; metric distances/speeds are
    therefore approximate. True homography + radar is Stage 2.
  * Track ids are not yet mapped to real player names/numbers — that is the
    HITL step (Stage 3). Stats are reported per track id.

Usage:
    python analyzer/pipeline.py --source clip.mp4 \
        --out web/public/clip-match.json --annotated web/public/clip-annotated.mp4 \
        --stride 3 --max-seconds 8
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
        conf: float = 0.25, imgsz: int = 640) -> MatchData:
    import cv2
    import supervision as sv
    from ultralytics import YOLO

    model = YOLO(model_name)
    tracker = sv.ByteTrack()
    ball_frames = 0

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"could not open video: {source}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    eff_fps = src_fps / stride

    pitch = Pitch()
    sx, sy = pitch.length_m / W, pitch.width_m / H

    writer = None
    if annotated:
        os.makedirs(os.path.dirname(os.path.abspath(annotated)), exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(annotated, fourcc, eff_fps, (W, H))
    box_ann = sv.BoxAnnotator() if annotated else None
    label_ann = sv.LabelAnnotator() if annotated else None

    frames: list[Frame] = []
    track_colors: dict[int, list[np.ndarray]] = defaultdict(list)
    raw_idx = 0
    kept = 0

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

        result = model(image, verbose=False, conf=conf, imgsz=imgsz)[0]
        det = sv.Detections.from_ultralytics(result)

        ball_xy = None
        ball_mask = det.class_id == BALL_CLASS
        if ball_mask.any():
            ball_frames += 1
            bx = det.xyxy[ball_mask]
            cx = (bx[:, 0] + bx[:, 2]) / 2
            cy = (bx[:, 1] + bx[:, 3]) / 2
            ball_xy = (float(cx[0]) * sx, float(cy[0]) * sy)

        people = det[det.class_id == PERSON_CLASS]
        tracked = tracker.update_with_detections(people)

        positions: list[Position] = []
        for i in range(len(tracked)):
            tid = int(tracked.tracker_id[i])
            x1, y1, x2, y2 = tracked.xyxy[i]
            feet_x = float((x1 + x2) / 2.0)
            feet_y = float(y2)  # bottom-center = player's feet on the ground
            positions.append(Position(player=f"T{tid}", x=feet_x * sx, y=feet_y * sy))
            track_colors[tid].append(_jersey_feature(image, tracked.xyxy[i]))

        frames.append(Frame(t=t, ball=ball_xy, positions=positions))

        if writer is not None:
            labels = [f"#{int(tracked.tracker_id[i])}" for i in range(len(tracked))]
            annotated_img = box_ann.annotate(image.copy(), tracked)
            annotated_img = label_ann.annotate(annotated_img, tracked, labels)
            writer.write(annotated_img)

        kept += 1
        raw_idx += 1

    cap.release()
    if writer is not None:
        writer.release()

    # team clustering on mean jersey colour per track
    tids = [t for t in track_colors if track_colors[t]]
    mean_feats = np.array([np.mean(track_colors[t], axis=0) for t in tids])
    team_of: dict[int, int] = {}
    if len(tids) >= 2:
        labels = _kmeans2(mean_feats)
        team_of = {tid: int(lbl) for tid, lbl in zip(tids, labels)}

    players: list[Player] = []
    for tid in sorted(tids):
        cluster = team_of.get(tid, 0)
        team = Team.HOME if cluster == 0 else Team.AWAY
        players.append(Player(
            id=f"T{tid}", team=team,
            label=f"Track #{tid}",
            color=HOME_COLOR if cluster == 0 else AWAY_COLOR,
            number=tid,
        ))

    meta = MatchMeta(
        id="clip-001", date="2026-06-17",
        home_team="Team A (cluster 0)", away_team="Team B (cluster 1)",
        fps=eff_fps, duration_s=(kept / eff_fps) if kept else 0.0,
        pitch=pitch,
    )
    md = MatchData(match=meta, players=players, frames=frames)
    # looser radius: positions are an uncalibrated image->pitch scaling, so the
    # metric 2.5 m default is too tight (see DESIGN.md, homography is Stage 2).
    analyze(md, possession_radius=4.5)

    os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
    md.save(out_json)
    return md


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Stage-1 CV pipeline (YOLO11 + ByteTrack).")
    ap.add_argument("--source", required=True, help="input video path")
    ap.add_argument("--out", default="web/public/clip-match.json")
    ap.add_argument("--annotated", default="web/public/clip-annotated.mp4")
    ap.add_argument("--stride", type=int, default=3, help="process every Nth frame (CPU speed)")
    ap.add_argument("--max-seconds", type=float, default=8.0, help="cap processed clip length")
    ap.add_argument("--model", default="yolo11n.pt")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=640)
    args = ap.parse_args(argv)

    md = run(args.source, args.out, args.annotated, args.stride, args.max_seconds,
             args.model, args.conf, args.imgsz)

    n_tracks = len(md.players)
    ball_n = sum(1 for f in md.frames if f.ball is not None)
    print(f"wrote {args.out}")
    print(f"  frames={len(md.frames)} tracks={n_tracks} ball_frames={ball_n} "
          f"events={len(md.events)} fps={md.match.fps:.1f}")
    top = sorted(md.stats.values(), key=lambda s: s.passes_completed, reverse=True)[:6]
    for s in top:
        p = md.player(s.player)
        print(f"  {p.label:10s} {p.team.value:4s} passes={s.passes_completed}/{s.passes} "
              f"tackles={s.tackles} losses={s.losses} poss={s.possession_pct:.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
