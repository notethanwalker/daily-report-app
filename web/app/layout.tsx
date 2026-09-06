import type { Metadata, Viewport } from "next";
import "./globals.css";
import "./polish.css";
import "./macro-flow.css";
import "./pro-polish.css";
import "./v18-polish.css";
import "./intelligence-suite.css";
import PwaRegister from "./pwa-register";

export const metadata: Metadata = {
  title: "Daily Report",
  description: "Market intelligence dashboard",
  applicationName: "Daily Report",
  appleWebApp: {
    capable: true,
    title: "Daily Report",
    statusBarStyle: "black-translucent",
  },
  icons: {
    icon: "/icon.svg",
  },
};

export const viewport: Viewport = {
  themeColor: "#0b0d10",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <PwaRegister />
        {children}
      </body>
    </html>
  );
}
