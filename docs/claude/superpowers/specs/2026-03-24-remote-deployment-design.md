# Remote Deployment Analysis — DJ Set Setlist Generator

**Date:** 2026-03-24
**Status:** Decision document (no code changes)

---

## Implementation Notes (as-built corrections)

The following details differ from the original spec. The as-built behavior is correct; this section records what changed.

| Topic | Original Spec | As Built |
|---|---|---|
| Submission mode names | `single_set`, `artist_discovery`, `curated_artist` | `url`, `artist`, `curated_artist` |
| CLI polling default | 5 s | 15 s (`--interval` flag, adjustable) |
| CLI auth env var | `SET_LIST_API_TOKEN` | `DJSET_API_TOKEN` (or saved token in `~/.config/set_list_worker/auth.json`) |
| DB claim helpers | Not named | `claim_next_artist_submission`, `claim_next_dispatchable_set_run`, `initialize_set_run_leases` |
| `claim_next_lease` | No slot_index arg | Requires `slot_index` parameter |
| Recognition slot default | 2 | Auto-tuned via scheduler; workflow input defaults to `"auto"` |
| Revalidation model | Tag-based ISR | `force-dynamic` + CDN TTL (60 s / 5 min SWR). `revalidatePath` calls kept for router cache hygiene. ISR + `revalidateTag` is the target when public archive pages are rebuilt as Next.js pages with real DB queries. |
| API token hashing | Salted slow hash (argon2id / scrypt) | scrypt (N=16384, r=8, p=1) with per-token random salt stored as `scrypt:<salt_hex>:<hash_hex>` |

---

## Table of Contents

1. [Project Context & Workload Profile](#1-project-context--workload-profile)
2. [Pipeline Execution Platforms](#2-pipeline-execution-platforms)
   - [Tier 1: Genuinely Viable at $0](#tier-1-genuinely-viable-at-0)
   - [Tier 2: Viable with Caveats](#tier-2-viable-with-caveats)
   - [Tier 3: Disqualified](#tier-3-disqualified)
   - [Worth Considering at Small Cost](#worth-considering-if-you-reconsider-the-0-constraint)
   - [Pipeline Execution Ranking](#pipeline-execution-ranking)
3. [Data Storage Platforms](#3-data-storage-platforms)
   - [Relational / SQL Options](#relational--sql-options)
   - [NoSQL / Document Options](#nosql--document-options)
   - [Disqualified](#disqualified-databases)
   - [Data Storage Ranking](#data-storage-ranking)
4. [Static Frontend Hosting](#4-static-frontend-hosting)
5. [Schema Design](#5-schema-design)
   - [Spotify OAuth for Remote Playlist Creation](#5b-spotify-oauth-for-remote-playlist-creation)
   - [Public Repo Considerations](#5c-public-repo-considerations-github-actions)
6. [Combined Architecture Recommendations](#6-combined-architecture-recommendations)
   - [Option A: GitHub Actions + Neon + Cloudflare Pages (Recommended)](#option-a-github-actions--neon--cloudflare-pages-recommended)
   - [Option B: Oracle Cloud VM (All-in-One)](#option-b-oracle-cloud-vm-all-in-one)
   - [Option C: GCP Cloud Run Jobs + Neon + Cloudflare Pages](#option-c-gcp-cloud-run-jobs--neon--cloudflare-pages)
   - [Option D: Single-Vendor GCP Stack](#option-d-single-vendor-gcp-stack)
   - [Option E: Single-Vendor Supabase + GitHub Actions](#option-e-single-vendor-supabase--github-actions)
   - [Option F: AWS Lambda Stream-Direct + Neon + Cloudflare Pages](#option-f-aws-lambda-stream-direct--neon--cloudflare-pages)
   - [Option G: Vercel Stream-Direct + Neon](#option-g-vercel-stream-direct--neon-closest-to-single-vendor)
7. [Final Ranking](#7-final-ranking)
8. [Decision Factors Summary](#8-decision-factors-summary)

---

## 1. Project Context & Workload Profile

### What the Pipeline Does
- Downloads audio from YouTube/SoundCloud via yt-dlp (requires yt-dlp + FFmpeg binaries)
- Segments audio and recognizes tracks via Shazam (async, IO-bound, long-running)
- Enriches metadata via Spotify, Discogs, and ReccoBeats APIs
- Outputs structured data: JSON track listings, artist summaries, interactive HTML pages
- Optionally creates Spotify playlists
- Has a checkpoint system for crash recovery mid-recognition

### Concrete Workload Numbers

| Metric | Value |
|---|---|
| Typical set duration | 60-90 minutes of audio |
| Processing time per set | ~20-30 minutes wall clock |
| Bottleneck | Shazam API calls (IO-bound), not CPU |
| Temp disk per set | ~200-500 MB (audio download + segments) |
| Shazam API calls per set | ~50-200 |
| Final output per set | ~50 KB JSON + ~100 KB HTML |
| Expected weekly volume | 5-10 sets/week |
| Burst scenario | 10-20 sets at once (artist discovery) |
| Monthly volume estimate | 20-40 sets/month typical, up to 80 in heavy months |

### Pipeline Stages — Decomposed View

The current codebase runs the pipeline as a single long-running process (~20-30 min per set). But every stage can be parallelized more aggressively than the current implementation does:

#### Current Implementation (sequential)
```
Download full audio (2-5 min) → Segment all chunks (1-2 min) → Recognize semi-serially (~20 min) → Cluster → Enrich → Store
Total: ~25 min, single machine, 500 MB disk
```

#### Decomposed — Stage Separation (previous analysis)
```
Download+Segment (one worker, 5 min) → Fan out 150× recognition workers (~15 sec each) → Cluster+Enrich (one worker, 3 min)
Total: ~5 min, needs intermediate storage (S3) for audio
```

#### Fully Parallel — Stream-Direct Workers (best approach)

**Key insight:** yt-dlp can extract the direct audio stream URL *without downloading the file*. FFmpeg can read from a remote URL with `-ss` (seek start) and `-t` (duration) to grab just a time slice over HTTP. This means download + segmentation + recognition can all happen inside a single parallel worker, with **zero intermediate storage**:

```
Orchestrator (10 sec):
  1. yt-dlp --get-url → extract direct stream URL
  2. yt-dlp --dump-json → get total duration
  3. Calculate segment offsets (e.g., 150 segments at 30 sec with 15 sec overlap)
  4. Fan out 150 workers, each with: {stream_url, offset, duration}

Workers (×150 in parallel, ~30-60 sec each):
  1. FFmpeg: read from stream_url at offset, extract 30-sec audio chunk (no full download)
  2. Shazam: recognize the chunk
  3. Return: {segment_index, timestamp, track_title, artist, shazam_id, recognized}

Aggregator (2-3 min):
  1. Collect all 150 results
  2. Cluster/deduplicate into setlist
  3. Enrich tracks via Spotify/Discogs/ReccoBeats
  4. Write to database
```

| Stage | Duration | Workers | Needs | Disk | Parallelizable? |
|---|---|---|---|---|---|
| **Orchestrate** | ~10 sec | 1 | yt-dlp (URL extraction only) | None | No |
| **Segment + Recognize** | ~30-60 sec each | **150 parallel** | FFmpeg + Shazam per worker | ~5 MB each (one segment) | **Fully parallel** |
| **Cluster + Enrich** | 2-3 min | 1 | All results + API calls | None | Enrichment parallelizable per track |

**Wall-clock time depends on Shazam IP diversity (see Caveat 2):** Best case ~1-3 minutes (distinct IPs per worker), worst case ~15-25 minutes (shared IP pool), likely ~3-8 minutes (partial IP diversity). The URL access and seeking efficiency have been **empirically validated** — the remaining variable is Shazam throughput on serverless.

**Why this could work:**
- FFmpeg's `-ss` flag can work on remote URLs, not just local files
- Each worker downloads only ~30 seconds of audio (~500 KB) instead of the full file (~200 MB)
- No intermediate storage needed if workers can stream from source
- Workers are stateless and identical — perfect for serverless

**VALIDATED CAVEATS — Empirical testing results and remaining constraints:**

#### Caveat 1: YouTube/SoundCloud stream URLs work cross-IP (EMPIRICALLY VALIDATED)

yt-dlp's FAQ states that requests *"must come from the same IP address and with the same cookies and/or HTTP headers"* ([source](https://github.com/yt-dlp/yt-dlp-wiki/blob/master/FAQ.md)). However, **empirical testing on 2026-03-24 disproved this for the tested sources:**

**Test methodology:** Two laptops. Laptop A resolved stream URLs via yt-dlp. Laptop B consumed those URLs — first on the same Wi-Fi, then on an iPhone hotspot (different public IP). No project code ran on Laptop B; only raw `curl` and `ffmpeg` commands.

**YouTube results** (source: `youtube.com/watch?v=vxjcRkZKBPc`):
- Bare-URL curl from same Wi-Fi: HTTP 206, 1 MB in 0.44s ✓
- Header-bearing curl from same Wi-Fi: HTTP 206, 1 MB in 0.19s ✓
- Bare-URL curl from hotspot (different IP): HTTP 206, 1 MB in 8.1s ✓
- Header-bearing curl from hotspot: HTTP 206, 1 MB in 4.3s ✓
- FFmpeg decode from hotspot (bare URL): success ✓
- FFmpeg decode from hotspot (with headers): success ✓
- The CDN responded with `ipbypass` and `mip` parameters, suggesting it adapted the request to the new network rather than rejecting it
- URLs still worked >25 minutes after resolution

**SoundCloud results** (source: `soundcloud.com/gala-festival/sweely-live-from-the-patio`):
- Resolved as a signed HLS m3u8 URL (not a single media file)
- Bare-URL curl from Laptop B: HTTP 200, 300 KB ✓
- Header-bearing curl from Laptop B: HTTP 200, 300 KB ✓
- FFmpeg slice-read from Laptop B (bare URL): success ✓
- FFmpeg slice-read from Laptop B (with headers): success ✓

**Seeking efficiency** (critical for stream-direct — confirms workers don't secretly download the full file):
- YouTube (62.8 MB full audio): beginning 279 KB / middle 426 KB / end 427 KB — only a few hundred KB per 15-second slice
- SoundCloud: 300 KB consistently across beginning/middle/end positions, 0 seeks, ~1s each

**Key findings:**
1. **Cross-IP access works** — resolved URLs worked from a different machine on a different public IP, without copied headers or cookies
2. **Seeking is efficient** — FFmpeg reads <500 KB per segment, not the full file
3. **URL lifetime is adequate** — URLs remained valid >25 minutes after resolution
4. **Headers/cookies not required** — bare URLs succeeded in all tested scenarios
5. **Both YouTube and SoundCloud validated** — different URL formats (direct media vs. signed HLS), both worked

**Limitations of this testing:**
- Only one YouTube source and one SoundCloud source were tested
- Shazam throughput from distributed workers was NOT tested (see Caveat 2)
- Datacenter IPs (as used by Lambda/Vercel) may behave differently than residential IPs
- Some YouTube content may have stricter access controls (geo-restricted, age-gated, etc.)

**Impact on stream-direct:** The "resolve once, hand URL to 150 workers" model is **validated for the tested sources**. The primary remaining question is whether serverless workers (Lambda/Vercel) get distinct enough IPs to bypass Shazam rate limiting (Caveat 2), not whether they can access the audio stream.

#### Caveat 2: Shazam rate limiting is IP-based — the remaining open question (NOT YET TESTED)

From [ShazamIO issue #120](https://github.com/shazamio/ShazamIO/issues/120):
- Shazam rate limits are **IP-based** — users confirm that VPN-switching to a different IP resets the limit
- One user successfully processed 10,000+ songs overnight by rotating IPs
- The codebase's current `CONCURRENT_RECOGNITIONS` default is 5 (with 2 observed as the practical safe limit before throttling on a single IP)
- When rate-limited, shazamio returns 429 errors; the codebase has a `QUOTA_COOLDOWN_DURATION` of 180 seconds

**The key question is now:** Do serverless workers (Lambda/Vercel/Cloud Run) get distinct enough IPs to bypass Shazam rate limiting?

**Scenario A — Workers share IPs (pessimistic):** Workers from the same cloud provider exit through shared NAT gateways or IP pools. 150 parallel workers all hit the same rate limit, providing no benefit over 2-5 concurrent on a single machine. Processing time: ~15-25 min/set (same as monolithic).

**Scenario B — Workers get distinct IPs (optimistic):** Each worker gets a genuinely different public IP. Shazam rate limiting is bypassed across workers. Processing time: ~1-3 min/set.

**Scenario C — Partial IP diversity (likely):** Workers get IPs from a pool of N distinct addresses. Effective concurrency is N × 2-5 calls per IP. If N=10, that's 20-50 concurrent Shazam calls. Processing time: ~3-8 min/set.

**This is testable.** A follow-up validation can deploy a small number of Lambda/Vercel functions, have each print its public IP, and test Shazam recognition from each. This would resolve the question definitively.

**Impact on architecture:** With Caveat 1 invalidated (URLs work cross-IP), the stream-direct architecture is now validated end-to-end *except* for Shazam throughput on serverless. The architecture should be designed assuming Scenario A (pessimistic) as the baseline, with the ability to benefit from Scenarios B or C without code changes — which is exactly what the fan-out model provides.

#### Caveat 3: FFmpeg on Vercel — works for Node.js, unproven for Python (PARTIALLY VALIDATED)

Vercel's official [ffmpeg-on-vercel](https://github.com/vercel-labs/ffmpeg-on-vercel) demo:
- Uses **Node.js/TypeScript only** (not Python)
- Relies on the `ffmpeg-static` npm package
- Requires Fluid Compute and recommends 3 GB+ memory
- The Python runtime has a 500 MB bundle limit which *should* accommodate a static FFmpeg binary (~100 MB), but there is no official Python + FFmpeg example
- A Vercel community member noted that FFmpeg "is not possible due to the package size limitations" — though this was before the 500 MB Python limit was introduced

**Status:** FFmpeg on Vercel is **confirmed for Node.js**, **unproven for Python**. A Python worker would need to bundle a static FFmpeg binary and execute it via `subprocess`. This is feasible but needs testing. Alternative: rewrite the FFmpeg segmentation in Node.js using the proven `ffmpeg-static` package.

**Note:** The empirical validation above confirmed that FFmpeg can seek efficiently into remote YouTube/SoundCloud URLs from any machine — the question for Vercel is purely about bundling the binary, not about whether the remote-seeking approach works.

#### Revised Realistic Timelines

Given the empirical validation (URLs work cross-IP, seeking is efficient) and the remaining Shazam rate limit uncertainty:

| Architecture | Recognition Parallelism | Est. Time per Set | Why |
|---|---|---|---|
| **Monolithic (current)** | 2-5 concurrent (single IP) | ~20-30 min | Current behavior |
| **Stream-direct, shared IPs (worst case)** | 2-5 concurrent (shared IP pool) | ~15-25 min | URL access validated; Shazam rate limit is the bottleneck |
| **Stream-direct, partial IP diversity** | N distinct IPs × 2-5 each | ~3-8 min | Likely scenario if serverless provides some IP diversity |
| **Stream-direct, full IP diversity** | 150 concurrent (distinct IPs) | ~1-3 min | Best case; testable with a small Lambda/Vercel deployment |
| **Decomposed + proxy rotation** | 2-5 per IP × N proxies | ~3-15 min | Guaranteed IP diversity, adds cost |

**Bottom line:** The stream-direct architecture is now **empirically validated** for URL access and seeking efficiency. The remaining variable is Shazam throughput on serverless — specifically, whether workers get distinct IPs. This is testable and does not require architectural changes to resolve. The fan-out model should be designed to benefit automatically from whatever IP diversity the platform provides.

**Three architectural approaches, re-evaluated after empirical testing:**

- **Monolithic:** Run the entire pipeline as one long job. ~20-30 min per set. Simplest code. No URL-sharing needed but also no parallelism benefits.
- **Stream-direct (validated):** Resolve URL once, fan out workers that each FFmpeg-seek and Shazam-recognize a single segment. ~1-25 min depending on Shazam IP diversity (testable). Zero intermediate storage. Enables serverless platforms with short timeouts.
- **Decomposed + proxy rotation:** Stream-direct workers use rotating proxies for guaranteed distinct IPs. ~3-15 min. Adds cost but guarantees parallelism.

All approaches are evaluated below, with Shazam rate limiting as the remaining open variable (not a known blocker).

### Fundamental Requirements (outcome-focused)

These are what the pipeline must *achieve*, independent of implementation:

1. **Resolve a YouTube/SoundCloud URL** to a playable audio stream (yt-dlp or equivalent)
2. **Extract audio segments** suitable for recognition (~30-second chunks) — can be done from a remote stream URL; does not require downloading the full file first
3. **Recognize each segment** via Shazam API (independent, parallelizable IO calls — each segment is self-contained)
4. **Cluster recognitions** into an ordered, deduplicated setlist
5. **Enrich tracks** with metadata from Spotify, Discogs, YouTube, ReccoBeats
6. **Store structured results** in a database (sets, tracks, artists)
7. **Optionally create a Spotify playlist** from recognized tracks
8. Network access to: YouTube, SoundCloud, Shazam, Spotify, Discogs, ReccoBeats
9. Environment variables for API keys and config

### Design Constraints (from user requirements)
- **Budget:** $0/month ongoing, permanently free tiers only (no 12-month introductory offers)
- **Code change tolerance:** High — full rewrite acceptable if needed. Architecture should optimize for outcomes, not preserve current implementation patterns.
- **Job triggering:** Both CLI and web frontend
- **Concurrency:** Support multiple simultaneous sets (typically 1, occasionally more)
- **Interactivity:** Background processing with polling status is sufficient
- **Data retention:** Only final normalized output in the database; raw artifacts (audio, checkpoints, logs) stay in the execution environment for debugging
- **Frontend:** Eventually public, portfolio-level traffic initially
- **Vendor preference:** Single-vendor stack preferred; mixed stack acceptable if justified
- **Spotify playlists:** Required remotely, with user toggle
- **Docker:** Acceptable
- **yt-dlp hosting:** Must not violate platform ToS
- **Frontend architecture:** Database/API as source of truth (web best practices)
- **Priority order:** Lowest cost > lowest ops burden > best frontend path > best scalability > minimal code changes

---

## 2. Pipeline Execution Platforms

Platforms are evaluated for two architectural approaches:
- **Monolithic:** Can it run a single 20-30 min job? Needs FFmpeg + yt-dlp + ~500 MB disk.
- **Decomposed (stream-direct, empirically validated):** Can it run individual workers (each ~30-60 sec)? Workers need FFmpeg (for remote audio slice extraction) + shazamio + network access. Orchestrator needs yt-dlp (URL extraction only, ~10 sec). Cross-IP URL access and seeking efficiency confirmed by testing.

### Tier 1: Genuinely Viable at $0

---

#### GitHub Actions (Public Repo) — TOP PICK

| Limit | Value | What it means for you |
|---|---|---|
| Minutes/month | **Unlimited** (public repo) | Process unlimited sets for free |
| Minutes/month (private) | 2,000 | ~80 sets/month at 25 min each |
| Job timeout | 6 hours | 12x your worst-case set duration |
| Runner RAM | 16 GB (public) / 8 GB (private) | 16-32x what the pipeline needs at peak |
| Runner disk | 14 GB SSD | Room for multiple concurrent set downloads |
| Runner CPU | 4 cores (public) / 2 cores (private) | Can increase `CONCURRENT_RECOGNITIONS` |
| FFmpeg | **Pre-installed** on ubuntu-latest | Zero setup required |
| Docker support | Yes | Can containerize for reproducibility |
| Always free? | **Yes, permanently** | No expiry, no credit card required |

**How it works:**
1. Define a GitHub Actions workflow with `workflow_dispatch` trigger (accepts parameters: URL, artist name, mode)
2. Workflow installs Python deps, runs the pipeline, writes results to remote database
3. Trigger from CLI via `gh workflow run`, from web frontend via GitHub REST API, or manually from GitHub UI
4. Secrets (API keys) stored in GitHub Secrets — never exposed even in public repos

**Pros:**
- Lowest ops burden of any option — zero servers to manage
- Unlimited free compute on public repos
- FFmpeg pre-installed, Docker available, 16 GB RAM
- Built-in logging, run history, and artifact storage
- Natural CI/CD integration if you want automated testing
- `workflow_dispatch` provides a clean API for triggering from any frontend
- Concurrent jobs supported (up to 20 parallel jobs on free tier)

**Cons:**
- Public repo required for unlimited free minutes (pipeline code visible, but secrets are safe)
- No persistent disk between runs — every run downloads fresh (but your pipeline already handles this via checkpoints)
- Shared GitHub runner IPs — if Shazam rate-limits by IP, you share with other Actions users
- No built-in job queue or web UI for status — you'd build a thin status layer on top
- Workflow dispatch has a 10-input limit per trigger
- yt-dlp on GitHub infrastructure: legitimate use, but GitHub reserves the right to restrict abusive patterns

**Code changes needed:**
- GitHub Actions YAML workflow definition
- Database write layer (pipeline writes results to remote DB instead of local files)
- Status reporting mechanism (write job status to DB for frontend polling)
- API key management via GitHub Secrets
- Dockerfile (optional, for reproducible builds)

---

#### Oracle Cloud Always-Free ARM VM

| Limit | Value | What it means for you |
|---|---|---|
| CPU | 4 ARM OCPUs (splittable across VMs) | More than enough for FFmpeg + concurrent Shazam |
| RAM | 24 GB total | Can run 5+ sets concurrently |
| Disk | 200 GB block storage | Room for ~400 concurrent set downloads |
| Bandwidth | 10 TB/month egress | Essentially unlimited |
| Timeout | **None** — persistent VM | Run as long as needed |
| Always free? | **Yes, permanently** | No expiry |

**How it works:**
- Provision an A1.Flex ARM VM (e.g., 2 OCPU / 12 GB or 4 OCPU / 24 GB)
- Install Python, FFmpeg, yt-dlp via apt
- Run the pipeline directly, or wrap it in a web server (FastAPI) + job queue (Celery/RQ/simple SQLite queue)
- Can also self-host Postgres on the same VM

**Pros:**
- Most powerful free compute available anywhere — 4 OCPU / 24 GB is extraordinary
- Full root access, install anything, no timeout limits
- Can run the entire stack on one VM (pipeline + DB + web server)
- Persistent disk — checkpoints, audio cache, everything survives reboots
- ARM A1 instances have dedicated (not shared/burst) CPU

**Cons:**
- **Idle reclamation is the #1 risk:** Oracle reclaims instances idle for 7 days (CPU < 20%, network < 20%, memory < 20% simultaneously). Requires a keepalive cron job to generate synthetic activity. You get a warning email, but if you miss it, the instance is deleted.
- Oracle Cloud Console UX is notoriously clunky and confusing
- You're fully responsible for ops: OS updates, security patches, firewall rules, backup strategy, SSL certs
- ARM architecture: most Python packages work, but occasional compatibility issues with native extensions
- Instance provisioning: A1.Flex free instances are in high demand — may take multiple retries across regions to successfully create one
- No managed anything — you're running a server, not using a service

**Code changes needed:**
- Web server wrapper (FastAPI or similar) for HTTP job triggering
- Job queue system for background processing
- Database persistence layer
- SSL/domain setup for HTTPS
- Keepalive script for idle reclamation prevention
- Monitoring/alerting setup

---

#### GCP Cloud Run Jobs

| Limit | Value | What it means for you |
|---|---|---|
| Free vCPU-seconds/month | 180,000 | **~120 sets/month** (at 25 min with 1 vCPU) |
| Free GiB-seconds/month | 360,000 | ~120 sets (at 25 min with 1 GiB memory) |
| Free requests/month | 2,000,000 | Far more than needed |
| Task timeout | Up to 24 hours (Jobs) | No issue |
| Memory per task | Up to 32 GiB configurable | Plenty |
| Concurrent tasks | Configurable | Support burst processing |
| FFmpeg | Bundle in Docker image | Full support |
| Always free? | **Yes, permanently** | No expiry |

**Translating the free quota:**
- 1 set = 25 min = 1,500 seconds at 1 vCPU = 1,500 vCPU-seconds
- Monthly budget: 180,000 / 1,500 = **120 sets/month free**
- At 10 sets/week (40/month): uses 33% of free budget
- Burst of 20 sets: uses 17% of monthly budget in one day — comfortably within limits
- At 2 vCPUs per job (for more Shazam parallelism): ~60 sets/month free

**How it works:**
1. Build a Docker image with Python + FFmpeg + yt-dlp + your pipeline code
2. Push to Google Artifact Registry (free tier: 500 MB)
3. Define a Cloud Run Job with the container
4. Trigger via `gcloud` CLI, Cloud Console, or HTTP (via a thin Cloud Run Service or Cloud Function as trigger)
5. Pipeline runs in the container, writes results to remote DB, exits
6. Container is destroyed after completion — no persistent state

**Pros:**
- 120 sets/month free is generous and covers your workload with headroom
- Proper container platform — reproducible, isolated builds
- No server to manage — Google handles scaling, scheduling, retry
- Cloud Run Jobs support task-level parallelism (process multiple sets concurrently)
- Pairs well with other GCP services (Firestore, Cloud Storage, etc.)
- Good logging via Cloud Logging (free tier: 50 GB/month)

**Cons:**
- Requires Docker container (you said this is fine)
- GCP account requires billing enabled + credit card (even for free tier — won't charge if within limits)
- No persistent disk — audio downloads and segments exist only during the job run
- Container image pull adds ~10-30 seconds cold start on first run after idle
- More GCP-specific configuration than GitHub Actions (IAM, Artifact Registry, Job definition)
- 500 MB Artifact Registry free tier is tight — a Docker image with `python:3.11-slim` (~130 MB) + FFmpeg (~100 MB) + Python deps (shazamio, spotipy, yt-dlp: ~200+ MB) could exceed 500 MB uncompressed. Mitigation: use multi-stage builds, Alpine base, or store in Docker Hub (free) instead of Artifact Registry

**Code changes needed:**
- Dockerfile
- Database write layer
- Job trigger mechanism (thin Cloud Run Service or Cloud Function)
- GCP-specific configuration (service account, IAM, Artifact Registry)

---

### Tier 2: Viable with Caveats

---

#### GCP Compute Engine e2-micro

| Limit | Value | What it means for you |
|---|---|---|
| CPU | 2 vCPU (burst), ~0.25 baseline | IO-bound Shazam calls may be fine |
| RAM | **1 GB** | **Risky** for FFmpeg + Python + async HTTP |
| Disk | 30 GB standard persistent | ~60 set downloads |
| Bandwidth egress | 1 GB/month (to most destinations) | Tight — but pipeline mostly *downloads* (ingress is free) |
| Always free? | **Yes** (us-west1/us-central1/us-east1 only) | No expiry |

**Verdict:** The 1 GB RAM is the critical constraint. FFmpeg transcoding + Python interpreter + shazamio async tasks + yt-dlp could collectively push past 1 GB, causing OOM kills. The pipeline might work if you reduce `CONCURRENT_RECOGNITIONS` to 1-2, but it's fragile.

**Best role:** A lightweight always-on orchestrator that *triggers* jobs elsewhere (e.g., dispatches GitHub Actions workflows), hosts a small web frontend, or runs a job queue — but doesn't execute the heavy pipeline itself.

---

#### AWS Lambda (Decomposed Architecture) — VIABLE WITH DECOMPOSITION

| Limit | Value | What it means for you |
|---|---|---|
| Invocations/month | 1,000,000 | Far more than needed |
| Compute | 400,000 GB-seconds/month | See decomposed budget below |
| **Max timeout** | **15 minutes** | Dealbreaker for monolithic; **fine for decomposed stages** |
| Memory | Up to 10 GB | Plenty |
| Ephemeral storage | 512 MB (10 GB paid) | Fits one set's audio |
| FFmpeg | Bundle as Lambda Layer or container | Works |
| Always free? | **Yes, permanently** | No expiry |

**Monolithic verdict: DISQUALIFIED.** 15-minute timeout vs. 20-30 min pipeline.

**Fully parallel (stream-direct) verdict: EXCELLENT.** With stream-direct workers, no single invocation needs more than ~60 seconds:

1. **Orchestrator Lambda** (~10 sec, 256 MB):
   - `yt-dlp --get-url` to extract direct audio stream URL (no download)
   - `yt-dlp --dump-json` to get duration
   - Calculate segment offsets (e.g., 150 segments for a 90-min set)
   - Fan out 150 worker Lambda invocations via Step Functions Map state

2. **Segment+Recognize Lambda (×150 parallel)** (~30-60 sec each, 512 MB):
   - FFmpeg reads from remote stream URL at given offset (`-ss`) for given duration (`-t`) — downloads only ~500 KB of audio per segment, not the full file
   - Shazam recognizes the segment
   - Returns `{segment_index, timestamp, track_title, artist, shazam_id, recognized}`
   - Worker is fully self-contained — no S3, no shared state

3. **Cluster + Enrich Lambda** (~2-3 min, 1 GB):
   - Receives all 150 recognition results from Step Functions
   - Clusters/deduplicates into setlist
   - Enriches via Spotify/Discogs/ReccoBeats
   - Writes final output to database
   - Optionally creates Spotify playlist

**No intermediate storage (S3) needed.** Each worker streams its own audio slice directly from the source URL.

**Free tier budget (stream-direct):**
- Orchestrator: 1 × 10 sec × 0.25 GB = 2.5 GB-seconds per set
- Recognition workers: 150 × 45 sec × 0.5 GB = 3,375 GB-seconds per set
- Cluster+Enrich: 1 × 3 min × 1 GB = 180 GB-seconds per set
- Total: ~3,558 GB-seconds per set
- Monthly budget: 400,000 / 3,558 = **~112 sets/month free**
- Wall-clock time: **~1-25 min** depending on Shazam IP diversity (see Caveat 2). Stream-direct URL access is empirically validated. Likely ~3-8 min with partial IP diversity.

**Stage-separated variant (fallback):**
If some audio sources don't support HTTP seeking (not observed in testing, but possible for edge cases), fall back to a Download+Segment Lambda that downloads the full file, uploads segments to S3, then fans out recognition workers. This uses more GB-seconds per set (~1,530 total) but supports **~261 sets/month free**.

**Pros:**
- **Potentially fastest: ~1-3 min/set** (if workers get distinct IPs); ~3-8 min likely; ~15-25 min worst case
- 112-261 sets/month free depending on variant
- No server to manage, no idle costs, no reclamation
- AWS Step Functions orchestrates stages (free tier: 4,000 state transitions/month — supports ~26 sets/month with 150 workers each; Express Workflows have no transition limit but are not always-free)
- No intermediate storage needed in stream-direct variant
- Each worker is stateless and identical — trivially scalable

**Cons:**
- Most complex architecture — orchestrator + worker Lambda + aggregator Lambda + Step Functions
- AWS ecosystem lock-in (Lambda + Step Functions)
- FFmpeg must be bundled as a Lambda Layer or container image (~100 MB)
- Step Functions Standard free tier (4,000 transitions/month) is a bottleneck: 150 workers × 3 transitions each = 450 per set, so ~8 sets/month before hitting the limit. **Mitigation:** Use Step Functions Express Workflows (priced per execution, not per transition — but not always-free) or use SQS + a coordination Lambda instead of Step Functions
- YouTube may rate-limit 150 parallel FFmpeg connections from the same IP/range — may need to throttle to ~50 concurrent (empirical testing used 1 consumer; 150 concurrent untested)
- AWS account management overhead (IAM, billing alerts, etc.)

**Step Functions bottleneck — important detail:**
The 4,000 free Standard Workflow transitions/month is the tightest constraint. A single set with 150 workers uses ~450 transitions (start + succeed + next for each parallel branch). That's only ~8 sets/month on the free tier of Standard Workflows. Solutions:
1. **SQS-based fan-out** instead of Step Functions — SQS has 1M free requests/month, plenty for this
2. **Step Functions Express Workflows** — charged per execution+duration, not per transition. Cost: ~$0.000025 per set. Effectively free but technically not $0.
3. **Reduce parallelism** — 50 workers instead of 150 uses ~150 transitions per set = ~26 sets/month on free tier
4. **Simple coordination Lambda** — fan out via async Lambda invocations, track completion in DynamoDB, trigger aggregator when all done. No Step Functions needed.

**When this approach wins:** If you want the best processing speed and don't mind the architectural complexity. The stream-direct model is **empirically validated** for URL access and seeking — a 90-minute set could be processed in 1-8 minutes depending on Shazam IP diversity.

---

#### Vercel (Stream-Direct Workers) — VIABLE WITH DECOMPOSITION

| Limit | Value | What it means for you |
|---|---|---|
| Function timeout (Hobby) | **300 seconds (5 minutes)** | ~5-8x headroom for stream-direct workers (~30-60 sec each) |
| Function memory (Hobby) | 2 GB / 1 vCPU | Comfortable for FFmpeg + Shazam per worker |
| Python runtime | Python 3.12-3.14, 500 MB bundle | Python supported natively; 500 MB fits FFmpeg + deps |
| Concurrency (Hobby) | Auto-scales up to 30,000 | Easily handles 150 parallel workers |
| Invocations/month | Included in Hobby plan | Within limits for your volume |
| Active CPU time (Hobby) | 100 hours/month | See budget below |
| Always free? | **Yes** (Hobby plan, personal/non-commercial) | No expiry |

**Monolithic verdict: DISQUALIFIED.** 5-minute timeout vs. 20-30 min pipeline.

**Stream-direct verdict: VIABLE and validated.** With Fluid Compute (enabled by default), Vercel Hobby gives 5 minutes per function — plenty of headroom for stream-direct workers that take ~30-60 sec each. Vercel now supports Python natively (3.12-3.14) with a 500 MB bundle size, which could accommodate FFmpeg. The stream-direct URL access pattern (resolve once, seek from workers) has been **empirically validated** for YouTube and SoundCloud.

**How it would work on Vercel:**
1. **Orchestrator endpoint** (Python function, ~10 sec): Receives job request, uses yt-dlp to extract stream URL and duration, calculates segment offsets, fans out worker invocations
2. **Stream-direct worker endpoint (×150 parallel)** (Python function, ~30-60 sec): FFmpeg reads from remote stream URL at offset, Shazam recognizes, returns result
3. **Aggregator endpoint** (Python function, ~2-3 min): Collects results, clusters, enriches, writes to DB

**Free tier budget:**
- Vercel Hobby includes 100 hours/month of active CPU time
- Each worker uses ~30 sec of CPU time → 150 workers = 75 min per set
- 100 hours / 1.25 hours per set = **~80 sets/month free**
- Provisioned memory: 1,000 GB-hours/month included → 150 workers × 60 sec × 2 GB = 5 GB-hours per set → 200 sets/month (not the bottleneck)

**Pros:**
- Same platform hosts frontend AND runs pipeline — true single-vendor for everything except the database
- Python supported natively with 500 MB bundle (enough for FFmpeg)
- 5-minute timeout provides comfortable headroom
- Auto-scaling to 30K concurrency handles parallel fan-out
- Excellent frontend DX (Next.js, Astro, etc.)
- Free `*.vercel.app` subdomain with SSL

**Cons:**
- **Non-commercial use only** on Hobby plan — if the project generates revenue, you need Pro ($20/month)
- Bundling FFmpeg in a Python function is possible but untested at 500 MB limit — may need a static FFmpeg binary
- No built-in fan-out/orchestration (you'd invoke workers via HTTP calls from the orchestrator)
- yt-dlp as a Python dependency adds to bundle size
- 100 hours/month CPU time is the binding constraint (~80 sets/month)
- Less isolation than Lambda — all functions share the same deployment
- 4.5 MB request/response body size limit — audio segments must be streamed, not passed as payloads (fine for stream-direct since workers read from the remote URL)

**Best role for Vercel:** Could be the entire stack (frontend + pipeline workers + API) paired with an external database (Neon). This is the strongest single-platform option if the non-commercial restriction is acceptable.

---

#### Cloudflare Workers (Decomposed — Recognition Fan-Out Only)

| Limit | Free Plan | What it means for you |
|---|---|---|
| CPU time per request | 10 ms | **Cannot run FFmpeg or yt-dlp** |
| Requests/day | 100,000 | Plenty for recognition fan-out |
| Memory | 128 MB | Enough for a single Shazam HTTP call |
| Subrequests | 50 per invocation | Limits fan-out from a single Worker |

**Monolithic verdict: DISQUALIFIED.** No native binaries, 10ms CPU time.

**Decomposed verdict: MARGINALLY VIABLE for recognition only.** A Worker could make a single Shazam HTTP call (fetch API, not shazamio library) and return the result. But:
- You'd need to rewrite the Shazam recognition in JavaScript/TypeScript (shazamio is Python-only)
- 10ms CPU time may not be enough for audio fingerprinting if any local processing is needed
- The download/segment stage still needs another platform
- Workers can't directly read audio files from S3 or Cloud Storage without subrequest limits

**Best role for Cloudflare:** Pages for frontend hosting (excellent), D1/KV for caching, Workers for lightweight API proxying. **Not for pipeline execution.**

---

### Tier 3: Disqualified (Even with Decomposition)

| Platform | Why even decomposition doesn't help |
|---|---|
| **Render Free** | No background workers on free tier ($7/month minimum). Free Web Service sleeps after 15 min inactivity. Even lightweight stages need a background execution context. |
| **Fly.io** | No free tier for new accounts (eliminated October 2024). Pay-as-you-go only. |
| **Railway** | $1/month free credit insufficient for any meaningful compute. |
| **Hetzner** | No free tier whatsoever. |
| **DigitalOcean** | No free tier. $200 trial for 60 days, then paid. |

### Worth Considering if You Reconsider the $0 Constraint

| Platform | Monthly Cost | What You Get | Why It Might Be Worth It |
|---|---|---|---|
| **Fly.io** | ~$3-5/month | Persistent VM, excellent CLI (`flyctl`), auto-deploy from Git, built-in Postgres | Best developer experience of any container platform. Deploy with `fly deploy`, done. |
| **Railway** | $5/month | Docker containers, managed deploys, built-in logging, database add-ons | Zero-config container hosting. Push to Git, it deploys. |
| **Render Starter** | $7/month | Background workers, 512 MB-4 GB RAM, persistent disk, managed Postgres | Purpose-built for background jobs. Simplest worker setup. |

**The pitch:** $5/month eliminates the Oracle idle-reclamation dance, GitHub Actions public-repo exposure, and GCP container orchestration overhead. If your time debugging infrastructure is worth more than $60/year, a paid tier pays for itself in ops burden reduction.

---

### Pipeline Execution Ranking

**Ranked by: cost > ops burden > frontend path > scalability > code changes**

#### Monolithic (single long-running job)

| Rank | Platform | Cost | Ops Burden | Sets/Month (free) | Processing Time/Set | Verdict |
|---|---|---|---|---|---|---|
| 1 | **GitHub Actions** | $0 | Very low | Unlimited (public) / 80 (private) | ~25 min | Best overall: zero servers, unlimited compute, FFmpeg pre-installed |
| 2 | **GCP Cloud Run Jobs** | $0 | Low | ~120 | ~25 min | Strong runner-up: proper container platform, good free quota |
| 3 | **Oracle Cloud ARM VM** | $0 | **High** | Unlimited | ~25 min | Most powerful, but ops burden is significant |
| 4 | **GCP e2-micro** | $0 | Medium | Unlimited (if RAM suffices) | ~25 min | Only viable as orchestrator, not primary compute |

#### Decomposed (stream-direct, empirically validated)

| Rank | Platform | Cost | Ops Burden | Sets/Month (free) | Processing Time/Set | Verdict |
|---|---|---|---|---|---|---|
| 1 | **AWS Lambda + Step Functions** | $0 | Medium | ~112-261 | **~1-8 min*** | Fastest processing; most complex architecture |
| 2 | **Vercel Functions** | $0 | Low | ~80 | ~1-8 min* | Single-platform (frontend + compute); simplest decomposed |
| 3 | **GCP Cloud Run Jobs (multi-task)** | $0 | Low-medium | ~120 | ~1-8 min* | Cloud Run Jobs support task parallelism natively |
| 4 | **GitHub Actions (matrix strategy)** | $0 | Low | Unlimited (public) | ~5-10 min | Matrix jobs for parallel recognition; simpler than Lambda |

*\* Stream-direct URL access is empirically validated. Processing time depends on Shazam IP diversity on serverless (testable): best ~1-3 min, likely ~3-8 min, worst ~15-25 min.*

**Key trade-off:** Decomposed architectures trade code complexity for processing speed and unlock platforms that were previously disqualified by timeout limits. The stream-direct approach is **validated** (URL access, seeking efficiency, cross-IP access all confirmed) and is worth it if:
- You process sets frequently enough that speed matters (potentially 25 min → 1-8 min per set)
- You want to burst-process 10-20 sets and don't want to wait hours
- You want to use AWS Lambda or Vercel's free tiers (which are generous and serverless)
- You want zero intermediate storage (each worker streams directly from source)

---

## 3. Data Storage Platforms

### Your Data Profile

Based on analysis of the project's actual output:

| Data Type | Size Per Set | At 500 Sets | At 2,000 Sets |
|---|---|---|---|
| Set JSON | ~15 KB | 7.5 MB | 30 MB |
| Artist summary JSON | ~120 KB per artist | ~6 MB (50 artists) | ~24 MB (200 artists) |
| Track records (DB rows) | ~500 bytes per track | 5 MB (10K tracks) | 20 MB (40K tracks) |
| Total structured data | — | **~20 MB** | **~75 MB** |

Even at 2,000 sets, the total structured data is well under 100 MB. Every database free tier listed below can handle this volume with room to spare. The differentiators are: operational friction, query capabilities, frontend integration, and pausing/sleep policies.

### Relational / SQL Options

---

#### Neon (Serverless Postgres) — TOP PICK

| Limit | Value | Adequate? |
|---|---|---|
| Storage | 512 MB per project | ~6,800 sets worth of structured data — yes |
| Compute | 100 CU-hours/month | See compute budget breakdown below |
| Branches | 10 per project | Useful for dev/staging/prod |
| Projects | 100 | More than enough |
| Auto-suspend | After 5 min idle (compute only) | **Data always accessible**, compute wakes on connection (~500ms cold start) |
| Always free? | **Yes, permanently** | No expiry |

**Compute budget breakdown (100 CU-hours/month at 0.25 CU minimum):**
- Neon's smallest compute is 0.25 CU. 100 CU-hours / 0.25 CU = 400 hours of active compute per month.
- Auto-suspend kicks in after 5 minutes of idle, so compute only runs when queries are active.
- **Pipeline writes:** 40 sets/month × ~30 seconds of DB writes each = ~20 minutes/month. Negligible.
- **Frontend page loads:** Each page view wakes compute (if suspended) and runs queries. At 0.25 CU, a page load keeping compute active for ~10 seconds = 0.0007 CU-hours. You'd need ~143,000 page views/month to exhaust the budget. At portfolio traffic (hundreds of views/month), this is a non-issue.
- **If compute ran continuously** (hypothetical worst case): 0.25 CU × 24h × 30 days = 180 CU-hours, which exceeds the 100 CU-hour budget. But auto-suspend at 5 minutes of idle means this only happens if you have constant query traffic — impossible at portfolio scale.
- **Bottom line:** At your traffic level, you'll use <5% of the compute budget.

**Key advantage over Supabase:** Neon only suspends *compute* (the Postgres process), not the project. Data persists and the database auto-wakes on connection. No manual intervention needed. For a pipeline that writes sporadically and then sits idle, this is dramatically better than Supabase's 7-day project pause.

**Frontend integration:** Neon provides a standard Postgres connection string. Works with any ORM (SQLAlchemy, Prisma, Drizzle), any framework (Next.js, FastAPI), and any serverless platform. Neon also offers a serverless HTTP driver for edge deployments.

**Pros:**
- Standard Postgres — no vendor lock-in, use any Postgres tool
- Auto-suspend/wake is seamless (no manual unpause)
- Branching for safe schema migrations
- Serverless HTTP driver for edge/serverless access
- Dashboard with SQL editor, monitoring, query insights

**Cons:**
- 512 MB storage is the ceiling (ample for your data, but finite)
- Cold start after idle (~500ms) — imperceptible for your use case
- No built-in auth, storage, or edge functions (unlike Supabase)

---

#### Supabase (Postgres + Platform)

| Limit | Value | Adequate? |
|---|---|---|
| Database storage | 500 MB | ~6,600 sets — yes |
| File storage | 1 GB | Can store album art, thumbnails |
| API requests | Unlimited | Yes |
| Edge function invocations | 500,000/month | Yes |
| Auth (MAUs) | 50,000 | More than enough for portfolio traffic |
| Active projects | 2 | Constraining if you want dev + prod |
| **Pausing policy** | **Pauses after 7 days inactivity** | **Problematic for automated pipeline** |
| Always free? | **Yes, permanently** | No expiry |

**The 7-day pause problem:** If your pipeline doesn't write to Supabase for a week, the project pauses automatically. Resuming requires logging into the Supabase dashboard manually. For an automated pipeline that runs 5-10 times per week, this is *usually* fine — but a vacation or slow week means a paused project and failed pipeline runs until you manually unpause.

**Workaround:** Schedule a weekly keepalive query (e.g., via GitHub Actions cron) to prevent pausing. Adds operational complexity.

**Frontend integration:** Supabase is the strongest option here. It provides:
- Auto-generated REST API (PostgREST) — query your DB from any frontend without a custom backend
- Auth (email, OAuth, magic links) — for future public access control
- Realtime subscriptions — live updates if you want them
- Edge functions (Deno) — serverless compute at the edge
- File storage — for album art, profile images
- Row-level security — fine-grained access control

**Pros:**
- Most complete "backend-as-a-service" — auth, storage, API, edge functions included
- Best frontend development path of any option
- PostgREST auto-generates a REST API from your schema
- Dashboard with table editor, SQL editor, logs
- Strong community, good documentation

**Cons:**
- **7-day inactivity pause** is a real operational issue
- Only 2 free projects (no separate dev/staging)
- Supabase-specific features create some vendor lock-in beyond standard Postgres

---

#### Turso (Distributed SQLite / libSQL)

| Limit | Value | Adequate? |
|---|---|---|
| Storage | 5 GB total | ~66,000 sets — yes, very generous |
| Databases | 100 | Yes |
| Row reads/month | 500 million | Far more than needed |
| Row writes/month | 10 million | Far more than needed |
| Always free? | **Yes, permanently** | No expiry |

**Architecture note:** Turso runs libSQL (a fork of SQLite) distributed across edge locations. It's SQLite-compatible, which means simpler tooling but fewer advanced Postgres features (no JSON operators, limited window functions, no full-text search without extensions).

**Pros:**
- Most generous storage free tier (5 GB)
- SQLite-compatible — simple, well-understood
- Edge-distributed for fast reads globally
- Embedded replicas for offline-capable apps

**Cons:**
- SQLite, not Postgres — fewer advanced query capabilities
- Smaller ecosystem and community than Postgres
- Less natural fit for a relational schema with joins
- No built-in auth, API, or storage platform

---

#### CockroachDB Basic (Distributed Postgres-Compatible)

| Limit | Value | Adequate? |
|---|---|---|
| Storage | 5 GiB | ~66,000 sets — yes |
| Request Units | 50M RUs/month | Adequate for your read/write volume |
| Always free? | **Yes, permanently** | No credit card required |

**Pros:**
- 5 GiB free storage is generous
- Postgres-compatible SQL
- Distributed, highly available
- No credit card required

**Cons:**
- Request Unit pricing model is opaque — hard to predict exactly when you'd hit limits
- Heavier than you need (CockroachDB is designed for multi-region distributed systems)
- Smaller community tooling compared to Postgres/Neon/Supabase
- Dashboard and DX are less polished than Neon or Supabase

---

#### Cloudflare D1 (SQLite at the Edge)

| Limit | Value | Adequate? |
|---|---|---|
| Storage per database | 500 MB | Yes |
| Total storage | 5 GB | Yes |
| Databases | 10 | Yes |
| Always free? | **Yes, permanently** | No expiry |

**Critical constraint:** D1 is only accessible from Cloudflare Workers. Your Python pipeline running on GitHub Actions or a VM can't connect to D1 directly — you'd need to write to D1 via an HTTP API exposed by a Cloudflare Worker. This adds a layer of indirection and means your DB access is always mediated by JavaScript/TypeScript Worker code.

**Best for:** If you go all-in on Cloudflare (Pages + Workers + D1). Not ideal for a Python-first pipeline.

---

### NoSQL / Document Options

---

#### AWS DynamoDB

| Limit | Value | Adequate? |
|---|---|---|
| Storage | 25 GB | Yes, very generous |
| Write capacity | 25 WCUs (sustained) | ~25 writes/sec — far exceeds your needs |
| Read capacity | 25 RCUs (sustained) | ~25 reads/sec — adequate for portfolio traffic |
| Always free? | **Yes, permanently** | No expiry |

**Pros:**
- 25 GB is the most generous free storage of any option
- Always-free, no sleep, no pause, no credit card surprises
- Your setlist JSON maps naturally to DynamoDB documents
- Predictable performance at low scale

**Cons:**
- NoSQL (key-value/document) — no SQL, no joins, no relational queries
- Querying across entities (e.g., "all tracks by label X across all sets") requires secondary indexes and careful data modeling
- AWS-specific — heavy vendor lock-in
- Frontend integration requires either AWS Amplify or a custom API layer
- DynamoDB's data modeling paradigm (single-table design, access-pattern-first) is a learning curve

---

#### MongoDB Atlas Free (M0)

| Limit | Value | Adequate? |
|---|---|---|
| Storage | 512 MB | Yes |
| Connections | 500 max | Yes |
| Operations | 100 ops/sec | Yes for portfolio traffic |
| Backups | **Not available** | No backups on free tier |
| Always free? | **Yes, permanently** | No expiry |

**Pros:**
- JSON document storage maps directly to your existing output format
- Flexible schema — easy to evolve without migrations
- MongoDB Query Language is powerful for document traversal

**Cons:**
- No backups on free tier — data loss risk
- 512 MB is adequate but not generous
- No relational integrity — if you want "all sets containing track X," you need to design for it
- MongoDB-specific query language (not SQL)
- Frontend integration requires a custom API or MongoDB Realm (now Atlas App Services)

---

#### GCP Firestore

| Limit | Value | Adequate? |
|---|---|---|
| Storage | 1 GB | Yes |
| Reads/day | 50,000 | Yes for portfolio traffic |
| Writes/day | 20,000 | Yes — pipeline writes a batch per set |
| Always free? | **Yes, permanently** (daily quota) | No expiry |

**Pros:**
- 1 GB storage is decent
- Always-free daily quotas, no pausing
- Document model fits your nested JSON
- Good Firebase/GCP integration
- Realtime listeners for live frontend updates

**Cons:**
- Not SQL — Firestore Query Language has significant limitations (no joins, no aggregations beyond count/sum/avg)
- Daily quota resets could cause issues if you hit limits mid-pipeline (unlikely at your scale)
- Vendor lock-in to GCP/Firebase
- Complex pricing model at scale (per-read/write/delete)

---

### Disqualified Databases

| Platform | Why |
|---|---|
| **PlanetScale** | Free tier eliminated April 2024. Minimum $39/month. |
| **AWS RDS** | 12-month trial only (not always-free). New accounts after July 2025 get no RDS free tier at all. |
| **GCP Cloud SQL** | No free tier. Minimum ~$9/month. |

---

### Data Storage Ranking

**Ranked by: cost > ops burden > frontend path > scalability > code changes**

| Rank | Platform | Type | Free Storage | Pausing? | Frontend Path | Verdict |
|---|---|---|---|---|---|---|
| 1 | **Neon** | Postgres | 512 MB | Compute only (auto-wakes) | Standard Postgres — works with everything | Best balance of reliability, simplicity, and flexibility |
| 2 | **Supabase** | Postgres + Platform | 500 MB | **7-day project pause** | Best (built-in API, auth, storage) | Best frontend DX, but pause policy is a real ops issue |
| 3 | **Turso** | SQLite (edge) | 5 GB | No | SDK-based access | Most generous storage; simpler but less capable than Postgres |
| 4 | **CockroachDB** | Postgres-compat | 5 GiB | No | Standard Postgres | Generous storage, but heavier than needed |
| 5 | **AWS DynamoDB** | NoSQL | 25 GB | No | Requires custom API | Most storage, but NoSQL limits query flexibility |
| 6 | **Cloudflare D1** | SQLite (edge) | 5 GB | No | Workers-only access | Great if all-in on Cloudflare, awkward otherwise |
| 7 | **GCP Firestore** | NoSQL | 1 GB | No | Firebase SDK | Good GCP integration, limited query capabilities |
| 8 | **MongoDB Atlas** | NoSQL | 512 MB | No | Requires custom API | No backups on free tier is concerning |

---

## 4. Static Frontend Hosting

For the web frontend that displays setlists, artist summaries, and provides job triggering.

| Platform | Bandwidth | Builds/month | Custom Domains | Free Subdomain | Always Free? | Notes |
|---|---|---|---|---|---|---|
| **Cloudflare Pages** | **Unlimited** | 500 | Yes (free) | `*.pages.dev` | Yes | Clear winner: unlimited bandwidth, no commercial restrictions |
| **Vercel** | 100 GB | 6,000 build-min | Yes (free) | `*.vercel.app` | Yes | Good DX but non-commercial use only on Hobby plan |
| **GitHub Pages** | 100 GB soft | Via git push | Yes (free) | `*.github.io` | Yes | Static only, no serverless functions |
| **Netlify** | 100 GB | 100 build-min | Yes (free) | `*.netlify.app` | Yes | Build minutes cut to 100/month in 2025 |

**Recommendation: Cloudflare Pages** — unlimited bandwidth, 500 builds/month, free custom domains, no commercial-use restriction, fast global CDN. The `*.pages.dev` subdomain is clean and professional for portfolio use.

---

## 5. Schema Design

### Proposed Relational Schema (Postgres / Neon)

The data naturally fits a relational model with four core tables:

```
artists
├── id (PK, auto-increment)
├── name (unique, indexed)
├── profile_image_url
├── profile_source ("spotify" | "discogs" | null)
├── profile_url
├── profile_confidence (float, 0-1)
├── profile_genre_overlap (float, 0-1)
├── genres (text[] or jsonb)
├── expected_genres (jsonb — genres used for image validation)
├── spotify_profile (jsonb — {name, image, url, genres})
├── discogs_profile (jsonb — {name, image, url, genres})
├── profile_rejected_reason (text, nullable)
├── created_at
└── updated_at

sets
├── id (PK, auto-increment)
├── artist_id (FK → artists, nullable for URL-mode sets)
├── title
├── source_url (unique, indexed)
├── platform ("youtube" | "soundcloud")
├── duration_seconds
├── uploader
├── track_count
├── recognition_rate (float — computed and stored for fast access)
├── processing_status ("pending" | "processing" | "completed" | "failed")
├── processed_at
├── created_at
└── updated_at

tracks
├── id (PK, auto-increment)
├── set_id (FK → sets)
├── position (1-indexed order in set)
├── title
├── artist_name
├── start_time_seconds
├── end_time_seconds
├── start_time_formatted
├── end_time_formatted
├── confidence ("HIGH" | "MEDIUM" | "LOW" | "UNCERTAIN")
├── detection_count
├── cluster_density
├── cluster_span
├── source_deep_link
├── spotify_url
├── spotify_album_art
├── spotify_preview_url
├── spotify_artist_id
├── spotify_artist_name
├── spotify_artist_url
├── spotify_artist_image
├── spotify_genres (text[] or jsonb)
├── youtube_url
├── discogs_url
├── discogs_label
├── discogs_label_url
├── discogs_genres (text[] or jsonb)
├── discogs_styles (text[] or jsonb)
├── bpm
├── musical_key
├── energy
├── danceability
└── created_at

jobs
├── id (PK, uuid)
├── mode ("url" | "artist" | "curated")
├── input (jsonb — URLs, artist name, etc.)
├── status ("queued" | "running" | "completed" | "failed")
├── progress (jsonb — current step, sets processed, etc.)
├── error_message
├── runner_id (GitHub Actions run ID, Cloud Run job ID, etc.)
├── started_at
├── completed_at
└── created_at
```

**Why this schema:**
- `artists` ↔ `sets` is 1:many (one artist has many sets; URL-mode sets have null artist_id)
- `sets` ↔ `tracks` is 1:many (one set has many tracks)
- `jobs` tracks pipeline execution for frontend status polling
- Track metadata (Spotify, Discogs, YouTube URLs, BPM, key) is denormalized onto the `tracks` table — each track-in-a-set has its own enrichment data
- Artist profile validation metadata (confidence, genre overlap, per-provider profiles) stored on `artists` table — supports debugging profile image selection
- `spotify_profile` and `discogs_profile` JSONB columns capture per-provider data without column explosion
- `recognition_rate` stored denormalized on `sets` for fast listing queries (recomputable from track counts)
- `processing_status` on `sets` enables the frontend to show which sets are still being processed
- Indexes on: `artists.name`, `sets.source_url`, `tracks.set_id`, `tracks.title`, `tracks.artist_name`

**Artist summaries are computed, not stored:** The current `artist_summary.json` contains aggregate stats (`sets_analyzed`, `unique_tracks`, `total_track_appearances`, confidence breakdowns, mini-timelines). In the database-backed architecture, these are computed on-the-fly via SQL queries against the `sets` and `tracks` tables. This eliminates stale summary data and reduces storage. The frontend or API layer runs the aggregation queries when rendering an artist page.

**Data migration:** Existing output data (~80+ sets across 20+ artists in `output/`) will need a one-time migration script that reads each JSON file and inserts records into the database. This is straightforward since the JSON structure maps directly to the schema.

**Future considerations (not needed now):**
- A `unique_tracks` table for deduplication across sets (same track appearing in multiple sets)
- Full-text search index on track title + artist name
- A `labels` table for Discogs label aggregation
- A `genres` table for normalized genre taxonomy

---

## 5b. Spotify OAuth for Remote Playlist Creation

Creating Spotify playlists requires the OAuth 2.0 Authorization Code flow — the user must grant permission via a browser redirect. This is fundamentally different from the client-credentials flow used for metadata lookup (which is server-to-server, no user interaction).

**The challenge:** The pipeline runs headlessly on GitHub Actions (or Cloud Run). There's no browser session to redirect through Spotify's consent screen.

**Solution: One-time browser auth via the frontend, persistent refresh token in the database.**

```
1. User clicks "Connect Spotify" on the Cloudflare Pages frontend
2. Frontend redirects to Spotify OAuth consent screen
   (callback URL: https://your-app.pages.dev/auth/spotify/callback)
3. User grants permission; Spotify redirects back with authorization code
4. Frontend exchanges code for access_token + refresh_token
5. refresh_token stored in the database (encrypted)
6. Pipeline (GitHub Actions) reads refresh_token from DB,
   uses it to get fresh access_token, creates playlist
7. refresh_token is long-lived — user only needs to re-auth
   if they revoke access or Spotify rotates the token
```

**Key implementation details:**
- The Spotify Developer Dashboard needs a new app with the callback URL set to the frontend's domain (`*.pages.dev` or custom domain)
- The `playlist-modify-public` and `playlist-modify-private` scopes are needed
- Refresh tokens are long-lived (months to years) — the user authenticates once, then the pipeline uses the stored token indefinitely
- The frontend should provide a toggle to enable/disable playlist creation per job
- Token storage in Neon should use encryption at rest (Neon supports this on all tiers)

**This flow works identically across all architecture options** — the frontend handles the interactive OAuth, the pipeline consumes the stored token.

---

## 5c. Public Repo Considerations (GitHub Actions)

Making the repository public (required for unlimited free GitHub Actions minutes) has implications beyond code visibility:

**What becomes public:**
- All pipeline source code (recognition strategy, clustering parameters, enrichment logic)
- `false_positive_rules.json` (suppression rules for known false Shazam matches)
- GitHub Actions workflow definitions
- **Workflow run logs** — these are public on public repos and may contain partial output, timing info, or error messages
- Issue tracker, pull requests, commit history

**What stays private:**
- All secrets stored in GitHub Secrets (API keys, DB credentials, tokens) — never exposed in logs
- The database itself (Neon, Supabase, etc.) — completely separate from the repo
- Environment variables set in workflow secrets

**Risk assessment for a portfolio project:**
- Someone could replicate the pipeline by reading the code — but the code has no proprietary advantage; the value is in the curated output
- False positive rules are project-specific and not sensitive
- Workflow logs may reveal which sets you're processing and when — low sensitivity for a music project
- **If this is unacceptable:** Use a private repo (2,000 min/month = ~80 sets/month, still covers your workload) or move to GCP Cloud Run Jobs (no public repo requirement)

---

## 6. Combined Architecture Recommendations

### Option A: GitHub Actions + Neon + Cloudflare Pages (RECOMMENDED)

```
┌─────────────────────┐     ┌──────────────────┐     ┌───────────────────┐
│   Cloudflare Pages  │────▶│   Neon Postgres   │◀────│  GitHub Actions   │
│   (Frontend + API)  │     │   (Database)      │     │  (Pipeline Runner)│
│                     │     │                   │     │                   │
│ • Next.js / Astro   │     │ • Sets, tracks,   │     │ • FFmpeg + yt-dlp │
│ • Job trigger UI    │     │   artists, jobs   │     │ • Shazam, Spotify │
│ • Status polling    │     │ • 512 MB free     │     │ • Writes to Neon  │
│ • Setlist browser   │     │ • Auto-wake       │     │ • Unlimited mins  │
│ • *.pages.dev domain│     │                   │     │   (public repo)   │
└─────────────────────┘     └──────────────────┘     └───────────────────┘
        │                                                      ▲
        │              GitHub REST API                         │
        └──────────────────────────────────────────────────────┘
                    (trigger workflow_dispatch)
```

**How it works:**
1. **Frontend** (Cloudflare Pages): A Next.js or Astro app that displays setlists, artist summaries, and provides a "Process New Set" form. Queries Neon directly via serverless Postgres driver or via Supabase-style auto-generated API.
2. **Database** (Neon): Stores all structured data. Auto-suspends compute when idle, auto-wakes on connection. Pipeline writes results here.
3. **Pipeline** (GitHub Actions): Triggered by `workflow_dispatch` — either from the frontend (via GitHub REST API) or from CLI (`gh workflow run`). Runs in a fresh Ubuntu runner with pre-installed FFmpeg. Writes results to Neon on completion.
4. **Job status**: Pipeline writes status updates to the `jobs` table in Neon. Frontend polls the `jobs` table for progress.

**Vendor count:** 3 (GitHub, Neon, Cloudflare)
**Monthly cost:** $0
**Ops burden:** Very low — no servers, no VMs, no containers to build, no idle reclamation
**Frontend path:** Strong — Cloudflare Pages supports any JS framework, Neon is standard Postgres
**Code changes:** Moderate — DB write layer, GitHub Actions workflow YAML, frontend app

**Why this is recommended:**
- Lowest ops burden: zero servers to manage, zero containers to build (FFmpeg is pre-installed)
- Unlimited free compute on public repos
- Neon's auto-wake eliminates the Supabase pause problem
- Cloudflare Pages' unlimited bandwidth means no traffic ceiling
- Each component can be replaced independently (Neon → any Postgres, GitHub Actions → any CI, Cloudflare → any static host)
- CLI access preserved via `gh workflow run`

**Trade-offs:**
- Three vendors (not single-vendor), but each is best-in-class for its role
- Public repo required for unlimited free minutes (secrets remain safe)
- Job triggering from frontend requires calling GitHub's REST API (straightforward but adds a dependency)

---

### Option B: Oracle Cloud VM (All-in-One)

```
┌─────────────────────────────────────────┐
│         Oracle Cloud ARM VM             │
│         (4 OCPU / 24 GB / 200 GB)       │
│                                         │
│  ┌──────────┐  ┌──────────┐  ┌───────┐ │
│  │ FastAPI   │  │ Postgres │  │Pipeline│ │
│  │ (Web +API)│  │ (self-   │  │Worker │ │
│  │           │──│ hosted)  │──│       │ │
│  │ Frontend  │  │          │  │FFmpeg │ │
│  │ served    │  │          │  │yt-dlp │ │
│  └──────────┘  └──────────┘  └───────┘ │
│                                         │
│  + Nginx reverse proxy + Let's Encrypt  │
│  + Keepalive cron job                   │
└─────────────────────────────────────────┘
```

**How it works:**
- Single VM runs everything: web server, database, pipeline worker
- FastAPI serves both the frontend (static files) and API endpoints
- Postgres installed locally, no network latency
- Pipeline runs as a background worker (Celery, RQ, or simple subprocess)
- Nginx handles SSL termination with Let's Encrypt certificates

**Vendor count:** 1 (Oracle Cloud)
**Monthly cost:** $0
**Ops burden:** **High** — OS updates, Postgres maintenance, SSL renewal, backup strategy, keepalive management, security hardening, monitoring
**Frontend path:** Moderate — you're building everything from scratch (no managed API, auth, or hosting)
**Code changes:** Moderate — web server, job queue, DB layer

**Why you might choose this:**
- True single-vendor solution
- Most powerful free compute (24 GB RAM, 200 GB disk)
- Full control over everything
- No public repo requirement
- Persistent disk for caching and checkpoints

**Why you probably shouldn't:**
- Highest ops burden of any option — you're a sysadmin now
- Idle reclamation risk requires constant vigilance
- Oracle UX is painful
- Single point of failure — VM goes down, everything is down
- No CDN for frontend — slower for geographically distant visitors

---

### Option C: GCP Cloud Run Jobs + Neon + Cloudflare Pages

```
┌─────────────────────┐     ┌──────────────────┐     ┌───────────────────┐
│   Cloudflare Pages  │────▶│   Neon Postgres   │◀────│  GCP Cloud Run    │
│   (Frontend)        │     │   (Database)      │     │  Jobs (Pipeline)  │
│                     │     │                   │     │                   │
│ • Static frontend   │     │ • Sets, tracks,   │     │ • Docker container│
│ • *.pages.dev       │     │   artists, jobs   │     │ • FFmpeg + yt-dlp │
└─────────────────────┘     └──────────────────┘     │ • ~120 sets/mo    │
        │                                             └───────────────────┘
        │         GCP API or thin Cloud Run Service           ▲
        └─────────────────────────────────────────────────────┘
                         (trigger job)
```

**Similar to Option A** but uses GCP Cloud Run Jobs instead of GitHub Actions for pipeline execution.

**Vendor count:** 3 (GCP, Neon, Cloudflare)
**Monthly cost:** $0
**Ops burden:** Low-medium — Docker container to build and maintain, GCP IAM/permissions
**Frontend path:** Same as Option A
**Code changes:** Moderate-large — Dockerfile, GCP-specific config, DB write layer, trigger mechanism

**vs. Option A (GitHub Actions):**
- **Pro:** Proper container platform, no public repo requirement, more "production-grade"
- **Con:** Requires Docker, GCP account with billing enabled, more setup complexity
- **Con:** 120 sets/month limit vs. unlimited on GitHub Actions
- **Con:** Cold start on container pull vs. near-instant GitHub Actions startup

---

### Option D: Single-Vendor GCP Stack

```
┌─────────────────────────────────────────────────────────┐
│                    Google Cloud Platform                  │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Cloud Run    │  │  Firestore   │  │ Cloud Run     │  │
│  │ Service      │  │  (Database)  │  │ Jobs          │  │
│  │ (Frontend)   │──│              │──│ (Pipeline)    │  │
│  │              │  │ 1 GB free    │  │ ~120 sets/mo  │  │
│  └──────────────┘  └──────────────┘  └───────────────┘  │
│                                                          │
│  Free tier: 180K vCPU-sec + 2M requests + 1 GB Firestore │
└─────────────────────────────────────────────────────────┘
```

**True single-vendor approach on GCP.** Frontend on Cloud Run (Service), data in Firestore, pipeline on Cloud Run (Jobs).

**Vendor count:** 1 (GCP)
**Monthly cost:** $0
**Ops burden:** Medium — GCP IAM, Docker, Firestore data modeling
**Frontend path:** Moderate — Firestore's query limitations make complex frontend queries harder than with Postgres
**Code changes:** Large — Firestore requires different data modeling than SQL, Cloud Run Service for frontend

**Why you might choose this:**
- True single-vendor
- Everything under one billing/IAM umbrella
- GCP free tier is generous and permanent

**Why Option A is better:**
- Firestore's NoSQL limitations (no joins, limited aggregations) make frontend development harder
- Cloud Run for frontend hosting is overkill vs. Cloudflare Pages
- More GCP-specific configuration overhead
- The "single vendor" benefit is real but doesn't outweigh the DX advantages of Neon + Cloudflare Pages

---

### Option E: Single-Vendor Supabase + GitHub Actions

```
┌─────────────────────────────────────────────────────────┐
│                       Supabase                           │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ PostgREST    │  │  Postgres    │  │ Edge Functions │  │
│  │ (Auto API)   │  │  (Database)  │  │ (500K/month)  │  │
│  │              │──│  500 MB      │──│               │  │
│  │ Auth (50K    │  │              │  │ Trigger GH    │  │
│  │  MAUs free)  │  │              │  │ Actions       │  │
│  └──────────────┘  └──────────────┘  └───────────────┘  │
│                                                          │
│  + Frontend hosted on Cloudflare Pages (or Vercel)       │
└─────────────────────────────────────────────────────────┘
         +
┌───────────────────┐
│  GitHub Actions   │
│  (Pipeline Runner) │
└───────────────────┘
```

**Supabase as the "backend platform" with GitHub Actions for compute.**

**Vendor count:** 2-3 (Supabase + GitHub + Cloudflare/Vercel for frontend hosting)
**Monthly cost:** $0
**Ops burden:** Low — Supabase handles DB, API, auth; GitHub handles compute
**Frontend path:** **Best** — Supabase's auto-generated API, auth, and realtime make frontend development fastest
**Code changes:** Moderate — DB write layer, GitHub Actions workflow, Supabase client integration

**vs. Option A (Neon):**
- **Pro:** Supabase gives you auth, auto-generated REST API, realtime, file storage — Neon is just a database
- **Con:** 7-day inactivity pause requires a keepalive mechanism
- **Con:** Only 2 free projects (Neon gives 100)

**When to choose this over Option A:** If you value frontend development speed above all else and don't mind adding a weekly keepalive cron job to prevent pausing.

---

### Option F: AWS Lambda Stream-Direct + Neon + Cloudflare Pages

```
┌─────────────────────┐     ┌──────────────────┐
│   Cloudflare Pages  │────▶│   Neon Postgres   │
│   (Frontend)        │     │   (Database)      │
│                     │     │   512 MB free     │
│ • *.pages.dev       │     │   Auto-wake       │
└─────────────────────┘     └──────────────────┘
                                     ▲
                                     │ writes
┌────────────────────────────────────┴──────────────────────────────┐
│                     AWS Lambda Pipeline                           │
│                                                                    │
│  ┌───────────────┐    ┌───────────────────────┐    ┌───────────┐  │
│  │ Orchestrator   │───▶│ 150× Stream-Direct    │───▶│ Cluster + │  │
│  │ Lambda         │    │ Worker Lambdas        │    │ Enrich    │  │
│  │                │    │                       │    │ Lambda    │  │
│  │ • yt-dlp       │    │ Each worker:          │    │           │  │
│  │   --get-url    │    │ • FFmpeg -ss <offset>  │    │ • Cluster │  │
│  │ • Calculate    │    │   reads from stream   │    │ • Spotify │  │
│  │   150 offsets  │    │   URL (~500KB audio)  │    │ • Discogs │  │
│  │ • Fan out      │    │ • Shazam recognize    │    │ • Write   │  │
│  │                │    │ • Return result       │    │   to Neon │  │
│  │ ~10 sec        │    │ ~30-60 sec each       │    │ ~2-3 min  │  │
│  └───────────────┘    └───────────────────────┘    └───────────┘  │
│                                                                    │
│  No intermediate storage needed — each worker streams from source  │
│  Coordination: SQS + DynamoDB counter (avoids Step Functions       │
│  transition limits) or async Lambda invocations                    │
└────────────────────────────────────────────────────────────────────┘
```

**How it works (stream-direct approach — empirically validated):**
1. **Orchestrator Lambda** (~10 sec, 256 MB): Uses `yt-dlp --get-url` to extract the direct audio stream URL (no download). Gets duration via `--dump-json`. Calculates segment offsets (e.g., 150 segments at 30 sec with 15 sec overlap). Fans out 150 worker invocations. Creates job record in Neon.
2. **Stream-Direct Worker Lambdas (×150 parallel)** (~30-60 sec each, 512 MB): Each receives `{stream_url, offset_seconds, duration_seconds, segment_index}`. FFmpeg reads from the remote stream URL at the given offset (`-ss`) for the given duration (`-t`) — downloads only ~500 KB of audio, not the full file (seeking efficiency confirmed by testing). Shazam recognizes the segment. Returns result. **Each worker is fully self-contained — no S3, no shared disk, no intermediate storage.**
3. **Cluster + Enrich Lambda** (~2-3 min, 1 GB): Collects all recognition results, clusters/deduplicates into setlist, enriches via Spotify/Discogs/ReccoBeats, writes final output to Neon, optionally creates Spotify playlist.

**Wall-clock time: ~1-25 min** depending on Shazam IP diversity on Lambda (testable). Cross-IP URL access is empirically validated — the remaining variable is whether Lambda workers get distinct IPs for Shazam. See Section 1 Caveat 2.

**Vendor count:** 3 (AWS + Neon + Cloudflare) — or 2 if using DynamoDB instead of Neon
**Monthly cost:** $0
**Ops burden:** Medium — Lambda packaging (FFmpeg layer), IAM setup, fan-out coordination, but no servers or storage to manage
**Frontend path:** Strong — Neon is standard Postgres, same as Option A
**Code changes:** Large — pipeline decomposed into 3 Lambda functions, Shazam calls refactored for single-segment invocation, fan-out coordination logic
**Processing speed:** ~1-25 min depending on Shazam IP diversity (testable). Stream-direct URL access is validated.

**Free tier budget:**
- Orchestrator: 1 × 10 sec × 0.25 GB = 2.5 GB-seconds per set
- Workers: 150 × 45 sec × 0.5 GB = 3,375 GB-seconds per set
- Aggregator: 1 × 3 min × 1 GB = 180 GB-seconds per set
- Total: ~3,558 GB-seconds per set
- Monthly: 400,000 / 3,558 = **~112 sets/month free**

**Fan-out coordination (avoiding Step Functions transition limits):**
Step Functions Standard free tier only allows 4,000 transitions/month (~8-26 sets depending on parallelism). Better options:
1. **Async Lambda invocations + DynamoDB atomic counter:** Orchestrator invokes workers asynchronously. Each worker writes its result to DynamoDB and atomically decrements a counter. When counter hits 0, the last worker triggers the aggregator. Simple, no Step Functions needed, fits entirely within DynamoDB free tier.
2. **SQS fan-out:** Workers push results to an SQS queue. Aggregator Lambda triggered by SQS batch. 1M free SQS requests/month — plenty.
3. **Simple approach:** Orchestrator invokes workers synchronously in batches of 50, collects results in-memory, then triggers aggregator. Slightly slower (~3 rounds × 60 sec = 3 min for workers) but simplest code.

**Why you might choose this:**
- **Stream-direct URL access is empirically validated** — workers can seek into remote YouTube/SoundCloud URLs from different IPs
- **Architecture naturally benefits from IP diversity** — if Lambda workers get distinct IPs, recognition parallelizes automatically without code changes
- No intermediate storage — each worker streams directly from source, fully stateless
- 112 sets/month free is generous (covers your 40/month typical + bursts)
- No servers, no idle costs, no reclamation
- Same Neon + Cloudflare Pages foundation as Option A — can start with A and migrate pipeline to F later

**Why you might not:**
- Most complex architecture of any option (3 Lambda functions + coordination)
- AWS ecosystem for compute (Lambda lock-in), though DB and frontend are portable
- FFmpeg must be bundled as a Lambda Layer (~100 MB)
- YouTube may rate-limit 150 parallel FFmpeg connections — may need ~50 concurrent (empirical testing used 1 consumer; high concurrency untested)
- Edge cases (geo-restricted, age-gated content) may have stricter URL access controls than tested sources
- More debugging surface area (distributed workers vs. single process)

**Fallback variant:** For edge cases where stream-direct doesn't work (unlikely given empirical validation, but possible for some content types), fall back to a Download+Segment Lambda that downloads the full file, stores segments in S3, then fans out recognition workers. Uses more GB-seconds but same architecture. S3 free tier is 12-month only, but post-trial cost is ~$0.01/month for transient storage.

---

### Option G: Vercel Stream-Direct + Neon (Closest to Single-Vendor)

```
┌──────────────────────────────────────────────────────────────┐
│                          Vercel                               │
│                                                               │
│  ┌──────────────┐  ┌─────────────────────────────────────┐   │
│  │ Frontend     │  │ Python Functions (Pipeline Workers)  │   │
│  │ (Next.js)    │  │                                     │   │
│  │              │  │ • Orchestrator: yt-dlp --get-url     │   │
│  │ • Setlist    │  │ • 150× Workers: FFmpeg stream-direct │   │
│  │   browser    │  │   + Shazam recognize (~30-60s each) │   │
│  │ • Job UI     │  │ • Aggregator: cluster + enrich       │   │
│  │ • Status     │  │                                     │   │
│  │   polling    │  │ 5 min timeout / 2 GB / Python 3.12+ │   │
│  └──────────────┘  └─────────────────────────────────────┘   │
│                                                               │
│  *.vercel.app subdomain • Auto-SSL • Auto-scaling to 30K     │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │   Neon Postgres   │
                    │   512 MB free    │
                    │   Auto-wake      │
                    └──────────────────┘
```

**How it works:**
1. **Frontend** (Next.js on Vercel): Displays setlists, artist pages, job submission form, status polling. Server-side renders pages from Neon data.
2. **Orchestrator API route** (Python function, ~10 sec): Receives job request from frontend form or CLI HTTP call. Uses yt-dlp to extract stream URL + duration. Calculates segment offsets. Fans out 150 worker invocations via HTTP calls to worker endpoint. Creates job record in Neon.
3. **Stream-direct worker endpoint** (Python function, ×150 parallel, ~30-60 sec each): Receives `{stream_url, offset, duration, segment_index}`. FFmpeg reads from remote URL at offset. Shazam recognizes. Returns result.
4. **Aggregator endpoint** (Python function, ~2-3 min): Collects all results, clusters/deduplicates, enriches via Spotify/Discogs, writes to Neon, creates Spotify playlist.

**Vendor count:** 2 (Vercel + Neon) — closest to single-vendor
**Monthly cost:** $0
**Ops burden:** **Low** — Vercel handles deployment, scaling, SSL, domains. Neon handles database. No containers, no VMs, no IAM.
**Frontend path:** **Best** — Next.js on Vercel is the gold standard for frontend DX
**Code changes:** Large — decompose pipeline into Python API routes, fan-out coordination, stream-direct workers
**Processing speed:** ~1-25 min depending on Shazam IP diversity (testable). Stream-direct URL access is empirically validated.

**Free tier budget:**
- 100 CPU-hours/month on Hobby plan
- Per set: 150 workers × ~30 sec CPU = ~75 min CPU per set
- Monthly: 100 hours / 1.25 hours = **~80 sets/month**
- At 10 sets/week (40/month): uses ~50% of CPU budget — comfortable

**Why this might be the best option:**
- **Closest to single-vendor:** Only Vercel + Neon. Frontend, API, and pipeline workers all on one platform.
- **Lowest ops burden of any decomposed option:** No Lambda configuration, no Step Functions, no SQS, no IAM. Just deploy Python functions alongside your Next.js frontend.
- **Best frontend DX:** Next.js on Vercel with server-side rendering, API routes, edge middleware
- **Stream-direct workers fit comfortably:** 5-min timeout with ~30-60 sec workers = plenty of headroom
- **Python natively supported:** No Docker, no Lambda layers — just `requirements.txt` + Python files
- **Auto-scaling to 30K concurrency:** 150 parallel workers is trivial

**Why you might not:**
- **Non-commercial clause:** Vercel Hobby is for personal, non-commercial use. If this project ever generates revenue, you need Pro ($20/month). For a portfolio project, this is fine.
- **FFmpeg bundling in Vercel Python functions is unproven:** The 500 MB bundle limit should accommodate a static FFmpeg binary (~100 MB) + Python deps (~200 MB), but this needs validation. Alternative: use a pure-Python audio library or call an external FFmpeg service.
- **Fan-out coordination:** Vercel has no built-in orchestration. The orchestrator function would invoke workers via HTTP and track completion in Neon (atomic counter pattern). Simpler than Lambda + Step Functions, but custom code.
- **80 sets/month CPU ceiling:** Generous for normal usage but could be hit during heavy burst processing. Reducing parallelism to 50 concurrent workers extends to ~240 sets/month (at the cost of ~3x longer wall-clock time per set — still only ~5-9 min).
- **4.5 MB request/response body limit:** Not an issue for stream-direct (workers read from URL, return small JSON), but limits passing audio as payloads.

---

## 7. Final Ranking

### Monolithic Architectures

| Rank | Architecture | Cost | Ops Burden | Frontend Path | Scalability | Code Change | Processing Speed | Best For |
|---|---|---|---|---|---|---|---|---|
| **1** | **A: GitHub Actions + Neon + Cloudflare Pages** | $0 | Very low | Strong | Good | Moderate | ~25 min/set | Best overall balance |
| **2** | **E: Supabase + GitHub Actions + CF Pages** | $0 | Low (needs keepalive) | **Best** | Good | Moderate | ~25 min/set | Fastest frontend development |
| **3** | **C: GCP Cloud Run + Neon + CF Pages** | $0 | Low-medium | Strong | Good | Moderate-large | ~25 min/set | Container-grade execution |
| **4** | **D: GCP All-in-One** | $0 | Medium | Moderate | Good | Large | ~25 min/set | Single-vendor GCP |
| **5** | **B: Oracle Cloud VM** | $0 | **High** | Moderate | **Best** | Moderate | ~25 min/set | Maximum power / full control |

### Decomposed Architectures (Stream-Direct — Empirically Validated)

| Rank | Architecture | Cost | Ops Burden | Frontend Path | Scalability | Code Change | Processing Speed | Best For |
|---|---|---|---|---|---|---|---|---|
| **1** | **G: Vercel decomposed + Neon** | $0 | **Low** | **Best** | Good | Large | ~1-8 min* | Best single-platform option (frontend + compute + API) |
| **2** | **F: AWS Lambda decomposed + Neon + CF Pages** | $0 | Medium | Strong | **Best** | Large | ~1-8 min* | Maximum scalability; most robust fan-out |
| **3** | **A': GitHub Actions matrix + Neon + CF Pages** | $0 | Low | Strong | Good | Moderate-large | ~5-10 min/set | Parallel recognition without Lambda complexity |
| **4** | **C': GCP Cloud Run multi-task + Neon + CF Pages** | $0 | Low-medium | Strong | Good | Moderate-large | ~5-10 min/set | Container-native parallelism |

**\* Processing speed note:** Stream-direct URL access and seeking efficiency are **empirically validated** (cross-IP access, <500 KB per segment, >25 min URL lifetime). The remaining variable is Shazam throughput on serverless — specifically, whether workers get distinct IPs. Best case ~1-3 min (distinct IPs), likely ~3-8 min (partial IP diversity), worst case ~15-25 min (shared IPs). This is testable with a small deployment. The stream-direct architecture benefits automatically from whatever IP diversity the platform provides, with no code changes needed.

**Option G: Vercel Decomposed + Neon** is the standout decomposed option. It hosts the frontend, API, AND pipeline workers on a single platform (Vercel) with Neon as the only external service. Python is supported natively, the 5-minute function timeout gives comfortable headroom for individual stages, and the frontend DX is best-in-class. The stream-direct approach is now validated — each worker can seek into the remote audio URL and recognize a single segment. The constraint is the non-commercial clause on Hobby plan, ~80 sets/month CPU budget, and unproven FFmpeg-in-Python on Vercel (bundling, not the approach itself). If those are acceptable (they likely are for a portfolio project), this is the cleanest architecture.

### The Recommendation

**Three paths, depending on your priorities:**

**Path 1 — Start simple with Option A (GitHub Actions + Neon + Cloudflare Pages).**

Best if you want the fastest path to a working deployment with minimal complexity:
- Lowest ops burden (your #2 priority after cost)
- All three services have permanently free tiers with no time limits
- The components are loosely coupled — swap any piece later
- FFmpeg is pre-installed on GitHub runners (zero Docker/container work)
- `gh workflow run` preserves your CLI workflow
- Cloudflare Pages gives you a free `*.pages.dev` domain with unlimited bandwidth
- ~25 min per set is the same as today — acceptable if you're patient

**Path 2 — Go with Option G (Vercel decomposed + Neon) for the cleanest architecture.**

Best if you want the simplest possible infrastructure with the best frontend DX:
- **Closest to single-vendor:** Only Vercel + Neon. Frontend, API, and pipeline workers all on Vercel.
- Stream-direct URL access is **empirically validated** — each worker seeks into the remote audio URL, no intermediate storage
- Processing speed potentially ~1-8 min/set (depends on Shazam IP diversity, testable)
- No Lambda, no Step Functions, no SQS, no IAM — just Python functions alongside your Next.js frontend
- Best frontend DX of any option (Next.js on Vercel)
- ~80 sets/month free CPU budget — comfortable for your workload
- **Trade-off:** Non-commercial clause on Hobby plan, FFmpeg-in-Vercel-Python needs validation (bundling, not the approach), larger code change

**Path 3 — Go with Option F (AWS Lambda decomposed + Neon + Cloudflare Pages) for maximum scalability.**

Best if you want the highest ceiling and most robust fan-out:
- Stream-direct approach is **empirically validated** — same architecture as G but with Lambda's more robust infrastructure
- 112 sets/month free, auto-scales to 1,000 concurrent invocations
- Lambda is purpose-built for the fan-out pattern
- Processing speed potentially ~1-8 min/set (same Shazam IP diversity variable)
- **Trade-off:** More complex (Lambda + fan-out coordination + IAM), AWS lock-in for compute

**Important realization about decomposition (updated after empirical validation):** The stream-direct architecture is now validated for URL access and seeking efficiency. The remaining benefits and trade-offs are:
1. **Enabling serverless platforms** with short function timeouts (Vercel, Lambda) — validated
2. **Zero intermediate storage** — workers stream directly from source (~500 KB per segment, confirmed)
3. **Automatic parallelism scaling** — architecture benefits from whatever IP diversity the platform provides, with no code changes
4. **Better fault isolation** — a failed recognition doesn't lose other work
5. **Potential for significant speedup** — if serverless workers get distinct IPs (testable), processing time drops from ~25 min to ~1-8 min

**The natural evolution:** Start with Option A to get deployed quickly. All options use Neon as the database, so switching compute layers later is straightforward:
- **A → G:** Move from GitHub Actions monolithic to Vercel decomposed. Add Python functions to your Vercel frontend project. Same Neon database.
- **A → F:** Move from GitHub Actions monolithic to Lambda decomposed. Same Neon database.
- **G → F:** Move from Vercel workers to Lambda workers if you hit Vercel's CPU ceiling. Same Neon database, keep Vercel for frontend only.

**Other upgrade paths:**
1. Need more frontend platform features → swap Neon for Supabase (Option E)
2. Need private repo for monolithic → move pipeline to GCP Cloud Run Jobs (Option C)
3. Need persistent compute / self-hosted → Oracle VM (Option B)
4. Willing to spend $5/month → Fly.io or Railway for dramatically better monolithic DX

---

## 8. Decision Factors Summary

| Factor | Option A (Monolithic) | Option G (Vercel Stream-Direct) | Option F (Lambda Stream-Direct) |
|---|---|---|---|
| Monthly cost | $0 | $0 | $0 |
| Sets/month capacity | Unlimited (public) / 80 (private) | ~80 | ~112 |
| Processing speed | ~25 min/set | ~1-8 min/set* (stream-direct validated) | ~1-8 min/set* (stream-direct validated) |
| FFmpeg + yt-dlp | Pre-installed on runners | Bundled in Python function (500 MB limit) | Bundled in Lambda layer/container |
| Intermediate storage | None (runner disk) | **None** (stream-direct) | **None** (stream-direct) |
| Job duration limit | 6 hours | 5 min per function (plenty) | 15 min per function (plenty) |
| Database | Neon (auto-wake) | Neon (auto-wake) | Neon (auto-wake) |
| Frontend hosting | Cloudflare Pages | **Vercel (same platform)** | Cloudflare Pages |
| CLI access | `gh workflow run` | HTTP call to Vercel API route | `aws lambda invoke` or CLI wrapper |
| Web UI access | Frontend → GitHub API | **Frontend → same-platform API route** | Frontend → API Gateway → Lambda |
| Concurrent workers | 20 parallel GitHub jobs | 30,000 auto-scale | 1,000 concurrent invocations |
| Spotify OAuth | Callback on `*.pages.dev` | Callback on `*.vercel.app` | Callback on `*.pages.dev` |
| yt-dlp concerns | GitHub runners | Vercel functions | AWS Lambda |
| Vendor count | 3 (GitHub + Neon + Cloudflare) | **2 (Vercel + Neon)** | 3 (AWS + Neon + Cloudflare) |
| Vendor lock-in | Low | Low-medium (Vercel for compute) | Medium (Lambda + coordination) |
| Architectural complexity | Low | Medium | Medium-high |
| Non-commercial restriction | No | **Yes (Hobby plan)** | No |
| Upgrade path | → G or F (change compute only) | → F (move workers to Lambda) | Already at high capability |

*\* Stream-direct processing speed: URL access and seeking efficiency empirically validated. Range depends on Shazam IP diversity on serverless (testable): best ~1-3 min, likely ~3-8 min, worst ~15-25 min. Architecture benefits automatically from whatever IP diversity the platform provides.*

**Suggested next validation step:** Deploy 5-10 Lambda/Vercel functions, have each print its public IP and make one Shazam recognition call. This resolves the IP diversity question definitively and narrows the processing time estimate from "~1-25 min" to a concrete number.
| Shared foundation | Neon | Neon | Neon |
