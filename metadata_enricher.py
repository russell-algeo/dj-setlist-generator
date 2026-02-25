"""Enrich tracks with metadata from Spotify, YouTube, Discogs, and ReccoBeats."""

import functools
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

        self._genre_cache = {}  # artist_id -> list of genres

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
                enriched['spotify_genres'] = self._get_artist_genres(artist_id)

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
            Dict with 'url', 'album_art_url', 'preview_url', 'artist_id', or None on failure.
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

            return {
                'url': best['external_urls']['spotify'],
                'album_art_url': album_art,
                'preview_url': best.get('preview_url'),
                'artist_id': best['artists'][0]['id'] if best.get('artists') else None,
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
        if not artist_id or not self.spotify:
            return []
        if artist_id in self._genre_cache:
            return self._genre_cache[artist_id]
        try:
            artist = self.spotify.artist(artist_id)
            genres = artist.get('genres', [])[:3]
            self._genre_cache[artist_id] = genres
            return genres
        except Exception:
            return []

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

            response = _discogs_session.get(url, headers=headers, params=params)
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

            return {
                'url': discogs_url,
                'genres': genres[:3],
                'styles': styles[:5],
                'label': label,
            }
        except Exception as e:
            print(f"    [Discogs] Search error: {e}")
            return None
