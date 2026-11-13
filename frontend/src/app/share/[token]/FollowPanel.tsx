"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui";
import { api, API_URL, ApiError } from "@/lib/api";

type State = "checking" | "off" | "on" | "blocked" | "unsupported";

function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const base64 = (base64url + "=".repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
}

const supported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
const remembered = (token: string) => {
  try {
    return window.localStorage.getItem(`follow:${token}`) === "1";
  } catch {
    return false;
  }
};
const remember = (token: string, on: boolean) => {
  try {
    if (on) window.localStorage.setItem(`follow:${token}`, "1");
    else window.localStorage.removeItem(`follow:${token}`);
  } catch {
    // private mode: the button just won't remember
  }
};

/** Follow (notifications) and add-to-calendar for a shared section timetable. No account, no name. */
export function FollowPanel({ token, title, pushKey }: { token: string; title: string; pushKey: string | null }) {
  const [state, setState] = useState<State>("checking");
  const [error, setError] = useState("");
  const path = `/api/public/timetable/${encodeURIComponent(token)}`;
  const calendarUrl = `${API_URL}${path}/calendar.ics`;

  useEffect(() => {
    if (!pushKey) return;
    let cancelled = false;
    (async () => {
      if (!supported()) return "unsupported" as const;
      if (Notification.permission === "denied") return "blocked" as const;
      const registration = await navigator.serviceWorker.getRegistration("/");
      const subscription = await registration?.pushManager.getSubscription();
      return subscription && remembered(token) ? ("on" as const) : ("off" as const);
    })()
      .then((next) => !cancelled && setState(next))
      .catch(() => !cancelled && setState("off"));
    return () => {
      cancelled = true;
    };
  }, [pushKey, token]);

  async function follow() {
    setError("");
    try {
      if ((await Notification.requestPermission()) !== "granted") {
        setState("blocked");
        return;
      }
      const registration = await navigator.serviceWorker.register("/sw.js");
      await navigator.serviceWorker.ready;
      const subscription =
        (await registration.pushManager.getSubscription()) ??
        (await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(pushKey!) }));
      await api(`${path}/follow`, { method: "POST", body: subscription.toJSON() });
      remember(token, true);
      setState("on");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Notifications could not be turned on in this browser.");
    }
  }

  async function unfollow() {
    setError("");
    try {
      const subscription = await (await navigator.serviceWorker.getRegistration("/"))?.pushManager.getSubscription();
      if (subscription) await api(`${path}/unfollow`, { method: "POST", body: { endpoint: subscription.endpoint } });
      remember(token, false);
      setState("off");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not stop following.");
    }
  }

  return (
    <section aria-label="Follow this timetable" className="flex flex-wrap items-center gap-x-4 gap-y-2 border border-stone-200 bg-white px-4 py-3 text-sm print:hidden">
      {pushKey && state === "off" && <Button onClick={follow}>Follow: notify me of changes</Button>}
      {pushKey && state === "on" && (
        <>
          <span className="text-stone-800">You will be notified when the timetable of {title} changes.</span>
          <Button variant="secondary" small onClick={unfollow}>
            Stop following
          </Button>
        </>
      )}
      {pushKey && state === "blocked" && (
        <span className="text-stone-700">Notifications are blocked for this site. Allow them in the browser settings to follow.</span>
      )}
      {pushKey && state === "unsupported" && (
        <span className="text-stone-700">
          This browser cannot show notifications. On an iPhone, tap Share → Add to Home Screen, then open the timetable from there.
        </span>
      )}
      <a className="text-primary-700 underline" href={calendarUrl.replace(/^https?:/, "webcal:")}>
        Add to phone calendar
      </a>
      <a className="text-primary-700 underline" href={calendarUrl} download>
        Download calendar file
      </a>
      {error && (
        <p role="alert" className="w-full text-red-700">
          {error}
        </p>
      )}
    </section>
  );
}
