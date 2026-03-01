"""Generate a master summary view across all artists.

Usage:
    python master_summary.py              # generate output/index.html
    python master_summary.py output/      # specify output root
"""

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from html_formatter import HtmlFormatter

_SUMMARY_FILES = {"artist_summary.json", "artist_summary.md", "artist_summary.html"}


def _normalize_key(artist: str, title: str) -> str:
    """Normalized lowercase track key for cross-artist matching."""
    return f"{artist.strip().lower()} - {title.strip().lower()}"


def _enrich_sets(track: dict) -> list[dict]:
    """Convert a track's plain set-title list into rich {title, href} objects."""
    link_map = track.get("set_link_map", {})
    result = []
    for title in track.get("sets", []):
        info = link_map.get(title, {})
        href = info.get("html_master_rel", "")
        pos = info.get("track_position")
        if href and pos:
            from urllib.parse import quote as _quote
            href = _quote(href, safe="/") + f"#track-{pos}"
        elif href:
            from urllib.parse import quote as _quote
            href = _quote(href, safe="/")
        result.append({"title": title, "href": href})
    return result


def _extract_youtube_id(url: str) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
        if host == "youtube.com":
            return parse_qs(parsed.query).get("v", [None])[0]
        if host == "youtu.be":
            return parsed.path.lstrip("/")
    except Exception:
        pass
    return None


class _Stub:
    """Minimal checkpoint_manager stub so HtmlFormatter.__init__ works."""
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)


class MasterSummarizer:
    """Aggregate data across all artists and generate output/index.html."""

    def __init__(self, output_root: Path):
        self._output_root = Path(output_root)

    def generate(self) -> Path | None:
        """Scan all artist directories and generate index.html."""
        artist_dirs = self._find_artist_dirs()
        if not artist_dirs:
            print("No artist directories found — skipping master summary.")
            return None

        artists_data = []
        for artist_dir in sorted(artist_dirs, key=lambda p: p.name.lower()):
            data = self._load_artist(artist_dir)
            if data:
                artists_data.append(data)

        if not artists_data:
            print("No valid artist data found — skipping master summary.")
            return None

        master_data = self._aggregate(artists_data)
        html_fmt = HtmlFormatter(checkpoint_manager=_Stub(self._output_root))
        return html_fmt.save_master_summary_html(master_data)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _find_artist_dirs(self) -> list[Path]:
        if not self._output_root.exists():
            return []
        return [
            e for e in self._output_root.iterdir()
            if e.is_dir() and (e / "artist_summary.json").exists()
        ]

    def _load_artist(self, artist_dir: Path) -> dict | None:
        summary_json = artist_dir / "artist_summary.json"
        try:
            with open(summary_json, encoding="utf-8") as f:
                summary = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  WARNING: could not read {summary_json}: {e}")
            return None

        artist_name = summary.get("artist", artist_dir.name)
        stats = summary.get("stats", {})

        tracks: dict[str, dict] = {}   # normalized_key -> enriched track data
        all_sets: list[dict] = []

        for set_dir in sorted(artist_dir.iterdir()):
            if not set_dir.is_dir():
                continue
            json_files = [f for f in set_dir.glob("*.json") if f.name not in _SUMMARY_FILES]
            if not json_files:
                continue

            try:
                with open(json_files[0], encoding="utf-8") as f:
                    set_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            mix_info = set_data.get("mix_info", {})
            metadata = set_data.get("metadata", {})
            raw_tracks = set_data.get("tracks", [])
            set_title = mix_info.get("title", set_dir.name)
            set_url = mix_info.get("url", "")
            duration = mix_info.get("duration", 0)
            total_tracks = metadata.get("total_tracks", len(raw_tracks))
            recognized = sum(1 for t in raw_tracks if t.get("title") != "Unknown Track")
            recognition_rate = (recognized / total_tracks * 100) if total_tracks else 0

            # HTML path relative to artist dir (for artist page links)
            html_files = list(set_dir.glob("*.html"))
            set_html_rel = None
            set_html_master_rel = None
            if html_files:
                try:
                    set_html_rel = str(html_files[0].relative_to(artist_dir))
                except ValueError:
                    pass
                try:
                    set_html_master_rel = str(html_files[0].relative_to(self._output_root))
                except ValueError:
                    pass

            mini_timeline = []
            for t in raw_tracks:
                if duration and t.get("start_time") is not None:
                    start = t["start_time"]
                    end = t.get("end_time") or duration
                    mini_timeline.append({
                        "start_pct": start / duration * 100,
                        "width_pct": max(0.5, (end - start) / duration * 100),
                        "confidence": t.get("confidence", "UNCERTAIN"),
                    })

            video_id = _extract_youtube_id(set_url)
            thumbnail_url = (
                f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg" if video_id else None
            )

            set_tracks_list = [
                {
                    "artist": t.get("artist", "Unknown"),
                    "title": t.get("title", "Unknown"),
                    "start_time_formatted": t.get("start_time_formatted", ""),
                    "confidence": t.get("confidence", "UNCERTAIN"),
                    "spotify_url": t.get("spotify_url"),
                    "track_key": f"{t.get('artist', 'Unknown')} - {t.get('title', 'Unknown')}",
                }
                for t in raw_tracks if t.get("title") != "Unknown Track"
            ]

            all_sets.append({
                "title": set_title,
                "url": set_url,
                "total_tracks": total_tracks,
                "high_confidence": metadata.get("high_confidence_tracks", 0),
                "set_html_rel": set_html_rel,
                "set_html_master_rel": set_html_master_rel,
                "tracks": set_tracks_list,
                "index": len(all_sets),
                "duration": duration,
                "recognition_rate": recognition_rate,
                "confidence_counts": {
                    "HIGH": metadata.get("high_confidence_tracks", 0),
                    "MEDIUM": metadata.get("medium_confidence_tracks", 0),
                    "LOW": metadata.get("low_confidence_tracks", 0),
                    "UNCERTAIN": metadata.get("uncertain_tracks", 0),
                },
                "mini_timeline": mini_timeline,
                "thumbnail_url": thumbnail_url,
                "track_search_text": " ".join(
                    f"{t.get('artist', '')} {t.get('title', '')}".lower()
                    for t in raw_tracks if t.get("title") != "Unknown Track"
                ),
                "artist_name": artist_name,
            })

            # Build enriched track dict from per-set JSON
            for t in raw_tracks:
                if t.get("title") == "Unknown Track":
                    continue
                t_artist = t.get("artist", "Unknown")
                t_title = t.get("title", "Unknown")
                key = _normalize_key(t_artist, t_title)

                genres = list(dict.fromkeys(
                    (t.get("discogs_styles") or [])
                    + (t.get("spotify_genres") or [])
                    + (t.get("discogs_genres") or [])
                ))

                if key not in tracks:
                    tracks[key] = {
                        "track_key": key,
                        "display_artist": t_artist,
                        "display_title": t_title,
                        "spotify_url": t.get("spotify_url"),
                        "spotify_album_art": t.get("spotify_album_art"),
                        "discogs_label": t.get("discogs_label"),
                        "discogs_label_url": t.get("discogs_label_url"),
                        "genres": genres,
                        "appearances": 0,
                        "sets": [],
                        "set_link_map": {},  # set_title → {html_master_rel, track_position}
                    }
                else:
                    if not tracks[key]["spotify_album_art"] and t.get("spotify_album_art"):
                        tracks[key]["spotify_album_art"] = t["spotify_album_art"]
                    if not tracks[key]["discogs_label"] and t.get("discogs_label"):
                        tracks[key]["discogs_label"] = t["discogs_label"]
                        tracks[key]["discogs_label_url"] = t.get("discogs_label_url")
                    if not tracks[key]["genres"] and genres:
                        tracks[key]["genres"] = genres

                tracks[key]["appearances"] += 1
                if set_title not in tracks[key]["sets"]:
                    tracks[key]["sets"].append(set_title)
                # Store link info for this set (first occurrence wins for position)
                if set_title not in tracks[key]["set_link_map"] and set_html_master_rel:
                    tracks[key]["set_link_map"][set_title] = {
                        "html_master_rel": set_html_master_rel,
                        "track_position": t.get("position"),
                    }

        # Genre counter for this artist
        genre_counter: Counter = Counter()
        for track in tracks.values():
            for g in track.get("genres", []):
                normalized = g.title()
                if normalized != "House":
                    genre_counter[normalized] += 1

        top_genres = [g for g, _ in genre_counter.most_common(3)]

        unique_count = len(tracks)
        repeat_count = sum(1 for t in tracks.values() if t["appearances"] > 1)
        signature_score = (repeat_count / unique_count * 100) if unique_count else 0

        return {
            "name": artist_name,
            "dir_name": artist_dir.name,
            "html_rel": f"{artist_dir.name}/artist_summary.html",
            "sets_analyzed": stats.get("sets_analyzed", len(all_sets)),
            "unique_tracks": unique_count,
            "total_appearances": stats.get(
                "total_track_appearances",
                sum(t["appearances"] for t in tracks.values()),
            ),
            "signature_score": round(signature_score, 1),
            "top_genres": top_genres,
            "tracks": tracks,
            "sets": all_sets,
            "genre_counter": genre_counter,
            "top_connections": [],  # filled during _aggregate
        }

    def _aggregate(self, artists_data: list[dict]) -> dict:
        """Compute cross-artist indexes, similarity matrix, and global stats."""
        total_sets = sum(a["sets_analyzed"] for a in artists_data)
        total_appearances = sum(a["total_appearances"] for a in artists_data)
        all_keys: set = set()
        for a in artists_data:
            all_keys.update(a["tracks"].keys())

        global_stats = {
            "total_artists": len(artists_data),
            "total_unique_tracks": len(all_keys),
            "total_sets": total_sets,
            "total_appearances": total_appearances,
        }

        name_to_dir = {a["name"]: a["dir_name"] for a in artists_data}

        # Inverted indexes
        track_to_artists: dict[str, dict] = defaultdict(dict)
        label_to_artists: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        music_artist_to_djs: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        genre_to_artists: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        global_genre_counter: Counter = Counter()
        global_label_counter: Counter = Counter()

        for artist in artists_data:
            for key, track in artist["tracks"].items():
                track_to_artists[key][artist["name"]] = track
                if track.get("discogs_label"):
                    label_to_artists[track["discogs_label"]][artist["name"]] += 1
                music_artist = track["display_artist"]
                if music_artist and music_artist.lower() not in ("unknown", ""):
                    music_artist_to_djs[music_artist][artist["name"]] += 1
                for g in track.get("genres", []):
                    norm = g.title()
                    if norm != "House":
                        genre_to_artists[norm][artist["name"]] += 1

            global_genre_counter.update(artist["genre_counter"])

        for label, djs in label_to_artists.items():
            global_label_counter[label] += sum(djs.values())

        # Global genre/label totals
        genre_totals = [
            {
                "genre": g,
                "count": c,
                "artists": sorted(genre_to_artists.get(g, {}).keys()),
            }
            for g, c in global_genre_counter.most_common()
        ]
        label_totals = [
            {
                "label": label,
                "count": count,
                "artists": sorted(label_to_artists[label].keys()),
            }
            for label, count in global_label_counter.most_common()
        ]

        # Most played tracks — top 50 by total appearances, ranked by cross-artist first
        most_played = []
        for key, artist_map in track_to_artists.items():
            first = next(iter(artist_map.values()))
            total_app = sum(v["appearances"] for v in artist_map.values())
            most_played.append({
                "track_key": key,
                "display_artist": first["display_artist"],
                "display_title": first["display_title"],
                "spotify_url": first.get("spotify_url"),
                "spotify_album_art": first.get("spotify_album_art"),
                "total_appearances": total_app,
                "num_djs": len(artist_map),
                "is_cross_artist": len(artist_map) >= 2,
                "dj_appearances": [
                    {
                        "dj": dj,
                        "appearances": data["appearances"],
                        "sets": data["sets"],
                        "dir_name": name_to_dir.get(dj, ""),
                    }
                    for dj, data in sorted(
                        artist_map.items(),
                        key=lambda x: x[1]["appearances"],
                        reverse=True,
                    )
                ],
            })
        # Sort: cross-artist first, then by total appearances
        most_played.sort(key=lambda x: (not x["is_cross_artist"], -x["total_appearances"]))
        most_played = most_played[:60]

        # Pairwise similarity matrix
        n = len(artists_data)
        similarity_matrix: dict[tuple, dict] = {}

        for i in range(n):
            for j in range(i + 1, n):
                a = artists_data[i]
                b = artists_data[j]
                a_keys = set(a["tracks"].keys())
                b_keys = set(b["tracks"].keys())
                shared_keys = a_keys & b_keys

                shared_tracks = []
                for k in sorted(shared_keys):
                    a_t = track_to_artists[k].get(a["name"], {})
                    b_t = track_to_artists[k].get(b["name"], {})
                    shared_tracks.append({
                        "track_key": k,
                        "display_artist": a_t.get("display_artist", ""),
                        "display_title": a_t.get("display_title", ""),
                        "spotify_album_art": (
                            a_t.get("spotify_album_art") or b_t.get("spotify_album_art")
                        ),
                        "spotify_url": a_t.get("spotify_url") or b_t.get("spotify_url"),
                        "appearances_a": a_t.get("appearances", 0),
                        "appearances_b": b_t.get("appearances", 0),
                        # Needed for track cards in connection panel — rich objects with href
                        "sets_a": _enrich_sets(a_t),
                        "sets_b": _enrich_sets(b_t),
                        "genres": list(dict.fromkeys(
                            (a_t.get("genres") or []) + (b_t.get("genres") or [])
                        )),
                        "discogs_label": a_t.get("discogs_label") or b_t.get("discogs_label"),
                    })
                shared_tracks.sort(
                    key=lambda x: x["appearances_a"] + x["appearances_b"], reverse=True
                )
                shared_key_set = set(t["track_key"] for t in shared_tracks)

                a_labels = {t["discogs_label"] for t in a["tracks"].values() if t.get("discogs_label")}
                b_labels = {t["discogs_label"] for t in b["tracks"].values() if t.get("discogs_label")}
                shared_label_names = a_labels & b_labels
                shared_labels = sorted(
                    [
                        {
                            "label": lbl,
                            "count_a": sum(
                                1 for t in a["tracks"].values() if t.get("discogs_label") == lbl
                            ),
                            "count_b": sum(
                                1 for t in b["tracks"].values() if t.get("discogs_label") == lbl
                            ),
                            "track_keys": [
                                k for k in shared_key_set
                                if (
                                    a["tracks"].get(k, {}).get("discogs_label") == lbl
                                    or b["tracks"].get(k, {}).get("discogs_label") == lbl
                                )
                            ],
                        }
                        for lbl in shared_label_names
                    ],
                    key=lambda x: x["count_a"] + x["count_b"],
                    reverse=True,
                )

                a_music = {
                    t["display_artist"]
                    for t in a["tracks"].values()
                    if t["display_artist"].lower() not in ("unknown", "")
                }
                b_music = {
                    t["display_artist"]
                    for t in b["tracks"].values()
                    if t["display_artist"].lower() not in ("unknown", "")
                }
                shared_music_artists = sorted(
                    [
                        {
                            "music_artist": ma,
                            "count_a": sum(
                                1 for t in a["tracks"].values() if t["display_artist"] == ma
                            ),
                            "count_b": sum(
                                1 for t in b["tracks"].values() if t["display_artist"] == ma
                            ),
                            "track_keys": [
                                k for k in shared_key_set
                                if (
                                    a["tracks"].get(k, {}).get("display_artist") == ma
                                    or b["tracks"].get(k, {}).get("display_artist") == ma
                                )
                            ],
                        }
                        for ma in (a_music & b_music)
                    ],
                    key=lambda x: x["count_a"] + x["count_b"],
                    reverse=True,
                )

                shared_genre_names = set(a["genre_counter"].keys()) & set(b["genre_counter"].keys())
                shared_genres = sorted(
                    [
                        {
                            "genre": g,
                            "count_a": a["genre_counter"][g],
                            "count_b": b["genre_counter"][g],
                            "track_keys": [
                                k for k in shared_key_set
                                if g.lower() in [
                                    x.lower() for x in (
                                        (a["tracks"].get(k, {}).get("genres") or [])
                                        + (b["tracks"].get(k, {}).get("genres") or [])
                                    )
                                ]
                            ],
                        }
                        for g in shared_genre_names
                    ],
                    key=lambda x: x["count_a"] + x["count_b"],
                    reverse=True,
                )

                raw_score = (
                    len(shared_tracks) * 3
                    + len(shared_labels)
                    + len(shared_music_artists)
                )
                entry = {
                    "score": raw_score,
                    "normalized_score": 0,  # filled below
                    "shared_tracks": shared_tracks,
                    "shared_labels": shared_labels,
                    "shared_music_artists": shared_music_artists,
                    "shared_genres": shared_genres,
                }
                similarity_matrix[(a["name"], b["name"])] = entry
                similarity_matrix[(b["name"], a["name"])] = entry

        # Normalize scores
        max_score = max((v["score"] for v in similarity_matrix.values()), default=1) or 1
        for entry in similarity_matrix.values():
            entry["normalized_score"] = round(entry["score"] / max_score * 100)

        # Attach top_connections to each artist card
        for artist in artists_data:
            connections = []
            for other in artists_data:
                if other["name"] == artist["name"]:
                    continue
                pair = (artist["name"], other["name"])
                if pair in similarity_matrix:
                    sim = similarity_matrix[pair]
                    if sim["score"] > 0:
                        connections.append({
                            "other_artist": other["name"],
                            "score": sim["normalized_score"],
                            "shared_tracks": len(sim["shared_tracks"]),
                            "shared_labels": len(sim["shared_labels"]),
                        })
            connections.sort(key=lambda x: x["score"], reverse=True)
            artist["top_connections"] = connections[:2]

        # Flat list of all sets (for section 6)
        all_sets_flat = []
        for artist in artists_data:
            for s in artist["sets"]:
                entry = dict(s)
                entry["artist_name"] = artist["name"]
                entry["artist_html_rel"] = artist["html_rel"]
                all_sets_flat.append(entry)

        # Serialisable similarity list (no tuple keys)
        seen_pairs: set = set()
        similarity_list = []
        for (a_name, b_name), data in similarity_matrix.items():
            if (b_name, a_name) in seen_pairs:
                continue
            seen_pairs.add((a_name, b_name))
            similarity_list.append({"artist_a": a_name, "artist_b": b_name, **data})
        similarity_list.sort(key=lambda x: x["score"], reverse=True)

        return {
            "global_stats": global_stats,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "artists": artists_data,
            "genre_totals": genre_totals,
            "label_totals": label_totals,
            "most_played_tracks": most_played,
            "similarity_matrix": similarity_matrix,
            "similarity_list": similarity_list,
            "artist_names": [a["name"] for a in artists_data],
            "all_sets": all_sets_flat,
        }


def generate_master_summary(output_root: str | Path) -> Path | None:
    """Generate output/index.html aggregating all artist data.

    Args:
        output_root: Path to the output/ directory.

    Returns:
        Path to the generated index.html, or None if no data found.
    """
    return MasterSummarizer(Path(output_root)).generate()


if __name__ == "__main__":
    import sys
    root = sys.argv[1] if len(sys.argv) > 1 else "output"
    result = generate_master_summary(root)
    if result:
        print(f"\nMaster summary: file://{Path(result).resolve()}")
