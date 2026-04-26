import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Lightsei",
  description: "Drop-in observability for AI agents",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-white text-gray-900 antialiased">{children}</body>
    </html>
  );
}
