"use client";

import { useEffect, useState } from "react";
import type { MatchData } from "@/lib/types";
import MatchViewer from "@/components/MatchViewer";

export default function Home() {
  const [data, setData] = useState<MatchData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // ?data=clip loads the real CV-pipeline output; default is the Stage-0 sim.
    const which =
      typeof window !== "undefined" &&
      new URLSearchParams(window.location.search).get("data") === "clip"
        ? "/clip-match.json"
        : "/sample-match.json";
    fetch(which)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

  if (error)
    return (
      <div className="app">
        <p>Failed to load match data: {error}</p>
        <p className="muted">
          Run <code>npm run gen:sample</code> (or{" "}
          <code>python3 analyzer/cli.py</code>) to generate it.
        </p>
      </div>
    );

  if (!data)
    return (
      <div className="app">
        <p className="muted">Loading match…</p>
      </div>
    );

  return <MatchViewer data={data} />;
}
