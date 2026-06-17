// HITL corrections model + a client-side preview of event-based stats.
// The authoritative recompute (incl. possession/speed) is analyzer/hitl.py;
// this mirrors only the event tallies + distance so /review updates live.

import type { EventType, MatchData, MatchEvent } from "./types";

export interface RosterPlayer {
  id: string;
  name: string;
  team: "home" | "away";
  number: number | null;
}

export interface Corrections {
  roster: RosterPlayer[];
  track_to_player: Record<string, string>;
  deleted_events: number[];
  event_edits: Record<number, Partial<Pick<MatchEvent, "type" | "player" | "target" | "outcome">>>;
  added_events: MatchEvent[];
}

export function emptyCorrections(): Corrections {
  return {
    roster: [],
    track_to_player: {},
    deleted_events: [],
    event_edits: {},
    added_events: [],
  };
}

export interface PreviewStat {
  player: string;
  passes: number;
  passes_completed: number;
  key_passes: number;
  losses: number;
  tackles: number;
  goals: number;
  assists: number;
  distance_m: number;
}

const PASS_LIKE: EventType[] = ["pass", "key_pass", "assist", "tackle", "loss"];

function dist(ax: number, ay: number, bx: number, by: number) {
  return Math.hypot(ax - bx, ay - by);
}

// Mirrors hitl.apply_corrections: remap tracks->players, drop unmapped and
// phantom self-events, tally event counts, and sum distance from frames.
export function previewStats(
  data: MatchData,
  corr: Corrections,
): Record<string, PreviewStat> {
  const rosterIds = new Set(corr.roster.map((r) => r.id));
  const m = corr.track_to_player;
  const stats: Record<string, PreviewStat> = {};
  for (const r of corr.roster) {
    stats[r.id] = {
      player: r.id, passes: 0, passes_completed: 0, key_passes: 0,
      losses: 0, tackles: 0, goals: 0, assists: 0, distance_m: 0,
    };
  }

  data.events.forEach((e, i) => {
    if (corr.deleted_events.includes(i)) return;
    const edit = corr.event_edits[i] ?? {};
    const player = edit.player ?? m[e.player] ?? e.player;
    const target = edit.target ?? (e.target ? m[e.target] ?? e.target : null);
    const type = (edit.type ?? e.type) as EventType;
    const outcome = edit.outcome ?? e.outcome;
    if (!rosterIds.has(player)) return;
    if (target === player && PASS_LIKE.includes(type)) return;
    const s = stats[player];
    if (type === "pass") {
      s.passes++;
      if (outcome === "completed") s.passes_completed++;
    } else if (type === "loss") {
      s.passes++;
      s.losses++;
    } else if (type === "tackle") s.tackles++;
    else if (type === "goal") s.goals++;
    else if (type === "assist") s.assists++;
    else if (type === "key_pass") s.key_passes++;
  });

  // distance: remap track positions -> player, dedupe per frame, sum steps
  const last: Record<string, [number, number]> = {};
  for (const f of data.frames) {
    const seen = new Set<string>();
    for (const p of f.positions) {
      const pid = m[p.player];
      if (!pid || !rosterIds.has(pid) || seen.has(pid)) continue;
      seen.add(pid);
      const prev = last[pid];
      if (prev) stats[pid].distance_m += dist(prev[0], prev[1], p.x, p.y);
      last[pid] = [p.x, p.y];
    }
  }
  return stats;
}

// Count how many frames each track appears in (helps spot real vs noise tracks).
export function trackFrameCounts(data: MatchData): Record<string, number> {
  const c: Record<string, number> = {};
  for (const f of data.frames)
    for (const p of f.positions) c[p.player] = (c[p.player] ?? 0) + 1;
  return c;
}
