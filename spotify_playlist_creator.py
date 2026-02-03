"""Create Spotify playlists from setlists."""

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from typing import List, Optional
from config import Config


class SpotifyPlaylistCreator:
    """Create and populate Spotify playlists."""

    def __init__(self):
        """Initialize playlist creator with user authentication."""
        self.spotify = None
        self.user_id = None

        if not Config.ENABLE_SPOTIFY_PLAYLISTS:
            return

        try:
            # Initialize OAuth with user permissions
            scope = "playlist-modify-public playlist-modify-private"
            self.spotify = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=Config.SPOTIFY_CLIENT_ID,
                client_secret=Config.SPOTIFY_CLIENT_SECRET,
                redirect_uri=Config.SPOTIFY_REDIRECT_URI,
                scope=scope,
                cache_path=".spotify_cache"
            ))

            # Get current user ID
            user_info = self.spotify.me()
            self.user_id = user_info['id']

        except Exception as e:
            print(f"Failed to initialize Spotify playlist creator: {e}")
            self.spotify = None

    def create_playlist_from_setlist(
        self,
        enriched_tracks: List[dict],
        mix_info: dict,
        playlist_name: str = None
    ) -> Optional[dict]:
        """
        Create Spotify playlist from setlist.

        Args:
            enriched_tracks: List of enriched track dictionaries
            mix_info: Mix metadata
            playlist_name: Custom playlist name (defaults to mix title)

        Returns:
            Dictionary with playlist URL and stats, or None if failed
        """
        if not self.spotify:
            print("Spotify playlist creation not available")
            return None

        # Filter tracks with valid Spotify URLs
        valid_tracks = self._filter_tracks_with_spotify_urls(enriched_tracks)

        if not valid_tracks:
            print("No tracks with Spotify URLs found - cannot create playlist")
            return None

        # Create playlist
        title = playlist_name or mix_info.get('title', 'DJ Set Playlist')
        description = self._generate_description(mix_info, len(valid_tracks), len(enriched_tracks))
        # Replace newlines with pipes to avoid API encoding issues
        clean_description = description.replace('\n', ' | ')

        try:
            # Create playlist with all details in one call
            playlist = self.spotify.user_playlist_create(
                self.user_id,
                title,
                public=False,
                description=clean_description
            )

            print(f"\nCreated playlist: {title}")
            print(f"Playlist ID: {playlist['id']}")

            # Add tracks in batches (Spotify API limit: 100 tracks per request)
            track_uris = [self._url_to_uri(track['metadata']['spotify_url'])
                         for track in valid_tracks]

            added_count = 0
            failed_tracks = []

            for i in range(0, len(track_uris), 100):
                batch = track_uris[i:i+100]
                try:
                    self.spotify.playlist_add_items(playlist['id'], batch)
                    added_count += len(batch)
                    print(f"  Added {len(batch)} tracks ({added_count}/{len(track_uris)})")
                except Exception as e:
                    print(f"  Failed to add batch: {e}")
                    failed_tracks.extend(batch)

            # Return results
            return {
                'playlist_url': playlist['external_urls']['spotify'],
                'playlist_id': playlist['id'],
                'total_tracks_in_setlist': len(enriched_tracks),
                'tracks_with_spotify_urls': len(valid_tracks),
                'tracks_added': added_count,
                'tracks_failed': len(failed_tracks)
            }

        except Exception as e:
            print(f"Failed to create playlist: {e}")
            return None

    def _filter_tracks_with_spotify_urls(self, enriched_tracks: List[dict]) -> List[dict]:
        """Filter tracks that have valid Spotify URLs."""
        return [
            track for track in enriched_tracks
            if track['metadata'].get('spotify_url')
            and track['track'].title != "Unknown Track"
        ]

    def _url_to_uri(self, spotify_url: str) -> str:
        """
        Convert Spotify URL to URI.

        Example:
            https://open.spotify.com/track/7a5BhcKkPKTRcIF5i6QeUa
            -> spotify:track:7a5BhcKkPKTRcIF5i6QeUa
        """
        # Extract track ID from URL
        track_id = spotify_url.split('/')[-1].split('?')[0]
        return f"spotify:track:{track_id}"

    def _generate_description(self, mix_info: dict, valid_count: int, total_count: int) -> str:
        """Generate playlist description."""
        uploader = mix_info.get('uploader', 'Unknown')
        url = mix_info.get('url', '')

        description = f"Generated from: {uploader} DJ set\n"
        description += f"{valid_count}/{total_count} tracks identified"
        if url:
            description += f"\nSet link: {url}"

        return description
