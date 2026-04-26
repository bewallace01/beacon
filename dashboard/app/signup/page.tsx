"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { setSession, signup } from "../api";

type Result = {
  apiKey: string;
  apiKeyPrefix: string;
};

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Result | null>(null);
  const [copied, setCopied] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await signup(email, password, workspaceName);
      setSession(res.session_token, res.user, res.workspace);
      setDone({ apiKey: res.api_key.plaintext, apiKeyPrefix: res.api_key.prefix });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <main className="p-8 max-w-md mx-auto">
        <h1 className="text-2xl font-semibold mb-2">You&apos;re in.</h1>
        <p className="text-gray-700 mb-6">
          Save the API key below. It&apos;s shown once.
        </p>
        <div className="border border-amber-300 bg-amber-50 rounded p-4">
          <div className="text-xs uppercase font-semibold text-amber-800 mb-1">
            api key
          </div>
          <code className="block font-mono text-sm break-all text-amber-900 mb-3">
            {done.apiKey}
          </code>
          <button
            type="button"
            onClick={async () => {
              await navigator.clipboard.writeText(done.apiKey);
              setCopied(true);
            }}
            className="text-sm text-blue-600 underline"
          >
            {copied ? "copied" : "copy to clipboard"}
          </button>
        </div>
        <pre className="mt-6 text-xs bg-gray-50 border border-gray-200 rounded p-3 overflow-x-auto">
{`pip install -e ./sdk openai
export BEACON_API_KEY="${done.apiKey}"
python examples/demo_bot.py`}
        </pre>
        <button
          type="button"
          onClick={() => router.push("/")}
          className="mt-6 w-full bg-blue-600 text-white rounded py-2 text-sm font-medium"
        >
          continue to dashboard
        </button>
      </main>
    );
  }

  return (
    <main className="p-8 max-w-sm mx-auto">
      <h1 className="text-2xl font-semibold mb-6">Sign up</h1>
      <form onSubmit={onSubmit} className="space-y-4">
        <div>
          <label className="block text-sm text-gray-700 mb-1">Workspace name</label>
          <input
            value={workspaceName}
            onChange={(e) => setWorkspaceName(e.target.value)}
            required
            placeholder="acme"
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm text-gray-700 mb-1">Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm text-gray-700 mb-1">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
          />
          <p className="text-xs text-gray-500 mt-1">at least 8 characters</p>
        </div>
        {error && (
          <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2">
            {error}
          </div>
        )}
        <button
          type="submit"
          disabled={busy}
          className="w-full bg-blue-600 text-white rounded py-2 text-sm font-medium disabled:opacity-50"
        >
          {busy ? "creating..." : "create account"}
        </button>
      </form>
      <p className="text-sm text-gray-600 mt-4">
        already have an account?{" "}
        <Link href="/login" className="text-blue-600 underline">
          log in
        </Link>
      </p>
    </main>
  );
}
