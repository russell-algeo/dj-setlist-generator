import type { Metadata } from "next";

import { socialPreview } from "@/lib/social-preview";

export const buildArchiveMetadata = ({
  title,
  description,
  canonicalPath,
  noindex = false,
}: {
  title: string;
  description: string;
  canonicalPath?: string;
  noindex?: boolean;
}): Metadata => ({
  title,
  description,
  alternates: canonicalPath
    ? {
        canonical: canonicalPath,
      }
    : undefined,
  openGraph: {
    title,
    description,
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
    title,
    description,
    images: [socialPreview.imagePath],
  },
  robots: noindex
    ? {
        follow: false,
        index: false,
      }
    : undefined,
});
