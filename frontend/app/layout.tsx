import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Jost } from "next/font/google";
import { Providers } from "@/components/providers";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

const jost = Jost({
  variable: "--font-jost",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "iori — IDX market intelligence",
  description: "Agentic IDX market analysis — information, not advice.",
};

/** Set the theme before first paint so there's no light/dark flash. The
 * stored preference lives under the same key lib/settings.tsx uses. */
const themeScript = `
(function () {
  var theme = "dark";
  try {
    var raw = window.localStorage.getItem("iori:settings");
    if (raw) theme = JSON.parse(raw).theme || "dark";
  } catch (e) {}
  var resolved = theme === "system"
    ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : theme;
  document.documentElement.classList.toggle("dark", resolved === "dark");
  document.documentElement.style.colorScheme = resolved;
})();
`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${inter.variable} ${jetbrainsMono.variable} ${jost.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-full flex flex-col">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
