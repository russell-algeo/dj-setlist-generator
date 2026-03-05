"""Enrich tracks with metadata from Spotify, YouTube, Discogs, and ReccoBeats."""

import functools
import re
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import yt_dlp
from typing import Optional
from config import Config
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# ReccoBeats API base URL (free, no API key required)
_RECCOBEATS_BASE = "https://api.reccobeats.com/v1"


def _make_discogs_session() -> requests.Session:
    """Create a requests Session with retry logic for Discogs API calls.

    Retries on 429/5xx with exponential backoff, honouring Retry-After headers.
    Mirrors the intent of JitterRetry used in track_recognizer.py.
    """
    retry = Retry(
        total=Config.MAX_RETRIES,
        backoff_factor=Config.BASE_DELAY,
        status_forcelist={429, 500, 502, 503, 504},
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


_discogs_session = _make_discogs_session()

# Spotify pitch class → note name (used by ReccoBeats key/mode mapping)
_KEY_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


from detail_explorer_common import (
    normalize_name as _normalize_name,
    is_valid_artist_image_url as _is_valid_artist_image_url,
)


def _tokenize_name(value: str) -> set[str]:
    """Tokenize an artist name into comparable lowercase tokens."""
    return set(re.findall(r"[a-z0-9]+", (value or "").lower()))


def _is_exact_artist_name_match(expected: str, candidate: str) -> bool:
    """Strict artist-name equality for profile matching across providers."""
    expected_norm = _normalize_name(expected)
    candidate_norm = _normalize_name(candidate)
    if not expected_norm or not candidate_norm:
        return False
    if expected_norm != candidate_norm:
        return False
    expected_tokens = _tokenize_name(expected)
    candidate_tokens = _tokenize_name(candidate)
    if expected_tokens and candidate_tokens and expected_tokens != candidate_tokens:
        return False
    return True




def _pick_discogs_artist_image(images: list[dict], fallback_url: str | None = None) -> str | None:
    """Pick the best Discogs artist image URL, preferring full-size images."""
    ranked = sorted(
        images or [],
        key=lambda img: (
            1 if str(img.get("type", "")).lower() == "primary" else 0,
            int(img.get("width") or 0) * int(img.get("height") or 0),
        ),
        reverse=True,
    )

    # Prefer full-size URI first.
    for img in ranked:
        url = img.get("uri")
        if _is_valid_artist_image_url(url):
            return url

    # Fall back to small URI only if no full-size URI exists.
    for img in ranked:
        url = img.get("uri150")
        if _is_valid_artist_image_url(url):
            return url

    return fallback_url if _is_valid_artist_image_url(fallback_url) else None


_GENRE_ALIAS_MAP = {
    "lo fi house": "lo-fi house",
    "italodance": "italo dance",
}
_GENRE_TOKEN_STOPWORDS = {"and", "the", "music", "style", "styles"}


def _normalize_genre_label(value: str) -> str:
    """Normalize a genre/style label for overlap matching."""
    if not value:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    if not normalized:
        return ""
    return _GENRE_ALIAS_MAP.get(normalized, normalized)


def _genre_label_set(genres: list[str] | None) -> set[str]:
    """Build a normalized set of genre/style labels."""
    return {n for g in (genres or []) if (n := _normalize_genre_label(g))}


def _genre_token_set(genres: list[str] | None) -> set[str]:
    """Build a normalized token set from genre/style labels."""
    tokens: set[str] = set()
    for label in _genre_label_set(genres):
        for token in label.split():
            if len(token) >= 3 and token not in _GENRE_TOKEN_STOPWORDS:
                tokens.add(token)
    return tokens


def _genre_overlap(expected_genres: list[str], provider_genres: list[str]) -> tuple[float, int, int]:
    """Compute overlap score and shared counts between expected and provider genres."""
    expected_labels = _genre_label_set(expected_genres)
    provider_labels = _genre_label_set(provider_genres)
    expected_tokens = _genre_token_set(expected_genres)
    provider_tokens = _genre_token_set(provider_genres)

    if not expected_labels or not provider_labels:
        return 0.0, 0, 0

    shared_labels = expected_labels & provider_labels
    shared_tokens = expected_tokens & provider_tokens
    label_overlap = len(shared_labels) / max(1, min(len(expected_labels), len(provider_labels)))
    token_overlap = 0.0
    if expected_tokens and provider_tokens:
        token_overlap = len(shared_tokens) / max(1, min(len(expected_tokens), len(provider_tokens)))

    return round(max(label_overlap, token_overlap), 3), len(shared_labels), len(shared_tokens)


def _is_genre_confident_match(
    expected_genres: list[str],
    provider_genres: list[str],
    min_overlap: float,
) -> tuple[bool, float, str, int, int]:
    """Return confidence decision for a provider profile using genre overlap."""
    if not expected_genres:
        return False, 0.0, "no_expected_genres", 0, 0
    if not provider_genres:
        return False, 0.0, "no_provider_genres", 0, 0

    overlap, shared_labels, shared_tokens = _genre_overlap(expected_genres, provider_genres)
    if overlap >= min_overlap and (shared_labels > 0 or shared_tokens > 0):
        return True, overlap, "genre_overlap_ok", shared_labels, shared_tokens
    return False, overlap, "genre_overlap_too_low", shared_labels, shared_tokens


def _platform_search(platform_name: str):
    """Decorator that wraps a search method with standard error handling."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(self, title: str, artist: str) -> Optional[str]:
            try:
                return fn(self, title, artist)
            except Exception as e:
                print(f"    [{platform_name}] Search error: {e}")
                return None
        return wrapper
    return decorator


class MetadataEnricher:
    """Fetch metadata from various platforms."""

    def __init__(self):
        self.spotify_enabled = Config.ENABLE_SPOTIFY
        self.youtube_enabled = Config.ENABLE_YOUTUBE
        self.discogs_enabled = Config.ENABLE_DISCOGS

        # Initialize Spotify client if enabled
        self.spotify = None
        if self.spotify_enabled:
            try:
                self.spotify = spotipy.Spotify(
                    client_credentials_manager=SpotifyClientCredentials(
                        client_id=Config.SPOTIFY_CLIENT_ID,
                        client_secret=Config.SPOTIFY_CLIENT_SECRET
                    )
                )
                print("✓ Spotify enrichment enabled")
            except Exception as e:
                print(f"✗ Spotify enrichment disabled: {e}")
                self.spotify_enabled = False

        if self.youtube_enabled:
            print("✓ YouTube enrichment enabled (using yt-dlp)")

        if self.discogs_enabled:
            print("✓ Discogs enrichment enabled")

        if not any([self.spotify_enabled, self.youtube_enabled, self.discogs_enabled]):
            print("⚠ No enrichment services enabled")

        # artist_id -> {'genres': [...], 'image_url': str|None, 'url': str|None, 'name': str|None}
        self._artist_cache = {}
        # normalized artist name -> set-level profile metadata
        self._set_artist_profile_cache = {}

    @staticmethod
    def infer_genre_profile(track_metadata: list[dict], limit: int = 20) -> list[str]:
        """Infer an artist's genre profile from enriched track metadata."""
        counts: dict[str, int] = {}
        for meta in track_metadata or []:
            genre_values = (
                (meta.get("discogs_styles") or [])
                + (meta.get("discogs_genres") or [])
                + (meta.get("spotify_genres") or [])
            )
            for raw in genre_values:
                label = _normalize_genre_label(raw)
                if not label:
                    continue
                counts[label] = counts.get(label, 0) + 1

        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        return [name for name, _ in ranked[:limit]]

    def enrich_track(self, track) -> dict:
        """
        Enrich a single track with metadata.

        Args:
            track: Track object

        Returns:
            Dictionary with platform links and rich metadata
        """
        enriched = {
            'spotify_url': None,
            'spotify_album_art': None,
            'spotify_preview_url': None,
            'spotify_artist_id': None,
            'spotify_artist_name': None,
            'spotify_artist_url': None,
            'spotify_artist_profile_image': None,
            'spotify_artist_image': None,
            'spotify_genres': [],
            'bpm': None,
            'key': None,
            'energy': None,
            'danceability': None,
            'youtube_url': None,
            'discogs_url': None,
            'discogs_genres': [],
            'discogs_styles': [],
            'discogs_label': None,
            'discogs_label_url': None,
        }

        # Skip unknown tracks
        if track.title == "Unknown Track":
            return enriched

        # Spotify
        if self.spotify_enabled:
            spotify_data = self._search_spotify_rich(track.title, track.artist)
            if spotify_data:
                enriched['spotify_url'] = spotify_data['url']
                enriched['spotify_album_art'] = spotify_data.get('album_art_url')
                enriched['spotify_preview_url'] = spotify_data.get('preview_url')
                artist_id = spotify_data.get('artist_id')
                enriched['spotify_artist_id'] = artist_id
                enriched['spotify_artist_name'] = spotify_data.get('artist_name')
                enriched['spotify_artist_url'] = spotify_data.get('artist_url')
                profile = self._get_artist_profile(artist_id)
                enriched['spotify_genres'] = profile.get('genres', [])
                profile_image_url = profile.get('image_url')
                enriched['spotify_artist_profile_image'] = profile_image_url
                # Backward-compatible alias used by older summaries/renderers.
                enriched['spotify_artist_image'] = profile_image_url

        # YouTube
        if self.youtube_enabled:
            enriched['youtube_url'] = self._search_youtube(track.title, track.artist)

        # Discogs (rich: URL + genres + styles + label)
        if self.discogs_enabled:
            discogs_data = self._search_discogs_rich(track.title, track.artist)
            if discogs_data:
                enriched['discogs_url'] = discogs_data['url']
                enriched['discogs_genres'] = discogs_data.get('genres', [])
                enriched['discogs_styles'] = discogs_data.get('styles', [])
                enriched['discogs_label'] = discogs_data.get('label')
                enriched['discogs_label_url'] = discogs_data.get('label_url')

        return enriched

    def enrich_all_tracks(self, tracks: list) -> list[dict]:
        """
        Enrich all tracks with metadata.

        Args:
            tracks: List of Track objects

        Returns:
            List of enriched track dictionaries
        """
        enriched_tracks = []

        print(f"\nEnriching {len(tracks)} tracks...")

        for i, track in enumerate(tracks, 1):
            metadata = self.enrich_track(track)

            enriched_tracks.append({
                'track': track,
                'metadata': metadata
            })

            print(f"  [{i}/{len(tracks)}] {track.artist} - {track.title}")

        # Batch fetch audio features from ReccoBeats (BPM, key, energy, danceability)
        self._batch_fetch_reccobeats(enriched_tracks)

        print("Enrichment complete")
        return enriched_tracks

    def enrich_set_artist_profile(
        self,
        artist_name: str,
        expected_genres: list[str] | None = None,
    ) -> dict:
        """Fetch DJ/set artist profile metadata for persistent set-level storage.

        Prefers Spotify artist profile matches, then falls back to Discogs.
        """
        normalized = _normalize_name(artist_name)
        expected_genres = expected_genres or []
        min_overlap = Config.ARTIST_IMAGE_MIN_GENRE_OVERLAP
        if not normalized:
            return {
                "artist_name": artist_name,
                "artist_profile_name": None,
                "artist_profile_image": None,
                "artist_profile_url": None,
                "artist_profile_source": None,
                "artist_profile_confidence": None,
                "artist_profile_genre_overlap": None,
                "artist_profile_expected_genres": expected_genres,
                "artist_profile_provider_genres": [],
                "artist_profile_rejected_reason": "invalid_artist_name",
                "spotify_artist_profile_name": None,
                "spotify_artist_profile_image": None,
                "spotify_artist_profile_url": None,
                "spotify_artist_profile_genres": [],
                "discogs_artist_profile_name": None,
                "discogs_artist_profile_image": None,
                "discogs_artist_profile_url": None,
                "discogs_artist_profile_genres": [],
            }

        profile = {
            "artist_name": artist_name,
            "artist_profile_name": None,
            "artist_profile_image": None,
            "artist_profile_url": None,
            "artist_profile_source": None,
            "artist_profile_confidence": None,
            "artist_profile_genre_overlap": None,
            "artist_profile_expected_genres": expected_genres,
            "artist_profile_provider_genres": [],
            "artist_profile_rejected_reason": None,
            "spotify_artist_profile_name": None,
            "spotify_artist_profile_image": None,
            "spotify_artist_profile_url": None,
            "spotify_artist_profile_genres": [],
            "discogs_artist_profile_name": None,
            "discogs_artist_profile_image": None,
            "discogs_artist_profile_url": None,
            "discogs_artist_profile_genres": [],
        }

        if normalized in self._set_artist_profile_cache:
            cached = dict(self._set_artist_profile_cache[normalized])
            cached["artist_profile_expected_genres"] = expected_genres
            if not cached.get("artist_profile_image") or not cached.get("artist_profile_source"):
                return cached
            if cached.get("artist_profile_provider_genres"):
                confident, overlap, reason, _, _ = _is_genre_confident_match(
                    expected_genres,
                    cached["artist_profile_provider_genres"],
                    min_overlap=min_overlap,
                )
                if confident and cached.get("artist_profile_image"):
                    cached["artist_profile_confidence"] = overlap
                    cached["artist_profile_genre_overlap"] = overlap
                    cached["artist_profile_rejected_reason"] = None
                    return cached
            cached["artist_profile_name"] = None
            cached["artist_profile_image"] = None
            cached["artist_profile_url"] = None
            cached["artist_profile_source"] = None
            cached["artist_profile_confidence"] = 0.0
            cached["artist_profile_genre_overlap"] = 0.0
            cached["artist_profile_rejected_reason"] = "cache_genre_validation_failed"
            return cached

        spotify_profile = self._search_spotify_artist_profile(artist_name)
        if spotify_profile:
            profile["spotify_artist_profile_name"] = spotify_profile.get("name")
            profile["spotify_artist_profile_url"] = spotify_profile.get("url")
            profile["spotify_artist_profile_genres"] = spotify_profile.get("genres", [])
            spotify_image_url = spotify_profile.get("image_url")
            if spotify_image_url:
                confident, overlap, reason, _, _ = _is_genre_confident_match(
                    expected_genres,
                    profile["spotify_artist_profile_genres"],
                    min_overlap=min_overlap,
                )
                if confident:
                    profile["spotify_artist_profile_image"] = spotify_image_url
                    profile["artist_profile_confidence"] = overlap
                    profile["artist_profile_genre_overlap"] = overlap
                    profile["artist_profile_provider_genres"] = profile["spotify_artist_profile_genres"]
                    profile["artist_profile_rejected_reason"] = None
                    profile["artist_profile_name"] = spotify_profile.get("name")
                    profile["artist_profile_image"] = spotify_image_url
                    profile["artist_profile_url"] = spotify_profile.get("url")
                    profile["artist_profile_source"] = "spotify"
                else:
                    profile["spotify_artist_profile_image"] = None
                    profile["artist_profile_rejected_reason"] = f"spotify_{reason}"

        if not profile["artist_profile_image"]:
            discogs_profile = self._search_discogs_artist_profile(artist_name)
            if discogs_profile:
                profile["discogs_artist_profile_name"] = discogs_profile.get("name")
                profile["discogs_artist_profile_url"] = discogs_profile.get("url")
                profile["discogs_artist_profile_genres"] = discogs_profile.get("genres", [])
                discogs_image_url = discogs_profile.get("image_url")
                if discogs_image_url:
                    confident, overlap, reason, _, _ = _is_genre_confident_match(
                        expected_genres,
                        profile["discogs_artist_profile_genres"],
                        min_overlap=min_overlap,
                    )
                    if confident:
                        profile["discogs_artist_profile_image"] = discogs_image_url
                        profile["artist_profile_confidence"] = overlap
                        profile["artist_profile_genre_overlap"] = overlap
                        profile["artist_profile_provider_genres"] = profile["discogs_artist_profile_genres"]
                        profile["artist_profile_rejected_reason"] = None
                        profile["artist_profile_name"] = discogs_profile.get("name")
                        profile["artist_profile_image"] = discogs_image_url
                        profile["artist_profile_url"] = discogs_profile.get("url")
                        profile["artist_profile_source"] = "discogs"
                    else:
                        profile["discogs_artist_profile_image"] = None
                        profile["artist_profile_rejected_reason"] = (
                            profile.get("artist_profile_rejected_reason") or f"discogs_{reason}"
                        )

        self._set_artist_profile_cache[normalized] = dict(profile)
        return profile

    def _batch_fetch_reccobeats(self, enriched_tracks: list) -> None:
        """Batch fetch audio features from ReccoBeats using Spotify track IDs.

        Populates bpm, key, energy, and danceability in each track's metadata.
        """
        track_ids = []
        for item in enriched_tracks:
            url = item['metadata'].get('spotify_url')
            if url:
                tid = url.split('/')[-1].split('?')[0]
                track_ids.append(tid)
            else:
                track_ids.append(None)

        valid_ids = [tid for tid in track_ids if tid]
        if not valid_ids:
            return

        print(f"\n  Fetching audio features from ReccoBeats for {len(valid_ids)} tracks...")
        all_features = {}  # track_id -> features dict
        batch_size = 50
        for i in range(0, len(valid_ids), batch_size):
            batch = valid_ids[i:i + batch_size]
            try:
                ids_param = ",".join(batch)
                resp = requests.get(
                    f"{_RECCOBEATS_BASE}/audio-features",
                    params={"ids": ids_param},
                    timeout=15,
                )
                if resp.status_code == 429:
                    print("    [ReccoBeats] Rate limited, waiting 2s...")
                    time.sleep(2)
                    resp = requests.get(
                        f"{_RECCOBEATS_BASE}/audio-features",
                        params={"ids": ids_param},
                        timeout=15,
                    )
                resp.raise_for_status()
                data = resp.json()
                features_list = data.get("content", data if isinstance(data, list) else [])
                for feat in features_list:
                    if feat and isinstance(feat, dict):
                        # ReccoBeats returns a UUID as "id"; Spotify track ID is in "href"
                        href = feat.get("href", "")
                        fid = href.split("/")[-1].split("?")[0] if href else None
                        if fid:
                            all_features[fid] = feat
                        elif len(batch) == 1:
                            all_features[batch[0]] = feat
            except Exception as e:
                print(f"    [ReccoBeats] Batch fetch error: {e}")
            if i + batch_size < len(valid_ids):
                time.sleep(0.5)

        # Apply features to enriched tracks
        applied = 0
        for item, tid in zip(enriched_tracks, track_ids):
            if not tid or tid not in all_features:
                continue
            feat = all_features[tid]
            meta = item['metadata']

            # BPM
            tempo = feat.get('tempo')
            if tempo:
                meta['bpm'] = round(float(tempo), 1)

            # Key (integer 0-11 pitch class + mode 0/1)
            key_idx = feat.get('key')
            mode = feat.get('mode')
            if key_idx is not None and int(key_idx) >= 0:
                key_str = _KEY_NAMES[int(key_idx)]
                if mode is not None and int(mode) == 0:
                    key_str += 'm'
                meta['key'] = key_str

            # Energy and danceability
            if feat.get('energy') is not None:
                meta['energy'] = round(float(feat['energy']), 3)
            if feat.get('danceability') is not None:
                meta['danceability'] = round(float(feat['danceability']), 3)

            applied += 1

        if applied:
            print(f"    [ReccoBeats] Applied audio features to {applied} tracks")
        else:
            print("    [ReccoBeats] No audio features returned")

    @_platform_search("Spotify")
    def _search_spotify(self, title: str, artist: str) -> Optional[str]:
        """Search Spotify for track URL (delegates to _search_spotify_rich)."""
        result = self._search_spotify_rich(title, artist)
        return result['url'] if result else None

    def _search_spotify_rich(self, title: str, artist: str) -> Optional[dict]:
        """Search Spotify and return rich metadata dict with album art, preview URL, and artist ID.

        Returns:
            Dict with track URL, album art, preview, and primary artist identity fields.
        """
        if not self.spotify:
            return None

        try:
            query = f"{artist} - {title}"
            results = self.spotify.search(q=query, type='track', limit=5)

            if not results or not results['tracks']['items']:
                print(f"[Spotify] No results found for query: {query}")
                return None

            # Score all results by number of matching words
            expected_artist_words = set(w for w in artist.lower().split() if len(w) > 2)
            expected_title_words = set(w for w in title.lower().split() if len(w) > 2)

            scored_results = []
            for item in results['tracks']['items']:
                observed_artist = item['artists'][0]['name']
                observed_title = item['name']

                observed_artist_words = set(w for w in observed_artist.lower().split() if len(w) > 2)
                observed_title_words = set(w for w in observed_title.lower().split() if len(w) > 2)

                artist_matches = len(expected_artist_words & observed_artist_words)
                title_matches = len(expected_title_words & observed_title_words)

                if artist_matches > 0 and title_matches > 0:
                    total_matches = artist_matches + title_matches
                    scored_results.append((total_matches, item))

            if not scored_results:
                print(f"[Spotify] ✗ No artist+title match for query: '{query}', skipping")
                return None

            scored_results.sort(key=lambda x: x[0], reverse=True)
            best = scored_results[0][1]

            album_images = best.get('album', {}).get('images', [])
            album_art = next(
                (img['url'] for img in album_images if img.get('height') == 300),
                album_images[0]['url'] if album_images else None
            )

            primary_artist = (best.get('artists') or [{}])[0]
            return {
                'url': best['external_urls']['spotify'],
                'album_art_url': album_art,
                'preview_url': best.get('preview_url'),
                'artist_id': primary_artist.get('id'),
                'artist_name': primary_artist.get('name'),
                'artist_url': (primary_artist.get('external_urls') or {}).get('spotify'),
            }
        except Exception as e:
            print(f"    [Spotify] Search error: {e}")
            return None

    def _get_artist_genres(self, artist_id: str) -> list:
        """Fetch genre tags for a Spotify artist, with caching to avoid redundant API calls.

        Args:
            artist_id: Spotify artist ID

        Returns:
            List of up to 3 genre strings, or empty list on failure.
        """
        return self._get_artist_profile(artist_id).get('genres', [])

    def _get_artist_profile(self, artist_id: str) -> dict:
        """Fetch Spotify artist profile fields used by the UI, with caching."""
        if not artist_id or not self.spotify:
            return {'genres': [], 'image_url': None, 'url': None, 'name': None}
        if artist_id in self._artist_cache:
            return self._artist_cache[artist_id]
        try:
            artist = self.spotify.artist(artist_id)
            images = artist.get('images', [])
            image_url = next(
                (img.get('url') for img in images if img.get('height') == 320),
                images[0].get('url') if images else None,
            )
            profile = {
                'genres': artist.get('genres', [])[:3],
                'image_url': image_url,
                'url': (artist.get('external_urls') or {}).get('spotify'),
                'name': artist.get('name'),
            }
            self._artist_cache[artist_id] = profile
            return profile
        except Exception:
            return {'genres': [], 'image_url': None, 'url': None, 'name': None}

    def _search_spotify_artist_profile(self, artist_name: str) -> Optional[dict]:
        """Search Spotify artist profiles and return a best-match profile dict."""
        if not self.spotify:
            return None
        if not _normalize_name(artist_name):
            return None
        try:
            queries = [f"artist:{artist_name}", f"\"{artist_name}\"", artist_name]
            items_by_id: dict[str, dict] = {}
            for query in queries:
                results = self.spotify.search(q=query, type="artist", limit=50)
                for item in results.get("artists", {}).get("items", []) or []:
                    artist_id = item.get("id")
                    if artist_id and artist_id not in items_by_id:
                        items_by_id[artist_id] = item

            items = list(items_by_id.values())
            if not items:
                return None

            exact_items = [
                item for item in items
                if _is_exact_artist_name_match(artist_name, item.get("name", ""))
            ]
            if not exact_items:
                return None

            def score(item: dict) -> tuple[int, int]:
                images = item.get("images", [])
                image_url = next(
                    (img.get("url") for img in images if img.get("height") == 320),
                    images[0].get("url") if images else None,
                )
                has_image = 1 if _is_valid_artist_image_url(image_url) else 0
                popularity = int(item.get("popularity", 0) or 0)
                return (has_image, popularity)

            best = sorted(exact_items, key=score, reverse=True)[0]
            best_artist_id = best.get("id")

            images = best.get("images", [])
            image_url = next(
                (img.get("url") for img in images if img.get("height") == 320),
                images[0].get("url") if images else None,
            )
            image_url = image_url if _is_valid_artist_image_url(image_url) else None
            genres = list(best.get("genres") or [])
            if not genres and best_artist_id:
                genres = self._get_artist_genres(best_artist_id)
            return {
                "id": best_artist_id,
                "name": best.get("name"),
                "url": (best.get("external_urls") or {}).get("spotify"),
                "image_url": image_url,
                "genres": genres[:12],
            }
        except Exception:
            return None

    def _search_discogs_artist_profile(self, artist_name: str) -> Optional[dict]:
        """Search Discogs artist profiles and return a best-match profile dict."""
        if Config.DISCOGS_TOKEN:
            auth_header = f'Discogs token={Config.DISCOGS_TOKEN}'
        elif Config.DISCOGS_CONSUMER_KEY and Config.DISCOGS_CONSUMER_SECRET:
            auth_header = f'Discogs key={Config.DISCOGS_CONSUMER_KEY}, secret={Config.DISCOGS_CONSUMER_SECRET}'
        else:
            return None

        if not _normalize_name(artist_name):
            return None

        headers = {'Authorization': auth_header}
        search_url = "https://api.discogs.com/database/search"
        try:
            response = _discogs_session.get(
                search_url,
                headers=headers,
                params={"q": artist_name, "type": "artist", "per_page": 5},
                timeout=10,
            )
            response.raise_for_status()
            results = response.json().get("results", []) or []
            if not results:
                return None

            def score(result: dict) -> tuple[int, int]:
                title = (result.get("title") or "").strip()
                exact = 1 if _is_exact_artist_name_match(artist_name, title) else 0
                overlap = len(_tokenize_name(artist_name) & _tokenize_name(title))
                return (exact, overlap)

            best = sorted(results, key=score, reverse=True)[0]
            title = (best.get("title") or "").strip()
            # Guard against weak matches; set-level artist profile should be strict.
            if not _is_exact_artist_name_match(artist_name, title):
                return None

            artist_id = best.get("id")
            profile_name = title or artist_name
            profile_url = f"https://www.discogs.com/artist/{artist_id}" if artist_id else None
            image_url = best.get("cover_image") or best.get("thumb")
            profile_genres: list[str] = []

            if artist_id:
                try:
                    artist_resp = _discogs_session.get(
                        f"https://api.discogs.com/artists/{artist_id}",
                        headers=headers,
                        timeout=10,
                    )
                    artist_resp.raise_for_status()
                    artist_data = artist_resp.json()
                    images = artist_data.get("images", []) or []
                    image_url = _pick_discogs_artist_image(images, fallback_url=image_url)
                    if artist_data.get("name"):
                        profile_name = artist_data["name"]
                    uri = artist_data.get("uri")
                    if uri:
                        profile_url = (
                            f"https://www.discogs.com{uri}" if str(uri).startswith("/") else str(uri)
                        )
                except Exception:
                    pass

                # Pull release-level genre/style tags for confidence validation.
                try:
                    genre_resp = _discogs_session.get(
                        search_url,
                        headers=headers,
                        params={"artist": profile_name, "type": "release", "per_page": 50},
                        timeout=10,
                    )
                    genre_resp.raise_for_status()
                    genre_results = genre_resp.json().get("results", []) or []
                    genre_counts: dict[str, int] = {}
                    for result in genre_results:
                        raw_values = (result.get("styles") or []) + (result.get("genres") or [])
                        for raw in raw_values:
                            label = _normalize_genre_label(raw)
                            if not label:
                                continue
                            genre_counts[label] = genre_counts.get(label, 0) + 1
                    ranked = sorted(genre_counts.items(), key=lambda item: item[1], reverse=True)
                    profile_genres = [name for name, _ in ranked[:12]]
                except Exception:
                    profile_genres = []

            image_url = image_url if _is_valid_artist_image_url(image_url) else None
            return {
                "name": profile_name,
                "url": profile_url,
                "image_url": image_url,
                "genres": profile_genres,
            }
        except Exception:
            return None

    @_platform_search("YouTube")
    def _search_youtube(self, title: str, artist: str) -> Optional[str]:
        """Search YouTube using yt-dlp (no API key needed)."""
        query = f"{artist} {title}".strip()

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'default_search': 'ytsearch1',
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch1:{query}", download=False)

            if result and 'entries' in result and result['entries']:
                video_id = result['entries'][0]['id']
                return f"https://www.youtube.com/watch?v={video_id}"

        return None

    @_platform_search("Discogs")
    def _search_discogs(self, title: str, artist: str) -> Optional[str]:
        """Search Discogs for track URL (delegates to _search_discogs_rich)."""
        result = self._search_discogs_rich(title, artist)
        return result['url'] if result else None

    def _search_discogs_rich(self, title: str, artist: str) -> Optional[dict]:
        """Search Discogs and return rich metadata dict with URL, genres, styles, and label.

        Returns:
            Dict with 'url', 'genres', 'styles', 'label', or None on failure.
        """
        if Config.DISCOGS_TOKEN:
            auth_header = f'Discogs token={Config.DISCOGS_TOKEN}'
        elif Config.DISCOGS_CONSUMER_KEY and Config.DISCOGS_CONSUMER_SECRET:
            auth_header = f'Discogs key={Config.DISCOGS_CONSUMER_KEY}, secret={Config.DISCOGS_CONSUMER_SECRET}'
        else:
            return None

        try:
            query = f"{artist} {title}"
            url = "https://api.discogs.com/database/search"

            headers = {
                'Authorization': auth_header
            }

            params = {
                'q': query,
                'type': 'release',
                'per_page': 1
            }

            response = _discogs_session.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if not data.get('results'):
                return None

            result = data['results'][0]

            # Build full Discogs URL from the URI path
            uri = result.get('uri', '')
            discogs_url = f"https://www.discogs.com{uri}" if uri and not uri.startswith('http') else uri

            # Extract genres, styles, and label from search result
            genres = result.get('genre', result.get('genres', []))
            styles = result.get('style', result.get('styles', []))
            labels = result.get('label', [])
            label = labels[0] if labels else None

            # Fetch label ID for a direct Discogs label profile URL.
            # Strategy 1: fetch the full release via resource_url — labels array contains IDs.
            # Strategy 2 (fallback): search by label name when the release endpoint fails or
            #   returns no labels (e.g. some compilations omit the labels array).
            label_url = None
            resource_url = result.get('resource_url', '')
            if resource_url and label:
                try:
                    rel_resp = _discogs_session.get(resource_url, headers=headers, timeout=10)
                    rel_resp.raise_for_status()
                    rel_data = rel_resp.json()
                    rel_labels = rel_data.get('labels', [])
                    if rel_labels:
                        label_id = rel_labels[0].get('id')
                        if label_id:
                            label_url = f"https://www.discogs.com/label/{label_id}"
                except Exception as e:
                    print(f"    [Discogs] Release fetch error (label URL): {e}")

            # Fallback: search for the label by name to get its ID
            if label and not label_url:
                try:
                    lb_resp = _discogs_session.get(
                        url, headers=headers,
                        params={'q': label, 'type': 'label', 'per_page': 1},
                        timeout=10,
                    )
                    lb_resp.raise_for_status()
                    lb_results = lb_resp.json().get('results', [])
                    if lb_results:
                        label_id = lb_results[0].get('id')
                        if label_id:
                            label_url = f"https://www.discogs.com/label/{label_id}"
                except Exception as e:
                    print(f"    [Discogs] Label search error: {e}")

            return {
                'url': discogs_url,
                'genres': genres[:3],
                'styles': styles[:5],
                'label': label,
                'label_url': label_url,
            }
        except Exception as e:
            print(f"    [Discogs] Search error: {e}")
            return None
