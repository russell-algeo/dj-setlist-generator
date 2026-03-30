const buildPreviewLegacyHref = (legacyPath: string) =>
  `/archive-preview/legacy${legacyPath
    .split("/")
    .filter(Boolean)
    .map((segment) => `/${encodeURIComponent(segment)}`)
    .join("")}`;

export const buildArtistHref = ({
  preview,
  slug,
  legacyPath,
}: {
  preview: boolean;
  slug: string;
  legacyPath: string | null;
}) =>
  preview
    ? legacyPath && (slug.startsWith("legacy:") || !slug)
      ? buildPreviewLegacyHref(legacyPath)
      : `/archive-preview/artists/${slug}`
    : `/artists/${slug}`;

export const buildSetHref = ({
  preview,
  slug,
  legacyPath,
}: {
  preview: boolean;
  slug: string;
  legacyPath: string | null;
}) =>
  preview
    ? legacyPath && (slug.startsWith("legacy:") || !slug)
      ? buildPreviewLegacyHref(legacyPath)
      : `/archive-preview/sets/${slug}`
    : legacyPath ?? `/sets/${slug}`;
