import type {
  ArchiveHomeArtistCard,
  ArchiveHomeBootstrapPayload,
  ArchiveHomeHeroSet,
} from "@/lib/archive/home-explorer-types";

const normalizeImageUrl = (value: string | null | undefined) => {
  if (typeof value !== "string") {
    return null;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
};

const randomShuffle = <T,>(items: T[]) => {
  const output = [...items];

  for (let index = output.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [output[index], output[swapIndex]] = [output[swapIndex]!, output[index]!];
  }

  return output;
};

export const applyArtistCardImageFallbacks = (
  artistCards: ArchiveHomeArtistCard[],
  fallbackImageBySlug: ReadonlyMap<string, string | null | undefined>,
): ArchiveHomeArtistCard[] =>
  artistCards.map((artistCard) => ({
    ...artistCard,
    imageUrl:
      normalizeImageUrl(artistCard.imageUrl) ??
      normalizeImageUrl(fallbackImageBySlug.get(artistCard.slug) ?? null),
  }));

export const buildHomeHeroPayload = ({
  artistCards,
  heroSetCandidates,
  tickerItems,
}: {
  artistCards: ArchiveHomeArtistCard[];
  heroSetCandidates: ArchiveHomeHeroSet[];
  tickerItems: string[];
}): ArchiveHomeBootstrapPayload["hero"] => {
  const shuffledSets = randomShuffle(heroSetCandidates);
  const railSets: ArchiveHomeHeroSet[] = [];

  if (shuffledSets.length) {
    const targetCount = Math.max(8, Math.min(12, shuffledSets.length * 2));

    for (let index = 0; index < targetCount; index += 1) {
      railSets.push(shuffledSets[index % shuffledSets.length]!);
    }
  }

  const imagePool = artistCards.filter((artistCard) => Boolean(normalizeImageUrl(artistCard.imageUrl)));
  const heroArtist = imagePool.length > 0 ? randomShuffle(imagePool)[0] : null;
  const heroImage =
    normalizeImageUrl(heroArtist?.imageUrl) ??
    railSets.find((setItem) => Boolean(normalizeImageUrl(setItem.thumbnailUrl)))?.thumbnailUrl ??
    null;

  return {
    imageAlt: heroArtist ? `${heroArtist.name} artist profile image` : "Set signal visual",
    imageUrl: heroImage,
    railSets,
    tickerItems,
  };
};
