# PitchVision

Automatic **per-player football analytics from match video** — passes, key passes,
losses, tackles, goals, assists, plus physical metrics (distance, speed, heatmaps,
possession). Think *"Veo, but with personal event-level statistics."*

See [`DESIGN.md`](./DESIGN.md) for the full product + technical plan.

## Status — Stage 0 (running skeleton)

A complete end-to-end loop **without any GPU or video**:

```
simulate (synthetic tracks)  ->  engine (events + stats)  ->  web viewer (radar/timeline/stats)
```

The same engine and unified JSON will later be fed by the real CV pipeline
(YOLO11 → ByteTrack → team clustering → homography). Only the *source* of the
frames changes — see the roadmap in `DESIGN.md`.

## Layout

```
analyzer/   Python core: data model + heuristic engine + simulator (future GPU worker)
web/        Next.js + TS viewer (Vercel): radar, event timeline, per-player stats
DESIGN.md   product + technical design (source of truth)
```

## Quick start

### 1. Generate match data (Python 3.11+, no deps)

```bash
python3 analyzer/cli.py
# -> writes web/public/sample-match.json
```

### 2. Run the viewer

```bash
cd web
npm install
npm run dev          # http://localhost:3000
```

`npm run gen:sample` (inside `web/`) regenerates the data via the analyzer.

## Stage 1 — real CV on a clip (`analyzer/pipeline.py`)

Runs the actual hard tech on a real football video and emits the **same**
canonical JSON, so the engine and viewer work unchanged:

```bash
pip install -r analyzer/requirements.txt
python3 analyzer/pipeline.py --source clip.mp4 \
    --out web/public/clip-match.json --annotated clips/clip-annotated.mp4 \
    --stride 3 --max-seconds 8 --conf 0.10 --imgsz 1280
# then view the real data:  http://localhost:3000/?data=clip
```

Pipeline: **YOLO11** (COCO person + sports-ball) → **ByteTrack** stable ids →
**KMeans** on jersey colour for teams → image→pitch projection → engine.

What this stage proves vs. what it does *not* (honest):

- ✅ Real player detection + multi-object tracking + per-track ids + team split,
  rendered as an annotated video.
- ⚠️ **Per-player event counts (passes/assists/goals/losses) are NOT trustworthy
  here.** They need (a) a football-tuned ball detector, (b) a real homography to
  measure metric proximity, and (c) stable Re-ID so a track == a player. On a
  moving broadcast camera with the generic COCO model, tracks fragment (a single
  player becomes many short track ids) and the ball is sparse — so possession,
  and everything derived from it, is unreliable. This is exactly why the design
  puts homography in Stage 2 and HITL Re-ID in Stage 3. The stat engine itself is
  proven correct on calibrated data (the Stage-0 simulation).

## Stage 2 — metric accuracy via homography (`analyzer/homography.py`)

This is what turns pixel tracks into trustworthy **meters**, and therefore into
trustworthy statistics. Given >= 4 correspondences between image pixels and known
pitch locations, we solve a 3x3 homography `H` so `pitch_m = H · pixel`.

```bash
# static (or near-static) camera: calibrate once, get real meters
python3 analyzer/pipeline.py --source clip.mp4 \
    --homography analyzer/calibration.example.json --slice --max-seconds 8
```

- **Static wide camera (the MVP target):** one homography is exact for the whole
  clip → metric distances/speeds and a correct 2.5 m possession radius → real
  per-player passes/tackles/possession.
- **Moving / broadcast camera:** a single `H` is wrong as the camera pans, so we
  propagate the frame-0 homography with **global motion compensation** (ORB
  feature matching → per-frame affine, chained). Approximate, but recovers metric
  positions without a pitch-keypoint model.

**Proven correct, not hand-waved.** `analyzer/tests/test_metric_pipeline.py`
renders a ground-truth match through a known camera into pixels, runs the exact
calibrate→project path, and asserts the recovered positions (≤1e-6 m) and every
per-player stat match the ground truth. `test_homography.py`/`test_engine.py`
cover the math and event logic.

```bash
python3 analyzer/homography.py             # homography self-test
python3 analyzer/tests/test_engine.py      # event + stats logic
python3 analyzer/tests/test_metric_pipeline.py   # full metric chain
```

### Honest accuracy ceiling here

On the bundled **broadcast** clip, with the generic COCO model, no GPU, and no
pitch-keypoint model (Roboflow's is behind a blocked host + API key), two limits
remain: Re-ID still fragments under camera motion, and propagated homography
drifts. So per-player event counts on *that* clip stay approximate. The pieces
that make them exact — a football-tuned detector, a keypoint homography model, a
GPU, and HITL Re-ID (Stage 3) — are the documented next steps. The machinery is
all here and tested; it needs calibrated input (a static camera or those models)
to deliver exact numbers.

## Stage 3 — human-in-the-loop corrections (`analyzer/hitl.py` + `/review`)

The fix for fragmented Re-ID. The pipeline emits *tracks*; a human maps each
track to a real roster player (many fragments of one player → one entry),
confirms/edits the critical events, and stats are recomputed per real player.

- **Web `/review`**: assign tracks → players, edit/confirm/delete events, live
  per-player preview. Saves to `localStorage`; Download produces `corrections.json`.
- **`analyzer/hitl.py`**: the authoritative recompute. `apply_corrections` merges
  trajectories, curates events, and — importantly — drops the *phantom self-pass*
  an id switch creates when a player appears to pass to themselves.

```bash
python3 analyzer/hitl.py --in web/public/clip-match.json \
    --corrections corrections.json --out web/public/clip-confirmed.json
```

Proven by `analyzer/tests/test_hitl.py`: fragmenting a player into two tracks and
mapping both back recovers the correct per-player passes, and a mid-possession id
switch no longer produces a phantom pass.

## Architecture (recap)

- **Vercel / Next.js** — frontend + light API (auth, match management, serving results).
- **GPU worker (separate)** — Python CV pipeline as a batch job. Not on Vercel.
- **Object storage (R2/S3)** — raw video + heavy per-frame artifacts.
- **Postgres** — users, teams, squads, matches, events, aggregated stats.

All pitch coordinates are in **meters**, decoupling logic from camera angle/resolution.
