"use client";

import type { MatchData, EventType } from "@/lib/types";

const EVENT_COLORS: Record<EventType, string> = {
  goal: "#fde047",
  assist: "#a855f7",
  key_pass: "#38bdf8",
  pass: "#22c55e",
  tackle: "#f97316",
  loss: "#ef4444",
};

// Which events earn a marker on the timeline (passes are too many to show).
const SHOWN: EventType[] = ["goal", "assist", "tackle", "loss"];

export default function Timeline({
  data,
  time,
  onSeek,
}: {
  data: MatchData;
  time: number;
  onSeek: (t: number) => void;
}) {
  const dur = data.match.duration_s;

  function handleClick(e: React.MouseEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const frac = (e.clientX - rect.left) / rect.width;
    onSeek(Math.max(0, Math.min(dur, frac * dur)));
  }

  return (
    <div>
      <div className="timeline" onClick={handleClick}>
        {data.events
          .filter((ev) => SHOWN.includes(ev.type))
          .map((ev, i) => (
            <div
              key={i}
              className="marker"
              title={`${ev.type} @ ${ev.t.toFixed(1)}s (${ev.player})`}
              style={{
                left: `${(ev.t / dur) * 100}%`,
                background: EVENT_COLORS[ev.type],
              }}
            />
          ))}
        <div className="playhead" style={{ left: `${(time / dur) * 100}%` }} />
      </div>
      <div className="legend">
        {SHOWN.map((t) => (
          <span key={t}>
            <span className="dot" style={{ background: EVENT_COLORS[t] }} />
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}
