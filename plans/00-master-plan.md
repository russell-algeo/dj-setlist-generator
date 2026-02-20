# Master Plan: HTML Output Revamp

## Overview

7 features to make the set-level and artist-level HTML outputs more interactive and delightful. Each feature has a detailed standalone plan in this `plans/` directory. Plans are designed so a fresh Claude Code iOS session can pick up any plan file and execute it independently — all context, file paths, code references, and step-by-step instructions are self-contained.

---

## Feature Summary

### Set-Level Features (modify `html_formatter.py` primarily)

| # | Feature | Plan File | What It Does |
|---|---------|-----------|-------------|
| 1 | **Embedded Player** | `feature-01-embedded-player.md` | Embeds YouTube/SoundCloud player in set HTML; timestamps seek the player instead of opening new tabs; real-time "now playing" highlight as the mix plays |
| 2 | **Track Card Upgrades** | `feature-02-track-card-upgrades.md` | Album art, 30s audio preview, BPM/key, genre tags, expandable detection details, drag-to-reorder; requires enrichment pipeline changes |
| 3 | **Spotify Playlist from HTML** | `feature-03-spotify-integration.md` | Per-track "Save to Liked Songs", bulk playlist creation via OAuth PKCE, inline Spotify embed player widget |

### Artist-Level Features (modify `html_formatter.py` + `artist_summary.py`)

| # | Feature | Plan File | What It Does |
|---|---------|-----------|-------------|
| 4 | **Track Frequency Heatmap** | `feature-04-track-frequency-heatmap.md` | Grid visualization: rows = top tracks, columns = sets, cells colored by confidence |
| 5 | **DJ Signature Analysis** | `feature-05-dj-signature-analysis.md` | Staples vs one-offs, signature score, sparkline trends, genre distribution |
| 6 | **Improved Set Grid** | `feature-06-improved-set-grid.md` | Mini-timeline sparklines, YouTube thumbnails, recognition rate, sort/filter, cross-set search |
| 7 | **Interactive Set Timeline** | `feature-07-interactive-set-timeline.md` | Horizontal scrollable timeline with expandable tracklists, SVG continuity arcs, recurring track highlighting |

---

## Dependency Graph

```
Feature 2 (Track Card Upgrades)
    │
    └──▶ Feature 5 (DJ Signature) uses genre data from Feature 2
         (gracefully degrades without it, but richer with it)

Feature 4, 6, 7 all extend artist_summary.py set_summaries
    (see Conflict Zones below)

Feature 1, 3 are fully independent of everything else
```

**Hard dependencies:** None — every feature can run standalone. Feature 5's genre distribution simply won't render if Feature 2 hasn't added `spotify_genres` to the enrichment pipeline yet.

---

## Parallel Session Strategy (Claude Code iOS)

You'll be running multiple Claude Code iOS sessions simultaneously. Here's the optimal parallelization:

### Round 1: Start 3 parallel sessions

| Session | Feature | Why parallelizable |
|---------|---------|-------------------|
| **Session A** | Feature 1 (Embedded Player) | Only touches `html_formatter.py` set-level JS/CSS/HTML template. Adds new functions, appends CSS. No overlap with Session B's enrichment pipeline changes. |
| **Session B** | Feature 2 (Track Card Upgrades) | Touches `metadata_enricher.py`, `output_formatter.py`, and `html_formatter.py` track card rendering. No overlap with Session A's player code or Session C's artist-level code. |
| **Session C** | Feature 4 (Heatmap) | Touches `artist_summary.py` (adds `confidence` to appearances) + `html_formatter.py` artist-level only (new `_render_heatmap()` function + `_SUMMARY_CSS`). Zero overlap with Sessions A/B which work on set-level code. |

**After Round 1 completes:** Merge all three into master. Merge order: **Feature 2 first** (most structural changes to track cards), then Feature 1 (player overlay), then Feature 4 (artist-level, no set-level conflicts).

### Round 2: Start 3 parallel sessions

| Session | Feature | Why parallelizable |
|---------|---------|-------------------|
| **Session D** | Feature 3 (Spotify Integration) | Only adds to set-level `html_formatter.py` — checkboxes in `_render_track_cards()`, new `_render_spotify_js()` function, playlist controls. Works on top of Features 1 & 2's merged code. |
| **Session E** | Feature 5 (DJ Signature) | Only adds to artist-level — new `_render_signature_analysis()` in `html_formatter.py` + genre extraction in `artist_summary.py`. Independent of Session D's set-level work. Now benefits from Feature 2's genre data in JSON. |
| **Session F** | Feature 7 (Interactive Timeline) | Adds full tracklists to `set_summaries` in `artist_summary.py` + new `_render_set_timeline()` in `html_formatter.py`. Different functions than Session E's signature analysis. |

**After Round 2 completes:** Merge all three. Order: **Feature 5 first** (smallest artist_summary.py change), then Feature 7 (adds tracks to set_summaries), then Feature 3 (set-level only).

### Round 3: Final session

| Session | Feature | Why last |
|---------|---------|---------|
| **Session G** | Feature 6 (Improved Set Grid) | Heavily rewrites `_render_set_cards()` in `html_formatter.py` and adds the most new fields to `set_summaries` in `artist_summary.py`. Running this last avoids conflicts with Features 4, 5, 7 which all also touch `artist_summary.py`. By this point, all other artist-level changes are merged, so Feature 6 can rewrite the set card rendering cleanly on top of the final state. |

---

## How to Start Each Session

When you open a new Claude Code iOS session, give it this prompt template:

```
I'm working on the DJ Set Setlist Generator project. I need you to implement a
feature from a detailed plan file. Please:

1. Read the plan file at: plans/feature-0N-FEATURE_NAME.md
2. Read the master plan at: plans/00-master-plan.md (just the Conflict Zones
   section so you know what to watch out for)
3. Follow the plan step by step
4. Commit when done with a descriptive message

The plan is self-contained with all file paths, code references, and
implementation details. Follow it precisely.
```

Replace `N` and `FEATURE_NAME` with the actual feature number and name.

### Important notes for iOS sessions:

- **Each session works on master** (or a feature branch off master). If you're doing worktrees, create them before starting sessions.
- **Don't start Round 2 until Round 1 is merged.** The plans for Round 2 features assume Round 1 code is already in place.
- **Feature 6 must go last.** It rewrites `_render_set_cards()` which other features' merges may have modified.
- **If a merge conflict occurs**, it will almost certainly be in CSS/JS string constants (just append-append) or in the `set_summaries.append()` dict (just combine all new keys). These are trivial to resolve.

---

## Conflict Zones & Mitigation

### Zone 1: `html_formatter.py` — CSS constant (`CSS` and `_SUMMARY_CSS`)

**Features affected:** Set-level: 1, 2, 3 append to `CSS`. Artist-level: 4, 5, 6, 7 append to `_SUMMARY_CSS`.

**Mitigation:** Each feature appends its CSS at the end with a clear section comment header (e.g., `/* ── Player ── */`, `/* ── Album Art ── */`). Merge conflicts are simple append-append — keep both.

### Zone 2: `html_formatter.py` — JS

**Features affected:** 1 (player JS), 2 (preview/drag JS), 3 (Spotify OAuth JS)

**Mitigation:** Each feature adds JS via a **new function** (`_render_player_js()`, `_render_spotify_js()`) that returns a separate `<script>` block. The existing `JS` constant stays mostly untouched. Only Feature 1 makes a small edit to the timeline click handler in `JS`.

### Zone 3: `html_formatter.py` — `_render_track_cards()`

**Features affected:** 1, 2, 3 (all modify track card rendering)

**This is the highest-conflict zone.** Merge order matters:
1. **Feature 2 first** — most structural change (new grid column for album art, new elements)
2. **Feature 1 second** — changes timestamp `<a>` behavior, adds play button to `.track-actions`
3. **Feature 3 last** — adds checkbox and "Add to Spotify" button to `.track-actions`

### Zone 4: `html_formatter.py` — `save_setlist_html()` template

**Features affected:** 1, 2, 3 insert at different points in the f-string template.

**Mitigation:** Feature 1 inserts player between header and stats. Feature 3 inserts playlist controls between filters and tracklist. These are far apart — git auto-merges cleanly.

### Zone 5: `artist_summary.py` — set_summaries building

**Features affected:** 4, 5, 6, 7 (all add fields to set_summaries dict)

**Mitigation:** All additions are new dict keys (additive only). When merging, just combine all new keys in the `append()` call.

### Zone 6: `html_formatter.py` — `save_artist_summary_html()` template

**Features affected:** 4, 5, 6, 7 insert new `<section>` blocks.

**Target section order in final HTML:**
1. Header + Stats strip (existing)
2. **DJ Signature** (Feature 5)
3. **Set Timeline** (Feature 7)
4. **Sets Analyzed** (existing, enhanced by Feature 6)
5. **Track Frequency Heatmap** (Feature 4)
6. **Most Played Tracks** (existing)
7. Failed sets + Footer (existing)

---

## Merge Sequence (Summary)

```
Round 1 (parallel):
  Session A: Feature 1 (Embedded Player)
  Session B: Feature 2 (Track Card Upgrades)
  Session C: Feature 4 (Heatmap)
  → Merge: Feature 2, then 1, then 4

Round 2 (parallel):
  Session D: Feature 3 (Spotify Integration)
  Session E: Feature 5 (DJ Signature)
  Session F: Feature 7 (Interactive Timeline)
  → Merge: Feature 5, then 7, then 3

Round 3 (solo):
  Session G: Feature 6 (Improved Set Grid)
  → Merge: Feature 6
```

Total: 7 features across 3 rounds, max 3 parallel sessions per round.

---

## Verification After All Features

1. `python main.py "https://youtube.com/watch?v=..."` → open set HTML:
   - Embedded player at top, seeks on timestamp click
   - Album art + genre tags + BPM/key + preview button on cards
   - Expandable detection details, drag-to-reorder
   - Checkboxes + "Create Spotify Playlist" + per-track "Save" + Spotify embed
2. `python main.py "DJ Name"` with 3+ sets → open artist_summary.html:
   - DJ Signature section with score + breakdown bar + sparklines + staple cards
   - Set Timeline with expandable tracklists and SVG continuity arcs
   - Enhanced set grid with thumbnails + mini-timelines + sort/filter + cross-set search
   - Track Frequency Heatmap with hover tooltip and click navigation
3. Edge cases: SoundCloud URLs, disabled Spotify, single-set artists, 10+ set artists
