#!/usr/bin/env python3
"""
Analyze checkpoint data and simulate simplified clustering algorithm.
"""

import json
from collections import defaultdict
from typing import Dict, List, Tuple, Set

def load_checkpoint(filepath: str) -> dict:
    """Load checkpoint JSON file."""
    with open(filepath, 'r') as f:
        return json.load(f)

def extract_valid_recognitions(checkpoint: dict) -> List[dict]:
    """Extract all valid recognitions (recognized=True) from checkpoint."""
    recognitions = checkpoint.get('data', {}).get('recognitions', [])
    return [r for r in recognitions if r.get('recognized', False)]

def create_track_id(recognition: dict) -> str:
    """Create track_id from recognition."""
    artist = recognition.get('artist', '')
    track_title = recognition.get('track_title', '')
    shazam_track_id = recognition.get('shazam_track_id', '')
    return f"{artist}|{track_title}|{shazam_track_id}"

def group_by_track_id(recognitions: List[dict]) -> Dict[str, List[dict]]:
    """Group all detections by track_id."""
    groups = defaultdict(list)
    for r in recognitions:
        track_id = create_track_id(r)
        groups[track_id].append(r)
    return dict(groups)

def calculate_cluster_metrics(detections: List[dict]) -> dict:
    """Calculate metrics for a cluster of detections."""
    segment_indices = sorted([d['segment_index'] for d in detections])
    detection_count = len(segment_indices)
    start_segment = min(segment_indices)
    end_segment = max(segment_indices)
    span = end_segment - start_segment + 1
    density = detection_count / span if span > 0 else 0

    # Extract track info from first detection
    first_det = detections[0]

    return {
        'track_id': create_track_id(first_det),
        'artist': first_det.get('artist', ''),
        'track_title': first_det.get('track_title', ''),
        'shazam_track_id': first_det.get('shazam_track_id', ''),
        'segment_indices': segment_indices,
        'detection_count': detection_count,
        'start_segment': start_segment,
        'end_segment': end_segment,
        'span': span,
        'density': density,
        'detections': detections
    }

def calculate_overlap(cluster1: dict, cluster2: dict) -> float:
    """Calculate temporal overlap percentage between two clusters."""
    start1, end1 = cluster1['start_segment'], cluster1['end_segment']
    start2, end2 = cluster2['start_segment'], cluster2['end_segment']

    overlap_start = max(start1, start2)
    overlap_end = min(end1, end2)

    if overlap_start > overlap_end:
        return 0.0

    overlap_length = overlap_end - overlap_start + 1
    min_span = min(cluster1['span'], cluster2['span'])

    return overlap_length / min_span if min_span > 0 else 0.0

def calculate_score(cluster: dict) -> float:
    """Calculate cluster score using multi-criteria scoring."""
    return (cluster['detection_count'] * 2.0 +
            cluster['span'] * 0.5 +
            cluster['density'] * 0.3)

def resolve_overlaps(clusters: List[dict], overlap_threshold: float = 0.3) -> List[dict]:
    """Resolve overlapping clusters using multi-criteria scoring."""
    clusters = sorted(clusters, key=lambda c: c['start_segment'])

    # Build overlap groups
    overlap_groups = []
    processed = set()

    for i, cluster in enumerate(clusters):
        if i in processed:
            continue

        group = [cluster]
        group_indices = {i}

        # Find all overlapping clusters
        for j, other in enumerate(clusters):
            if j <= i or j in processed:
                continue

            # Check if other overlaps with any cluster in current group
            overlaps_with_group = False
            for g_cluster in group:
                if calculate_overlap(g_cluster, other) >= overlap_threshold:
                    overlaps_with_group = True
                    break

            if overlaps_with_group:
                group.append(other)
                group_indices.add(j)

        if len(group) > 1:
            overlap_groups.append((group, group_indices))
            processed.update(group_indices)

    # Resolve each overlap group
    winners = []
    losers = []

    for group, indices in overlap_groups:
        # Calculate scores
        scored = [(calculate_score(c), c) for c in group]
        scored.sort(reverse=True, key=lambda x: x[0])

        winner = scored[0][1]
        winner['overlap_winner'] = True
        winners.append(winner)

        for score, cluster in scored[1:]:
            cluster['overlap_loser'] = True
            losers.append(cluster)

    # Add non-overlapping clusters
    non_overlapping = [c for i, c in enumerate(clusters) if i not in processed]

    return winners, losers, non_overlapping

def apply_filtering(clusters: List[dict], overlap_winners: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Apply filtering rules to clusters."""
    kept = []
    filtered = []

    for cluster in clusters:
        detection_count = cluster['detection_count']
        density = cluster['density']

        # Special handling for overlap winners
        if cluster.get('overlap_winner', False):
            if detection_count >= 3:
                kept.append(cluster)
                cluster['filter_reason'] = 'overlap_winner_min_detections'
                continue
            else:
                filtered.append(cluster)
                cluster['filter_reason'] = 'overlap_winner_insufficient_detections'
                continue

        # Standard filtering rules
        if (detection_count >= 15 or
            (detection_count >= 10 and density >= 0.5) or
            (detection_count >= 8 and density >= 0.6) or
            (detection_count >= 5 and density >= 0.7) or
            (detection_count >= 3 and density >= 0.8)):
            kept.append(cluster)
            cluster['filter_reason'] = 'passed_filter'
        else:
            filtered.append(cluster)
            cluster['filter_reason'] = 'failed_filter'

    return kept, filtered

def simplified_algorithm(recognitions: List[dict]) -> dict:
    """Run simplified clustering algorithm."""
    # Step 1: Group by track_id
    track_groups = group_by_track_id(recognitions)

    # Step 2: Calculate metrics for each group
    initial_clusters = []
    for track_id, detections in track_groups.items():
        cluster = calculate_cluster_metrics(detections)
        initial_clusters.append(cluster)

    # Step 3: Resolve overlaps
    overlap_winners, overlap_losers, non_overlapping = resolve_overlaps(initial_clusters)

    # Step 4: Apply filtering
    candidates_for_filtering = overlap_winners + non_overlapping
    kept_clusters, filtered_clusters = apply_filtering(candidates_for_filtering, overlap_winners)

    return {
        'initial_clusters': initial_clusters,
        'overlap_winners': overlap_winners,
        'overlap_losers': overlap_losers,
        'non_overlapping': non_overlapping,
        'kept_clusters': sorted(kept_clusters, key=lambda c: c['start_segment']),
        'filtered_clusters': filtered_clusters
    }

def analyze_checkpoint(filepath: str, mix_name: str) -> dict:
    """Analyze a checkpoint file."""
    checkpoint = load_checkpoint(filepath)
    recognitions = extract_valid_recognitions(checkpoint)

    print(f"\n{'='*80}")
    print(f"Analyzing: {mix_name}")
    print(f"{'='*80}")
    print(f"Total recognitions: {len(checkpoint.get('data', {}).get('recognitions', []))}")
    print(f"Valid recognitions (recognized=True): {len(recognitions)}")

    # Run simplified algorithm
    results = simplified_algorithm(recognitions)

    print(f"\nSimplified Algorithm Results:")
    print(f"  Initial clusters (all track_ids): {len(results['initial_clusters'])}")
    print(f"  Overlap winners: {len(results['overlap_winners'])}")
    print(f"  Overlap losers: {len(results['overlap_losers'])}")
    print(f"  Non-overlapping: {len(results['non_overlapping'])}")
    print(f"  Final kept clusters: {len(results['kept_clusters'])}")
    print(f"  Filtered out: {len(results['filtered_clusters'])}")

    return {
        'checkpoint': checkpoint,
        'mix_name': mix_name,
        'recognitions': recognitions,
        'results': results
    }

def format_time(segment_index: int) -> str:
    """Format segment index as time string (assumes 15s step size)."""
    seconds = segment_index * 15
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}:{secs:02d}"

def generate_markdown_report(yoyaku_analysis: dict, masda_analysis: dict,
                            yoyaku_reference: List[str], masda_reference: List[str]) -> str:
    """Generate detailed markdown report."""

    md = ["# Simplified Algorithm Analysis Report\n"]
    md.append(f"*Generated: 2026-02-01*\n")
    md.append("---\n")

    md.append("## Executive Summary\n")
    md.append("This report compares a **simplified clustering algorithm** to the current complex approach ")
    md.append("that uses adaptive gap tolerance, duplicate merging, overlap resolution, and filtering.\n")

    md.append("### Simplified Algorithm Steps\n")
    md.append("1. **Group by track_id**: All detections with same artist|track_title|shazam_track_id\n")
    md.append("2. **Calculate metrics**: detection_count, span, density for each group\n")
    md.append("3. **Overlap resolution**: Multi-criteria scoring (detection_count×2.0 + span×0.5 + density×0.3)\n")
    md.append("4. **Filtering**: Keep if meets detection/density thresholds OR overlap winner with 3+ detections\n")

    # Analyze each set
    for analysis, reference, set_name in [(yoyaku_analysis, yoyaku_reference, "Yoyaku"),
                                           (masda_analysis, masda_reference, "DJ Masda")]:
        md.append(f"\n---\n")
        md.append(f"## {set_name} - {analysis['mix_name']}\n")

        results = analysis['results']
        kept = results['kept_clusters']

        md.append(f"### Algorithm Execution Summary\n")
        md.append(f"- **Valid recognitions**: {len(analysis['recognitions'])}\n")
        md.append(f"- **Initial clusters**: {len(results['initial_clusters'])}\n")
        md.append(f"- **After overlap resolution**: {len(results['overlap_winners'])} winners, ")
        md.append(f"{len(results['overlap_losers'])} losers, {len(results['non_overlapping'])} non-overlapping\n")
        md.append(f"- **After filtering**: {len(kept)} tracks kept, {len(results['filtered_clusters'])} filtered out\n")

        md.append(f"\n### Final Setlist ({len(kept)} tracks)\n")
        md.append("| # | Track | Artist | Segments | Count | Span | Density | Start | End |\n")
        md.append("|---|-------|--------|----------|-------|------|---------|-------|-----|\n")

        for i, cluster in enumerate(kept, 1):
            md.append(f"| {i} | {cluster['track_title']} | {cluster['artist']} | ")
            md.append(f"{cluster['start_segment']}-{cluster['end_segment']} | ")
            md.append(f"{cluster['detection_count']} | {cluster['span']} | ")
            md.append(f"{cluster['density']:.2f} | {format_time(cluster['start_segment'])} | ")
            md.append(f"{format_time(cluster['end_segment'])} |\n")

        # Compare to reference
        md.append(f"\n### Comparison to Reference Setlist\n")
        reference_set = set([t.lower() for t in reference])
        detected_titles = [c['track_title'].lower() for c in kept]
        detected_set = set(detected_titles)

        true_positives = reference_set & detected_set
        false_positives = detected_set - reference_set
        false_negatives = reference_set - detected_set

        precision = len(true_positives) / len(detected_set) if detected_set else 0
        recall = len(true_positives) / len(reference_set) if reference_set else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        md.append(f"**Accuracy Metrics:**\n")
        md.append(f"- True Positives: {len(true_positives)} / {len(reference_set)}\n")
        md.append(f"- False Positives: {len(false_positives)}\n")
        md.append(f"- False Negatives: {len(false_negatives)}\n")
        md.append(f"- Precision: {precision:.2%}\n")
        md.append(f"- Recall: {recall:.2%}\n")
        md.append(f"- F1 Score: {f1:.2%}\n")

        if true_positives:
            md.append(f"\n**Correctly Detected ({len(true_positives)}):**\n")
            for title in sorted(true_positives):
                md.append(f"- {title.title()}\n")

        if false_positives:
            md.append(f"\n**False Positives ({len(false_positives)}):**\n")
            for title in sorted(false_positives):
                cluster = next(c for c in kept if c['track_title'].lower() == title)
                md.append(f"- {title.title()} (count={cluster['detection_count']}, ")
                md.append(f"density={cluster['density']:.2f}, ")
                md.append(f"reason={cluster.get('filter_reason', 'unknown')})\n")

        if false_negatives:
            md.append(f"\n**False Negatives ({len(false_negatives)}):**\n")
            for title in sorted(false_negatives):
                md.append(f"- {title.title()}\n")

        # Show overlap resolution details
        if results['overlap_losers']:
            md.append(f"\n### Overlap Resolution Details\n")
            md.append(f"**Rejected due to overlap ({len(results['overlap_losers'])}):**\n")
            md.append("| Track | Artist | Count | Span | Density | Score | Winner |\n")
            md.append("|-------|--------|-------|------|---------|-------|--------|\n")

            for loser in results['overlap_losers']:
                # Find the winner it lost to
                winner_track = "Unknown"
                for winner in results['overlap_winners']:
                    if calculate_overlap(loser, winner) >= 0.3:
                        winner_track = winner['track_title']
                        break

                score = calculate_score(loser)
                md.append(f"| {loser['track_title']} | {loser['artist']} | ")
                md.append(f"{loser['detection_count']} | {loser['span']} | ")
                md.append(f"{loser['density']:.2f} | {score:.2f} | {winner_track} |\n")

        # Show filtered tracks
        if results['filtered_clusters']:
            md.append(f"\n### Filtered Tracks\n")
            md.append(f"**Removed by filtering ({len(results['filtered_clusters'])}):**\n")
            md.append("| Track | Artist | Count | Span | Density | Reason |\n")
            md.append("|-------|--------|-------|------|---------|--------|\n")

            for cluster in sorted(results['filtered_clusters'], key=lambda c: c['detection_count'], reverse=True):
                md.append(f"| {cluster['track_title']} | {cluster['artist']} | ")
                md.append(f"{cluster['detection_count']} | {cluster['span']} | ")
                md.append(f"{cluster['density']:.2f} | {cluster.get('filter_reason', 'unknown')} |\n")

    # Comparative analysis
    md.append("\n---\n")
    md.append("## Comparative Analysis\n")

    md.append("### Simplified vs Complex Algorithm\n")
    md.append("**Key Differences:**\n")
    md.append("1. **Grouping Strategy**\n")
    md.append("   - Simplified: Groups ALL detections by track_id immediately (no gap tolerance)\n")
    md.append("   - Complex: Uses adaptive gap tolerance to create separate clusters for same track\n")
    md.append("2. **Duplicate Handling**\n")
    md.append("   - Simplified: No duplicate merging step (relies on track_id grouping)\n")
    md.append("   - Complex: Explicit duplicate merging with time-based proximity checks\n")
    md.append("3. **Overlap Resolution**\n")
    md.append("   - Simplified: Same multi-criteria scoring\n")
    md.append("   - Complex: Same multi-criteria scoring\n")
    md.append("4. **Filtering**\n")
    md.append("   - Simplified: Same rules\n")
    md.append("   - Complex: Same rules\n")

    md.append("\n### Pros of Simplified Approach\n")
    md.append("- **Simpler logic**: Fewer steps, easier to understand and maintain\n")
    md.append("- **No gap tolerance tuning**: Eliminates need to configure adaptive parameters\n")
    md.append("- **Faster execution**: Fewer passes through data\n")
    md.append("- **Deterministic**: No adaptive behavior that varies by dataset\n")

    md.append("\n### Cons of Simplified Approach\n")
    md.append("- **May merge distinct plays**: If same track played twice with gap, will merge into one cluster\n")
    md.append("- **Less nuanced**: Cannot distinguish between continuous play vs. scattered detections\n")
    md.append("- **Potential for false negatives**: May create low-density clusters that get filtered\n")
    md.append("- **No gap-based refinement**: Cannot split clearly separate segments of same track\n")

    md.append("\n### Recommendations\n")
    md.append("Based on this analysis:\n")
    md.append("1. **If tracks rarely repeat in sets**: Simplified approach may be sufficient\n")
    md.append("2. **If data quality is high**: Simplified approach benefits from cleaner grouping\n")
    md.append("3. **If tracks often repeat**: Complex algorithm better handles multiple plays\n")
    md.append("4. **For production use**: Run both algorithms and compare results on more test sets\n")

    return ''.join(md)

def main():
    # File paths
    yoyaku_checkpoint = "/Users/russellalgeo/Desktop/Side Job/set_list/checkpoints/Yoyaku instore session with Tomoki Tamura/checkpoint_8fbff800ee1f.json"
    masda_checkpoint = "/Users/russellalgeo/Desktop/Side Job/set_list/checkpoints/DJ Masda - Live At Dimensions 2021/checkpoint_f4a1b31c6db3.json"

    # Reference setlists
    yoyaku_reference = [
        "Experiment 001", "Closer", "Rock da echo", "Kief", "Runnin",
        "Moodymann Edit 9", "Different Circles", "Moment 4 Life", "MF 3",
        "It's Midnight", "My Back Is Against the Wall", "Closer to Midnight",
        "Searching", "Sly"
    ]

    # DJ Masda reference - actual detected tracks from current algorithm
    masda_reference = [
        "Ghost", "Big Decision", "You Have Time", "Beast",
        "Anonymous Force", "A Flash Storm (And Then It Was Gone)",
        "Narcotic Influence", "Dance Machine (Alexander Robotnick Remix)",
        "Renee Running", "Drunk As a Monk (Rabbit In The Moon's Brass Monkey Remix)",
        "Bass Equations", "Sensaureal 2.3.1", "That Acid Track"
    ]

    # Analyze checkpoints
    yoyaku_analysis = analyze_checkpoint(yoyaku_checkpoint, "Yoyaku instore session with Tomoki Tamura")
    masda_analysis = analyze_checkpoint(masda_checkpoint, "DJ Masda - Live At Dimensions 2021")

    # Generate report
    report = generate_markdown_report(yoyaku_analysis, masda_analysis,
                                     yoyaku_reference, masda_reference)

    # Save report
    output_path = "/Users/russellalgeo/Desktop/Side Job/set_list/simplified_algorithm_analysis.md"
    with open(output_path, 'w') as f:
        f.write(report)

    print(f"\n{'='*80}")
    print(f"Report saved to: {output_path}")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
