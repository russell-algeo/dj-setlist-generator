"""Shared source-link duplicate matching heuristics.

The goal is high precision for automatic cross-platform source links. Anything
that looks plausible but not strong enough should stay out of automatic source
links and can be reviewed manually later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence
import difflib
import re
import unicodedata

ACCEPTED = "accepted"
AMBIGUOUS = "ambiguous"
REJECTED = "rejected"

SUPPORTED_PLATFORMS = {"youtube", "soundcloud"}
IGNORED_ARTIST_TOKENS = {"dj", "de", "fr", "uk", "us", "usa", "live", "official"}
ANCHOR_STOPWORDS = {
    "dj",
    "set",
    "live",
    "mix",
    "b2b",
    "podcast",
    "radio",
    "show",
    "full",
    "official",
    "session",
    "music",
    "house",
    "techno",
    "guest",
    "recorded",
    "at",
    "from",
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "in",
    "on",
    "for",
    "to",
    "by",
    "with",
    "feat",
    "ft",
    "presents",
    "x",
}
SERIES_PREFIX_WORDS = {
    "episode",
    "ep",
    "vol",
    "volume",
    "part",
    "pt",
    "installment",
    "chapter",
    "no",
    "nr",
    "number",
    "edition",
    "ed",
}
MONTHS = {
    "jan": 1,
    "january": 1,
    "janvier": 1,
    "feb": 2,
    "february": 2,
    "fevrier": 2,
    "mar": 3,
    "march": 3,
    "mars": 3,
    "apr": 4,
    "april": 4,
    "avril": 4,
    "may": 5,
    "mai": 5,
    "jun": 6,
    "june": 6,
    "juin": 6,
    "jul": 7,
    "july": 7,
    "juillet": 7,
    "aug": 8,
    "august": 8,
    "aout": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "septembre": 9,
    "oct": 10,
    "october": 10,
    "octobre": 10,
    "nov": 11,
    "november": 11,
    "novembre": 11,
    "dec": 12,
    "december": 12,
    "decembre": 12,
}


@dataclass
class MatchSource:
    title: str
    platform: str
    duration_seconds: int | None = None
    uploader: str | None = None


def normalize_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", normalized.lower())).strip()


def _expand_common_aliases(value: str | None) -> str:
    text = normalize_text(value)
    replacements = {
        r"\bra\b": "resident advisor",
        r"\blab ldn\b": "lab london",
        r"\bessential mix\b": "essential mix bbc radio 1",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text)
    return text


def detect_platform(url: str | None) -> str:
    value = (url or "").lower()
    if "soundcloud.com" in value:
        return "soundcloud"
    if "youtube.com" in value or "youtu.be" in value:
        return "youtube"
    return "unknown"


def title_similarity(left: str, right: str) -> float:
    return difflib.SequenceMatcher(None, normalize_text(left), normalize_text(right)).ratio()


def extract_years(value: str | None) -> set[int]:
    return {int(match.group(0)) for match in re.finditer(r"\b(?:19|20)\d{2}\b", value or "")}


def extract_part_markers(value: str | None) -> set[str]:
    text = normalize_text(value)
    markers = set()
    for match in re.finditer(r"\b(?:part|pt)\s+([0-9ivx]+)\b", text):
        markers.add(match.group(1))
    return markers


def extract_series_markers(value: str | None) -> set[str]:
    tokens = normalize_text(value).split()
    markers: set[str] = set()
    for index, token in enumerate(tokens[:-1]):
        if token in SERIES_PREFIX_WORDS and re.fullmatch(r"[0-9ivx]+", tokens[index + 1]):
            markers.add(f"{token}:{tokens[index + 1]}")
    return markers


def extract_bare_numbers(value: str | None) -> set[int]:
    years = extract_years(value)
    numbers = set()
    for token in normalize_text(value).split():
        if token.isdigit():
            number = int(token)
            if number not in years:
                numbers.add(number)
    return numbers


def normalize_year(value: str) -> int:
    year = int(value)
    if year < 100:
        return 2000 + year if year <= 68 else 1900 + year
    return year


def add_date(dates: set[str], year: int, month: int, day: int) -> None:
    try:
        dates.add(date(year, month, day).isoformat())
    except ValueError:
        return


def extract_dates(value: str | None) -> set[str]:
    text = value or ""
    dates: set[str] = set()

    for match in re.finditer(r"\b((?:19|20)\d{2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})\b", text):
        add_date(dates, normalize_year(match.group(1)), int(match.group(2)), int(match.group(3)))

    for match in re.finditer(r"\b(\d{1,2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*((?:19|20)?\d{2})\b", text):
        first, second, year = int(match.group(1)), int(match.group(2)), normalize_year(match.group(3))
        add_date(dates, year, first, second)
        add_date(dates, year, second, first)

    month_pattern = "|".join(MONTHS)
    for match in re.finditer(
        rf"\b({month_pattern})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+((?:19|20)?\d{{2}})\b",
        text,
        flags=re.IGNORECASE,
    ):
        add_date(dates, normalize_year(match.group(3)), MONTHS[match.group(1).lower().rstrip(".")], int(match.group(2)))
    for match in re.finditer(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_pattern})\.?[,]?\s+((?:19|20)?\d{{2}})\b",
        text,
        flags=re.IGNORECASE,
    ):
        add_date(dates, normalize_year(match.group(3)), MONTHS[match.group(2).lower().rstrip(".")], int(match.group(1)))

    return dates


def extract_months(value: str | None) -> set[int]:
    tokens = normalize_text(value).split()
    months = {MONTHS[token] for token in tokens if token in MONTHS}

    for index in range(len(tokens) - 2):
        first, second, third = tokens[index], tokens[index + 1], tokens[index + 2]
        if not (first.isdigit() and second.isdigit() and re.fullmatch(r"(?:19|20)\d{2}", third)):
            continue
        first_number, second_number = int(first), int(second)
        if first_number > 12 and 1 <= second_number <= 12:
            months.add(second_number)
        elif second_number > 12 and 1 <= first_number <= 12:
            months.add(first_number)
        else:
            if 1 <= first_number <= 12:
                months.add(first_number)
            if 1 <= second_number <= 12:
                months.add(second_number)

    return months


def token_set(value: str | None) -> set[str]:
    return set(normalize_text(value).split())


def significant_artist_tokens(value: str | None) -> set[str]:
    return {token for token in token_set(value) if len(token) > 1 and token not in IGNORED_ARTIST_TOKENS}


def _artist_overlap(artist_names: Sequence[str], candidate_blob: str) -> float:
    candidate_tokens = token_set(candidate_blob)
    overlaps = []
    for artist_name in artist_names:
        artist_tokens = significant_artist_tokens(artist_name)
        if artist_tokens:
            overlaps.append(len(artist_tokens & candidate_tokens) / len(artist_tokens))
    return max(overlaps) if overlaps else 0.0


def _artist_content_similarity(left: str, right: str, artist_names: Sequence[str]) -> float:
    artist_tokens: set[str] = set()
    for artist_name in artist_names:
        artist_tokens.update(significant_artist_tokens(artist_name))

    left_text = " ".join(token for token in normalize_text(left).split() if token not in artist_tokens)
    right_text = " ".join(token for token in normalize_text(right).split() if token not in artist_tokens)
    if not left_text or not right_text:
        return 0.0
    return difflib.SequenceMatcher(None, left_text, right_text).ratio()


def anchor_tokens(value: str | None, artist_names: Sequence[str]) -> set[str]:
    artist_tokens: set[str] = set()
    for artist_name in artist_names:
        artist_tokens.update(significant_artist_tokens(artist_name))
    return {
        token
        for token in normalize_text(_expand_common_aliases(value)).split()
        if token not in artist_tokens and token not in ANCHOR_STOPWORDS and len(token) > 1
    }


def anchor_jaccard_similarity(left: str, right: str, artist_names: Sequence[str]) -> float:
    left_tokens = anchor_tokens(left, artist_names)
    right_tokens = anchor_tokens(right, artist_names)
    union_size = len(left_tokens | right_tokens)
    return len(left_tokens & right_tokens) / union_size if union_size else 0.0


def duration_diff_minutes(known: MatchSource, candidate: MatchSource) -> float | None:
    if known.duration_seconds is None or candidate.duration_seconds is None:
        return None
    return abs(known.duration_seconds - candidate.duration_seconds) / 60


def score_source_match(
    known: MatchSource,
    candidate: MatchSource,
    *,
    artist_names: Sequence[str],
) -> dict[str, Any]:
    expected_platform = "soundcloud" if known.platform == "youtube" else "youtube"
    if candidate.platform != expected_platform:
        return {
            "status": REJECTED,
            "score": 0.0,
            "reason": "wrong_platform",
            "title_similarity": 0.0,
            "content_similarity": 0.0,
            "duration_diff_minutes": None,
        }

    similarity = title_similarity(known.title, candidate.title)
    content_similarity = _artist_content_similarity(known.title, candidate.title, artist_names)
    # Use literal title similarity for automatic accepts/rejects. The
    # artist-stripped content similarity is useful for review recall, but it
    # can make different artists in the same series look deceptively identical.
    effective_similarity = max(similarity, content_similarity)
    duration_diff = duration_diff_minutes(known, candidate)
    known_years = extract_years(known.title)
    candidate_years = extract_years(candidate.title)
    known_dates = extract_dates(known.title)
    candidate_dates = extract_dates(candidate.title)
    known_months = extract_months(known.title)
    candidate_months = extract_months(candidate.title)
    known_parts = extract_part_markers(known.title)
    candidate_parts = extract_part_markers(candidate.title)
    known_series = extract_series_markers(known.title)
    candidate_series = extract_series_markers(candidate.title)
    part_mismatch = bool(known_parts or candidate_parts) and known_parts != candidate_parts
    series_mismatch = bool(known_series or candidate_series) and known_series != candidate_series
    known_anchors = anchor_tokens(known.title, artist_names)
    candidate_anchors = anchor_tokens(candidate.title, artist_names)
    anchor_overlap_count = len(known_anchors & candidate_anchors)
    anchor_overlap_ratio = anchor_overlap_count / max(1, min(len(known_anchors), len(candidate_anchors)))
    anchor_jaccard = anchor_jaccard_similarity(known.title, candidate.title, artist_names)

    if known_dates and candidate_dates and not (known_dates & candidate_dates):
        return {
            "status": REJECTED,
            "score": similarity,
            "reason": "date_conflict",
            "title_similarity": round(similarity, 4),
            "content_similarity": round(content_similarity, 4),
            "duration_diff_minutes": duration_diff,
        }
    if known_years and candidate_years and not (known_years & candidate_years):
        return {
            "status": REJECTED,
            "score": similarity,
            "reason": "year_conflict",
            "title_similarity": round(similarity, 4),
            "content_similarity": round(content_similarity, 4),
            "duration_diff_minutes": duration_diff,
        }
    if (
        known_months
        and candidate_months
        and not (known_months & candidate_months)
        and (not known_years or not candidate_years or bool(known_years & candidate_years))
    ):
        return {
            "status": REJECTED,
            "score": similarity,
            "reason": "month_conflict",
            "title_similarity": round(similarity, 4),
            "content_similarity": round(content_similarity, 4),
            "duration_diff_minutes": duration_diff,
            "anchor_jaccard": round(anchor_jaccard, 4),
        }

    known_numbers = extract_bare_numbers(known.title)
    candidate_numbers = extract_bare_numbers(candidate.title)
    if known_numbers and candidate_numbers and known_numbers != candidate_numbers:
        known_tokens = token_set(known.title)
        candidate_tokens = token_set(candidate.title)
        differing = (known_tokens ^ candidate_tokens) - {str(number) for number in known_numbers | candidate_numbers}
        same_explicit_date = bool(known_dates and candidate_dates and known_dates & candidate_dates)
        likely_same_recording_despite_numbers = (
            same_explicit_date
            or (duration_diff is not None and duration_diff <= 0.1 and similarity >= 0.9)
            or (
                duration_diff is not None
                and duration_diff <= 1
                and anchor_overlap_count >= 2
                and anchor_overlap_ratio >= 0.66
                and similarity >= 0.5
            )
        )
        numeric_series_like = anchor_overlap_count >= 1 and similarity >= 0.5
        if not likely_same_recording_despite_numbers and (
            numeric_series_like or not differing or all(len(token) <= 2 for token in differing)
        ):
            return {
                "status": REJECTED,
                "score": similarity,
                "reason": "numeric_series_conflict",
                "title_similarity": round(similarity, 4),
                "content_similarity": round(content_similarity, 4),
                "duration_diff_minutes": duration_diff,
                "anchor_overlap_count": anchor_overlap_count,
                "anchor_overlap_ratio": round(anchor_overlap_ratio, 4),
            }

    artist_overlap = _artist_overlap(artist_names, f"{candidate.title} {candidate.uploader or ''}")
    duration_close = duration_diff is not None and duration_diff <= 5
    duration_very_close = duration_diff is not None and duration_diff <= 2
    duration_half_minute = duration_diff is not None and duration_diff <= 0.5
    duration_near_exact = duration_diff is not None and duration_diff <= 0.05

    if duration_diff is not None and duration_diff > 45 and similarity < 0.95:
        status = REJECTED
        reason = "duration_conflict"
    elif artist_names and artist_overlap == 0 and similarity < 0.9:
        status = REJECTED
        reason = "missing_artist_overlap"
    elif similarity >= 0.92 and duration_close and not part_mismatch and not series_mismatch:
        status = ACCEPTED
        reason = "strong_title_duration_match"
    elif similarity >= 0.84 and duration_very_close and artist_overlap >= 0.5 and not part_mismatch and not series_mismatch:
        status = ACCEPTED
        reason = "title_duration_artist_match"
    elif (
        content_similarity >= 0.95
        and duration_very_close
        and artist_overlap >= 1.0
        and anchor_overlap_count >= 2
        and anchor_overlap_ratio >= 0.9
        and not part_mismatch
        and not series_mismatch
    ):
        status = ACCEPTED
        reason = "alias_content_duration_match"
    elif (
        duration_half_minute
        and similarity >= 0.45
        and anchor_jaccard >= 0.3
        and (not artist_names or artist_overlap >= 0.5)
        and not part_mismatch
        and not series_mismatch
    ):
        status = ACCEPTED
        reason = "exact_duration_token_match"
    elif (
        duration_near_exact
        and content_similarity >= 0.2
        and (not artist_names or artist_overlap >= 1.0)
        and not part_mismatch
        and not series_mismatch
    ):
        status = ACCEPTED
        reason = "near_exact_duration_context_match"
    elif (
        duration_diff is not None
        and duration_diff <= 0.25
        and not part_mismatch
        and not series_mismatch
        and (
            effective_similarity >= 0.4
            or anchor_overlap_count >= 1
            or (effective_similarity >= 0.2 and artist_overlap >= 1.0)
        )
    ):
        status = AMBIGUOUS
        reason = "calibrated_exact_duration_match"
    elif (
        duration_diff is not None
        and duration_diff <= 5
        and artist_overlap >= 1.0
        and effective_similarity >= 0.4
        and not part_mismatch
        and not series_mismatch
    ):
        status = AMBIGUOUS
        reason = "calibrated_duration_artist_match"
    elif (
        duration_diff is not None
        and duration_diff <= 11
        and artist_overlap >= 1.0
        and effective_similarity >= 0.62
        and anchor_overlap_count >= 1
        and anchor_overlap_ratio >= 0.5
        and not part_mismatch
        and not series_mismatch
    ):
        status = AMBIGUOUS
        reason = "calibrated_long_duration_anchor_match"
    elif (
        duration_diff is not None
        and duration_diff <= 5
        and artist_overlap >= 0.5
        and anchor_overlap_count >= 4
        and anchor_overlap_ratio >= 0.55
        and not part_mismatch
        and not series_mismatch
    ):
        status = AMBIGUOUS
        reason = "calibrated_anchor_match"
    elif (
        duration_diff is not None
        and duration_diff <= 0.5
        and artist_overlap >= 1.0
        and anchor_overlap_count >= 2
        and anchor_overlap_ratio >= 0.75
        and effective_similarity >= 0.55
        and (part_mismatch or series_mismatch)
    ):
        status = AMBIGUOUS
        reason = "calibrated_exact_duration_series_match"
    elif (effective_similarity >= 0.62 and (not artist_names or artist_overlap >= 0.75 or duration_close)) or (
        duration_close and artist_overlap >= 0.5
    ):
        status = AMBIGUOUS
        if part_mismatch:
            reason = "manual_review_part_mismatch"
        elif series_mismatch:
            reason = "manual_review_series_mismatch"
        else:
            reason = "manual_review"
    else:
        status = REJECTED
        reason = "weak_match"

    duration_component = 1.0 if duration_diff is None else max(0.0, 1.0 - min(duration_diff, 30) / 30)
    score = round((effective_similarity * 0.75) + (duration_component * 0.2) + (artist_overlap * 0.05), 4)
    return {
        "status": status,
        "score": score,
        "reason": reason,
        "title_similarity": round(similarity, 4),
        "content_similarity": round(content_similarity, 4),
        "duration_diff_minutes": None if duration_diff is None else round(duration_diff, 2),
        "artist_overlap": round(artist_overlap, 4),
        "anchor_overlap_count": anchor_overlap_count,
        "anchor_overlap_ratio": round(anchor_overlap_ratio, 4),
        "anchor_jaccard": round(anchor_jaccard, 4),
    }
