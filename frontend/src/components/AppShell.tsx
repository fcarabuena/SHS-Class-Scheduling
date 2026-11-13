"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { labelOf, NOTIFICATIONS_EVENT, ROLES } from "@/lib/types";

import { Alert, Button, Spinner } from "./ui";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/notifications", label: "Notifications" },
  { href: "/timetable", label: "Timetable" },
  { href: "/teacher-loading", label: "Teacher loading" },
  { href: "/substitutes", label: "Find a substitute" },
  { href: "/strands", label: "Tracks & strands" },
  { href: "/subjects", label: "Subjects" },
  { href: "/sections", label: "Sections" },
  { href: "/teachers", label: "Teachers" },
  { href: "/rooms", label: "Rooms" },
  { href: "/users", label: "User accounts", adminOnly: true },
  { href: "/history", label: "Change history", adminOnly: true },
  { href: "/onboarding", label: "School setup", adminOnly: true },
  { href: "/platform", label: "All schools", platformOnly: true },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, school, loading, isAdmin, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const [unread, setUnread] = useState(0);

  const needsSetup = !!school && !school.onboarding_completed;

  useEffect(() => {
    if (loading) return;
    if (!user) router.replace("/login");
    else if (needsSetup && isAdmin) router.replace("/onboarding");
  }, [loading, user, needsSetup, isAdmin, router]);

  // shortcut: polls once a minute and on each page change; push (websocket) only if minutes matter.
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    const load = () =>
      api<{ unread: number }>("/api/notifications", { params: { limit: 1 } })
        .then((result) => !cancelled && setUnread(result.unread))
        .catch(() => undefined);
    load();
    const timer = window.setInterval(load, 60_000);
    window.addEventListener(NOTIFICATIONS_EVENT, load);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener(NOTIFICATIONS_EVENT, load);
    };
  }, [user, pathname]);

  if (loading || !user || !school || (needsSetup && isAdmin)) return <Spinner />;

  const links = NAV.filter((item) => (!item.adminOnly || isAdmin) && (!item.platformOnly || user.is_platform_admin));

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <header className="flex items-center justify-between border-t-4 border-red-600 bg-primary-700 px-4 py-3 text-white md:hidden print:hidden">
        <span className="truncate font-semibold">{school.name}</span>
        <button
          type="button"
          className="border border-white/40 px-3 py-1 text-sm"
          aria-expanded={menuOpen}
          aria-controls="main-nav"
          onClick={() => setMenuOpen((open) => !open)}
        >
          Menu
        </button>
      </header>

      <aside
        id="main-nav"
        className={`${menuOpen ? "block" : "hidden"} w-full shrink-0 bg-primary-700 text-primary-50 md:flex md:border-t-4 md:border-red-600 md:min-h-screen md:w-60 md:flex-col print:hidden`}
      >
        <div className="hidden px-5 pb-4 pt-6 md:block">
          <p className="text-xs uppercase tracking-wider text-accent">Class scheduling</p>
          <p className="mt-1 text-lg font-semibold leading-snug text-white">{school.name}</p>
        </div>
        <nav aria-label="Main" className="flex-1 pb-3 md:pb-0">
          <ul className="space-y-0.5">
            {links.map((item) => {
              const active = pathname === item.href;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    onClick={() => setMenuOpen(false)}
                    className={`block border-l-4 px-4 py-2 text-sm -outline-offset-2 ${
                      active
                        ? "border-accent bg-primary-950 font-semibold text-white"
                        : "border-transparent text-primary-100 hover:bg-primary-800 hover:text-white"
                    }`}
                  >
                    {item.label}
                    {item.href === "/notifications" && unread > 0 && (
                      <span className="ml-2 inline-block min-w-5 bg-red-600 px-1.5 text-center text-xs font-semibold text-white">
                        {unread}
                        <span className="sr-only"> unread</span>
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="border-t border-primary-500 px-5 py-4 text-sm">
          <p className="truncate font-medium text-white">{user.full_name}</p>
          <p className="text-primary-100">{labelOf(ROLES, user.role)}</p>
          <Button
            variant="ghost"
            small
            className="mt-2 !px-0 !text-primary-50 hover:!bg-transparent hover:underline"
            onClick={() => {
              logout();
              router.replace("/login");
            }}
          >
            Sign out
          </Button>
        </div>
      </aside>

      <main className="min-w-0 flex-1 px-4 py-6 md:px-8 md:py-8">
        {needsSetup && (
          <div className="mb-6">
            <Alert kind="warning">
              School setup is not finished yet. Ask your school administrator to complete it.
            </Alert>
          </div>
        )}
        {children}
      </main>
    </div>
  );
}
