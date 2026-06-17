// TypeScript mirror of analyzer/model.py — the canonical unified JSON.
// Keep in sync with the Python data model (schemas/ will formalize this later).

export type TeamId = "home" | "away";

export type EventType =
  | "pass"
  | "key_pass"
  | "assist"
  | "loss"
  | "tackle"
  | "goal";

export interface Pitch {
  length_m: number;
  width_m: number;
  goal_width_m: number;
}

export interface MatchMeta {
  id: string;
  date: string;
  home_team: string;
  away_team: string;
  fps: number;
  duration_s: number;
  pitch: Pitch;
}

export interface Player {
  id: string;
  team: TeamId;
  label: string;
  color: string;
  number: number | null;
}

export interface Position {
  player: string;
  x: number;
  y: number;
}

export interface Frame {
  t: number;
  ball: [number, number] | null;
  positions: Position[];
}

export interface MatchEvent {
  t: number;
  type: EventType;
  player: string;
  target: string | null;
  outcome: string | null;
  confidence: number;
  confirmed: boolean;
}

export interface PlayerStats {
  player: string;
  passes: number;
  passes_completed: number;
  pass_pct: number;
  key_passes: number;
  losses: number;
  tackles: number;
  goals: number;
  assists: number;
  distance_m: number;
  top_speed_kmh: number;
  possession_s: number;
  possession_pct: number;
}

export interface MatchData {
  match: MatchMeta;
  players: Player[];
  frames: Frame[];
  events: MatchEvent[];
  stats: Record<string, PlayerStats>;
}
