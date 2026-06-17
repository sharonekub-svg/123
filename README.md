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

## Architecture (recap)

- **Vercel / Next.js** — frontend + light API (auth, match management, serving results).
- **GPU worker (separate)** — Python CV pipeline as a batch job. Not on Vercel.
- **Object storage (R2/S3)** — raw video + heavy per-frame artifacts.
- **Postgres** — users, teams, squads, matches, events, aggregated stats.

All pitch coordinates are in **meters**, decoupling logic from camera angle/resolution.
