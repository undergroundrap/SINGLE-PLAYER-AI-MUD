import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Infinite AI MUD",
  description: "A procedurally generated single-player MMORPG powered by LM Studio.",
  icons: {
    icon: "/assets/ui/logo.png",
    shortcut: "/assets/ui/logo.png",
    apple: "/assets/ui/logo.png",
  },
  manifest: "/manifest.webmanifest",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,700;1,400&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet" />
      </head>
      <body>{children}</body>
    </html>
  );
}
