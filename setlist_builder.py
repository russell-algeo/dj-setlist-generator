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

        # Step 1: Create clusters (group all detections by track_id)
        clusters = self._create_clusters(valid_recognitions)

        # Step 2: Resolve temporal overlaps (competing tracks at same time)
        # Do this BEFORE filtering to choose dominant track among competitors
        if Config.OVERLAP_RESOLUTION_ENABLED:
            clusters = self._resolve_overlapping_clusters(clusters)

        # Step 3: Filter noise (now that overlaps are resolved)
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
        """Group ALL detections by track_id (simplified approach - no gap splitting).

        This simplified algorithm groups all detections of the same track together,
        regardless of gap size. Overlap resolution will handle competing detections.
        """
        if not recognitions:
            return []

        print(f"\n{'='*70}")
        print(f"CLUSTERING PHASE (Simplified)")
        print(f"{'='*70}")

        sorted_recs = sorted(recognitions, key=lambda x: x.segment_index)

        # Group by track ID - collect ALL detections for each track
        track_sequences = defaultdict(list)
        for rec in sorted_recs:
            track_id = f"{rec.artist}|{rec.track_title}|{rec.shazam_track_id}"
            track_sequences[track_id].append(rec)

        clusters = []

        # Create one cluster per track_id (all detections grouped together)
        for track_id, recs in track_sequences.items():
            artist, title = track_id.split('|')[0:2]

            # Only create cluster if we have minimum detections
            if len(recs) >= self.min_cluster_size:
                clusters.append(self._make_cluster_dict(track_id, recs))
                print(f"✓ Clustered: {artist} - {title} ({len(recs)} detections)")
            else:
                print(f"✗ Skipped: {artist} - {title} ({len(recs)} detections < {self.min_cluster_size} minimum)")

        clusters.sort(key=lambda c: c['start_segment'])
        print(f"\nCreated {len(clusters)} initial clusters")
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

    def _resolve_overlapping_clusters(self, clusters: list[dict]) -> list[dict]:
        """When tracks overlap in time, keep the dominant one using multi-criteria scoring.

        Uses multi-criteria scoring (not just density) to choose the winner:
        - detection_count * 2.0: Primary signal - more detections = stronger
        - span * 0.5: Secondary - longer span = more dominant
        - density * 0.3: Tertiary - density helps but doesn't dominate

        This prevents mixing artifacts (short, high-density) from beating real tracks.
        """
        if not clusters:
            return []

        print(f"\n{'='*70}")
        print(f"OVERLAP RESOLUTION PHASE")
        print(f"{'='*70}")

        sorted_clusters = sorted(clusters, key=lambda c: c['start_segment'])
        resolved = []
        i = 0
        overlap_count = 0

        while i < len(sorted_clusters):
            current = sorted_clusters[i]
            overlapping = [current]

            # Find all clusters that overlap with current
            for j in range(i + 1, len(sorted_clusters)):
                next_cluster = sorted_clusters[j]

                # Check if they overlap in time
                if self._clusters_overlap(current, next_cluster):
                    overlapping.append(next_cluster)
                elif next_cluster['start_segment'] > current['end_segment']:
                    # No more overlaps possible
                    break

            if len(overlapping) > 1:
                print(f"\n⚠️  OVERLAP DETECTED: {len(overlapping)} competing tracks")

                # Calculate scores for each track
                scored = []
                for c in overlapping:
                    artist, title = c['track_id'].split('|')[0:2]
                    score = (
                        c['detection_count'] * 2.0 +
                        c['span'] * 0.5 +
                        c['density'] * 0.3
                    )
                    scored.append((c, score, artist, title))
                    print(f"  📊 {artist} - {title}")
                    print(f"     └─ {c['detection_count']} detections, span {c['span']}, density {c['density']:.2f}")
                    print(f"     └─ Score: {score:.1f}")

                # Choose track using MULTI-CRITERIA scoring
                winner = max(overlapping, key=lambda c: (
                    c['detection_count'] * 2.0 +
                    c['span'] * 0.5 +
                    c['density'] * 0.3
                ))

                winner_artist, winner_title = winner['track_id'].split('|')[0:2]
                print(f"  ✅ KEEPING: {winner_artist} - {winner_title}")

                for c in overlapping:
                    if c != winner:
                        loser_artist, loser_title = c['track_id'].split('|')[0:2]
                        print(f"  ❌ REMOVING: {loser_artist} - {loser_title}")

                # Mark winner as having won overlap resolution for more lenient filtering
                winner['won_overlap_resolution'] = True
                resolved.append(winner)
                overlap_count += 1

                # Skip all losing clusters
                i += len(overlapping)
            else:
                resolved.append(current)
                i += 1

        print(f"\nResolved {overlap_count} overlap conflict(s)")
        print(f"Clusters after resolution: {len(resolved)} (from {len(sorted_clusters)})")

        return resolved

    def _clusters_overlap(self, cluster1: dict, cluster2: dict) -> bool:
        """Check if two clusters overlap in time (>= configured threshold overlap)."""
        start1, end1 = cluster1['start_segment'], cluster1['end_segment']
        start2, end2 = cluster2['start_segment'], cluster2['end_segment']

        # Calculate overlap
        overlap_start = max(start1, start2)
        overlap_end = min(end1, end2)
        overlap = max(0, overlap_end - overlap_start)

        # Check if overlap is significant (>= configured threshold, default 30%)
        span1 = end1 - start1
        span2 = end2 - start2

        return overlap >= min(span1, span2) * Config.OVERLAP_THRESHOLD

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
            won_overlap = cluster.get('won_overlap_resolution', False)

            # Decision tree for filtering
            keep = False
            reason = ""

            # Special handling for overlap resolution winners
            # These tracks beat competing detections, so they're likely real
            if won_overlap and count >= 3:
                keep = True
                reason = "won overlap resolution (dominant track)"
            elif count >= 15:
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