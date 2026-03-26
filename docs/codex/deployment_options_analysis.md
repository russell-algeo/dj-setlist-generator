# Remote Deployment Options Analysis

## Scope and assumptions

This document evaluates two separate concerns:

1. Data storage + serving for normalized setlist data
2. Remote execution of the recognition pipeline

Assumptions used for the workload translations:

- Average processing time: 25 minutes per set
- Typical monthly volume: 22 to 44 sets/month
- Burst case: 20 sets in a short batch
- Current segment settings: 30s segments, 15s overlap, 128 kbps MP3
- Shazam traffic estimate: about 239 segments for a 60-minute set, about 359 for a 90-minute set
- Shazam upload estimate: about 115 MB for a 60-minute set, about 172 MB for a 90-minute set, before retries
- Final normalized data only goes into the product database
- Checkpoints and temp artifacts can live outside the product database
- The current CLI implementation is a baseline for sizing, not a hard architectural constraint
- Heavy refactoring, queue-based workers, and chunked processing are all in scope if they improve the deployment fit

## Executive summary

There is no clean single-vendor, permanently-free stack that gives you all three of these at once:

- managed database with a good future web-app path
- public frontend hosting / API ergonomics
- long-running binary-friendly worker compute

For your priorities, the practical answer is:

- Best strict `$0` execution platform: Oracle Cloud Always Free compute
- Best strict `$0` worker alternative: GitHub Actions
- Best storage + frontend platform: Supabase if you optimize for product ergonomics, Turso if you optimize for free-tier headroom
- Best "tiny cost but much easier" execution platform: GCP Cloud Run Jobs

After the prototype work in this repo, `stream-direct` should now be treated as the primary worker architecture, not just a speculative option. We validated it on one real YouTube source and one real SoundCloud source across:

- two separate laptops
- same-Wi-Fi and different-public-IP access
- bare URL fetches and FFmpeg slice reads
- beginning / middle / end seek positions

If you stay strict on `$0`, the best overall architecture is still a mixed stack:

- worker compute on Oracle Cloud Always Free
- database on Supabase or Turso
- frontend on a static/edge host later

If you relax the `$0` rule slightly, Cloud Run Jobs becomes very compelling because the compute itself fits inside the free tier; your likely monthly spend is driven mostly by internet egress from Shazam uploads, and that should be low single-digit dollars, often around `$1`.

Allowing a full re-architecture changes the runtime shape more than it changes the final ranking. You can absolutely redesign away from a single 25-minute monolith, but that mostly solves duration ceilings. It does not remove the deeper constraints:

- you still need a reliable media-ingest path
- you still need many outbound recognition requests
- you still need queueing, de-duplication, and state management
- you still need a host that will tolerate media downloading behavior

The biggest uncertainty is no longer "can workers stream and seek remote media directly?" For the tested YouTube and SoundCloud flows, the answer is yes. The main unresolved risk is now Shazam throughput and generalization across a wider long-tail of sources.

## Workload translated into platform math

- 25 minutes/set means 44 sets/month is about 1,100 worker-minutes/month, or about 18.3 hours/month
- At 1 vCPU, that is about 66,000 vCPU-seconds/month
- At 2 GiB RAM, that is about 132,000 GiB-seconds/month
- A burst of 20 sets is about 500 worker-minutes total
- A single set likely causes roughly 0.12 to 0.17 GB of outbound traffic to Shazam alone
- 44 sets/month therefore likely means roughly 5 to 7.5 GB/month of outbound Shazam traffic

That last point is the most important hidden constraint. Many serverless free tiers have enough compute for your workload, but not enough free internet egress to stay at `$0`.

## Prototype validation results

These are local test results from this repo's stream-direct probes, not vendor documentation.

### Test setup

- Laptop A resolved the playable stream URL with `yt-dlp`
- Laptop A ran a local FFmpeg smoke test
- Laptop B ran pasted terminal commands only
- Laptop B was tested both:
  - on the same Wi-Fi
  - on an iPhone hotspot with a different public IP

### YouTube: `https://www.youtube.com/watch?v=vxjcRkZKBPc`

- Laptop A local FFmpeg smoke test:
  - `exit_code=0`
  - `elapsed_seconds=13.344`
- Laptop B same-Wi-Fi bare `curl`:
  - `HTTP 206`
  - `SIZE 1048576`
  - `TIME 0.439082`
- Laptop B same-Wi-Fi header-bearing `curl`:
  - `HTTP 206`
  - `SIZE 1048576`
  - `TIME 0.192420`
- Laptop B hotspot bare `curl`:
  - `HTTP 206`
  - `SIZE 1048576`
  - `TIME 8.111002`
- Laptop B hotspot header-bearing `curl`:
  - `HTTP 206`
  - `SIZE 1048576`
  - `TIME 4.322709`
- Laptop B hotspot FFmpeg mid-file slice read:
  - bare URL: success, no stderr
  - copied headers: success, no stderr

Interpretation:

- The resolved YouTube media URL was reusable across hosts
- The same resolved URL was reusable across different public IPs
- Actual FFmpeg decoding worked on the second host, not just raw byte fetches
- Copied headers were not required for access in this test case

### SoundCloud: `https://soundcloud.com/gala-festival/sweely-live-from-the-patio`

- Laptop A local FFmpeg smoke test:
  - `exit_code=0`
  - `elapsed_seconds=1.254`
- Laptop B bare `curl`:
  - `HTTP 200`
  - `SIZE 300225`
  - `TIME 0.603869`
- Laptop B header-bearing `curl`:
  - `HTTP 200`
  - `SIZE 300225`
  - `TIME 0.322373`
- Laptop B FFmpeg mid-file slice read:
  - bare URL: success, no stderr
  - copied headers: success, no stderr

Interpretation:

- The resolved SoundCloud URL was a signed `m3u8` manifest, so `HTTP 200` is expected
- The meaningful result is that FFmpeg on the second host also succeeded, which proves the downstream segment-fetching path worked
- Copied headers were not required for access in this test case

### Seeking-efficiency results

We also tested whether later slices cause FFmpeg to pull a large fraction of the full set, which would undermine the value of stream-direct.

YouTube `https://www.youtube.com/watch?v=vxjcRkZKBPc`:

- beginning: `278,528 bytes`, `0 seeks`, `8.541s`
- middle: `425,984 bytes`, `1 seek`, `12.934s`
- end: `427,292 bytes`, `1 seek`, `1.026s`

Interpretation:

- The full object was about `62.8 MB`
- FFmpeg only read a few hundred KB for each 15-second slice
- Mid and end slices did not require downloading anything close to the full asset

SoundCloud `https://soundcloud.com/gala-festival/sweely-live-from-the-patio`:

- beginning: `300,225 bytes`, `0 seeks`, `1.118s`
- middle: `300,225 bytes`, `0 seeks`, `1.017s`
- end: `300,225 bytes`, `0 seeks`, `1.314s`

Interpretation:

- The HLS path was extremely consistent across beginning, middle, and end slices
- Stream-direct seeking did not degrade for later positions on this source

### What these tests do and do not prove

The tests now support these conclusions:

- stream-direct is viable for at least one real YouTube set
- stream-direct is viable for at least one real SoundCloud set
- same-host-only and same-IP-only assumptions are too pessimistic for the tested YouTube case
- copied headers and cookies are not default requirements for the tested cases
- seeking efficiency is good enough on the tested YouTube and SoundCloud paths
- resolved YouTube URLs remained usable after 25+ minutes in follow-up checks, which is enough to treat URL refresh as an operational detail rather than a design blocker

The tests do not prove:

- every YouTube or SoundCloud source behaves this way
- very long URL lifetimes for every source
- high-concurrency Shazam scaling
- how often edge-case uploaders require fallback behavior

## Outcome-first architecture implications

The current implementation details are not the real product requirements.

The real requirements are:

- ingest audio from a supported source
- sample enough windows to recover an ordered tracklist
- aggregate and de-duplicate overlapping recognitions
- enrich the final entities
- optionally create a Spotify playlist
- persist normalized results and job status for CLI and web triggers

What is not sacred:

- Python specifically
- FFmpeg specifically
- `yt-dlp` specifically
- one uninterrupted 20 to 30 minute process per set
- downloading the entire set before any recognition starts
- local flat-file checkpoints

What is still hard even after a rewrite:

- media acquisition from YouTube and SoundCloud
- lots of outbound Shazam traffic
- chunk-boundary handling and duplicate suppression
- remote job orchestration and retry behavior
- provider policy risk around downloader-heavy traffic

Swapping out FFmpeg does not change the platform answer very much. You do not need FFmpeg by name, but you do need some equivalent native-capable media decode / trim / resample path. Replacing FFmpeg with GStreamer, PyAV, or another media layer mostly changes packaging, not the free-tier economics.

The same applies to `yt-dlp`. If the product still needs to ingest from YouTube and SoundCloud directly, some downloader / extractor layer with similar network and policy implications remains necessary. The bigger architectural question is whether download happens once centrally or many times in parallel.

## Parallelism ladder

These are all valid architectures to consider, but they are not equally mature or equally reliable.

| Level | Shape | Valid? | Main advantage | Main risk |
| --- | --- | --- | --- | --- |
| 1 | Sequential monolith | Yes | Simplest and most proven | Slow end-to-end time, coarse retries |
| 2 | Stage-separated acquire -> fan-out recognize -> aggregate | Yes | Strong balance of speed and robustness | Usually needs shared artifacts or shared storage across workers |
| 3 | Stream-direct self-contained workers | Yes | Best latency and least shared infrastructure on the tested sources | Still depends on long-tail source coverage and safe Shazam concurrency ceilings |

### 1. Sequential

This is the current baseline at about 25 minutes per set. It remains valid as a fallback and local-debugging mode, but it should not be the target remote architecture.

### 2. Stage-separated

This is a strong production design and should absolutely stay in scope.

Important correction: it does not strictly "need S3." It needs one of these:

- object storage such as S3/R2/GCS
- shared disk on the same worker host
- a design where the chunk manifest is shared but the audio itself is still fetched on demand

If workers run on a single VM, shared local disk is enough. If workers fan out across serverless jobs or multiple hosts, object storage is the cleanest option.

### 3. Stream-direct

This is now the strongest default candidate for the main processing path.

The right outcome-focused requirement is not "download audio file." It is:

- resolve a source into a playable media stream plus the headers/cookies needed to access it
- seek to the needed slice
- decode just enough audio to recognize the track
- return the recognition evidence

On the tested YouTube and SoundCloud sources, it worked reliably enough to remove "media access viability" as a primary blocker. In those tests it removed the need for full-set download and the need for shared audio artifact storage on the happy path.

It is still not automatically robust for every source. It depends on several conditions:

- the resolved media URL remains valid long enough for workers to use it
- workers can reproduce the required headers, cookies, and user-agent behavior when needed
- the source protocol supports reasonably efficient seeking or ranged fetching
- high worker fan-out does not trigger upstream throttling
- Shazam concurrency can be increased safely without causing a new bottleneck

The last point remains the biggest uncertainty. Your current pipeline appears Shazam-bound, so a 150-worker design may shift the bottleneck from wall-clock time to rate limits, retries, and reliability. Treat aggressive 1 to 3 minute per-set claims as hypotheses, not planning facts.

### Pipeline shapes worth considering

| Shape | What changes | What it buys you | What it does not fix | Verdict |
| --- | --- | --- | --- | --- |
| Monolithic worker | Keep one worker per set, close to the current CLI | Fastest path, easiest local parity, simplest debugging | Long runtimes, coarse retries, weaker burst scaling | Good fallback, but not the best long-term shape |
| Chunked ingest + fan-out recognition | Download once, create chunk manifest, let many workers segment + recognize their own chunk, then aggregate | Short jobs, clean queue/poll model, easier web triggering, better parallelism, easier resumability | Roughly the same total Shazam call volume and outbound traffic | Best fallback architecture |
| Streaming segmentation pipeline | Start emitting chunks while the source is still downloading | Lower peak temp storage, faster time-to-first-result | Harder retries, harder observability, more moving parts | Useful optimization later, not the first version |
| Parallel source-section downloads | Each worker downloads a different source time-range directly | Potentially earlier parallelism | Repeats extractor work, raises source-side risk, less reliable across formats/sites | Not recommended as the primary design |
| User-supplied audio mode | Accept uploaded audio instead of downloading remotely | Simplest hosting story, avoids downloader issues | Drops a core product feature if used as the only path | Good optional secondary mode, not the main product architecture |

### What I would actually re-architect toward

The best redesign is not "remove FFmpeg" or "force everything into serverless." Based on the prototype results, the main path should be:

1. A short resolve stage that produces a fresh playable stream URL
2. A worker queue of short slice-recognition jobs
3. Workers that:
   - accept the stream URL and a time window
   - FFmpeg-seek just the needed slice
   - generate the recognition signature
   - submit the Shazam request
   - return candidate matches and timing evidence
4. An aggregation stage that merges adjacent duplicates and resolves overlaps
5. An enrichment / publish stage that writes normalized rows and optionally creates a playlist

And the best fallback path should be:

1. Acquire audio once
2. Build a chunk manifest
3. Let workers process local chunks
4. Aggregate and enrich as above

That gives you a fast default path and a robust compatibility path.

### Concrete implications of chunking

- A 60-minute set becomes about 12 chunk jobs if you use 5-minute chunks, or about 6 chunk jobs if you use 10-minute chunks
- A 90-minute set becomes about 18 chunk jobs at 5 minutes, or about 9 chunk jobs at 10 minutes
- Each chunk worker can do its own segmentation, so segmentation no longer has to be a separate global pre-pass
- This means you do not need one uninterrupted 25-minute runtime anymore
- Inference: with careful chunk sizing, 15-minute serverless limits become technically reachable

That last point matters, but only technically. Economically and operationally, the story changes less:

- chunking does not materially reduce total outbound traffic to Shazam
- chunking does not remove downloader policy concerns
- chunking adds orchestration complexity, status tracking, and aggregation logic

So the big winner from chunking is execution shape, not total monthly cost.

### Should you parallelize the download stage itself?

Usually, no.

`yt-dlp` does support partial time-range downloads via `--download-sections`, and it also supports concurrent fragment downloads for HLS / DASH streams. But I would not make "many workers downloading different source slices" the core design. It is usually the wrong axis of parallelism for this product because:

- it multiplies extractor and source-request overhead
- it makes retries more fragile across different source formats
- it is more likely to look abusive to the upstream platform
- it complicates exact boundary handling

The better default for the fallback path is:

- acquire once
- chunk after acquisition
- fan out recognition work

If you later want faster time-to-first-result, a streaming ingest-to-chunk pipeline is safer than many independent source-section downloads.

### Important caveat for stream-direct workers

yt-dlp's own FAQ notes that direct media requests often need to come from the same IP and with the same cookies and headers used during extraction, and advises relaying the content from the machine running yt-dlp when that is not true. That means a naive "resolve once, send URL to 150 independent workers" design may fail or become flaky depending on the source and protocol. Inference: stream-direct is real, but it may require either:

- same-host workers after URL resolution
- a relay/proxy stage under your control
- or per-worker source resolution instead of one central resolver

The prototype results materially weaken this caveat for common cases. We now know that for at least one real YouTube source:

- the same resolved URL worked across hosts
- the same resolved URL worked across different public IPs
- FFmpeg decoding on the second host also worked

So this remains a valid warning for the long tail, but it should no longer dominate the overall architecture decision.

### Shazam concurrency and IP-distribution risk

Your observed behavior matters more than the theoretical fan-out numbers.

If throughput collapses once you go above 2 concurrent recognitions from one device, the safe planning assumption is:

- baseline reliable Shazam concurrency per egress IP is about 2 until proven otherwise

What the `shazamio` code suggests:

- it retries on HTTP `429`
- it supports proxies
- it randomizes device type, UUIDs, and user agent per recognition request

Inference:

- the bottleneck is probably not just "same process" or a single static client identifier
- distinct egress IPs might help
- but they may not help enough if the upstream limit is based on broader abuse detection, datacenter IP reputation, or overall request pacing

So there are two planning scenarios:

| Scenario | Assumption | What it means |
| --- | --- | --- |
| Conservative | Distinct IPs do not materially improve Shazam throughput | Stream-direct still works, but you plan around about 2 concurrent recognition workers total per worker host |
| Optimistic | Distinct IPs materially improve throughput | A multi-host or proxy-sharded worker pool can scale recognition fan-out much further |

For strict `$0`, you should design around the conservative scenario. The optimistic scenario is a bonus only after testing.

This changes the practical interpretation of the stream-direct idea:

- it is still attractive because it removes shared audio artifacts
- but it should not be modeled as "150 workers" unless you validate both source access and Shazam scaling
- if Shazam remains capped near 2 concurrent requests per IP, the main gain from stream-direct is cleaner worker isolation, not massive speedup

This also affects provider choice:

- if multiple distinct IPs are required for high throughput, free serverless becomes less attractive because controlled multi-IP egress usually requires paid networking
- Oracle remains strong because you can run multiple small VMs with different public IPs inside the Always Free envelope
- GitHub Actions may incidentally give you distributed egress IPs across runners, but not with guarantees you can design around
- Cloud Run, Lambda, and similar platforms get weaker if the design depends on stable or intentionally sharded egress IPs

### How to validate or continue validating stream-direct feasibility

Do not decide this from theory. Run a focused prototype and measure success rate, latency, and retry behavior.

Validation matrix:

1. Source-access baseline
   - Resolve a direct media URL plus headers/cookies from one host
   - On the same host, have FFmpeg read only a short slice from that direct URL
   - Record startup latency, bytes transferred, and success rate

2. Cross-host URL-affinity test
   - Resolve the media URL on host A
   - Try to read the same URL from host B:
     - without copied headers/cookies
     - with copied headers/cookies and user agent
   - Compare failures, latency, and expiry behavior

3. URL lifetime test
   - Resolve once
   - Attempt reads after 0, 30, 120, 300, and 900 seconds
   - This tells you whether URLs are long-lived enough for a fan-out design

4. Seeking efficiency test
   - Read slices near the beginning, middle, and end of a long set
   - Compare how many bytes are actually transferred for each
   - If later seeks effectively require downloading most of the file, stream-direct loses much of its value

5. Shazam concurrency test on one IP
   - Run the exact same recognition worker shape at concurrency 1, 2, 3, 4, 6
   - Measure:
     - end-to-end time
     - request latency
     - number of `429`s
     - retries
     - success rate
   - This will confirm whether your observed "2 is safe, 3+ chokes" holds in the rewritten architecture

6. Shazam concurrency test across distinct IPs
   - Repeat the same test across 2 or more hosts / proxies with separate egress IPs
   - If throughput scales roughly linearly while `429`s stay controlled, IP distribution matters
   - If it does not, the limit is not meaningfully solved by IP sharding

7. Source-throttling fan-out test
   - Run 2, 4, 8, 16 workers reading from the same source
   - Watch for source-side errors, stalls, or throttling even before Shazam becomes the bottleneck

8. Per-worker resolve versus shared resolve
   - Compare two modes:
     - central resolver produces one stream URL for all workers
     - each worker resolves its own playable stream URL
   - This determines whether central URL distribution is even viable

Already completed in this repo's prototype work:

- source-access baseline
- cross-host URL-affinity test
- partial URL lifetime check beyond 25 minutes on YouTube
- seeking efficiency test

Success criteria for adopting stream-direct as the main architecture:

- high slice-read success rate across your target sources
- acceptable URL lifetime
- efficient seeking for mid-file slices
- no major source-side throttling at your desired worker count
- clear enough Shazam behavior for your deployment target

For the tested YouTube and SoundCloud flows, the first three criteria are already met well enough to justify stream-direct as the default architecture. If you are comfortable deploying at about 2 concurrent recognitions per worker host, you do not need a pre-deployment Shazam stress test to move forward. The remaining open area is production-grade source coverage and post-deploy Shazam tuning.

## Recommended normalized schema

The data is relational. A SQL database fits better than document or key-value stores.

Core tables:

- `artists`
  - canonical artist row
  - normalized name, display name, profile image, genres, external ids
- `tracks`
  - canonical track row
  - title, normalized title, release metadata, bpm/key/label if available, external ids
- `track_artists`
  - many-to-many join between tracks and artists
- `sets`
  - one row per DJ set
  - title, slug, source platform, source url, duration, uploader, set-level artist, playlist ids, created/updated timestamps
- `set_tracks`
  - one row per track appearance in a set
  - `set_id`, `track_id` nullable for unknowns, ordinal, start_sec, end_sec, confidence, detection_count, source timestamp links
- `external_links`
  - optional normalized link table for Spotify / Discogs / YouTube / SoundCloud / ReccoBeats
- `artist_aliases`
  - optional alias table for fuzzy matching and de-duplication

Derived / optional:

- `artist_summaries`
- `set_summaries`
- `search_documents` or database-native FTS index
- `job_runs` and `job_events` for remote execution status

Do not put raw audio, raw recognition payloads, or transient checkpoints in this main product database unless you later decide they are product features.

## Storage size expectations

You are not storing raw audio. That changes everything.

A rough but conservative estimate for normalized storage is:

- 150 KB to 300 KB per set, including indexes and summary/search overhead

That implies:

- 500 MB database budget: roughly 1,500 to 3,000 sets
- 1 GB: roughly 3,000 to 6,000 sets
- 5 GB: roughly 15,000 to 30,000 sets
- 10 GB: roughly 30,000 to 60,000 sets

For your target of hundreds to low thousands of sets, storage is not the hard problem. Product ergonomics and future frontend fit matter more.

## Data storage + serving

### Ranking for this project

This ranking assumes you are willing to re-architect heavily if needed. The reason the top order still does not move much is that duration ceilings are only one part of the problem; free-forever economics and downloader-friendly hosting still dominate.

1. Supabase
2. Turso
3. Cloudflare D1
4. Neon
5. CockroachDB
6. MongoDB Atlas
7. Firestore
8. DynamoDB
9. PlanetScale
10. Cloud SQL / RDS

### Storage comparison

| Option | Free tier now | Concrete translation for this workload | Frontend / API fit | Verdict |
| --- | --- | --- | --- | --- |
| Supabase | 500 MB database, 50k MAU, 5 GB egress, 1 GB file storage, 2 active projects; free projects pause after 1 week idle | 500 MB is likely enough for roughly 1.5k to 3k sets if you only keep normalized data. Write volume is trivial. 5 GB egress is about 50k page loads/month if each response averages 100 KB. | Best product ergonomics here: Postgres, Auth, Storage, RLS, built-in APIs, Edge Functions | Best choice if you optimize for future app development, not raw free-tier headroom |
| Turso | 100 DBs, 5 GB total storage, 500M rows read/month, 10M rows written/month, 3 GB sync | 5 GB is far beyond your expected data volume. 10M writes/month is effectively tens of thousands of sets/month at your ingest pattern. | Strong with edge/static apps; SQLite + libSQL is very good for read-heavy public sites, but you must supply auth/API yourself | Best pure free-tier headroom; slightly more build-it-yourself than Supabase |
| Cloudflare D1 | 5M rows read/day, 100k rows written/day, 5 GB/account, 500 MB/database on free, 7-day time travel | 100k row writes/day is still hundreds of ingested sets/day. 500 MB per DB is probably enough for your near-term scope but is tighter than Turso/Cockroach. | Excellent with Workers + Pages. Good SQL story. Single-threaded per DB, so query design matters. | Very attractive if you already want a Cloudflare frontend, but the 500 MB per-DB cap is real |
| Neon | 100 projects, 100 CU-hours/project/month, 0.5 GB/project, 10 branches/project, 60k Neon Auth MAU, 5 GB public network transfer, scale to zero after inactivity | Storage is fine for your current scope. The catch is compute: a database that is continuously active can outgrow the free compute budget faster than storage suggests. | Great Postgres core, branching, Data API, Auth. Less turnkey than Supabase for a full product stack. | Good database choice, weaker "all the web-app pieces" story than Supabase |
| CockroachDB Basic | 50M RUs + 10 GiB storage free per month, scales to zero | 10 GiB is far beyond your expected data volume. 50M RUs is comfortably above your ingest needs. | SQL, multi-region, durable. But less ergonomic than Postgres for mainstream app tooling and more vendor-specific. | Strong free economics, lower practicality than Supabase/Turso for this app |
| MongoDB Atlas | Free forever M0 with 512 MB shared cluster | Storage is probably still enough for low-thousands of sets, but the model is less natural for your relational queries and future search pages. | Good general hosting ecosystem, but less natural than SQL for set/track/artist joins. Atlas Search is a separate consideration. | Viable, but a schema fit downgrade |
| Firestore | 1 GiB storage, 50k reads/day, 20k writes/day, 20k deletes/day, 10 GiB outbound/month | Writes are fine. Reads are the trap: a naive public set page could easily do 40 to 100 document reads, which makes 50k/day less generous than it looks. | Great with Firebase Hosting/Auth, weak for relational querying and search-heavy public browsing without denormalization | Good if you intentionally want Firebase, otherwise not a fit-first choice |
| DynamoDB | 25 GB free storage is still visible on pricing; AWS new-account free program is now credit-based for 6 months, with always-free services still present | Storage is huge for your needs. Read/write throughput is not likely your bottleneck. The real issue is that DynamoDB is a poor fit for your relational browsing/search model. | Works if you deliberately design around access patterns; poor fit for future SQL-style querying and reporting | Only worth it if you actively want AWS + NoSQL |
| PlanetScale | No free plan on current pricing page; paid plans start at $5/month | Not compatible with your permanent-free requirement | Good MySQL platform, but the free plan is gone | Eliminate |
| Cloud SQL / Amazon RDS | No permanent free tier. Cloud SQL has a free trial. RDS is promotional / legacy-program territory, not permanent free for new signups. | Not compatible with your permanent-free requirement | Good managed relational databases, but not under your constraints | Eliminate for strict `$0` |
| Cloudflare KV / R2 | KV: 1 GB and low daily write limits; R2: object storage, not a database | Not primary databases for your normalized query model | Useful as adjacent services only | Use only for artifacts or caches, not as the main product database |

### Storage takeaways

- The actual data volume is small enough that several free databases work.
- The best schema remains relational.
- Supabase is the best app platform.
- Turso is the best pure free-tier storage bargain.
- D1 is the best Cloudflare-native database, but the per-database 500 MB cap is tighter.
- Firestore and DynamoDB are schema compromises, not storage wins.

## Remote pipeline execution

### Ranking for this project

1. Oracle Cloud Always Free compute
2. GitHub Actions
3. GCE e2-micro Always Free
4. GCP Cloud Run Jobs
5. AWS Lambda only if you are willing to redesign into chunked jobs
6. GCP Cloud Functions 2nd gen only if you are willing to accept a less natural execution model
7. Fly.io
8. Railway
9. Render
10. AWS ECS / Fargate
11. AWS EC2 free tier
12. Cloudflare Workers
13. Vercel Functions

### How stream-direct changes the ranking

The prototype results strengthen stream-direct materially, but they still do not fully overturn the provider ordering because free-forever economics and egress policy still dominate.

- Oracle stays first for strict `$0` because it is the least sensitive to URL-affinity, temp-storage, binary, and egress quirks
- GitHub Actions stays strong because each worker can still be fully self-contained without much infrastructure
- Cloud Run Jobs improves because removing shared audio artifacts makes job design cleaner
- AWS Lambda becomes more technically credible because 15-minute limits stop being the main blocker
- Vercel improves from "basically wrong runtime" to "theoretically possible but still fragile"
- Cloudflare Workers still does not become a real worker option

So yes, the analysis changes, but not enough to overturn the main hosting recommendation.

### Execution comparison

| Option | Free tier now | Can it run FFmpeg + yt-dlp? | Concrete translation | Complexity | Verdict |
| --- | --- | --- | --- | --- | --- |
| Oracle Cloud Always Free VM | Up to 4 Ampere OCPUs / 24 GB RAM total or micro AMD shapes, 200 GB block volume, 10 TB outbound/month | Yes. Native VM or Docker. Install anything you want. | 10 TB outbound means the Shazam upload pattern is effectively irrelevant. 200 GB disk is ample. Enough compute for multiple workers. | Medium ops: you own the VM(s) | Best strict `$0` execution fit |
| GitHub Actions | Standard GitHub-hosted runners are free and unlimited on public repos; private repos get plan-based minutes. Standard Ubuntu runner is 4 CPU / 16 GB RAM / 14 GB SSD. Jobs max at 6 hours. | Yes. Install via apt/pip or use container jobs. | One 25-minute set consumes 25 runner-minutes. 44 sets/month is about 1,100 runner-minutes, which even fits inside private-repo free quotas, and is trivial on a public repo. 14 GB SSD is plenty. | Medium: workflow orchestration is less natural than a real worker service | Best "no server to manage" option |
| GCE e2-micro Always Free | 1 e2-micro VM/month in select US regions, 30 GB standard persistent disk, 1 GB outbound/day | Yes. Native VM or Docker. | Compute is likely enough because the workload is IO-bound, but 1 GB outbound/day is only about 6 to 8 sets/day at your Shazam upload pattern. A 20-set burst in one day can break free usage. | Medium ops | Good fallback if Oracle is unavailable, weaker for bursts |
| Cloud Run Jobs | Jobs free tier: 240k vCPU-seconds + 450k GiB-seconds/month. Task timeout up to 168 hours. | Yes, via container image. | Compute free tier is enough for about 150 sets/month at 1 vCPU / 2 GiB. But Cloud Run file system is in-memory, so your 200 to 500 MB temp files consume RAM directly. Internet egress is the real risk, so this is likely not truly `$0` at your usage. | Low to medium ops if containerized | Best low-cost PaaS, not best strict-free choice |
| Cloud Functions 2nd gen | HTTP functions can run up to 60 minutes; free monthly invocations and compute exist | Technically yes if packaged carefully, but it is a worse shape than Cloud Run Jobs | 25-minute jobs fit under 60 minutes, but you still inherit serverless request semantics and Cloud Run-style runtime constraints. | High relative to Cloud Run Jobs | Possible, but not the right default |
| AWS Lambda | 1M requests + 400k GB-seconds free/month, but max timeout is 900 seconds (15 minutes) | Yes via container image or layers, but packaging is not the main problem | Chunking can make Lambda technically viable, but only after a queue/state-machine redesign. It still fails the spirit of your permanent-free requirement because AWS's broader free-program story for new accounts is no longer a clean forever-free path. | High rewrite cost | Technically possible after chunking, still not a practical strict-free recommendation |
| AWS ECS / Fargate | No meaningful permanent free tier for new projects; AWS new-account program is credit-based for 6 months | Yes | Technically a good fit, but fails your permanent-free requirement | Medium | Eliminate for strict `$0` |
| AWS EC2 free tier | Not a permanent free path for new accounts. AWS now pushes new customers into a 6-month credit-based plan. | Yes | Good technically, not compatible with your free-forever requirement | Medium ops | Eliminate for strict `$0` |
| Cloudflare Workers | 100k requests/day, 10 ms CPU/request on free plan | No, not for the worker itself in classic Workers | Workers can front a queue or API, but the actual media / recognition worker must live somewhere else. Re-architecting does not change that. | Very high if redesigned around external compute | Fine as control plane, hard no as the worker runtime |
| Vercel Functions | Current docs show Hobby with Fluid Compute enabled by default at up to 300 seconds max; older / non-Fluid behavior is 60 seconds max. Python bundle limit is 500 MB uncompressed. | Maybe, for a fully rewritten stream-direct worker | With 30 to 60 second stream-direct workers, Vercel becomes technically possible. But it is still tight in practice because cold starts, source resolution, retries, and upstream throttling can easily eat the margin. | High rewrite cost | Worth mentioning only as an experimental edge case, not a serious default |
| Fly.io | Free allowances are legacy-only for old accounts. New customers are on pay-as-you-go and require a card. | Yes | Good technical fit, not a permanent-free fit for a new project today | Medium | Consider only if you accept paid hosting |
| Railway | Free trial with credits, then minimum paid plan | Yes | Technical fit is fine, but it is not free forever. Also the visible entry plan includes only 0.5 GB volume storage, which is tight for your temp-file pattern. | Low to medium | Not compatible with strict `$0` |
| Render | Free instances exist for web services and some datastores; background workers are not part of the free story | Yes on paid workers | Your actual worker belongs on a background worker, and that is not the free path. Free web instances are the wrong shape for this job. | Low to medium | Not a real free worker option |

### Execution takeaways

- Oracle is the best strict-free worker host by a clear margin.
- GitHub Actions is the best no-server alternative, especially if the repo can be public.
- GCE e2-micro is viable, but its daily egress cap makes bursts awkward.
- Cloud Run Jobs is the best tiny-paid option.
- Lambda and Cloud Functions become technically plausible only if you intentionally redesign the pipeline into resumable chunks.
- Vercel becomes technically plausible only for a very optimized stream-direct architecture, but remains a weak practical fit.
- Cloudflare Workers are still wrong for the worker itself.
- Heavy re-architecture mainly improves time-limit fit. It does not erase the outbound-traffic and hosting-policy constraints.

### Step Functions bottleneck

If you model a high fan-out worker graph on AWS Step Functions Standard, the free tier is too small very quickly.

- AWS Step Functions Standard includes 4,000 free state transitions per month
- A 150-worker fan-out can easily consume a few hundred transitions per set even before retries
- At that scale, you can burn through the free tier in well under one month

So this is a valid bottleneck and the mitigation is correct:

- do not use Step Functions Standard as the main coordination layer for a 150-worker fan-out on a strict free budget
- prefer SQS, a database-backed job table, or a DynamoDB counter / lease pattern for coordination

## Recommended worker architecture

### Best strict `$0` architecture

- Frontend/API: separate lightweight app
- Queue / status: database-backed job table
- Worker control plane: one scheduler on Oracle VM
- Worker execution: stream-direct slice workers on the same Oracle VM or VM pool
- Initial recognition concurrency: cap at about 2 per worker host until production data says otherwise
- Product DB: Supabase or Turso
- URL refresh: resolve new playable URLs as needed when the current one ages out
- Fallback path: acquire-once chunk workers only for sources that fail stream-direct

Why this wins:

- matches the prototype-validated happy path
- supports a queue/poll model cleanly for both CLI and web triggers
- enough bandwidth to ignore Shazam upload costs
- enough disk for the fallback path when a source does need acquisition
- lets you scale workers horizontally without forcing everything into request-scoped serverless

### Best low-ops worker architecture

- Frontend/API: lightweight web app
- Trigger: GitHub Actions workflow dispatch
- Worker: GitHub-hosted runner
- Execution model: either one set per workflow or stream-direct fan-out followed by an aggregate job
- Product DB: Supabase or Turso
- Checkpoints: job-state rows and small manifests in the database; artifact/object storage only if fallback chunk files must be shared between jobs

Why this wins:

- almost no infrastructure to administer
- enough CPU/RAM/disk for the current pipeline
- web and CLI triggers are both straightforward via the GitHub API / `gh`

Tradeoff:

- GitHub is a workflow engine, not a first-class background worker platform

### Best tiny-paid architecture

- Frontend/API: Cloud Run service or static frontend + API route
- Worker: Cloud Run Jobs
- Execution model: queue-driven stream-direct slice jobs plus an aggregate/publish job
- Product DB: Supabase or Turso
- Intermediate artifacts: usually just externalized job state; object storage only for fallback acquisition jobs

Why it is worth reconsidering:

- the compute quota itself is strong enough for your monthly workload
- the likely spend driver is egress, not CPU
- at your volume, that cost should usually stay in low single digits
- operationally this is cleaner than babysitting VMs
- chunked jobs are a very natural fit for this platform

## Single-vendor reality check

If you insist on one vendor and permanent free:

- Oracle is the only credible answer

Why:

- Always Free compute is real
- outbound bandwidth is real
- block storage is real
- Oracle also offers Always Free database products, including Autonomous Database and MySQL HeatWave

Why it still is not my first recommendation:

- weaker frontend/product ergonomics than Supabase or Cloudflare-style stacks
- more operational friction
- Oracle signup / region capacity issues are common gotchas

## Spotify and auth gotchas

- Remote playlist creation is feasible, but it changes the auth story.
- If only you create playlists, store one refresh token securely and expose a toggle in the app.
- If public users should create playlists in their own accounts, you need a full user-auth model and callback handling.
- The current local callback assumption (`127.0.0.1`) must be replaced with a real deployed callback URL.

## yt-dlp hosting gotchas

- VM-style hosts are safer than edge/serverless platforms for this workload.
- Free PaaS and workflow platforms can still throttle or suspend workloads that look like media downloading abuse.
- This is another reason Oracle VM or a small paid Cloud Run / VM path is better than trying to force the worker into Vercel, Workers, or a free web-service tier.

## Bottom-line recommendation

### If you stay strict on permanent free

- Storage: Supabase if you want the best future product platform, Turso if you want more free headroom
- Execution: Oracle Cloud Always Free VM

My default recommendation for you is:

- Oracle Cloud VM for the stream-direct pipeline
- conservative recognition concurrency of about 2 per worker host at launch
- Supabase for the product database
- stage-separated acquire/fan-out as the fallback path
- separate frontend later

That is mixed-vendor, but it best matches your actual priorities.

### If you allow a very small monthly cost

- Cloud Run Jobs becomes the most attractive execution platform

Why:

- much lower ops than Oracle
- much more natural than Lambda
- enough free compute for your real monthly load
- likely only small egress cost at your current scale
- stream-direct workers are now prototype-validated enough to make this a very clean fit

## Sources

### Storage

- [Supabase pricing](https://supabase.com/pricing)
- [Supabase database size limits](https://supabase.com/docs/guides/platform/database-size)
- [Neon pricing](https://neon.com/pricing)
- [Turso pricing](https://turso.tech/pricing)
- [MongoDB pricing](https://www.mongodb.com/pricing)
- [CockroachDB pricing](https://www.cockroachlabs.com/pricing/)
- [PlanetScale pricing](https://planetscale.com/pricing)
- [Cloudflare D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/)
- [Cloudflare D1 limits](https://developers.cloudflare.com/d1/platform/limits/)
- [Cloudflare KV pricing](https://developers.cloudflare.com/kv/platform/pricing/)
- [Cloudflare KV limits](https://developers.cloudflare.com/kv/platform/limits/)
- [Cloudflare R2 pricing](https://developers.cloudflare.com/r2/pricing/)
- [Firestore pricing](https://cloud.google.com/firestore/pricing)
- [Google Cloud free-tier catalog](https://docs.cloud.google.com/free/docs/free-cloud-features)
- [Amazon DynamoDB on-demand pricing](https://aws.amazon.com/dynamodb/pricing/on-demand/)
- [Amazon RDS free tier page](https://aws.amazon.com/rds/free/)
- [yt-dlp documentation](https://github.com/yt-dlp/yt-dlp)
- [FFmpeg formats documentation](https://ffmpeg.org/ffmpeg-formats.html)

### Execution

- [Oracle Cloud Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
- [AWS Free Tier FAQs](https://aws.amazon.com/free/free-tier-faqs/)
- [AWS Free Tier overview](https://aws.amazon.com/free/)
- [AWS Lambda pricing](https://aws.amazon.com/lambda/pricing/)
- [AWS Lambda timeout limit](https://docs.aws.amazon.com/lambda/latest/dg/configuration-timeout.html)
- [Cloud Run pricing](https://cloud.google.com/run/pricing)
- [Cloud Run request timeout](https://cloud.google.com/run/docs/configuring/request-timeout)
- [Cloud Run jobs](https://cloud.google.com/run/docs/create-jobs)
- [Cloud Run container contract](https://cloud.google.com/run/docs/container-contract)
- [Cloud Run functions quotas](https://docs.cloud.google.com/functions/quotas)
- [Vercel Functions limits](https://vercel.com/docs/functions/limitations)
- [Vercel function duration configuration](https://vercel.com/docs/functions/configuring-functions/duration)
- [Fly.io pricing](https://fly.io/docs/about/pricing/)
- [Railway pricing](https://railway.com/pricing)
- [Render pricing](https://render.com/pricing)
- [Render free docs](https://render.com/docs/free)
- [Render background workers](https://render.com/docs/background-workers)
- [AWS Step Functions pricing](https://aws.amazon.com/step-functions/pricing/)
- [GitHub-hosted runner specs](https://docs.github.com/en/actions/reference/github-hosted-runners-reference)
- [GitHub Actions billing](https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions/about-billing-for-github-actions)
- [GitHub Actions limits](https://docs.github.com/en/actions/reference/limits)
- [yt-dlp FAQ](https://github.com/yt-dlp/yt-dlp/wiki/FAQ)
