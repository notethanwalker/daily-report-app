import type { Metadata, Viewport } from "next";
import "./globals.css";
import "./polish.css";
import "./macro-flow.css";
import "./pro-polish.css";
import "./v18-polish.css";
import "./intelligence-suite.css";
import "./intelligence-extras.css";
import "./portfolio-access.css";
import "./intelligence-v2.css";
import "./v3-workspaces.css";
import "./v4-fixes.css";
import "./auth.css";
import PwaRegister from "./pwa-register";
import IntelligenceAugmentations from "./intelligence-augmentations";

export const metadata: Metadata = {
  title: "Daily Report",
  description: "Market intelligence dashboard",
  applicationName: "Daily Report",
  appleWebApp: {
    capable: true,
    title: "Daily Report",
    statusBarStyle: "black-translucent",
  },
  icons: { icon: "/icon.svg" },
};

export const viewport: Viewport = {
  themeColor: "#0b0d10",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body><PwaRegister />{children}<IntelligenceAugmentations /></body></html>;
}
