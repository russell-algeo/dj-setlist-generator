"""Build setlist from recognition results with advanced clustering."""

from dataclasses import dataclass
from typing import Optional, List
from config import Config
from collections import defaultdict

@dataclass
class Track:
    """Represents a track in the setlist."""
    title: str
    artist: str
    start_time: float
    end_time: Optional[float]
    confidence: str
    detection_count: int
    shazam_track_id: Optional[str]
    cluster_density: float
    cluster_span: int
    segment_indices: List[int]

class SetlistBuilder:
    """Build deduplicated setlist from recognitions."""
    
    def __init__(self, min_confidence_threshold: int = None):
        """Initialize builder."""
        self.min_confidence = min_confidence_threshold or Config.MIN_CONFIDENCE_THRESHOLD
        
        # Clustering parameters
        self.min_cluster_size = Config.MIN_CLUSTER_SIZE
        self.max_gap_size = Config.MAX_GAP_SIZE
        self.min_density = Config.MIN_CLUSTER_DENSITY
        self.min_unknown_gap_size = Config.MIN_UNKNOWN_GAP_SIZE
        
    def build_setlist(self, recognitions: list) -> list[Track]:
        """Build setlist from recognition results."""
        valid_recognitions = [r for r in recognitions if r.recognized]
        
        if not valid_recognitions:
            print("No tracks recognized")
            return []
        
        # Create clusters
        clusters = self._create_clusters(valid_recognitions)
        
        # Filter noise
        filtered_clusters = self._filter_clusters(clusters)
        
        # Convert to tracks
        tracks = [self._cluster_to_track(cluster) for cluster in filtered_clusters]
        
        # Calculate confidence
        tracks = self._calculate_confidence(tracks)
        
        print(f"\n{'='*70}")
        print(f"CLUSTERING RESULTS")
        print(f"{'='*70}")
        print(f"Built setlist with {len(tracks)} tracks")
        print(f"Filtered out {len(clusters) - len(filtered_clusters)} noise detections")
        
        return tracks
    
    def _create_clusters(self, recognitions: list) -> list[dict]:
        """Group recognitions into clusters with gap tolerance."""
        if not recognitions:
            return []
        
        sorted_recs = sorted(recognitions, key=lambda x: x.segment_index)
        
        # Group by track ID
        track_sequences = defaultdict(list)
        for rec in sorted_recs:
            track_id = f"{rec.artist}|{rec.track_title}|{rec.shazam_track_id}"
            track_sequences[track_id].append(rec)
        
        clusters = []
        
        for track_id, recs in track_sequences.items():
            current_cluster = [recs[0]]
            
            for i in range(1, len(recs)):
                prev_idx = current_cluster[-1].segment_index
                curr_idx = recs[i].segment_index
                gap = curr_idx - prev_idx
                
                if gap <= self.max_gap_size:
                    current_cluster.append(recs[i])
                else:
                    # Save current cluster if valid
                    if len(current_cluster) >= self.min_cluster_size:
                        clusters.append(self._make_cluster_dict(track_id, current_cluster))
                    current_cluster = [recs[i]]
            
            # Save last cluster
            if len(current_cluster) >= self.min_cluster_size:
                clusters.append(self._make_cluster_dict(track_id, current_cluster))
        
        clusters.sort(key=lambda c: c['start_segment'])
        return clusters
    
    def _make_cluster_dict(self, track_id: str, recognitions: list) -> dict:
        """Create cluster dictionary from recognitions."""
        segment_indices = [r.segment_index for r in recognitions]
        start_seg = min(segment_indices)
        end_seg = max(segment_indices)
        span = end_seg - start_seg + 1
        count = len(recognitions)
        density = count / span
        
        return {
            'track_id': track_id,
            'recognitions': recognitions,
            'segment_indices': segment_indices,
            'start_segment': start_seg,
            'end_segment': end_seg,
            'span': span,
            'detection_count': count,
            'density': density
        }
    
    def _filter_clusters(self, clusters: list[dict]) -> list[dict]:
        """Filter out noise using multi-factor analysis."""
        if not clusters:
            return []
        
        print(f"\n{'='*70}")
        print(f"CLUSTER FILTERING")
        print(f"{'='*70}")
        
        filtered = []
        
        for cluster in clusters:
            count = cluster['detection_count']
            density = cluster['density']
            span = cluster['span']
            
            # Decision tree for filtering
            keep = False
            reason = ""
            
            if count >= 15:
                keep = True
                reason = "long cluster (15+ detections)"
            elif count >= 10 and density >= 0.5:
                keep = True
                reason = "medium cluster with good density"
            elif count >= 8 and density >= 0.6:
                keep = True
                reason = "dense cluster"
            elif count >= 5 and density >= 0.7:
                keep = True
                reason = "very dense short cluster"
            elif count >= 3 and density >= 0.8:
                keep = True
                reason = "extremely dense minimal cluster"
            
            artist, title = cluster['track_id'].split('|')[0:2]
            
            if keep:
                filtered.append(cluster)
                print(f"✓ KEEP: {artist} - {title}")
                print(f"  └─ {count} detections, {density:.0%} density, span {span} segments")
                print(f"  └─ Reason: {reason}")
            else:
                print(f"✗ FILTER: {artist} - {title}")
                print(f"  └─ {count} detections, {density:.0%} density, span {span} segments")
                print(f"  └─ Reason: below thresholds")
        
        return filtered
    
    def _cluster_to_track(self, cluster: dict) -> Track:
        """Convert cluster to Track object."""
        first = cluster['recognitions'][0]
        last = cluster['recognitions'][-1]
        artist, title, shazam_id = cluster['track_id'].split('|')
        
        return Track(
            title=title,
            artist=artist,
            start_time=first.timestamp,
            end_time=last.timestamp + 30,
            confidence="",
            detection_count=cluster['detection_count'],
            shazam_track_id=shazam_id,
            cluster_density=cluster['density'],
            cluster_span=cluster['span'],
            segment_indices=cluster['segment_indices']
        )
    
    def _calculate_confidence(self, tracks: list[Track]) -> list[Track]:
        """Calculate confidence scores."""
        for track in tracks:
            # Multi-factor confidence
            if track.detection_count >= 15:
                track.confidence = "HIGH"
            elif track.detection_count >= 10 or (track.detection_count >= 8 and track.cluster_density >= 0.7):
                track.confidence = "HIGH"
            elif track.detection_count >= 5 and track.cluster_density >= 0.6:
                track.confidence = "MEDIUM"
            elif track.detection_count >= 3 and track.cluster_density >= 0.75:
                track.confidence = "MEDIUM"
            else:
                track.confidence = "LOW"
        
        return tracks
    
    def add_unknown_tracks(self, tracks: list[Track], recognitions: list) -> list[Track]:
        """Add Unknown Track entries for gaps."""
        if not tracks:
            return []
        
        all_tracks = []
        
        # Get all covered segments
        covered_segments = set()
        for track in tracks:
            covered_segments.update(track.segment_indices)
        
        # Find gaps
        all_segments = sorted([r.segment_index for r in recognitions])
        gap_segments = [s for s in all_segments if s not in covered_segments]
        
        # Group consecutive gaps
        unknown_gaps = []
        current_gap = []
        
        for seg_idx in gap_segments:
            if not current_gap or seg_idx - current_gap[-1] <= 2:
                current_gap.append(seg_idx)
            else:
                if len(current_gap) >= self.min_unknown_gap_size:
                    unknown_gaps.append(current_gap)
                current_gap = [seg_idx]
        
        if len(current_gap) >= self.min_unknown_gap_size:
            unknown_gaps.append(current_gap)
        
        # Create Unknown Track entries
        unknown_tracks = []
        for gap in unknown_gaps:
            # Find corresponding timestamp
            gap_recs = [r for r in recognitions if r.segment_index in gap]
            if gap_recs:
                unknown_tracks.append(Track(
                    title="Unknown Track",
                    artist="Unknown",
                    start_time=gap_recs[0].timestamp,
                    end_time=gap_recs[-1].timestamp + 30,
                    confidence="UNCERTAIN",
                    detection_count=0,
                    shazam_track_id=None,
                    cluster_density=0.0,
                    cluster_span=len(gap),
                    segment_indices=gap
                ))
        
        print(f"\nIdentified {len(unknown_tracks)} unknown track gaps")
        
        # Merge and sort
        all_tracks = sorted(tracks + unknown_tracks, key=lambda t: t.start_time)
        return all_tracks