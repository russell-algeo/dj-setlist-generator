"""Enrich tracks with metadata from Spotify, YouTube, and Discogs."""

import requests
import yt_dlp
from typing import Optional
from config import Config
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials


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
    
    def enrich_track(self, track) -> dict:
        """
        Enrich a single track with metadata.
        
        Args:
            track: Track object
        
        Returns:
            Dictionary with platform links
        """
        enriched = {
            'spotify_url': None,
            'youtube_url': None,
            'discogs_url': None,
        }
        
        # Skip unknown tracks
        if track.title == "Unknown Track":
            return enriched
        
        # Spotify
        if self.spotify_enabled:
            enriched['spotify_url'] = self._search_spotify(track.title, track.artist)
        
        # YouTube
        if self.youtube_enabled:
            enriched['youtube_url'] = self._search_youtube(track.title, track.artist)
        
        # Discogs
        if self.discogs_enabled:
            enriched['discogs_url'] = self._search_discogs(track.title, track.artist)
        
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
        
        print("Enrichment complete")
        return enriched_tracks
    
    def _search_spotify(self, title: str, artist: str) -> Optional[str]:
        """Search Spotify for track with logging and validation."""
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
                observed_url = item['external_urls']['spotify']

                # Count matching words for artist and title
                observed_artist_words = set(w for w in observed_artist.lower().split() if len(w) > 2)
                observed_title_words = set(w for w in observed_title.lower().split() if len(w) > 2)

                artist_matches = len(expected_artist_words & observed_artist_words)
                title_matches = len(expected_title_words & observed_title_words)

                # Only consider if both artist and title have at least one match
                if artist_matches > 0 and title_matches > 0:
                    total_matches = artist_matches + title_matches
                    scored_results.append((total_matches, observed_url, observed_artist, observed_title))

            if scored_results:
                # Sort by match count (descending) and return best match
                scored_results.sort(key=lambda x: x[0], reverse=True)
                best_match = scored_results[0]
                return best_match[1]  # Return URL of best match

            # No match found
            print(f"[Spotify] ✗ No artist+title match for query: '{query}', skipping")
            return None

        except Exception as e:
            print(f"[Spotify] Error: {e}")

        return None
    
    def _search_youtube(self, title: str, artist: str) -> Optional[str]:
        """Search YouTube using yt-dlp (no API key needed)."""
        try:
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
        
        except Exception as e:
            print(f"    YouTube search error: {e}")
        
        return None
    
    def _search_discogs(self, title: str, artist: str) -> Optional[str]:
        """Search Discogs for track."""
        if not Config.DISCOGS_TOKEN:
            return None
        
        try:
            query = f"{artist} {title}"
            url = "https://api.discogs.com/database/search"
            
            headers = {
                'Authorization': f'Discogs token={Config.DISCOGS_TOKEN}'
            }
            
            params = {
                'q': query,
                'type': 'release',
                'per_page': 1
            }
            
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get('results'):
                return data['results'][0]['uri']
        
        except Exception as e:
            print(f"    Discogs search error: {e}")
        
        return None