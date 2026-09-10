import type { Metadata, Viewport } from "next";
import "./globals.css";
import "./auth.css";
import "./v4/global-ticker-search-host.css";
import "./v4/v4-card-layout-host.css";
import PwaRegister from "./pwa-register";
import DestructiveActionGuard from "./destructive-action-guard";
import AccessibilityRuntime from "./accessibility-runtime";
import GlobalTickerSearchHost from "./v4/global-ticker-search-host";
import V4CardLayoutHost from "./v4/v4-card-layout-host";

export const metadata: Metadata = {
  title: "Daily Report",
  description: "Market intelligence decision stack",
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
  return <html lang="en"><body><PwaRegister /><AccessibilityRuntime /><DestructiveActionGuard /><GlobalTickerSearchHost /><V4CardLayoutHost />{children}</body></html>;
}
