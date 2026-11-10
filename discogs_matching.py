"""Conservative Discogs release-track validation, with no provider I/O.

A release match proves track inclusion, never the recording's original label or
original-release date. Search rank, release title and shared name fragments do
not establish identity. Unsupported or incomplete evidence produces no match.
"""
from __future__ import annotations

import itertools
import re
from spotify_matching import compact_text, normalize_text

DISCOGS_MATCHING_VERSION = 1
MAX_DISCOGS_CANDIDATES = 5
DISCOGS_FIELDS = ('discogs_url', 'discogs_genres', 'discogs_styles',
                  'discogs_label', 'discogs_label_url', 'discogs_metadata_scope')


def release_id(value):
    """Canonical release identity; never follow a provider-supplied resource URL."""
    match = re.fullmatch(r'https://(?:www\.)?discogs\.com/release/(\d+)(?:-[^/?#]*)?/?', str(value or ''))
    return int(match[1]) if match else None


def _artist_key(value):
    # Discogs disambiguation numbers are catalogue syntax, not artist names.
    return compact_text(re.sub(r'\s*\(\d+\)\s*$', '', str(value or '')))


def _credits(value):
    return frozenset(_artist_key(p) for p in re.split(
        r'\s+(?:&|and|x|feat\.?|featuring|vs\.?|/)\s+|,\s*', value, flags=re.I) if _artist_key(p))


def artist_credit_matches(expected, artists):
    """Require the whole artist credit, allowing explicit provider ANVs only."""
    if not isinstance(artists, list) or not artists or len(artists) > 8:
        return False
    variants = []
    for artist in artists:
        if not isinstance(artist, dict):
            return False
        names = [str(artist.get(k) or '').strip() for k in ('name', 'anv')]
        names = list(dict.fromkeys(name for name in names if name))
        if not names:
            return False
        variants.append(names)
    wanted = _credits(str(expected or ''))
    if not wanted:
        return False
    for names in itertools.islice(itertools.product(*variants), 32):
        if wanted == _credits(' & '.join(names)):
            return True
    return False


def title_version_match(expected, observed):
    """Exact recording title/version; only an explicit Original Mix may omit its suffix.

    A bare title is not evidence for a named remix, edit, dub or extended mix,
    in either direction. This is deliberately stricter than video matching.
    """
    if not normalize_text(expected) or not normalize_text(observed):
        return None
    if compact_text(expected) == compact_text(observed):
        return 'exact_title_version'
    original = r'\s*(?:\((?:original(?: mix| version)?)\)|\[(?:original(?: mix| version)?)\]|\s[-–—]\soriginal(?: mix| version)?)\s*$'
    left = re.sub(original, '', expected, flags=re.I)
    right = re.sub(original, '', observed, flags=re.I)
    if (left != expected or right != observed) and compact_text(left) == compact_text(right):
        return 'original_suffix_omitted'
    return None


def _compilation(release):
    artists = release.get('artists')
    if isinstance(artists, list) and any(_artist_key(a.get('name')) in ('various', 'variousartists')
            for a in artists if isinstance(a, dict)):
        return True
    formats = release.get('formats')
    if not isinstance(formats, list):
        return False
    return any(str(d).lower() in ('compilation', 'mixed')
        for f in formats if isinstance(f, dict) and isinstance(f.get('descriptions'), list)
        for d in f['descriptions'])


def _tracks(release):
    """Flatten bounded nested index/sub-track lists, inheriting credits only."""
    remaining = 1000
    def walk(rows, inherited, depth):
        nonlocal remaining
        if depth > 4 or not isinstance(rows, list):
            return
        for row in rows:
            remaining -= 1
            if remaining < 0:
                return
            if not isinstance(row, dict):
                continue
            artists = row.get('artists') or inherited
            if row.get('type_', 'track') == 'track' and not row.get('sub_tracks'):
                yield row, artists
            yield from walk(row.get('sub_tracks'), artists, depth + 1)
    # A compilation DJ must never be mistaken for an uncredited track artist.
    formats = release.get('formats')
    valid_formats = isinstance(formats, list) and bool(formats) and all(
        isinstance(f, dict) and isinstance(f.get('descriptions', []), list) for f in formats)
    inherited = release.get('artists') or [] if valid_formats and not _compilation(release) else []
    yield from walk(release.get('tracklist'), inherited, 0)


def validate_discogs_release(artist, title, release):
    """Return stable evidence for a track included in this release, else None."""
    if not isinstance(release, dict) or type(release.get('id')) is not int or release['id'] <= 0:
        return None
    release_artists = release.get('artists')
    if not isinstance(release_artists, list):
        release_artists = []
    for track, artists in _tracks(release):
        version = title_version_match(str(title or ''), str(track.get('title') or ''))
        if not version or not artist_credit_matches(artist, artists):
            continue
        url = f"https://www.discogs.com/release/{release['id']}"
        return {
            'status': 'matched', 'reason': 'release_tracklist_artist_title_version',
            'matching_version': DISCOGS_MATCHING_VERSION, 'url': url,
            'title': track['title'], 'artists': [a['name'] for a in artists if a.get('name')],
            'track_position': str(track.get('position') or ''),
            'version_comparison': version,
            'release_id': release['id'], 'release_title': release.get('title'),
            'release_artists': [a.get('name') for a in release_artists if isinstance(a, dict) and isinstance(a.get('name'), str) and a.get('name')],
            'metadata_scope': 'release', 'original_release_verified': False,
            'compilation': _compilation(release),
        }
    return None


def _rejected_urls(metadata):
    previous = metadata.get('discogs_rejected_urls')
    previous = previous if isinstance(previous, list) else []
    evidence = (metadata.get('platform_matches') or {}).get('discogs') or {}
    if evidence.get('reason') == 'reviewed_rejection':
        previous = [*previous, evidence.get('rejected_url')]
    return list(dict.fromkeys(url for url in previous if release_id(url) is not None))


def rejected_release(metadata, url):
    """Honor an explicit reviewed correction even if a stale stage is replayed."""
    candidate = release_id(url)
    return candidate is not None and candidate in {release_id(u) for u in _rejected_urls(metadata)}


def merge_discogs_metadata(old, new, merged, matches, index, conflicts):
    """Preserve old data on outages; never replay a reviewed rejected release.

    Historical correction is a separate reviewed operation, not a side effect
    of re-enrichment. Unsupported legacy links become audit conflicts; new
    matches carry their evidence and release-only scope together.
    """
    from copy import deepcopy
    old_match = (old.get('platform_matches') or {}).get('discogs') or {}
    new_match = (new.get('platform_matches') or {}).get('discogs') or {}
    old_url, new_url = old.get('discogs_url'), new.get('discogs_url')
    modern = bool(new.get('discogs_matching_version'))
    rejected_urls = _rejected_urls(old)
    reviewed_rejection = bool(rejected_urls)
    if rejected_urls:
        merged['discogs_rejected_urls'] = rejected_urls
    valid = new_match.get('status') == 'matched' and new_match.get('url') == new_url
    preserve = False
    if reviewed_rejection and new_url and (rejected_release(old, new_url) or not modern or not valid):
        conflicts.append(dict(index=index, platform='discogs', reason='reviewed_rejection',
            previous=old_match.get('rejected_url'), proposed=new_url))
        preserve = True
    elif modern and new_url and not valid:
        raise RuntimeError('production_discogs_evidence_missing')
    elif not new_url and (old_url or reviewed_rejection):
        preserve = True
        if old_url and new_match.get('status') == 'no_match':
            conflicts.append(dict(index=index, platform='discogs', reason='discogs_revalidation_required',
                previous=old_url, proposed=None))
    elif old_url and new_url and old_url != new_url:
        conflicts.append(dict(index=index, platform='discogs', previous=old_url, proposed=new_url))
    elif reviewed_rejection and new_url and not old_url:
        conflicts.append(dict(index=index, platform='discogs', reason='reviewed_discogs_replacement',
            previous=old_match.get('rejected_url'), proposed=new_url))
    if preserve:
        for key in (*DISCOGS_FIELDS, 'discogs_matching_version'):
            if key in old:
                merged[key] = deepcopy(old[key])
            else:
                merged.pop(key, None)
        if old_match:
            matches['discogs'] = deepcopy(old_match)
        else:
            matches.pop('discogs', None)
        merged['discogs_revalidation'] = deepcopy(new_match)
    elif modern:
        # URL, evidence and derived fields form one provider receipt. Empty
        # fields on a new release must not inherit another release's label.
        for key in DISCOGS_FIELDS:
            default = [] if key in ('discogs_genres', 'discogs_styles') else None
            merged[key] = deepcopy(new.get(key, default)) if valid and new_url else default
        merged['discogs_metadata_scope'] = 'release' if valid and new_url else None
        matches['discogs'] = deepcopy(new_match)
    elif new_match:
        matches['discogs'] = deepcopy(new_match)
    return merged
