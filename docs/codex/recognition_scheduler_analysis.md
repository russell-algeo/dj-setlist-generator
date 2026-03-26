# Recognition Scheduler Analysis

## Benchmark Setup

- Benchmark source: `https://soundcloud.com/soundofthecity/dyed-soundorom-sound-of-the`
- Prepared workload:
  - `240` segments
  - `30s` segment duration
  - `15s` overlap
- Concurrency:
  - `CONCURRENT_RECOGNITIONS = 2` per recognize runner
- Objective:
  - minimize end-to-end GitHub Actions wall time, not just recognition duration

## Slot Sweep At `lease_size=10`

| Slots | Leases | Leases/Slot | Total (s) | Workflow |
|------:|-------:|------------:|----------:|---------:|
| 6 | 24 | 4.0 | 414 | `23594772190` |
| 8 | 24 | 3.0 | 329 | `23595069162` |
| 10 | 24 | 2.4 | 342 | `23595307130` |
| 12 | 24 | 2.0 | 288 | `23595554976` |
| 16 | 24 | 1.5 | 319 | `23595766630` |

### Takeaway

- The slot curve improves through `12` and then rolls over at `16`.
- `12` slots is the best observed width on this benchmark set.
- The winning slot-width region is near `2` leases per slot.

## Large-Lease Sweep At `12` Slots

| Lease Size | Leases | Leases/Slot | Total (s) | Workflow |
|-----------:|-------:|------------:|----------:|---------:|
| 10 | 24 | 2.00 | 288 | `23595554976` |
| 12 | 20 | 1.67 | 312 | `23596076504` |
| 15 | 16 | 1.33 | 288 | `23596308725` |
| 20 | 12 | 1.00 | 306 | `23596713480` |
| 24 | 10 | 0.83 | 344 | `23596956002` |

### Takeaway

- The coarse-lease trend is not monotonic:
  - `15` matched the best single `10` run once
  - `12`, `20`, and `24` were all worse than the best `10` run
- So `10` and `15` are the only plausible minima in this region.

## Variance Check For The Top Two Configs

Repeated successful runs:

### `12` slots / `lease_size=10`

- Workflows: `23595554976`, `23597277660`, `23598305099`
- Totals: `288`, `299`, `326`
- Mean: `304.3s`
- Median: `299s`
- Population stdev: `16.0s`
- Range: `38s`

### `12` slots / `lease_size=15`

- Workflows: `23596308725`, `23597516997`, `23598580438`
- Totals: `288`, `328`, `314`
- Mean: `310.0s`
- Median: `314s`
- Population stdev: `16.6s`
- Range: `40s`

### Variance Interpretation

- The variance band is real and non-trivial. At this runner scale, the noise floor is on the order of `~15-17s`.
- Because of that, a tiny single-run delta is not meaningful by itself.
- The `10` vs `15` comparison is still directionally usable because:
  - `10` has the lower mean
  - `10` has the lower median
  - `10` has the lower max
  - `10` ties `15` on best-case time
- The gap is modest, not dramatic. The correct read is:
  - `lease_size=10` is the safer local minimum
  - `lease_size=15` is same-tier but slightly worse in central tendency

## Failure / Robustness Notes

Failed attempts observed during benchmarking:

- `12` slots / `lease_size=10`
  - failed workflow runs: `23597786373`, `23598024431`
- `12` slots / `lease_size=20`
  - failed workflow run: `23596520831`

Failure mode for all three:

- recognize runner failure during `Install ffmpeg`
- no evidence of scheduler or publish logic failure

Interpretation:

- These failures should be treated as GitHub Actions infrastructure/setup noise, not as evidence that a specific lease size is logically incorrect.
- They still matter operationally because they lengthen time-to-result when retries are required.
- They should not be used as the primary selector between `10` and `15`, because the failure step happens before the workload-specific recognition logic runs.

## Recommended Scheduler Formula

Use an auto scheduler with:

- `AUTO_MAX_RECOGNITION_SLOTS = 12`
- `AUTO_TARGET_SEGMENTS_PER_SLOT = 20`
- `AUTO_TARGET_LEASES_PER_SLOT = 2`
- `AUTO_MIN_LEASE_SIZE = 10`

That yields, for the benchmark set:

- `slot_count = 12`
- `lease_size = 10`
- `lease_count = 24`

## Why This Formula

- It lands exactly on the best measured slot-width.
- It targets the best measured lease-density region, about `2` leases per slot.
- It avoids the clearly slower regimes:
  - too few slots (`6`, `8`)
  - too many slots (`16`)
  - too-coarse leases (`20`, `24`)
- It also beats the smaller-lease experiments from the earlier sweep (`4`, `6`, `8`) where scheduler overhead dominated.

## Final Recommendation

Default to:

- `12` effective recognition slots
- `10` segments per lease
- auto-computed from segment count using the formula above

Manual overrides should remain available for benchmarking and future retuning.
