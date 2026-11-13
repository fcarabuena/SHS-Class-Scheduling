import type { Metadata } from "next";

import { AuthProvider } from "@/lib/auth";

import "@fontsource/ibm-plex-sans/300.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/600.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "SHS Class Scheduling",
  description: "Class scheduling and teacher loading for Senior High Schools",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
