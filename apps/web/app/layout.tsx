import type { Metadata } from "next";
import { Manrope, Space_Mono } from "next/font/google";

import { Providers } from "@/components/providers";
import { env } from "@/lib/env";
import { socialPreview } from "@/lib/social-preview";

import "./globals.css";

const manrope = Manrope({
  variable: "--font-sans",
  subsets: ["latin"],
});

const spaceMono = Space_Mono({
  variable: "--font-mono",
  weight: ["400", "700"],
  subsets: ["latin"],
});

const metadataBase = (() => {
  const candidateUrl =
    env.appBaseUrl || (env.deploymentTarget === "development" ? "http://localhost:3000" : undefined);

  if (!candidateUrl) {
    return undefined;
  }

  try {
    return new URL(candidateUrl);
  } catch {
    return undefined;
  }
})();

export const metadata: Metadata = {
  metadataBase,
  title: socialPreview.title,
  description: socialPreview.description,
  icons: {
    icon: [{ url: socialPreview.iconPath, type: "image/svg+xml" }],
  },
  openGraph: {
    title: socialPreview.title,
    description: socialPreview.description,
    siteName: socialPreview.siteName,
    type: "website",
    images: [
      {
        alt: socialPreview.imageAlt,
        height: socialPreview.imageHeight,
        url: socialPreview.imagePath,
        width: socialPreview.imageWidth,
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: socialPreview.title,
    description: socialPreview.description,
    images: [socialPreview.imagePath],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${manrope.variable} ${spaceMono.variable}`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
