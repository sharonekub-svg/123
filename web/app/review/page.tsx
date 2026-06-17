"use client";

import { useEffect, useState } from "react";
import type { MatchData } from "@/lib/types";
import ReviewScreen from "@/components/ReviewScreen";

export default function ReviewPage() {
  const [data, setData] = useState<MatchData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const which =
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

  if (error) return <div className="app"><p>Failed to load: {error}</p></div>;
  if (!data) return <div className="app"><p className="muted">Loading…</p></div>;
  return <ReviewScreen data={data} />;
}
