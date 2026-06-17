"use client";

import { useEffect, useRef, useState } from "react";
import type { MatchData } from "@/lib/types";
import RadarView from "./RadarView";
import Timeline from "./Timeline";
import StatsTable from "./StatsTable";

const SPEEDS = [0.5, 1, 2, 4];

export default function MatchViewer({ data }: { data: MatchData }) {
  const dur = data.match.duration_s;
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [tab, setTab] = useState<"all" | "home" | "away">("all");
  const raf = useRef<number | null>(null);
  const last = useRef<number>(0);

  useEffect(() => {
    if (!playing) return;
    last.current = performance.now();
    const tick = (now: number) => {
      const dt = (now - last.current) / 1000;
      last.current = now;
      setTime((t) => {
        const next = t + dt * speed;
        return next >= dur ? 0 : next;
      });
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, [playing, speed, dur]);

  const score = data.events.filter((e) => e.type === "goal");
  const homeIds = new Set(data.players.filter((p) => p.team === "home").map((p) => p.id));
  const homeGoals = score.filter((g) => homeIds.has(g.player)).length;
  const awayGoals = score.length - homeGoals;

  const filtered: MatchData = {
    ...data,
    players: data.players.filter((p) => tab === "all" || p.team === tab),
  };

  return (
    <div className="app">
      <div className="header">
        <div>
          <h1>⚽ PitchVision</h1>
          <div className="scoreline">
            <b>{data.match.home_team}</b> {homeGoals} – {awayGoals}{" "}
            <b>{data.match.away_team}</b> · {data.match.date}
          </div>
        </div>
        <span className="badge">Stage 0 · simulation mode</span>
      </div>

      <div className="panel">
        <h2>Radar (top-down)</h2>
        <RadarView data={data} time={time} />
        <div className="controls">
          <button onClick={() => setPlaying((p) => !p)}>
            {playing ? "❚❚ Pause" : "▶ Play"}
          </button>
          <input
            type="range"
            min={0}
            max={dur}
            step={0.05}
            value={time}
            onChange={(e) => {
              setPlaying(false);
              setTime(parseFloat(e.target.value));
            }}
          />
          <span className="time">
            {time.toFixed(1)}s / {dur.toFixed(0)}s
          </span>
          <button
            className="secondary"
            onClick={() => setSpeed((s) => SPEEDS[(SPEEDS.indexOf(s) + 1) % SPEEDS.length])}
          >
            {speed}×
          </button>
        </div>
        <p className="muted">
          Real match video with overlay will sit above this radar in Stage 1+.
          For now the radar IS the picture, driven by synthetic tracks.
        </p>
      </div>

      <div className="panel">
        <h2>Event timeline</h2>
        <Timeline data={data} time={time} onSeek={(t) => { setPlaying(false); setTime(t); }} />
      </div>

      <div className="panel">
        <h2>Per-player statistics</h2>
        <div className="tabs">
          {(["all", "home", "away"] as const).map((t) => (
            <button
              key={t}
              className={tab === t ? "active" : ""}
              onClick={() => setTab(t)}
            >
              {t === "all" ? "All" : t === "home" ? data.match.home_team : data.match.away_team}
            </button>
          ))}
        </div>
        <StatsTable data={filtered} />
      </div>
    </div>
  );
}
