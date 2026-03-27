import { env } from "@/lib/env";

export const socialPreview = {
  description:
    "DJ set archive with set explorers, artist decks, track atlases, and recurring-signal analysis.",
  iconPath: "/set-signal-icon.svg",
  imageAlt: "Set Signal Archive social preview card",
  imageHeight: 630,
  imagePath: "/set-signal-social-card.svg",
  imageWidth: 1200,
  siteName: "Set Signal Archive",
  title: "Set Signal Archive",
} as const;

const escapeHtml = (value: string) =>
  value
    .replaceAll("&", "&amp;")
    .replaceAll("'", "&#39;")
    .replaceAll("\"", "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");

export const extractDocumentTitle = (html: string) => {
  const match = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  return match?.[1].trim() || socialPreview.title;
};

const resolveBaseUrl = (requestUrl?: string) => {
  const value = requestUrl || env.appBaseUrl;

  if (!value) {
    return null;
  }

  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
};

const resolveUrl = (path: string, requestUrl?: string) => {
  const baseUrl = resolveBaseUrl(requestUrl);

  if (!baseUrl) {
    return path;
  }

  return new URL(path, baseUrl).toString();
};

export const buildArchiveSocialHead = ({
  html,
  pagePath,
  requestUrl,
}: {
  html: string;
  pagePath: string;
  requestUrl?: string;
}) => {
  const title = extractDocumentTitle(html);
  const description = socialPreview.description;
  const imageUrl = resolveUrl(socialPreview.imagePath, requestUrl);
  const iconUrl = resolveUrl(socialPreview.iconPath, requestUrl);
  const pageUrl = resolveUrl(pagePath, requestUrl);

  return [
    `<meta name="description" content="${escapeHtml(description)}" />`,
    `<meta name="theme-color" content="#0A0A0A" />`,
    `<link rel="icon" href="${escapeHtml(iconUrl)}" type="image/svg+xml" />`,
    `<meta property="og:site_name" content="${escapeHtml(socialPreview.siteName)}" />`,
    `<meta property="og:type" content="website" />`,
    `<meta property="og:title" content="${escapeHtml(title)}" />`,
    `<meta property="og:description" content="${escapeHtml(description)}" />`,
    `<meta property="og:image" content="${escapeHtml(imageUrl)}" />`,
    `<meta property="og:image:alt" content="${escapeHtml(socialPreview.imageAlt)}" />`,
    `<meta property="og:image:width" content="${socialPreview.imageWidth}" />`,
    `<meta property="og:image:height" content="${socialPreview.imageHeight}" />`,
    `<meta property="og:url" content="${escapeHtml(pageUrl)}" />`,
    `<meta name="twitter:card" content="summary_large_image" />`,
    `<meta name="twitter:title" content="${escapeHtml(title)}" />`,
    `<meta name="twitter:description" content="${escapeHtml(description)}" />`,
    `<meta name="twitter:image" content="${escapeHtml(imageUrl)}" />`,
  ].join("\n  ");
};

export const injectArchiveSocialMetadata = ({
  html,
  pagePath,
  requestUrl,
}: {
  html: string;
  pagePath: string;
  requestUrl?: string;
}) => {
  const socialHead = buildArchiveSocialHead({ html, pagePath, requestUrl });

  if (/<\/head>/i.test(html)) {
    return html.replace(/<\/head>/i, `  ${socialHead}\n</head>`);
  }

  return html;
};
