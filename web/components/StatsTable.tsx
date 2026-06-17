"use client";

import { useState } from "react";
import type { MatchData, PlayerStats } from "@/lib/types";

type Col = {
  key: keyof PlayerStats | "label" | "pass";
  label: string;
  fmt?: (s: PlayerStats, label: string) => string;
  sort: (s: PlayerStats) => number;
};

const COLS: Col[] = [
  { key: "goals", label: "G", fmt: (s) => `${s.goals}`, sort: (s) => s.goals },
  { key: "assists", label: "A", fmt: (s) => `${s.assists}`, sort: (s) => s.assists },
  {
    key: "pass",
    label: "Passes",
    fmt: (s) => `${s.passes_completed}/${s.passes} (${s.pass_pct}%)`,
    sort: (s) => s.passes_completed,
  },
  { key: "key_passes", label: "KP", fmt: (s) => `${s.key_passes}`, sort: (s) => s.key_passes },
  { key: "tackles", label: "Tck", fmt: (s) => `${s.tackles}`, sort: (s) => s.tackles },
  { key: "losses", label: "Loss", fmt: (s) => `${s.losses}`, sort: (s) => s.losses },
  {
    key: "possession_pct",
    label: "Poss%",
    fmt: (s) => `${s.possession_pct}`,
    sort: (s) => s.possession_pct,
  },
  {
    key: "distance_m",
    label: "Dist",
    fmt: (s) => `${(s.distance_m / 1000).toFixed(2)} km`,
    sort: (s) => s.distance_m,
  },
  {
    key: "top_speed_kmh",
    label: "Top km/h",
    fmt: (s) => `${s.top_speed_kmh.toFixed(1)}`,
    sort: (s) => s.top_speed_kmh,
  },
];

export default function StatsTable({ data }: { data: MatchData }) {
  const [sortKey, setSortKey] = useState<string>("distance_m");

  const rows = data.players
    .map((p) => ({ p, s: data.stats[p.id] }))
    .filter((r) => r.s)
    .sort((a, b) => {
      const col = COLS.find((c) => c.key === sortKey);
      if (!col) return 0;
      return col.sort(b.s) - col.sort(a.s);
    });

  return (
    <table>
      <thead>
        <tr>
          <th>Player</th>
          {COLS.map((c) => (
            <th key={c.key as string} onClick={() => setSortKey(c.key as string)}>
              {c.label}
              {sortKey === c.key ? " ▾" : ""}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map(({ p, s }) => (
          <tr key={p.id} className={p.team}>
            <td>{p.label}</td>
            {COLS.map((c) => (
              <td key={c.key as string}>{c.fmt ? c.fmt(s, p.label) : ""}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
