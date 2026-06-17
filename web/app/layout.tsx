import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PitchVision",
  description: "Automatic per-player football analytics from match video.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
