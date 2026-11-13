"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Alert, Badge, Button, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { NOTIFICATIONS_EVENT } from "@/lib/types";

type Item = { id: number; title: string; body: string; link: string | null; count: number; created_at: string; read: boolean };

export default function NotificationsPage() {
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<{ items: Item[] }>("/api/notifications")
      .then((result) => setItems(result.items))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load notifications."));
  }, []);

  async function markAllRead() {
    await api("/api/notifications/read", { method: "POST", body: {} });
    setItems((current) => (current ?? []).map((item) => ({ ...item, read: true })));
    window.dispatchEvent(new Event(NOTIFICATIONS_EVENT)); // refresh the count in the menu
  }

  if (error) return <Alert>{error}</Alert>;
  if (!items) return <Spinner />;
  const unread = items.filter((item) => !item.read).length;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[1.75rem] font-normal leading-tight text-stone-900">Notifications</h1>
          <p className="mt-1 text-sm text-stone-600">Changes to your classes and finished auto-schedule runs.</p>
        </div>
        {unread > 0 && (
          <Button variant="secondary" onClick={markAllRead}>
            Mark all as read
          </Button>
        )}
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-stone-600">Nothing yet.</p>
      ) : (
        <ul className="divide-y divide-stone-100 border border-stone-200 bg-white">
          {items.map((item) => (
            <li key={item.id} className={`px-4 py-3 text-sm ${item.read ? "" : "border-l-4 border-l-primary-600"}`}>
              <div className="flex flex-wrap items-baseline gap-2">
                <span className={item.read ? "text-stone-800" : "font-semibold text-stone-900"}>{item.title}</span>
                {!item.read && <Badge tone="sky">New</Badge>}
                {item.count > 1 && <span className="text-xs text-stone-500">{item.count} changes</span>}
                <span className="ml-auto text-xs tabular-nums text-stone-500">{new Date(item.created_at).toLocaleString()}</span>
              </div>
              {item.body && <p className="mt-0.5 text-stone-700">{item.count > 1 ? `Latest: ${item.body}` : item.body}</p>}
              {item.link && (
                <Link href={item.link} className="mt-1 inline-block text-primary-700 underline">
                  Open
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
