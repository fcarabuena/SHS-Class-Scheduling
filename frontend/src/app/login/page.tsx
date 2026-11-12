"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AuthCard } from "@/components/AuthCard";
import { Alert, Button, TextField } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(email, password);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in.");
      setBusy(false);
    }
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
      <p className="mt-6 text-center text-sm text-stone-600">
        Setting up a new school?{" "}
        <Link href="/register" className="font-medium text-emerald-800 underline">
          Register your school
        </Link>
      </p>
    </AuthCard>
  );
}
