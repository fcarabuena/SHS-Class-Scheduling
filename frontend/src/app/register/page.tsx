"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AuthCard } from "@/components/AuthCard";
import { Alert, Button, TextField } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function RegisterPage() {
  const { register } = useAuth();
  const router = useRouter();
  const [form, setForm] = useState({ school_name: "", full_name: "", email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const set = (key: keyof typeof form) => (value: string) => setForm((current) => ({ ...current, [key]: value }));

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await register(form);
      router.replace("/onboarding");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not register.");
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Register your school" subtitle="This creates your school's workspace and its first administrator account.">
      <form onSubmit={submit} className="space-y-4">
        <TextField label="School name" required value={form.school_name} onChange={set("school_name")} />
        <TextField label="Your full name" required autoComplete="name" value={form.full_name} onChange={set("full_name")} />
        <TextField label="Email" type="email" required autoComplete="username" value={form.email} onChange={set("email")} />
        <TextField
          label="Password"
          type="password"
          required
          minLength={10}
          autoComplete="new-password"
          hint="At least 10 characters."
          value={form.password}
          onChange={set("password")}
        />
        {error && <Alert>{error}</Alert>}
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? "Creating…" : "Create school workspace"}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-stone-600">
        Already registered?{" "}
        <Link href="/login" className="font-medium text-primary-800 underline">
          Sign in
        </Link>
      </p>
    </AuthCard>
  );
}
