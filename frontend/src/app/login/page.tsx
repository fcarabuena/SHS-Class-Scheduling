"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthCard } from "@/components/AuthCard";
import { Alert, Button, TextField } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Demo = { enabled: boolean; password?: string; accounts?: { role: string; email: string }[]; student_link?: string };

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState<Demo | null>(null);

  useEffect(() => {
    api<Demo>("/api/demo")
      .then(setDemo)
      .catch(() => undefined);
  }, []);

  async function signIn(address: string, secret: string) {
    setBusy(true);
    setError("");
    try {
      await login(address, secret);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in.");
      setBusy(false);
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    await signIn(email, password);
  }

  return (
    <AuthCard title="Sign in" subtitle="Use the account your school administrator gave you.">
      <form onSubmit={submit} className="space-y-4">
        <TextField label="Email" type="email" autoComplete="username" required value={email} onChange={setEmail} />
        <TextField
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={setPassword}
        />
        {error && <Alert>{error}</Alert>}
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
      {demo?.enabled && (
        <section aria-label="Try the demo" className="mt-6 border border-primary-200 bg-primary-50 p-4 text-sm">
          <h2 className="font-semibold text-stone-900">Try the demo</h2>
          <p className="mt-1 text-stone-700">
            A fictional school with a ready timetable. The scheduler can change anything; the teacher account is
            view-only. It resets every day.
          </p>
          <div className="mt-3 space-y-2">
            {demo.accounts?.map((account) => (
              <Button
                key={account.email}
                variant="secondary"
                className="w-full justify-between"
                disabled={busy}
                onClick={() => signIn(account.email, demo.password!)}
              >
                <span>Sign in as {account.role}</span>
                <span className="text-xs text-stone-500">{account.email}</span>
              </Button>
            ))}
            {demo.student_link && (
              <Link href={demo.student_link} className="block border border-stone-500 bg-white px-4 py-2 text-center font-normal text-stone-900 hover:bg-stone-100">
                See a student&apos;s view (no account needed)
              </Link>
            )}
          </div>
          <p className="mt-2 text-xs text-stone-600">Demo password: {demo.password}</p>
        </section>
      )}
      <p className="mt-6 text-center text-sm text-stone-600">
        Setting up a new school?{" "}
        <Link href="/register" className="font-medium text-primary-800 underline">
          Register your school
        </Link>
      </p>
    </AuthCard>
  );
}
