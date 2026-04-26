"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchRunSummaries, RunSummary, UnauthorizedError } from "./api";
import Header from "./Header";

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function Home() {
  const router = useRouter();
  const [rows, setRows] = useState<RunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const data = await fetchRunSummaries();
        if (!alive) return;
        setRows(data);
        setError(null);
      } catch (e) {
        if (!alive) return;
        if (e instanceof UnauthorizedError) {
          router.replace("/login");
          return;
        }
        setError(String(e));
      } finally {
        if (alive) setLoading(false);
      }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [router]);

  return (
    <main className="p-8 max-w-6xl mx-auto">
      <Header />

      {error && (
        <div className="mb-4 p-3 border border-red-300 bg-red-50 text-red-700 text-sm rounded">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-gray-500">loading...</div>
      ) : rows.length === 0 ? (
        <div className="text-gray-500">no runs yet</div>
      ) : (
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-gray-600">
              <th className="py-2 pr-4 font-medium">Started</th>
              <th className="py-2 pr-4 font-medium">Agent</th>
              <th className="py-2 pr-4 font-medium">Model</th>
              <th className="py-2 pr-4 font-medium">Events</th>
              <th className="py-2 pr-4 font-medium">Tokens (in / out)</th>
              <th className="py-2 pr-4 font-medium">Latency</th>
              <th className="py-2 pr-4 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="py-2 pr-4">
                  <Link
                    href={`/runs/${r.id}`}
                    className="text-blue-600 underline"
                  >
                    {fmtTime(r.started_at)}
                  </Link>
                </td>
                <td className="py-2 pr-4">{r.agent_name}</td>
                <td className="py-2 pr-4 font-mono text-xs">
                  {r.model ?? "-"}
                </td>
                <td className="py-2 pr-4">{r.event_count}</td>
                <td className="py-2 pr-4 font-mono text-xs">
                  {r.input_tokens} / {r.output_tokens}
                </td>
                <td className="py-2 pr-4">
                  {r.latency_ms > 0 ? `${r.latency_ms} ms` : "-"}
                </td>
                <td className="py-2 pr-4">
                  {r.denied ? (
                    <span
                      className="inline-block px-2 py-0.5 rounded bg-red-100 text-red-800 text-xs font-medium"
                      title={r.denial?.reason ?? "policy denied"}
                    >
                      denied
                    </span>
                  ) : r.ended_at ? (
                    <span className="text-gray-700">ended</span>
                  ) : (
                    <span className="text-amber-700">running</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
