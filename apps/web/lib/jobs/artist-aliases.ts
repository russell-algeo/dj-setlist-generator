export const maxArtistAliases = 5;

type PrepareArtistAliasesInput = {
  mode: string;
  artistName?: string | null;
  artistAliases?: readonly string[] | null;
};

export type PrepareArtistAliasesResult = {
  aliases: string[];
  exceedsLimit: boolean;
};

const collapseWhitespace = (value: string) => value.replace(/\s+/gu, " ").trim();

const normalizedAliasKey = (value: string) => collapseWhitespace(value).toLocaleLowerCase();

export const prepareArtistAliases = ({
  mode,
  artistName,
  artistAliases,
}: PrepareArtistAliasesInput): PrepareArtistAliasesResult => {
  if (mode !== "artist") {
    return { aliases: [], exceedsLimit: false };
  }

  const primaryKey = artistName ? normalizedAliasKey(artistName) : null;
  const seen = new Set<string>();
  const aliases: string[] = [];

  for (const alias of artistAliases ?? []) {
    const cleaned = collapseWhitespace(alias);
    if (!cleaned) {
      continue;
    }

    const key = normalizedAliasKey(cleaned);
    if ((primaryKey && key === primaryKey) || seen.has(key)) {
      continue;
    }

    if (aliases.length >= maxArtistAliases) {
      return { aliases, exceedsLimit: true };
    }

    seen.add(key);
    aliases.push(cleaned);
  }

  return { aliases, exceedsLimit: false };
};
