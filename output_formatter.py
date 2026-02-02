"""Format setlist output as JSON and Markdown."""

import json
from pathlib import Path
from datetime import datetime
from config import Config

class OutputFormatter:
    """Format and save setlist output."""
    
    def __init__(self, output_dir: Path = None):
        """
        Initialize formatter.
        
        Args:
            output_dir: Directory to save output files (if None, uses Config.OUTPUT_DIR)
        """
        self.output_dir = output_dir or Config.OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def format_time(self, seconds: float) -> str:
        """Convert seconds to MM:SS format."""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d}"
    
    def save_json(self, enriched_tracks: list, mix_info: dict, filename: str = None) -> Path:
        """Save setlist as JSON."""
        if not filename:
            filename = f"setlist_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        output_path = self.output_dir / f"{filename}.json"
        
        output_data = {
            'mix_info': mix_info,
            'tracks': [
                {
                    'position': i + 1,
                    'title': item['track'].title,
                    'artist': item['track'].artist,
                    'start_time': item['track'].start_time,
                    'end_time': item['track'].end_time,
                    'start_time_formatted': self.format_time(item['track'].start_time),
                    'confidence': item['track'].confidence,
                    'detection_count': item['track'].detection_count,
                    'cluster_density': item['track'].cluster_density,
                    'cluster_span': item['track'].cluster_span,
                    'spotify_url': item['metadata']['spotify_url'],
                    'youtube_url': item['metadata']['youtube_url'],
                    'discogs_url': item['metadata']['discogs_url'],
                }
                for i, item in enumerate(enriched_tracks)
            ],
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'total_tracks': len(enriched_tracks),
                'high_confidence_tracks': sum(1 for item in enriched_tracks if item['track'].confidence == 'HIGH'),
                'medium_confidence_tracks': sum(1 for item in enriched_tracks if item['track'].confidence == 'MEDIUM'),
                'low_confidence_tracks': sum(1 for item in enriched_tracks if item['track'].confidence == 'LOW'),
                'uncertain_tracks': sum(1 for item in enriched_tracks if item['track'].confidence == 'UNCERTAIN'),
            }
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
        lines.append(f"**Duration:** {self.format_time(mix_info.get('duration', 0))}")
        lines.append(f"**Source:** {mix_info.get('url', 'N/A')}")
        lines.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"\n---\n")
        lines.append(f"\n## Tracklist\n")
        
        for i, item in enumerate(enriched_tracks, 1):
            track = item['track']
            metadata = item['metadata']
            
            # Confidence indicator
            confidence_icon = {
                'HIGH': '🟢',
                'MEDIUM': '🟡',
                'LOW': '🟠',
                'UNCERTAIN': '⚪'
            }.get(track.confidence, '⚪')
            
            lines.append(f"\n### {i}. {track.artist} - {track.title} {confidence_icon}")
            lines.append(f"**Time:** {self.format_time(track.start_time)}")
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
        lines.append("\n---\n")
        lines.append("## Summary\n")
        lines.append(f"- **Total Tracks:** {len(enriched_tracks)}")
        lines.append(f"- **High Confidence:** {sum(1 for item in enriched_tracks if item['track'].confidence == 'HIGH')}")
        lines.append(f"- **Medium Confidence:** {sum(1 for item in enriched_tracks if item['track'].confidence == 'MEDIUM')}")
        lines.append(f"- **Low Confidence:** {sum(1 for item in enriched_tracks if item['track'].confidence == 'LOW')}")
        lines.append(f"- **Uncertain/Unknown:** {sum(1 for item in enriched_tracks if item['track'].confidence == 'UNCERTAIN')}")
        
        # Clustering parameters used
        lines.append("\n## Algorithm Parameters\n")
        lines.append(f"- **Min Cluster Size:** {Config.MIN_CLUSTER_SIZE} detections")
        lines.append(f"- **Min Unknown Gap Size:** {Config.MIN_UNKNOWN_GAP_SIZE} segments")
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        print(f"Saved Markdown: {output_path}")
        return output_path