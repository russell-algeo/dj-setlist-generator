"""Pure Spotify candidate matching helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any


ARTIST_RATIO_THRESHOLD = 1.0
VERSION_TERMS = {
    "club",
    "dub",
    "edit",
    "extended",
    "instrumental",
    "mix",
    "mixed",
    "original",
    "radio",
    "remaster",
    "remastered",
    "remix",
    "version",
}
GENRE_ALIAS_MAP = {
    "lo fi house": "lo-fi house",
    "italodance": "italo dance",
}
GENRE_TOKEN_STOPWORDS = {
    "and",
    "dance",
    "electronic",
    "indie",
    "music",
    "pop",
    "rock",
    "style",
    "styles",
    "the",
}


@dataclass(frozen=True)
class CandidateMatch:
    """A scored candidate returned by matching helpers."""

    item: dict[str, Any]
    score: float
    reason: str
    strong_artist_evidence: bool = False


def normalize_text(value: str | None) -> str:
    """Normalize text for fuzzy comparisons while preserving word boundaries."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


def compact_text(value: str | None) -> str:
    """Normalize text to only lowercase alphanumerics."""
    return normalize_text(value).replace(" ", "")


def comparable_words(value: str | None, *, min_length: int = 3) -> set[str]:
    """Return normalized words useful for matching."""
    return {word for word in normalize_text(value).split() if len(word) >= min_length}


def artist_initials(value: str | None) -> str:
    """Return initials from an artist name, including one-letter parts."""
    return "".join(word[0] for word in normalize_text(value).split() if word)


def candidate_title(item: dict[str, Any]) -> str:
    """Return a candidate title from Spotify-shaped or test-shaped data."""
    return str(item.get("name") or item.get("title") or "")


def candidate_artist_names(item: dict[str, Any]) -> list[str]:
    """Return artist names from Spotify-shaped or test-shaped data."""
    artists = item.get("artists")
    if isinstance(artists, list):
        names = [str(artist.get("name") or "").strip() for artist in artists if isinstance(artist, dict)]
        return [name for name in names if name]
    artist = str(item.get("artist") or "").strip()
    return [artist] if artist else []


def candidate_artist_text(item: dict[str, Any]) -> str:
    """Return candidate artists as one comparable string."""
    return " ".join(candidate_artist_names(item))


def candidate_artist_genres(item: dict[str, Any]) -> list[str]:
    """Return Spotify artist genres attached by the enricher or tests."""
    values = (
        item.get("_spotify_artist_genres")
        or item.get("spotify_artist_genres")
        or item.get("spotify_genres")
        or item.get("artist_genres")
        or []
    )
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value or "").strip()]


def discogs_release_title(discogs_data: dict[str, Any] | None) -> str:
    """Return the Discogs release result title, when present."""
    if not discogs_data:
        return ""
    return str(
        discogs_data.get("title")
        or discogs_data.get("release_title")
        or discogs_data.get("discogs_title")
        or ""
    )


def discogs_artist_text(discogs_data: dict[str, Any] | None) -> str:
    """Return the artist portion of a Discogs release title."""
    title = discogs_release_title(discogs_data)
    if " - " in title:
        return title.split(" - ", 1)[0]
    return title


def discogs_genres(discogs_data: dict[str, Any] | None) -> list[str]:
    """Return combined Discogs style and genre labels."""
    if not discogs_data:
        return []
    values = (discogs_data.get("styles") or []) + (discogs_data.get("genres") or [])
    return [str(value) for value in values if str(value or "").strip()]


def normalize_genre_label(value: str | None) -> str:
    """Normalize a genre/style label for overlap matching."""
    normalized = normalize_text(value)
    return GENRE_ALIAS_MAP.get(normalized, normalized)


def genre_label_set(genres: list[str] | None) -> set[str]:
    """Build a normalized set of genre/style labels."""
    return {label for value in (genres or []) if (label := normalize_genre_label(value))}


def genre_token_set(genres: list[str] | None) -> set[str]:
    """Build meaningful normalized tokens from genre/style labels."""
    tokens: set[str] = set()
    for label in genre_label_set(genres):
        for token in label.split():
            if len(token) >= 3 and token not in GENRE_TOKEN_STOPWORDS:
                tokens.add(token)
    return tokens


def genre_overlap(expected_genres: list[str] | None, provider_genres: list[str] | None) -> tuple[float, set[str]]:
    """Return a genre overlap score and shared labels/tokens."""
    expected_labels = genre_label_set(expected_genres)
    provider_labels = genre_label_set(provider_genres)
    expected_tokens = genre_token_set(expected_genres)
    provider_tokens = genre_token_set(provider_genres)
    shared_labels = expected_labels & provider_labels
    shared_tokens = expected_tokens & provider_tokens
    shared = shared_labels | shared_tokens
    if not shared:
        return 0.0, set()
    denominator = max(1, min(len(expected_labels | expected_tokens), len(provider_labels | provider_tokens)))
    return len(shared) / denominator, shared


def title_only_eligible(expected_title: str, observed_title: str) -> tuple[bool, float]:
    """Return whether a title-only candidate is close enough to consider."""
    if len(normalize_text(expected_title).split()) < 2:
        return False, 0.0
    return title_match_score(expected_title, observed_title)


def title_match_score(expected_title: str, observed_title: str) -> tuple[bool, float]:
    """Keep the whole title (including short words); allow explicit version suffixes."""
    expected_norm = normalize_text(expected_title)
    observed_norm = normalize_text(observed_title)
    if not expected_norm:
        return False, 0.0
    if expected_norm and expected_norm == observed_norm:
        return True, 2.0
    # A shared word or a title embedded in a different song is not identity.
    # Only strip a delimited suffix that actually describes a mix/version.
    for suffix in re.finditer(r"\s*(?:\(|\[|\s[-–—]\s)\s*", observed_title):
        base = observed_title[:suffix.start()]
        if normalize_text(base) == expected_norm and comparable_words(observed_title[suffix.end():]) & VERSION_TERMS:
            return True, 1.0
    return False, 0.0


def has_expected_artist_evidence(expected_artist: str, item: dict[str, Any]) -> bool:
    """Return true when a candidate artist plausibly aliases the expected artist."""
    expected_compact = compact_text(expected_artist)
    expected_initials = artist_initials(expected_artist)
    for artist_name in candidate_artist_names(item):
        candidate_compact = compact_text(artist_name)
        if not candidate_compact:
            continue
        if candidate_compact == expected_compact:
            return True
        if expected_initials and candidate_compact == expected_initials:
            return True
    return False


def has_discogs_artist_evidence(discogs_data: dict[str, Any] | None, item: dict[str, Any]) -> bool:
    """Return true when Discogs release artist text corroborates the Spotify artist."""
    discogs_artist = compact_text(discogs_artist_text(discogs_data))
    if not discogs_artist:
        return False
    # Match a complete artist credit, not a substring such as "Collective".
    credits = re.split(r"\s+(?:/|&|feat\.?|featuring)\s+", discogs_artist_text(discogs_data), flags=re.I)
    return any(compact_text(name) == compact_text(credit) for name in candidate_artist_names(item) for credit in credits)


def discogs_corroborates_title(expected_title: str, discogs_data: dict[str, Any] | None) -> bool:
    """A search result for a different release cannot establish an alias."""
    titles = re.split(r"\s*/\s*", discogs_release_title(discogs_data).partition(" - ")[2])
    return any(title_match_score(expected_title, title)[0] for title in titles)


def score_artist_title_candidates(
    expected_artist: str,
    expected_title: str,
    candidates: list[dict[str, Any]],
) -> list[CandidateMatch]:
    """Score complete artist credits and titles, preserving short identity words."""
    expected_artist_credit = re.sub(r"^the ", "", normalize_text(expected_artist))
    if not expected_artist_credit or not normalize_text(expected_title):
        return []

    scored: list[CandidateMatch] = []
    for item in candidates:
        title_eligible, title_score = title_match_score(expected_title, candidate_title(item))
        if not title_eligible:
            continue
        # Evaluate each credited artist individually; unrelated collaborators
        # must not combine into the expected artist's name.
        # A complete short name embedded in another name is still a different
        # identity (for example Hammer versus Velvet Hammer).
        artist_ratio = float(any(
            re.sub(r"^the ", "", normalize_text(name)) == expected_artist_credit
            for name in candidate_artist_names(item)
        ))
        if has_expected_artist_evidence(expected_artist, item):
            artist_ratio = 1.0
        # Explicit collaboration credits may correspond to separate Spotify
        # artists. Only split named separators, never arbitrary name words.
        expected_credits = re.split(r"\s+(?:&|and|x|feat\.?|featuring)\s+|,\s*", expected_artist, flags=re.I)
        if len(expected_credits) > 1 and all(
            has_expected_artist_evidence(credit, item) for credit in expected_credits
        ):
            artist_ratio = 1.0
        if artist_ratio < ARTIST_RATIO_THRESHOLD:
            continue
        score = (artist_ratio * 4.0) + title_score
        scored.append(CandidateMatch(item=item, score=score, reason="artist_title", strong_artist_evidence=True))

    return sorted(scored, key=lambda match: match.score, reverse=True)


def score_title_only_candidates(
    expected_artist: str,
    expected_title: str,
    candidates: list[dict[str, Any]],
    *,
    discogs_data: dict[str, Any] | None = None,
) -> list[CandidateMatch]:
    """Score title-only candidates using artist, Discogs, and genre corroboration."""
    scored: list[CandidateMatch] = []
    expected_genres = discogs_genres(discogs_data)
    for item in candidates:
        eligible, title_score = title_only_eligible(expected_title, candidate_title(item))
        if not eligible:
            continue

        score = title_score
        reasons: list[str] = []
        expected_artist_evidence = has_expected_artist_evidence(expected_artist, item)
        discogs_artist_evidence = (discogs_corroborates_title(expected_title, discogs_data)
                                  and has_discogs_artist_evidence(discogs_data, item))

        if expected_artist_evidence:
            score += 4.0
            reasons.append("expected_artist_alias")
        if discogs_artist_evidence:
            score += 4.0
            reasons.append("discogs_artist")

        provider_genres = candidate_artist_genres(item)
        overlap, shared_genres = genre_overlap(expected_genres, provider_genres)
        if overlap > 0:
            score += 2.0 + min(overlap, 1.0)
            reasons.append("genre_overlap")

        # Genre agreement helps rank a corroborated identity; it cannot prove
        # that two unrelated artists with the same title are the same track.
        has_corrob = expected_artist_evidence or discogs_artist_evidence
        if not has_corrob:
            continue

        strong_artist_evidence = expected_artist_evidence or discogs_artist_evidence
        if expected_genres and provider_genres and not shared_genres and not strong_artist_evidence:
            continue

        scored.append(
            CandidateMatch(
                item=item,
                score=score,
                reason="+".join(reasons) or "title_only",
                strong_artist_evidence=strong_artist_evidence,
            )
        )

    scored.sort(key=lambda match: match.score, reverse=True)
    return scored


def select_spotify_candidate(
    expected_artist: str,
    expected_title: str,
    primary_candidates: list[dict[str, Any]],
    fallback_candidates: list[dict[str, Any]] | None = None,
    *,
    discogs_data: dict[str, Any] | None = None,
) -> CandidateMatch | None:
    """Select the best Spotify candidate, including a guarded title-only fallback."""
    primary_matches = score_artist_title_candidates(expected_artist, expected_title, primary_candidates)
    if primary_matches:
        return select_unambiguous_match(primary_matches)

    fallback_matches = score_title_only_candidates(
        expected_artist,
        expected_title,
        fallback_candidates or [],
        discogs_data=discogs_data,
    )
    if not fallback_matches:
        return None

    return select_unambiguous_match(fallback_matches)


def select_unambiguous_match(matches: list[CandidateMatch]) -> CandidateMatch | None:
    """Equivalent album listings are OK; equally supported identities are not."""
    if not matches:
        return None
    best = matches[0]
    best_identity = (compact_text(candidate_artist_text(best.item)), normalize_text(candidate_title(best.item)))
    for runner_up in matches[1:]:
        if best.score - runner_up.score >= 0.5:
            break
        identity = (compact_text(candidate_artist_text(runner_up.item)), normalize_text(candidate_title(runner_up.item)))
        if identity != best_identity:
            return None
    return best
