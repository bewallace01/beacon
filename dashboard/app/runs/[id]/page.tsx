"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Event, fetchRunEvents, Run, UnauthorizedError } from "../../api";
import Header from "../../Header";

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function RunDetail({ params }: { params: { id: string } }) {
  const runId = params.id;
  const router = useRouter();
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const data = await fetchRunEvents(runId);
        if (!alive) return;
        setRun(data.run);
        setEvents(data.events);
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
  }, [runId, router]);

  return (
    <main className="p-8 max-w-6xl mx-auto">
      <Header />

      <div className="mb-4">
        <Link href="/" className="text-blue-600 underline text-sm">
          &larr; runs
        </Link>
      </div>

      <h1 className="text-xl font-semibold mb-1 font-mono">{runId}</h1>
      {run && (
        <div className="text-sm text-gray-600 mb-6">
          agent <span className="font-mono">{run.agent_name}</span>
          {" · started "}
          {fmtTime(run.started_at)}
          {run.ended_at ? ` · ended ${fmtTime(run.ended_at)}` : " · running"}
        </div>
      )}

      {error && (
        <div className="mb-4 p-3 border border-red-300 bg-red-50 text-red-700 text-sm rounded">
          {error}
        </div>
      )}

      {(() => {
        const denial = events.find((e) => e.kind === "policy_denied");
        if (!denial) return null;
        const p = denial.payload as {
          policy?: string;
          reason?: string;
          cap_usd?: number;
          cost_so_far_usd?: number;
          action?: string;
        };
        return (
          <div className="mb-6 p-4 border border-red-300 bg-red-50 rounded">
            <div className="flex items-baseline gap-3">
              <span className="px-2 py-0.5 rounded bg-red-200 text-red-900 text-xs font-semibold uppercase">
                denied
              </span>
              <span className="text-red-800 font-medium">
                {p.reason ?? "policy denied"}
              </span>
            </div>
            <div className="mt-2 text-sm text-red-800 space-y-0.5">
              {p.policy && (
                <div>
                  policy: <span className="font-mono">{p.policy}</span>
                </div>
              )}
              {p.action && (
                <div>
                  action: <span className="font-mono">{p.action}</span>
                </div>
              )}
              {typeof p.cost_so_far_usd === "number" &&
                typeof p.cap_usd === "number" && (
                  <div>
                    cost so far:{" "}
                    <span className="font-mono">
                      ${p.cost_so_far_usd.toFixed(6)}
                    </span>{" "}
                    / cap{" "}
                    <span className="font-mono">${p.cap_usd.toFixed(6)}</span>
                  </div>
                )}
            </div>
          </div>
        );
      })()}

      {loading ? (
        <div className="text-gray-500">loading...</div>
      ) : events.length === 0 ? (
        <div className="text-gray-500">no events</div>
      ) : (
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-gray-600">
              <th className="py-2 pr-4 font-medium w-40">Time</th>
              <th className="py-2 pr-4 font-medium w-48">Kind</th>
              <th className="py-2 pr-4 font-medium">Payload</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e) => {
              const isDenial = e.kind === "policy_denied";
              return (
                <tr
                  key={e.id}
                  className={
                    "border-b align-top " +
                    (isDenial
                      ? "border-red-200 bg-red-50"
                      : "border-gray-100")
                  }
                >
                  <td className="py-2 pr-4 font-mono text-xs">
                    {fmtTime(e.timestamp)}
                  </td>
                  <td className="py-2 pr-4 font-mono text-xs">
                    {isDenial ? (
                      <span className="text-red-800 font-semibold">
                        {e.kind}
                      </span>
                    ) : (
                      e.kind
                    )}
                  </td>
                  <td className="py-2 pr-4">
                    <pre
                      className={
                        "font-mono text-xs whitespace-pre-wrap break-words " +
                        (isDenial ? "text-red-900" : "text-gray-800")
                      }
                    >
                      {JSON.stringify(e.payload, null, 2)}
                    </pre>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </main>
  );
}
