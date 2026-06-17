"use client";

import { useEffect, useMemo, useState } from "react";
import type { EventType, MatchData } from "@/lib/types";
import {
  Corrections,
  RosterPlayer,
  emptyCorrections,
  previewStats,
  trackFrameCounts,
} from "@/lib/corrections";

const EVENT_TYPES: EventType[] = [
  "pass", "key_pass", "assist", "loss", "tackle", "goal",
];

export default function ReviewScreen({ data }: { data: MatchData }) {
  const storageKey = `pv-corrections:${data.match.id}`;
  const [corr, setCorr] = useState<Corrections>(emptyCorrections());
  const [seq, setSeq] = useState(1);

  // load saved corrections
  useEffect(() => {
    const raw = typeof window !== "undefined" && localStorage.getItem(storageKey);
    if (raw) {
      try {
        const c = JSON.parse(raw) as Corrections;
        setCorr(c);
        setSeq(c.roster.length + 1);
      } catch {
        /* ignore */
      }
    }
  }, [storageKey]);

  const counts = useMemo(() => trackFrameCounts(data), [data]);
  const tracks = useMemo(
    () => [...data.players].sort((a, b) => (counts[b.id] ?? 0) - (counts[a.id] ?? 0)),
    [data, counts],
  );
  const preview = useMemo(() => previewStats(data, corr), [data, corr]);
  const rosterById = useMemo(
    () => Object.fromEntries(corr.roster.map((r) => [r.id, r])),
    [corr.roster],
  );

  function save() {
    localStorage.setItem(storageKey, JSON.stringify(corr));
    alert("Saved locally. Download to run the analyzer recompute offline.");
  }

  function download() {
    const blob = new Blob([JSON.stringify(corr, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "corrections.json";
    a.click();
  }

  function upload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    file.text().then((t) => {
      try {
        setCorr(JSON.parse(t) as Corrections);
      } catch {
        alert("Invalid corrections JSON");
      }
    });
  }

  function addPlayer(team: "home" | "away", name?: string, number?: number | null) {
    const id = `p${seq}`;
    setSeq((s) => s + 1);
    const r: RosterPlayer = { id, name: name ?? `Player ${seq}`, team, number: number ?? null };
    setCorr((c) => ({ ...c, roster: [...c.roster, r] }));
    return id;
  }

  function assign(trackId: string, playerId: string) {
    setCorr((c) => {
      const map = { ...c.track_to_player };
      if (playerId) map[trackId] = playerId;
      else delete map[trackId];
      return { ...c, track_to_player: map };
    });
  }

  function createAndAssign(track: { id: string; team: string }) {
    const pid = addPlayer(track.team as "home" | "away");
    assign(track.id, pid);
  }

  function editEventType(i: number, type: EventType) {
    setCorr((c) => ({ ...c, event_edits: { ...c.event_edits, [i]: { ...c.event_edits[i], type } } }));
  }

  function toggleDelete(i: number) {
    setCorr((c) => {
      const del = c.deleted_events.includes(i)
        ? c.deleted_events.filter((x) => x !== i)
        : [...c.deleted_events, i];
      return { ...c, deleted_events: del };
    });
  }

  const assignedCount = Object.keys(corr.track_to_player).length;

  return (
    <div className="app">
      <div className="header">
        <div>
          <h1>🧑‍🔧 HITL Review</h1>
          <div className="scoreline">
            {data.match.home_team} vs {data.match.away_team} · {tracks.length} tracks ·{" "}
            {assignedCount} assigned
          </div>
        </div>
        <div className="controls" style={{ marginTop: 0 }}>
          <a href="/" className="badge">← viewer</a>
          <button onClick={save}>Save</button>
          <button className="secondary" onClick={download}>Download</button>
          <label className="secondary" style={{ padding: "8px 12px", borderRadius: 8, cursor: "pointer", border: "1px solid var(--border)" }}>
            Load
            <input type="file" accept="application/json" onChange={upload} style={{ display: "none" }} />
          </label>
        </div>
      </div>

      <p className="muted">
        Map each detected track to a real player (fragmented tracks of one player
        all point to the same roster entry — that fixes Re-ID). Edit/▢ confirm or
        ✕ delete events. Stats below update live; possession &amp; speed are
        recomputed by <code>analyzer/hitl.py</code> from the downloaded file.
      </p>

      <div className="panel">
        <h2>Roster</h2>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
          <button className="secondary" onClick={() => addPlayer("home")}>+ Home player</button>
          <button className="secondary" onClick={() => addPlayer("away")}>+ Away player</button>
        </div>
        {corr.roster.length === 0 ? (
          <p className="muted">No players yet. Add players, or use “+player” next to a track.</p>
        ) : (
          <table>
            <thead>
              <tr><th>Name</th><th>#</th><th>Team</th><th>Tracks</th></tr>
            </thead>
            <tbody>
              {corr.roster.map((r) => {
                const nTracks = Object.values(corr.track_to_player).filter((v) => v === r.id).length;
                return (
                  <tr key={r.id} className={r.team}>
                    <td>
                      <input
                        value={r.name}
                        onChange={(e) =>
                          setCorr((c) => ({
                            ...c,
                            roster: c.roster.map((x) => x.id === r.id ? { ...x, name: e.target.value } : x),
                          }))
                        }
                        style={inputStyle}
                      />
                    </td>
                    <td>
                      <input
                        type="number" value={r.number ?? ""} style={{ ...inputStyle, width: 56 }}
                        onChange={(e) =>
                          setCorr((c) => ({
                            ...c,
                            roster: c.roster.map((x) => x.id === r.id ? { ...x, number: e.target.value ? +e.target.value : null } : x),
                          }))
                        }
                      />
                    </td>
                    <td>{r.team}</td>
                    <td>{nTracks}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <h2>Tracks → players</h2>
        <table>
          <thead>
            <tr><th>Track</th><th>Team</th><th>Frames</th><th>Assign to</th></tr>
          </thead>
          <tbody>
            {tracks.map((t) => (
              <tr key={t.id} className={t.team}>
                <td>
                  <span className="dot" style={{ background: t.color }} /> {t.label}
                </td>
                <td>{t.team}</td>
                <td>{counts[t.id] ?? 0}</td>
                <td>
                  <select
                    value={corr.track_to_player[t.id] ?? ""}
                    onChange={(e) => assign(t.id, e.target.value)}
                    style={inputStyle}
                  >
                    <option value="">— unassigned —</option>
                    {corr.roster.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name}{r.number != null ? ` #${r.number}` : ""} ({r.team})
                      </option>
                    ))}
                  </select>{" "}
                  <button className="secondary" style={{ padding: "4px 8px" }} onClick={() => createAndAssign(t)}>
                    +player
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2>Events ({data.events.length})</h2>
        {data.events.length === 0 ? (
          <p className="muted">No events detected for this match.</p>
        ) : (
          <table>
            <thead>
              <tr><th>t (s)</th><th>Type</th><th>Player</th><th>→ Target</th><th>conf</th><th></th></tr>
            </thead>
            <tbody>
              {data.events.map((e, i) => {
                const deleted = corr.deleted_events.includes(i);
                const mappedP = corr.track_to_player[e.player];
                const mappedT = e.target ? corr.track_to_player[e.target] : null;
                const type = corr.event_edits[i]?.type ?? e.type;
                return (
                  <tr key={i} style={deleted ? { opacity: 0.4, textDecoration: "line-through" } : undefined}>
                    <td>{e.t.toFixed(1)}</td>
                    <td>
                      <select value={type} onChange={(ev) => editEventType(i, ev.target.value as EventType)} style={inputStyle}>
                        {EVENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </td>
                    <td>{mappedP ? rosterById[mappedP]?.name : e.player}</td>
                    <td>{mappedT ? rosterById[mappedT]?.name : e.target ?? "—"}</td>
                    <td>{(e.confidence * 100).toFixed(0)}%</td>
                    <td>
                      <button className="secondary" style={{ padding: "4px 8px" }} onClick={() => toggleDelete(i)}>
                        {deleted ? "undo" : "✕"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <h2>Per-player stats (live preview)</h2>
        {corr.roster.length === 0 ? (
          <p className="muted">Assign tracks to see recomputed stats.</p>
        ) : (
          <table>
            <thead>
              <tr><th>Player</th><th>#</th><th>G</th><th>A</th><th>Passes</th><th>KP</th><th>Tck</th><th>Loss</th><th>Dist</th></tr>
            </thead>
            <tbody>
              {corr.roster.map((r) => {
                const s = preview[r.id];
                return (
                  <tr key={r.id} className={r.team}>
                    <td>{r.name}</td><td>{r.number ?? "—"}</td>
                    <td>{s.goals}</td><td>{s.assists}</td>
                    <td>{s.passes_completed}/{s.passes}</td>
                    <td>{s.key_passes}</td><td>{s.tackles}</td><td>{s.losses}</td>
                    <td>{(s.distance_m / 1000).toFixed(2)} km</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <p className="muted">
          Distance here is in the data&apos;s coordinate units (meters only when
          the pipeline ran with a homography calibration).
        </p>
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  background: "var(--panel-2)",
  color: "var(--text)",
  border: "1px solid var(--border)",
  borderRadius: 6,
  padding: "4px 6px",
};
