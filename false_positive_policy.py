"""Known false-positive rule loading and matching."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


def _clean_text(value: str | None) -> str | None:
    """Trim and normalize empty strings to None."""
    text = str(value or "").strip()
    return text or None


def normalize_text(value: str | None) -> str:
    """Normalize text for loose matching."""
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def normalize_artist_title(artist: str | None, title: str | None) -> str | None:
    """Build a normalized artist/title lookup key."""
    artist_norm = normalize_text(artist)
    title_norm = normalize_text(title)
    if not artist_norm or not title_norm:
        return None
    return f"{artist_norm} | {title_norm}"


@dataclass(frozen=True)
class FalsePositiveRule:
    """One unconditional suppression rule."""

    id: str
    reason: str
    shazam_track_id: str | None = None
    artist: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class FalsePositiveMatch:
    """Resolved rule match for a cluster candidate."""

    rule: FalsePositiveRule
    match_type: str


class FalsePositivePolicy:
    """Lookup helper for known false-positive tracks."""

    def __init__(self, rules: list[FalsePositiveRule]):
        self.rules = tuple(rules)
        self._by_shazam_track_id: dict[str, FalsePositiveRule] = {}
        self._by_artist_title: dict[str, FalsePositiveRule] = {}
        self._validate_and_index_rules()

    @classmethod
    def load_from_path(cls, path: Path) -> "FalsePositivePolicy":
        """Load rules from a JSON file."""
        if not path.exists():
            raise FileNotFoundError(f"False-positive rules file not found: {path}")

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid false-positive rules JSON in {path}: {exc}") from exc

        if not isinstance(payload, list):
            raise ValueError(f"False-positive rules file must contain a JSON list: {path}")

        rules = [
            cls._rule_from_dict(item, index, path)
            for index, item in enumerate(payload, start=1)
        ]
        return cls(rules)

    @staticmethod
    def _rule_from_dict(item: object, index: int, path: Path) -> FalsePositiveRule:
        """Convert one raw rule dict into a validated dataclass."""
        if not isinstance(item, dict):
            raise ValueError(f"False-positive rule #{index} in {path} must be an object")

        rule_id = _clean_text(item.get("id"))
        reason = _clean_text(item.get("reason"))
        shazam_track_id = _clean_text(item.get("shazam_track_id"))
        artist = _clean_text(item.get("artist"))
        title = _clean_text(item.get("title"))

        if not rule_id:
            raise ValueError(f"False-positive rule #{index} in {path} is missing 'id'")
        if not reason:
            raise ValueError(f"False-positive rule '{rule_id}' in {path} is missing 'reason'")
        if not shazam_track_id and not (artist and title):
            raise ValueError(
                f"False-positive rule '{rule_id}' in {path} must define "
                "'shazam_track_id' or both 'artist' and 'title'"
            )

        return FalsePositiveRule(
            id=rule_id,
            reason=reason,
            shazam_track_id=shazam_track_id,
            artist=artist,
            title=title,
        )

    def _validate_and_index_rules(self) -> None:
        """Reject duplicate match keys and populate indexes."""
        for rule in self.rules:
            if rule.shazam_track_id:
                if rule.shazam_track_id in self._by_shazam_track_id:
                    other = self._by_shazam_track_id[rule.shazam_track_id]
                    raise ValueError(
                        "Duplicate false-positive shazam_track_id "
                        f"'{rule.shazam_track_id}' in rules '{other.id}' and '{rule.id}'"
                    )
                self._by_shazam_track_id[rule.shazam_track_id] = rule

            artist_title_key = normalize_artist_title(rule.artist, rule.title)
            if artist_title_key:
                if artist_title_key in self._by_artist_title:
                    other = self._by_artist_title[artist_title_key]
                    raise ValueError(
                        "Duplicate false-positive artist/title match "
                        f"for rules '{other.id}' and '{rule.id}'"
                    )
                self._by_artist_title[artist_title_key] = rule

    def match(
        self,
        artist: str | None,
        title: str | None,
        shazam_track_id: str | None,
    ) -> FalsePositiveMatch | None:
        """Find a matching false-positive rule for a recognized track."""
        track_id = _clean_text(shazam_track_id)
        if track_id:
            rule = self._by_shazam_track_id.get(track_id)
            if rule:
                return FalsePositiveMatch(rule=rule, match_type="shazam_track_id")

        artist_title_key = normalize_artist_title(artist, title)
        if artist_title_key:
            rule = self._by_artist_title.get(artist_title_key)
            if rule:
                return FalsePositiveMatch(rule=rule, match_type="artist_title")

        return None
