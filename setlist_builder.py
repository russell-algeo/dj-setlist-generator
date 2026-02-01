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

        # Step 1: Create clusters with adaptive gap tolerance
    clusters = self._create_clusters(valid_recognitions)

        # Step 2: Merge duplicate clusters (same track detected nearby)
        # Do this BEFORE filtering so merged clusters can pass quality thresholds
        if Config.DUPLICATE_MERGE_ENABLED:
            clusters = self._merge_duplicate_clusters(clusters)

        # Step 3: Resolve temporal overlaps (competing tracks at same time)
        # Do this BEFORE filtering to choose dominant track among competitors
        if Config.OVERLAP_RESOLUTION_ENABLED:
            clusters = self._resolve_overlapping_clusters(clusters)

        # Step 4: Filter noise (now that duplicates are merged and overlaps resolved)
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
        """Group recognitions into clusters with adaptive gap tolerance."""
        if not recognitions:
            return []

        print(f"\n{'='*70}")
        print(f"CLUSTERING PHASE")
        print(f"{'='*70}")

        sorted_recs = sorted(recognitions, key=lambda x: x.segment_index)

        # Group by track ID
        track_sequences = defaultdict(list)
        for rec in sorted_recs:
            track_id = f"{rec.artist}|{rec.track_title}|{rec.shazam_track_id}"
            track_sequences[track_id].append(rec)

        clusters = []

        for track_id, recs in track_sequences.items():
            artist, title = track_id.split('|')[0:2]
            current_cluster = [recs[0]]

            for i in range(1, len(recs)):
                prev_idx = current_cluster[-1].segment_index
                curr_idx = recs[i].segment_index
                gap = curr_idx - prev_idx

                # Use adaptive gap tolerance if enabled
                if Config.ADAPTIVE_GAP_ENABLED:
                    allowed_gap = self._calculate_allowed_gap(current_cluster)
                else:
                    allowed_gap = self.max_gap_size

                if gap <= allowed_gap:
                    current_cluster.append(recs[i])
                else:
                    # Gap too large - split into new cluster
                    print(f"\n🔀 SPLIT: {artist} - {title}")
                    print(f"  └─ Gap of {gap} segments exceeds allowed {allowed_gap}")
                    print(f"  └─ Saving cluster with {len(current_cluster)} detections")

                    # Save current cluster if valid
                    if len(current_cluster) >= self.min_cluster_size:
                        clusters.append(self._make_cluster_dict(track_id, current_cluster))
                    current_cluster = [recs[i]]

            # Save last cluster
            if len(current_cluster) >= self.min_cluster_size:
                clusters.append(self._make_cluster_dict(track_id, current_cluster))

        clusters.sort(key=lambda c: c['start_segment'])
        print(f"\nCreated {len(clusters)} initial clusters")
        return clusters

    def _calculate_allowed_gap(self, current_cluster: list) -> int:
        """Calculate allowed gap based on recent detection density.

        Uses revised thresholds from regression testing:
        - density >= 0.6: allow gap up to 8 segments (2 minutes)
        - density >= 0.4: allow gap up to 5 segments (75 seconds)
        - otherwise: strict gap of 5 segments (75 seconds)

        FIX: Allow adaptive gap tolerance to work with 2+ detections (not just 3+)
        to avoid catch-22 where you need 3 detections to get adaptive tolerance,
        but need adaptive tolerance to bridge the gap to get the 3rd detection.
        """
        if len(current_cluster) < 2:
            return self.max_gap_size  # Base case: single detection uses default

        # Calculate recent density (last 10 segments or all if fewer)
        recent_count = min(10, len(current_cluster))
        recent_recs = current_cluster[-recent_count:]

        # Calculate span of recent detections
        recent_indices = [r.segment_index for r in recent_recs]
        recent_span = max(recent_indices) - min(recent_indices) + 1
        recent_density = len(recent_recs) / recent_span

        # Adaptive thresholds (validated via regression testing)
        if recent_density >= Config.ADAPTIVE_GAP_STRONG_THRESHOLD:
            print(f"  ⚡ ADAPTIVE GAP: Strong density {recent_density:.2f} → allowing {Config.ADAPTIVE_GAP_STRONG_SIZE} segment gap")
            return Config.ADAPTIVE_GAP_STRONG_SIZE
        elif recent_density >= Config.ADAPTIVE_GAP_MODERATE_THRESHOLD:
            print(f"  ⚡ ADAPTIVE GAP: Moderate density {recent_density:.2f} → allowing {Config.ADAPTIVE_GAP_MODERATE_SIZE} segment gap")
            return Config.ADAPTIVE_GAP_MODERATE_SIZE
        else:
            return self.max_gap_size

    def _merge_duplicate_clusters(self, clusters: list[dict]) -> list[dict]:
        """Merge clusters of same track_id if they're close together.

        Validated via regression testing to fix duplicates like 'Rock da echo'
        in Yoyaku set (split into clusters at 44:45 and 48:00 with 6-segment gap).
        """
        if not clusters:
            return []

        print(f"\n{'='*70}")
        print(f"DUPLICATE MERGING PHASE")
        print(f"{'='*70}")

        # Group by track_id
        by_track = defaultdict(list)
        for cluster in clusters:
            by_track[cluster['track_id']].append(cluster)

        merged = []
        merge_count = 0

        for track_id, track_clusters in by_track.items():
            # Sort by start time
            track_clusters.sort(key=lambda c: c['start_segment'])

            if len(track_clusters) > 1:
                artist, title = track_id.split('|')[0:2]
                print(f"\n📋 Checking {len(track_clusters)} clusters for: {artist} - {title}")

            current_merged = [track_clusters[0]]

            for next_cluster in track_clusters[1:]:
                last = current_merged[-1]
                gap = next_cluster['start_segment'] - last['end_segment']

                # Merge if gap <= configured distance (default 10 segments = 2.5 minutes)
                if gap <= Config.DUPLICATE_MERGE_DISTANCE:
                    # Combine clusters
                    artist, title = track_id.split('|')[0:2]
                    print(f"  🔗 MERGE: Gap of {gap} segments (≤ {Config.DUPLICATE_MERGE_DISTANCE})")
                    print(f"    └─ Combining {last['detection_count']} + {next_cluster['detection_count']} detections")

                    combined_recs = last['recognitions'] + next_cluster['recognitions']
                    current_merged[-1] = self._make_cluster_dict(track_id, combined_recs)
                    merge_count += 1
                else:
                    # Keep as separate (might be played twice in set)
                    print(f"  ⏭️  KEEP SEPARATE: Gap of {gap} segments (> {Config.DUPLICATE_MERGE_DISTANCE})")
                    current_merged.append(next_cluster)

            merged.extend(current_merged)

        print(f"\nMerged {merge_count} duplicate cluster(s)")
        print(f"Clusters after merging: {len(merged)} (from {len(clusters)})")

        # Sort by start time
        return sorted(merged, key=lambda c: c['start_segment'])

    def _resolve_overlapping_clusters(self, clusters: list[dict]) -> list[dict]:
        """When tracks overlap in time, keep the dominant one using multi-criteria scoring.

        Validated via regression testing. Example from Yoyaku:
        - "Closer" (6 detections, 195s span) vs "Machine lernt" (5 detections, 75s span)
        - Using multi-criteria: Closer scores 19.1 vs Machine lernt 13.3
        - Correctly keeps "Closer" (the real track) and removes "Machine lernt" (mixing artifact)
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

                # Choose track using MULTI-CRITERIA scoring (not just density!)
                # detection_count * 2.0: Primary signal - more detections = stronger
                # span * 0.5: Secondary - longer span = more dominant
                # density * 0.3: Tertiary - density helps but doesn't dominate
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
        """Check if two clusters overlap in time (>= 30% overlap)."""
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