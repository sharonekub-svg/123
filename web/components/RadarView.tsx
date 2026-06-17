"use client";

import { useEffect, useRef } from "react";
import type { Frame, MatchData } from "@/lib/types";

const PAD = 6; // meters of margin around the pitch

function frameAt(data: MatchData, t: number): Frame | null {
  const { frames } = data;
  if (frames.length === 0) return null;
  const idx = Math.max(
    0,
    Math.min(frames.length - 1, Math.round(t * data.match.fps)),
  );
  return frames[idx];
}

export default function RadarView({
  data,
  time,
}: {
  data: MatchData;
  time: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const colorById = useRef<Record<string, string>>({});

  if (Object.keys(colorById.current).length === 0) {
    for (const p of data.players) colorById.current[p.id] = p.color;
  }

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const { length_m: L, width_m: W } = data.match.pitch;
    const scale = 9; // px per meter
    const w = (L + PAD * 2) * scale;
    const h = (W + PAD * 2) * scale;

    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== h) canvas.height = h;

    const mx = (x: number) => (x + PAD) * scale;
    const my = (y: number) => (y + PAD) * scale;

    // pitch
    ctx.fillStyle = "#15803d";
    ctx.fillRect(0, 0, w, h);
    // mowing stripes
    ctx.fillStyle = "rgba(255,255,255,0.03)";
    for (let i = 0; i < L; i += 10) {
      if ((i / 10) % 2 === 0) ctx.fillRect(mx(i), my(0), 10 * scale, W * scale);
    }

    ctx.strokeStyle = "rgba(255,255,255,0.75)";
    ctx.lineWidth = 2;
    // outline
    ctx.strokeRect(mx(0), my(0), L * scale, W * scale);
    // halfway line
    ctx.beginPath();
    ctx.moveTo(mx(L / 2), my(0));
    ctx.lineTo(mx(L / 2), my(W));
    ctx.stroke();
    // center circle
    ctx.beginPath();
    ctx.arc(mx(L / 2), my(W / 2), 9.15 * scale, 0, Math.PI * 2);
    ctx.stroke();
    // penalty boxes
    const boxD = 16.5,
      boxW = 40.3;
    ctx.strokeRect(mx(0), my((W - boxW) / 2), boxD * scale, boxW * scale);
    ctx.strokeRect(mx(L - boxD), my((W - boxW) / 2), boxD * scale, boxW * scale);
    // goals
    const gw = data.match.pitch.goal_width_m;
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(mx(0), my((W - gw) / 2));
    ctx.lineTo(mx(0), my((W + gw) / 2));
    ctx.moveTo(mx(L), my((W - gw) / 2));
    ctx.lineTo(mx(L), my((W + gw) / 2));
    ctx.stroke();

    const frame = frameAt(data, time);
    if (!frame) return;

    // players
    ctx.font = `bold ${1.6 * scale}px ui-sans-serif, system-ui`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (const pos of frame.positions) {
      const col = colorById.current[pos.player] ?? "#999";
      ctx.beginPath();
      ctx.arc(mx(pos.x), my(pos.y), 1.9 * scale, 0, Math.PI * 2);
      ctx.fillStyle = col;
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = "rgba(0,0,0,0.5)";
      ctx.stroke();
      const num = pos.player.replace(/^[HA]/, "");
      ctx.fillStyle = "#fff";
      ctx.fillText(num, mx(pos.x), my(pos.y));
    }

    // ball
    if (frame.ball) {
      ctx.beginPath();
      ctx.arc(mx(frame.ball[0]), my(frame.ball[1]), 1.3 * scale, 0, Math.PI * 2);
      ctx.fillStyle = "#fde047";
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = "#1c1917";
      ctx.stroke();
    }
  }, [data, time]);

  return (
    <div className="radar-wrap">
      <canvas ref={ref} className="radar" />
    </div>
  );
}
