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

## Architecture (recap)

- **Vercel / Next.js** — frontend + light API (auth, match management, serving results).
- **GPU worker (separate)** — Python CV pipeline as a batch job. Not on Vercel.
- **Object storage (R2/S3)** — raw video + heavy per-frame artifacts.
- **Postgres** — users, teams, squads, matches, events, aggregated stats.

All pitch coordinates are in **meters**, decoupling logic from camera angle/resolution.
