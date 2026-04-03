const normalizeImageUrl = (value: string | null | undefined) => {
  if (typeof value !== "string") {
    return null;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
};

export const pickFirstImageUrl = (candidates: Array<string | null | undefined>) => {
  for (const candidate of candidates) {
    const normalized = normalizeImageUrl(candidate);
    if (normalized) {
      return normalized;
    }
  }

  return null;
};

export const buildArtistHeroRail = <T extends { id: string; heroImageUrl: string | null }>(
  sets: T[],
) => {
  const uniqueSets = sets.filter(
    (setItem, index, value) => value.findIndex((candidate) => candidate.id === setItem.id) === index,
  );

  if (uniqueSets.length === 0) {
    return [];
  }

  const visualSets = uniqueSets.filter((setItem) => Boolean(normalizeImageUrl(setItem.heroImageUrl)));
  const orderedSets = visualSets.length > 0 ? visualSets : uniqueSets;

  return orderedSets.length > 1 ? [...orderedSets, ...orderedSets] : orderedSets;
};
