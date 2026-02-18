"""Format setlist output as JSON and Markdown."""

import json
from collections import Counter
from pathlib import Path
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, parse_qs
from config import Config
from setlist_builder import CONFIDENCE_ICONS


def format_time(seconds: float) -> str:
    """Convert seconds to MM:SS format."""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


def make_source_url(source_url: str, timestamp_seconds: float) -> Optional[str]:
    """Generate a platform deep-link to a specific timestamp.

    Supports YouTube (youtube.com/watch and youtu.be short links).
    Returns None for SoundCloud and other platforms — no reliable
    timestamp anchor format exists for them.

    Args:
        source_url: The original mix URL stored in mix_info['url'].
        timestamp_seconds: Seconds from the start of the video.
                           Derived from segment_index * step, so it maps
                           1-to-1 to video time with no additional offset.

    Returns:
        Deep-link URL string, or None if the platform isn't supported.
    """
    if not source_url:
        return None

    try:
        parsed = urlparse(source_url)
    except Exception:
        return None

    host = parsed.netloc.lower()
    # Normalise: strip www. and m. prefixes
    host = host.removeprefix('www.').removeprefix('m.')

    t = int(timestamp_seconds)

    if host == 'youtube.com':
        params = parse_qs(parsed.query)
        video_id = params.get('v', [None])[0]
        if not video_id:
            return None
        return f"https://www.youtube.com/watch?v={video_id}&t={t}"

    if host == 'youtu.be':
        video_id = parsed.path.lstrip('/')
        if not video_id:
            return None
        return f"https://www.youtube.com/watch?v={video_id}&t={t}"

    # SoundCloud and everything else: not supported
    return None


class OutputFormatter:
    """Format and save setlist output."""

    def __init__(self, checkpoint_manager=None):
        """
        Initialize formatter.

        Args:
            checkpoint_manager: CheckpointManager instance. If None, falls back to Config.OUTPUT_DIR.
        """
        self.output_dir = checkpoint_manager.output_dir if checkpoint_manager else Config.OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _count_by_confidence(enriched_tracks: list) -> Counter:
        """Count tracks by confidence level."""
        return Counter(item['track'].confidence for item in enriched_tracks)

    def _build_metadata(self, enriched_tracks: list) -> dict:
        """Build metadata summary dict with confidence counts."""
        counts = self._count_by_confidence(enriched_tracks)
        return {
            'generated_at': datetime.now().isoformat(),
            'total_tracks': len(enriched_tracks),
            'high_confidence_tracks': counts.get('HIGH', 0),
            'medium_confidence_tracks': counts.get('MEDIUM', 0),
            'low_confidence_tracks': counts.get('LOW', 0),
            'uncertain_tracks': counts.get('UNCERTAIN', 0),
        }

    def save_json(self, enriched_tracks: list, mix_info: dict, filename: str = None) -> Path:
        """Save setlist as JSON."""
        if not filename:
            filename = f"setlist_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        output_path = self.output_dir / f"{filename}.json"
        
        source_url = mix_info.get('url', '')
        output_data = {
            'mix_info': mix_info,
            'tracks': [
                {
                    'position': i + 1,
                    'title': item['track'].title,
                    'artist': item['track'].artist,
                    'start_time': item['track'].start_time,
                    'end_time': item['track'].end_time,
                    'start_time_formatted': format_time(item['track'].start_time),
                    'end_time_formatted': format_time(item['track'].end_time) if item['track'].end_time is not None else None,
                    'confidence': item['track'].confidence,
                    'detection_count': item['track'].detection_count,
                    'cluster_density': item['track'].cluster_density,
                    'cluster_span': item['track'].cluster_span,
                    'source_deep_link': make_source_url(source_url, item['track'].start_time),
                    'spotify_url': item['metadata']['spotify_url'],
                    'youtube_url': item['metadata']['youtube_url'],
                    'discogs_url': item['metadata']['discogs_url'],
                }
                for i, item in enumerate(enriched_tracks)
            ],
            'metadata': self._build_metadata(enriched_tracks)
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print(f"Saved JSON: {output_path}")
        return output_path
    
    def save_markdown(self, enriched_tracks: list, mix_info: dict, filename: str = None) -> Path:
        """Save setlist as Markdown."""
        if not filename:
            filename = f"setlist_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        output_path = self.output_dir / f"{filename}.md"
        
        lines = []
        lines.append(f"# {mix_info.get('title', 'DJ Set')}")
        lines.append(f"\n**By:** {mix_info.get('uploader', 'Unknown')}")
        lines.append(f"**Duration:** {format_time(mix_info.get('duration', 0))}")
        lines.append(f"**Source:** {mix_info.get('url', 'N/A')}")
        lines.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"\n---\n")
        lines.append(f"\n## Tracklist\n")
        
        source_url = mix_info.get('url', '')
        for i, item in enumerate(enriched_tracks, 1):
            track = item['track']
            metadata = item['metadata']

            icon = CONFIDENCE_ICONS.get(track.confidence, '⚪')
            lines.append(f"\n### {i}. {track.artist} - {track.title} {icon}")

            time_str = format_time(track.start_time)
            end_str = f" \u2013 {format_time(track.end_time)}" if track.end_time is not None else ""
            deep_link = make_source_url(source_url, track.start_time)
            if deep_link:
                lines.append(f"**Time:** [{time_str}]({deep_link}){end_str}")
            else:
                lines.append(f"**Time:** {time_str}{end_str}")
            lines.append(f"**Confidence:** {track.confidence} ({track.detection_count} detections, {track.cluster_density:.0%} density)")
            
            # Links
            links = []
            if metadata['spotify_url']:
                links.append(f"[Spotify]({metadata['spotify_url']})")
            if metadata['youtube_url']:
                links.append(f"[YouTube]({metadata['youtube_url']})")
            if metadata['discogs_url']:
                links.append(f"[Discogs]({metadata['discogs_url']})")
            
            if links:
                lines.append(f"**Links:** {' • '.join(links)}")
            
            lines.append("")
        
        # Summary
        counts = self._count_by_confidence(enriched_tracks)
        lines.append("\n---\n")
        lines.append("## Summary\n")
        lines.append(f"- **Total Tracks:** {len(enriched_tracks)}")
        lines.append(f"- **High Confidence:** {counts.get('HIGH', 0)}")
        lines.append(f"- **Medium Confidence:** {counts.get('MEDIUM', 0)}")
        lines.append(f"- **Low Confidence:** {counts.get('LOW', 0)}")
        lines.append(f"- **Uncertain/Unknown:** {counts.get('UNCERTAIN', 0)}")
        
        # Clustering parameters used
        lines.append("\n## Algorithm Parameters\n")
        lines.append(f"- **Min Cluster Size:** {Config.MIN_CLUSTER_SIZE} detections")
        lines.append(f"- **Min Unknown Gap Size:** {Config.MIN_UNKNOWN_GAP_SIZE} segments")
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        print(f"Saved Markdown: {output_path}")
        return output_path