export const API_URL =
  process.env.NEXT_PUBLIC_BEACON_API_URL || "http://localhost:8000";

// Optional fallback bearer token baked at build time. Local docker compose
// sets this to "demo-key" so the spine demo works without logging in. In
// production it's empty: visitors must log in.
export const FALLBACK_API_KEY = process.env.NEXT_PUBLIC_BEACON_API_KEY || "";

const SESSION_KEY = "beacon.session_token";
const USER_KEY = "beacon.user";
const WORKSPACE_KEY = "beacon.workspace";

export class UnauthorizedError extends Error {
  constructor(message = "unauthorized") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

export type SessionUser = {
  id: string;
  email: string;
  workspace_id: string;
};

export type SessionWorkspace = {
  id: string;
  name: string;
};

export function getSessionToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(SESSION_KEY);
}

export function setSession(
  token: string,
  user: SessionUser,
  workspace: SessionWorkspace,
): void {
  localStorage.setItem(SESSION_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  localStorage.setItem(WORKSPACE_KEY, JSON.stringify(workspace));
}

export function clearSession(): void {
  localStorage.removeItem(SESSION_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(WORKSPACE_KEY);
}

export function getStoredUser(): SessionUser | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  return raw ? (JSON.parse(raw) as SessionUser) : null;
}

export function getStoredWorkspace(): SessionWorkspace | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(WORKSPACE_KEY);
  return raw ? (JSON.parse(raw) as SessionWorkspace) : null;
}

function authHeaders(): Record<string, string> {
  const token = getSessionToken() || FALLBACK_API_KEY;
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

export type Run = {
  id: string;
  agent_name: string;
  started_at: string;
  ended_at: string | null;
};

export type Event = {
  id: number;
  run_id: string;
  agent_name: string;
  kind: string;
  payload: Record<string, unknown>;
  timestamp: string;
};

export type Denial = {
  policy?: string;
  reason?: string;
  cap_usd?: number;
  cost_so_far_usd?: number;
  action?: string;
};

export type RunSummary = Run & {
  model?: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  event_count: number;
  denied: boolean;
  denial?: Denial;
};

export async function fetchRuns(): Promise<Run[]> {
  const r = await fetch(`${API_URL}/runs`, {
    cache: "no-store",
    headers: authHeaders(),
  });
  if (r.status === 401) throw new UnauthorizedError();
  if (!r.ok) throw new Error(`/runs returned ${r.status}`);
  const body = (await r.json()) as { runs: Run[] };
  return body.runs;
}

export async function fetchRunEvents(
  runId: string,
): Promise<{ run: Run; events: Event[] }> {
  const r = await fetch(`${API_URL}/runs/${runId}/events`, {
    cache: "no-store",
    headers: authHeaders(),
  });
  if (r.status === 401) throw new UnauthorizedError();
  if (!r.ok) throw new Error(`/runs/${runId}/events returned ${r.status}`);
  return (await r.json()) as { run: Run; events: Event[] };
}

export function summarize(run: Run, events: Event[]): RunSummary {
  let model: string | undefined;
  let input_tokens = 0;
  let output_tokens = 0;
  let latency_ms = 0;
  let denial: Denial | undefined;

  for (const e of events) {
    if (e.kind === "llm_call_completed") {
      const p = e.payload as {
        model?: string;
        input_tokens?: number;
        output_tokens?: number;
        duration_s?: number;
      };
      if (p.model) model = p.model;
      input_tokens += p.input_tokens ?? 0;
      output_tokens += p.output_tokens ?? 0;
      if (typeof p.duration_s === "number") latency_ms += p.duration_s * 1000;
    } else if (e.kind === "policy_denied" && !denial) {
      const p = e.payload as Denial;
      denial = {
        policy: p.policy,
        reason: p.reason,
        cap_usd: p.cap_usd,
        cost_so_far_usd: p.cost_so_far_usd,
        action: p.action,
      };
    }
  }

  return {
    ...run,
    model,
    input_tokens,
    output_tokens,
    latency_ms: Math.round(latency_ms),
    event_count: events.length,
    denied: denial !== undefined,
    denial,
  };
}

export async function fetchRunSummaries(): Promise<RunSummary[]> {
  const runs = await fetchRuns();
  return Promise.all(
    runs.map(async (r) => {
      try {
        const { events } = await fetchRunEvents(r.id);
        return summarize(r, events);
      } catch {
        return summarize(r, []);
      }
    }),
  );
}

export async function signup(
  email: string,
  password: string,
  workspaceName: string,
): Promise<{
  user: SessionUser;
  workspace: SessionWorkspace;
  api_key: { plaintext: string; prefix: string };
  session_token: string;
}> {
  const r = await fetch(`${API_URL}/auth/signup`, {
    method: "POST",
    cache: "no-store",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      email,
      password,
      workspace_name: workspaceName,
    }),
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail || `signup failed (${r.status})`);
  }
  return await r.json();
}

export async function login(
  email: string,
  password: string,
): Promise<{
  user: SessionUser;
  workspace: SessionWorkspace;
  session_token: string;
}> {
  const r = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    cache: "no-store",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail || `login failed (${r.status})`);
  }
  return await r.json();
}

export async function logout(): Promise<void> {
  const token = getSessionToken();
  if (!token) return;
  try {
    await fetch(`${API_URL}/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
  } finally {
    clearSession();
  }
}
