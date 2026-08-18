# Field Tests

- [Field Test #1](#field-test-1--v035-alpha) — first production attach,
  controlled conditions (2026-07-19)
- [Field Test #2](#field-test-2--unplanned-blackout-recovery) —
  **unplanned datacenter blackout**, real disaster recovery (2026-07-23)
- [Field Test #3](#field-test-3--nine-day-run--worst-case-cache-behaviour)
  — nine-day run, cache thrashing analysis, **worst-case validation**
  (2026-08-02)
- [Field Test #4](#field-test-4--unexplained-host-reset-remote-recovery)
  — unexplained spontaneous reset, **fully remote recovery**
  (2026-08-06)
- [Field Test #6](#field-test-6--power-loss-during-array-initialisation)
  — both power cords pulled mid-BGI; recovery with an uninitialised
  array underneath (2026-08-13)
- [Field Test #7](#field-test-7--ssd-tier-where-the-bottleneck-actually-is)
  — uncached SSD tier measured locally and through the fabric: **a
  cache policy cost 6× write throughput, and the FC link is the next
  wall** (2026-08-14)
- [Field Test #5](#field-test-5--raid-0-vs-raid-6-same-vm-same-cache)
  — RAID 0 vs RAID 6 on identical VM and cache: **84,700 IOPS at 1.49 ms
  through the cache, and the discovery that a faster array makes the
  cache itself 5.9× faster** (2026-08-10 → 2026-08-15, complete)
- [Field Test #8](#field-test-8--guest-to-guest-copy-read-modify-write-measured)
  — an ordinary 10 GB file copy between two VMs: **the RAID 6
  read-modify-write penalty measured directly, and the 8 Gb upgrade
  case narrowed to reads only** (2026-08-16)
- [Field Test #9](#field-test-9--a-working-day-measured-layer-by-layer)
  — a full working day captured unfiltered: **the read path decomposed
  across three layers (0.010 ms RAM / 12.77 ms array / 0.08 ms as the
  guest sees it), the fabric at 19.9 % of capacity in its busiest
  minute, and the discovery that the cumulative counters had been
  measuring our own benchmarks** (2026-08-17)

Measurement procedure for all performance runs:
[benchmark-protocol.md](benchmark-protocol.md)

Controller and drive findings from building the arrays underneath —
MegaCli addressing quirks, cache policy choices, drive screening:
[hardware-notes.md](hardware-notes.md)

---

# Field Test #1 — v0.3.5-alpha

Date: 2026-07-19
First production attach of Yellowstone Cache on real hardware.

## Environment

| Component | Detail |
|-----------|--------|
| Server | Dell PowerEdge R510, 24 threads, 62 GiB RAM |
| Controller | Dell PERC H700 |
| Origin volume | 2-disk RAID 0, ~15 TB (temporary; final target is 8×8 TB RAID 6) |
| Fabric | QLogic FC (qla2xxx target mode) → VMware ESXi 7.0 |
| OS | Ubuntu, kernel 6.8.0-136-generic |
| Cache | 12 GiB RAM (brd), writethrough, smq, preallocated |
| Workload | Windows NVR VM (boot + 1 GiB file copy), Alpine VM with containers (PHP + MySQL site) |

Device map for the iostat capture below:

```text
dm-3 = TestDiskCached        (cache target — what LIO exports)
dm-2 = TestDiskCached-cdata  (RAM data area — reads here are CACHE HITS)
dm-1 = TestDiskCached-cmeta  (metadata)
dm-0 = ubuntu-vg root LV     (system, unrelated)
sdb  = origin RAID 0         (cache MISSES + all writethrough writes)
sda  = system disk
```

## Results summary

| Metric | Result |
|--------|--------|
| Attach downtime (`up`, incl. 12 GiB prealloc) | **9.69 s** |
| ESXi datastore after attach | re-detected automatically, same NAA, **no resignature** |
| Cache hit read latency (dm-2) | **0.01–0.02 ms** |
| Cache miss read latency (sdb, 2-disk RAID 0) | 11–50 ms (up to ~75 ms under write pressure) |
| Peak hit-served read burst | **61.3 of 61.7 MB/s (~99 %) from RAM** at 0.02 ms |
| Writethrough verification | dm-3 write MB/s == sdb write MB/s in every interval; **dirty = 0 throughout** |
| Read latency of hits during 95–98 % origin utilization | still sub-millisecond (immune to write pressure) |
| After ~30 min mixed workload | 47,330 read hits / 27,217 misses (**63.5 %** cumulative from cold start) |
| Promoted working set | 5,515 × 256 KiB blocks ≈ **1.4 GiB** (11.33 % of cache) |
| Demotions | 0 (no cache pressure) |
| Subjective | containerized PHP + MySQL site "noticeably faster" after first warm-up |

## Interpretation

**1. Windows VM boot (first interval).** Hits served from dm-2 at
0.01 ms while misses hit sdb at 11.5 ms — a ~1000× latency gap between
RAM and spindles, visible in a single iostat line.

**2. 1 GiB file copy — read phase.** dm-3 delivered 61.7 MB/s of reads
at 1.02 ms average; 61.3 MB/s of that came from dm-2 (RAM) at 0.02 ms,
with sdb contributing only 3.5 MB/s. The following interval was even
cleaner: 40.6 of 40.7 MB/s from RAM (~99 % hit).

**3. 1 GiB file copy — write phase.** Writethrough behaved exactly as
specified: every interval shows dm-3 write throughput equal to sdb
write throughput (e.g. 43.8 == 43.8 MB/s), and `dirty` remained 0 at
all times. The RAID 0 volume saturated at 95–98 % util with read
latencies climbing to 45–75 ms — while cache hits stayed at 0.0x ms,
demonstrating that cached reads are immune to origin write pressure.

**4. Cache discipline.** Only ~1.4 GiB was promoted despite tens of GB
of I/O passing through — the smq policy bypassed sequential streams
and promoted only the genuinely hot working set. Zero demotions: no
pressure, ample headroom in the 12 GiB cache.

## Raw data

### `yellowstone up` (after quiescing the ESXi initiator — see note)

```text
[ OK ] Cache attached to 'TestDisk' (downtime 9.69s, wwn untouched).
```

Note: the first attach attempt hung in `targetctl clear` because the
ESXi host still had an active FC session (datastore mounted, an SSH
session parked inside the datastore path, ISP error recovery mid-
teardown). Lesson recorded: unmount the datastore / quiesce initiators
before `up`/`down`. After a reboot with `target.service` disabled, the
attach completed in seconds.

### `yellowstone status TestDisk` (after ~30 min of mixed workload)

```text
Cache: TestDisk
---------------
Origin                : /dev/disk/by-id/wwn-0x6848f690dafdf90031eb4a5a19ecaa0c
Cache device          : /dev/ram0
Configured mode       : writethrough

Statistics
----------
Mode                  : writethrough
Cache usage           : 5515/48660 blocks (11.33%)
Metadata usage        : 103/31457
Read hits/misses      : 47330/27217 (ratio 0.6349)
Write hits/misses     : 7581/11251 (ratio 0.4026)
Dirty blocks          : 0
Promotions            : 5515
Demotions             : 0
```

### iostat capture (selected intervals)

Windows boot — hits at 0.01 ms, misses at 11.5 ms:

```text
Device       r/s     rkB/s  r_await   w/s    wkB/s  w_await  aqu-sz  %util
dm-2       50.60   2147.07     0.01  10.53  1543.63    0.06    0.00   0.13   <- RAM hits
dm-3       83.10   3585.45     5.07   6.22    58.69    5.67    0.46  11.27   <- cache target
sdb        73.87   6815.18    11.54   5.72    93.36    0.13    0.85  15.67   <- origin misses
```

File copy, read phase — ~99 % served from RAM:

```text
dm-2      792.60  61378.70     0.02  14.60  3131.00    0.10    0.02   2.00
dm-3      814.80  61763.50     1.02   2.80    33.40    0.07    0.83  61.00
sdb        45.80   3508.00    39.88   2.80    33.40    0.14    1.83  63.42

dm-2      534.20  40623.20     0.02   3.80   415.80    0.00    0.01   1.04
dm-3      537.60  40688.70     0.28   2.40     9.40    0.00    0.15   7.98
sdb         6.40    475.10    45.19   2.40     9.40    0.17    0.29   7.54
```

File copy, write phase — writethrough (dm-3 writes == sdb writes),
origin saturated, hits still sub-ms:

```text
dm-2        3.20     41.40     0.00  21.00  3355.80    0.06    0.00   0.12
dm-3      253.80  19239.00    76.71 219.80 15858.20    1.34   19.76  97.60
sdb       204.40  22243.20    73.37 163.40 15858.20    0.20   15.03  98.18

dm-2      179.00   1956.00     0.01 150.20 19519.90    0.04    0.01   0.76
dm-3      440.60  18645.60    34.02 637.60 43861.10    2.37   16.50  92.60
sdb       324.20  32254.40    45.75 490.00 43861.10    0.22   14.94  95.04
```

<details>
<summary>Full iostat -x 5 log (unabridged)</summary>

Full capture retained in project records; the intervals above are
representative excerpts. The complete log shows the same pattern
across all 16 intervals: dm-2 read latency 0.00–0.02 ms in every
interval with read activity, dm-3 write throughput equal to sdb write
throughput in every interval, dirty blocks 0 throughout.

</details>

## Caveats

- Origin was a 2-disk RAID 0 — miss latencies will differ on the final
  8×8 TB RAID 6 array. A new baseline and full re-test is planned
  there.
- Hit ratio (63.5 %) is cumulative from a completely cold cache and
  includes all warm-up misses; steady-state ratio is higher.
- Single test system, single day. This is an alpha field test, not a
  benchmark suite.

---

# Field Test #2 — Unplanned blackout recovery

Date: 2026-07-23 · Yellowstone Cache **v0.3.5-alpha**
**This was not a scheduled test.** A real datacenter blackout provided
the harshest possible validation: violent power loss mid-I/O, cold
start, full recovery.

## The incident

City power grid work caused a building-wide blackout during the night.
The backup generator failed to start, UPS units drained, and no static
transfer switch was installed (a known, previously reported gap). All
servers — storage nodes, FC fabric, ESXi hosts — lost power hard,
mid-operation. FC links dropped in the middle of active I/O.

At the time of the blackout the Yellowstone node had been serving four
production VMs (Windows NVR, M365 archive backup, Moodle in containers,
nginx WAF) for ~4 days, with a fully warm cache that had passed
~2 TB of promotions and hundreds of millions of I/Os.

## Yellowstone recovery — worked exactly as designed

```text
power restored
  → node boots, LIO intentionally NOT started (target.service disabled)
  → yellowstone repair            # plan: recreate
  → yellowstone repair --apply    # RAM disk rebuilt (16 GiB, prealloc),
                                  # dm-cache reassembled from state
                                  # (origin via stable by-id path),
                                  # LIO restored from saveconfig.json
  → LUN exported with the SAME NAA ID
```

Results:

| Check | Outcome |
|-------|---------|
| Data loss | **Zero** — writethrough: every acknowledged write was on the RAID before the power died |
| Recovery procedure | `repair --apply` — single command, no manual dm/LIO surgery |
| LUN identity | identical NAA, ESXi accepted the datastore without resignature |
| State machinery | phase tracking + by-id origin in `state/caches.json` behaved per spec (docs/state.md) |
| Cache | restarted cold (expected for RAM cache) and re-warmed under load |

Operator note: cache size was raised from 12 GiB to 16 GiB during
re-establishment (config change only — `cache_ram = 16G`).

## What required manual work (initiator side, not Yellowstone)

The ESXi side needed hands-on recovery, now documented in
[docs/recovery.md](recovery.md):

- **Dead world locks**: hosts that had running VMs at power loss kept
  stale locks on the LUN — cleared per host with a force-kill +
  rescan one-liner (post-crash only!).
- **Frozen FC HBA driver**: after the power hit, `qlnativefc` entered
  a queue freeze (link up, no traffic) — recovered with
  `esxcli storage core adapter rescan --type=all` and, where needed,
  re-attaching the LUN from the ESXi "detached" list.
- **vCenter chicken-and-egg**: the vCenter VM lived on the Yellowstone
  datastore, so cluster orchestration was unavailable until the storage
  itself was recovered; vCenter had to be booted directly from a host.
  **Lesson: the orchestrator must not depend on storage that requires
  manual assembly.** (Planned: move vCenter to the primary array.)

## Conclusions

1. The core design promises held under a real disaster: writethrough =
   zero loss, identity preservation = zero resignature, `repair` =
   one-command recovery. Nothing about the Yellowstone layer needed
   improvisation.
2. The deliberate "nothing runs at boot, admin drives recovery" policy
   proved its worth: no half-started services, no boot loops, recovery
   happened in a controlled order once the hardware was stable.
3. The gaps were all on the initiator side and organizational side
   (ESXi lock/HBA recovery — now documented; missing redundant power —
   reported long before the incident).

---

# Field Test #3 — Nine-day run & worst-case cache behaviour

Date: 2026-08-02 · Yellowstone Cache **v0.3.5-alpha** (uptime 8d 22h since blackout recovery)

The most important test so far is not the best-case number — it is
what the cache does when the workload actively fights it.

## Setup change

Cache raised from 12 GiB to 16 GiB during post-blackout recovery
(config change only: `cache_ram = 16G`, applied on next assemble).

Single LUN (`TestDisk` / datastore `PRIVREMEN15T`, 14.6 TiB) shared by
six VMs — deliberately not split:

| VM | Provisioned | Used | I/O character |
|----|-------------|------|---------------|
| phpLIST (M365 archive) | 12.48 TB | 6.07 TB | large scans + 3×/week full-read replication |
| Video_Nadzor (NVR) | 2.93 TB | 1.47 TB | many concurrent camera streams |
| 2012rwin2 | 98 GB | 98 GB | small hot working set |
| wcl_proxy_clone | 74 GB | 74 GB | small hot working set |
| waf_wcl_clone (nginx WAF) | 39 GB | 39 GB | small hot working set |
| wcl_proxy_new_U | 74 GB | (off) | — |

Environment note: VMFS automatic space reclamation is enabled at
100 MB/s on all datastores. dm-cache invalidates the affected cache
blocks, so reclamation and caching coexist without stale data.

**Correction (2026-08-15):** an earlier version of this note claimed the
discard is also passed down to the origin. It is not — `dmsetup status`
on this system reports the `no_discard_passdown` feature, which the
kernel sets automatically because the H700 virtual disk over spinning
disks does not advertise discard support. UNMAP therefore stops at the
cache layer. Harmless for HDDs, but worth knowing before assuming TRIM
reaches an SSD tier behind the same controller.

## Cumulative counters after 9 days

```text
Cache usage      : 64880/64880 blocks (100.0%)
Read hits/misses : 145573368 / 212384609  (ratio 0.4067)
Write hits/misses:  85482750 /  35546544  (ratio 0.7063)
Dirty blocks     : 0
Promotions       : 24055988      (≈ 6.15 TB moved through a 16 GiB cache)
Demotions        : 23991110
```

## Delta measurements — why cumulative numbers lie

Two consecutive samples were taken to measure the *current* regime
rather than nine days of history:

| Interval | Read hits | Read misses | Hit ratio | Promotions | Data promoted | Cache turnover |
|----------|-----------|-------------|-----------|------------|---------------|----------------|
| ~10 min | +159,693 | +322,330 | **33.1 %** | +50,984 | 13.0 GB | ~12.7 min |
| ~15 min | +422,819 | +823,098 | **33.9 %** | +132,299 | 33.9 GB | **~7.5 min** |

Promotions equal demotions to within a few blocks in both intervals —
the textbook signature of a saturated cache: every incoming block must
evict another.

**Cache turnover of ~7.5 minutes** means a promoted block is evicted
before it can be reused. The cache is behaving as a conveyor belt, not
as a cache. The current-rate ratio (~34 %) is *worse* than the
cumulative one (40.7 %), so this is the live regime, not historical
baggage.

## Root cause: workloads that defeat sequential bypass

`smq` deliberately bypasses sequential I/O, so video streams should
never have entered the cache. They do anyway — because **an NVR writes
and reads many camera streams concurrently, and at the block layer
those interleave into what looks like random I/O**. Each stream is
sequential on its own; together they defeat the sequential detector.

Video is the worst possible cache tenant: enormous volume, zero reuse
(nobody reads yesterday's footage twice). The same applies to the
3×/week replication job, which reads the entire 6 TB archive VM.

`smq` exposes no tunable for this (the old `mq` policy's
`sequential_threshold` was removed), so the only remedy is structural:
**give bulk/streaming workloads storage of their own.**

## Worst-case validation — the actual finding

During the 15-minute sample the system demanded **1,384 read IOPS**.
The cache absorbed **~470 IOPS**; only 914 reached the disks. The
origin at that time was a **2-disk RAID 0**, realistically capable of
300–400 random IOPS.

Without the cache the array could not have delivered what was asked of
it — latency would have collapsed. Even while being actively poisoned
by video streams, the 16 GiB RAM cache was the difference between a
working system and a saturated one.

Both ends of the spectrum are now measured on the same tool:

| Workload | Read hit ratio |
|----------|----------------|
| Normal VM workload (Field Test #1) | **96 %** |
| Cache-hostile (multi-stream video + full-scan backup) | **34 %** — still prevents array saturation |

And through all of it, across ~6 TB of promotions, a blackout and a
live cache resize: **dirty blocks 0**.

## Planned A/B (baseline recorded)

The NVR VM will be migrated to the QNAP array (FC, SATA + NVMe read
cache — the right home for sequential video). Baseline for comparison:

```text
BEFORE (2026-08-02): hit ratio 33.9 % | promotions 37.6 MB/s |
                     turnover 7.5 min | 1,384 read IOPS
```

Expected after removal: turnover measured in hours rather than
minutes, hit ratio back into the 70–90 % range — an isolated, single-
variable test of the video-pollution hypothesis.

## Lessons

1. **Measure deltas, not cumulative counters.** Nine-day totals said
   41 %; the live regime was 34 % with a 7.5-minute turnover. Only the
   delta explains *why*. (`status --delta` is now on the roadmap.)
2. **Multi-stream NVR/video workloads defeat dm-cache sequential
   bypass** — they must not share a cached LUN with latency-sensitive
   VMs.
3. **Full-scan backup/replication jobs flush the entire cache** on
   every run; place the VMs they read on uncached storage where
   possible.
4. A low hit ratio is not automatically a failure. Absorbing a third of
   the read load can be the difference between a functioning array and
   a saturated one.

---

# Field Test #4 — Unexplained host reset, remote recovery

Date: 2026-08-06 · Yellowstone Cache **v0.3.5-alpha**

Second unplanned outage, and the first one recovered **entirely
remotely** — no console, no site access, no manual dm/LIO surgery.

## What happened

After 13 days of uninterrupted operation the storage node reset itself
at 18:45. Nobody was on site: the server room floor was locked and the
administrator was at home. The first symptom seen from the outside was
an ESXi host losing its datastore.

State found on the node:

```text
$ yellowstone status TestDisk
[FAIL] Cache 'TestDiskCached' does not exist.

$ dmsetup ls
ubuntu--vg-ubuntu--lv (252:0)      # only the system LV — cache gone

$ uptime
19:07:59 up 22 min                 # the node had rebooted

$ lsblk
sdb  14.6T disk                    # origin present and healthy
```

`state/caches.json` still held the record (`phase: active`), and
`saveconfig.json` still pointed at `/dev/mapper/TestDiskCached` — the
exact "recreate" case described in [state.md](state.md).

## Recovery — one command, from home

```text
$ sudo yellowstone repair --apply

Repair — EXECUTED
Name    : TestDisk
Action  : recreate
State   : phase=active, saveconfig.dev=/dev/mapper/TestDiskCached, dm_target=missing
[ OK ] 'TestDisk' cache recreated after reboot, LIO up.
```

The RAM disk was rebuilt, dm-cache reassembled over the origin (taken
from the **state file**, as a stable `/dev/disk/by-id/` path — after an
attach, `saveconfig.json` no longer contains the origin), and LIO
restored. The datastore reappeared on the ESXi hosts **by itself**,
without a rescan, because the NAA never changed.

| Check | Outcome |
|-------|---------|
| Data loss | **Zero** (writethrough — dirty was 0 at all times) |
| Operator action | one command, over SSH, from off-site |
| Console / physical access needed | **none** |
| LUN identity | unchanged; hosts re-attached automatically |
| Cache after recovery | cold, warming: 1.65 % used, 68.9 % hit ratio within minutes |

## Root cause: main power rails collapsed (BMC power telemetry)

Every log was silent, but the BMC's **power monitoring statistics**
caught it — the one instrument that samples continuously rather than
waiting for an event to declare itself:

```text
Min Power Consumption (last day / last week) : 26 W
Min Power Time                               : Aug 06 2026 04:41:47 PM   (BMC clock, UTC)
                                             = 18:41:47 local (CEST)  ← the reset
Normal running draw                          : ~155 W
```

**26 W is standby-only draw.** The machine did not warm-reset — its
main rails went down and came back up.

Crucially, this is *not* an input power failure: the BMC runs on the
standby rail and never rebooted (no `System Boot` entry, and it kept
logging normally). Input voltage was present on both supplies before
and after. So:

> The 12 V rails collapsed while standby survived — the signature of a
> supply-side internal fault or a power-sequencing failure on the
> board, not of a datacenter power event.

On a 2009-era platform with original PSUs, aged capacitors are the
leading candidate. Follow-up: monitor BMC `Min Power` (any dip below
~100 W is an event), swap one PSU if a spare exists, inspect and
reseat both at the next downtime, and verify the two supplies really
are on independent UPS branches.

**Timekeeping note:** the BMC clock ran 2 hours behind the OS (UTC vs
CEST). Without noticing that offset the 16:41 event would never have
been matched to the 18:45 reset. Check BMC/OS clock alignment *before*
you need to correlate logs.

### Evidence table (what was ruled out along the way)

| Evidence | Conclusion |
|----------|------------|
| `last -x` shows `crash`, no `shutdown` record | abrupt reset, not an orderly reboot |
| journal of previous boot ends mid-stream, no errors | nothing was written before the reset |
| IPMI SEL empty since the last manual clear | no logged hardware fault (memory, thermal, PSU) |
| iDRAC RAC log: no `hardreset` request, **no `System Boot` entry** | iDRAC never lost power → not a power outage |
| iDRAC power monitoring graph: flat ~170 W across the week | no interruption on the supply side |
| Drive temperature 32 °C, room A/C working | not thermal |
| `kernel.panic = 0` | a kernel panic would have *hung*, not rebooted |
| no `/dev/watchdog`, no watchdog module, `RuntimeWatchdogUSec=0` | no watchdog could have issued the reset |
| floor locked, nobody on site | not a physical button press |
| Both PSUs present, redundancy OK, 232/230 V input | healthy at inspection time |
| **BMC min-power telemetry: 26 W at the moment of the reset** | **main rails collapsed — the actual finding** |

Nothing in software was capable of rebooting the machine and no
component logged a fault, so the first conclusion drawn was "transient,
undetermined". That was wrong, and only the power telemetry corrected
it: the box genuinely powered down. Event logs record *events a
component decided to declare*; continuous telemetry records what
actually happened. When the logs are empty, go looking for a sampled
metric.

## Hardening scheduled (next planned downtime)

The investigation was limited by missing instrumentation. To be armed
before the next event:

1. `kdump` — `crashkernel=` was absent from the kernel cmdline
   (`kdump-config status` → *not ready*); fix and reboot so the next
   panic leaves a vmcore.
2. Hardware watchdog — load `ipmi_watchdog`, set
   `RuntimeWatchdogSec=60`. A hung kernel then recovers itself *and*
   the BMC logs the watchdog expiry, turning a future mystery into
   evidence.
3. `kernel.panic = 30` — a storage node should never hang waiting for a
   human.
4. memtest86+ pass and PSU reseat/inspection during the RAID 6 rebuild
   window; daily EDAC counter check in the meantime.

## Lessons

1. **Recovery design is validated by the bad days, not the good ones.**
   Two unplanned outages, two single-command recoveries, zero data
   loss, and the second one without ever touching the building.
2. **Keep the origin path in your own state file.** After an attach,
   `saveconfig.json` points at the mapper device; the only reliable
   record of the real origin is the state file — and it must hold a
   stable `by-id` path, not `sdX`.
3. **Instrument before you need it.** kdump and a watchdog cost nothing
   while idle and are the difference between "root cause: X" and "root
   cause: undetermined".
4. **Absence of evidence is evidence — but only up to a point.** The
   missing `System Boot` entry correctly proved the *input* supply
   never dropped. It did not prove, as first concluded, that power was
   uninvolved: standby survived while the main rails did not.
5. **When the event logs are empty, look for continuous telemetry.**
   Min/max power statistics, sensor histories and trend graphs record
   reality without needing a component to raise an alarm first. In this
   incident a single "26 W" data point was the entire root cause.
6. **Check clock alignment between OS and BMC before an incident.** A
   two-hour offset nearly hid the one piece of evidence that existed.

---

# Field Test #5 — RAID 0 vs RAID 6, same VM, same cache

Date: 2026-08-10 → *(in progress)* · Yellowstone Cache
**v0.3.5-alpha** (baseline) → **v0.4.0-alpha**

A controlled A/B that only exists because it was taken **before the old
array was destroyed**: the same cloned VM, the same 16 GiB RAM cache,
the same host and fabric — with only the backing array changed.

Full method: [benchmark-protocol.md](benchmark-protocol.md).

## Configurations

| Label | Array | Cache | Notes |
|-------|-------|-------|-------|
| `RAID0-2disk` | 2 × 8 TB WD Purple (WD85PURZ), RAID 0 | 16 GiB RAM, writethrough | the temporary array, measured on its last day |
| `RAID6-8disk` | 8 × 8 TB, RAID 6 | 16 GiB RAM, writethrough | mixed drive ages; 2 held as cold spares |
| `SSD-RAID10` *(later)* | 4 × SATA SSD, RAID 10 | none | separate LUN for MinIO / AI workload |

Both HDD arrays sit behind the same PERC H700 and are exported over the
same FC fabric to the same ESXi host, so the storage layer is the only
variable.

## Why this comparison is not a simple "which is faster"

- **RAID 0 has no parity cost** and is the fastest possible use of two
  spindles. It is not a weak opponent on writes.
- **RAID 6 has four times the spindles** but pays a read-modify-write
  penalty on small random writes.

So the expectation is: reads improve substantially, sequential improves
substantially, and **small random writes are the genuinely interesting
number**. The 2-disk array is also the one that produced Field Test #3's
saturation at ~300–400 random IOPS — the point of the rebuild is to
remove that ceiling.

## Part 1 — `RAID0-2disk` baseline (captured 2026-08-10)

```text
LABEL : RAID0-2disk / 16 GiB RAM cache / writethrough
ARRAY : 2 × 8 TB WD Purple (WD85PURZ), RAID 0, PERC H700
PATH  : guest → ESXi 7.0 → 4 Gb FC → LIO → dm-cache → RAM / array
GUEST : cloned VM, raw 100 GB virtual disk (/dev/sdb), no filesystem,
        unlimited IOPS, single VM powered on
CACHE : freshly recreated before the run (cold start)
```

| Run | IOPS | Bandwidth | avg lat | p50 | p99 | hit ratio (delta) |
|-----|------|-----------|---------|-----|-----|-------------------|
| A1 cold (8 GiB) | 468 | 1.9 MiB/s | 272 ms | 255 ms | 726 ms | 39.3 % |
| A2 warm (8 GiB) | 1,042 | 4.2 MiB/s | 122 ms | 79 ms | 505 ms | 67.4 % |
| **A3 hot (8 GiB)** | **14,400** | **56.3 MiB/s** | **8.9 ms** | **1.7 ms** | 183 ms | **97.6 %** |
| **A-lat (8 GiB, QD1)** | 3,879 | 15.2 MiB/s | **255 µs** | **243 µs** | **392 µs** | 98.1 % |
| **B array (64 GiB rand read)** | **739** | 2.9 MiB/s | 173 ms | 155 ms | 542 ms | ~49 % |
| C write (64 GiB rand write) | 806 | 3.2 MiB/s | 159 ms | 157 ms | 401 ms | — |
| D sequential read (1 MiB, QD8) | 285 | **286 MiB/s** | 27.9 ms | 21 ms | 64 ms | — |

Peak instantaneous during A3: **80,400 IOPS / 314 MiB/s**.

### Cache warming is a process, not a state

The three A passes are the same command run three times in a row. The
only thing that changed between them is how much of the 8 GiB working
set had made it into the 16 GiB cache:

```text
pass 1:    468 IOPS   272 ms    39 % hits    (array-bound)
pass 2:  1,042 IOPS   122 ms    67 % hits
pass 3: 14,400 IOPS   8.9 ms    98 % hits    (cache-bound)
```

**30× the IOPS and 30× lower latency**, same hardware, same VM, three
minutes apart. Any benchmark that reports a single number for a cached
device is reporting an accident of timing.

Why warming took three passes: the 64 GiB preparation write had filled
the cache with its own blocks, so the test region had to evict them
first. Which produced an unexpected finding of its own —

### Finding: `smq` does not bypass sequential *writes*

After the 64 GiB sequential prep write the cache was **99.7 % full**
with ~127,000 promotions. Sequential *reads* are bypassed by the smq
policy as documented, but in writethrough mode the sequential write
stream was promoted like any other traffic. Worth knowing before
assuming a large sequential ingest will leave a cache untouched.

### Finding: at saturation, cache hits queue behind misses

In pass 3 the median request took 1.7 ms while the p99 was 183 ms. A
RAM hit is a ~250 µs operation (measured directly in A-lat), so the
millisecond-scale p50 is not the cache being slow — it is head-of-line
blocking: with 128 requests outstanding against an array that can
sustain ~200 random IOPS, hits wait in the same queue as misses.

This is why the QD1 run matters. Removing the queue exposes what the
cache actually delivers end-to-end:

```text
A-lat (QD1): avg 255 µs | p50 243 µs | p99 392 µs | max 2.9 ms
```

A quarter of a millisecond, across guest → ESXi → FC → LIO → dm-cache →
RAM, with the FC round trip alone accounting for perhaps half of it.
A miss on the same path costs 10–15 ms — the cache is **40–60× faster**
through the entire virtualization and SAN stack.

### Finding: queue depth changes the answer by 3×

The preparation pass, written with fio's defaults (`psync`, QD1),
reported 97 MiB/s sequential write. Run D, the same array with QD8,
reported **286 MiB/s** sequential read. The first number is
latency-bound (10 ms × ~100 IOPS), not a throughput measurement.
Benchmarks must state queue depth or they state nothing.

## Part 2 — `RAID6-8disk` (measured 2026-08-15)

```text
LABEL : RAID6-8disk / 16 GiB RAM cache / writethrough
ARRAY : 8 × 8 TB, RAID 6, 43.7 TB usable, 64 KB strip,
        WriteBack / ReadAdaptive / Direct, BGI complete
CACHE : reset immediately before the run (cold start)
PATH  : guest → ESXi 7.0 → 4 Gb FC → LIO → dm-cache → array
GUEST : cloned VM, raw 100 GB virtual disk, unlimited IOPS,
        the only VM powered on
NOTE  : Patrol Read **stopped** for the duration of the measurements
        and restarted afterwards
```

### Through the fabric — RAID 0 vs RAID 6, same VM, same cache

| Run | RAID0-2disk | RAID6-8disk | Change |
|-----|-------------|-------------|--------|
| A2 warm (8 GiB) | 1,042 IOPS | 57,600 IOPS | 55× |
| **A3 hot (8 GiB)** | 14,400 IOPS / 8.9 ms / p99 **183 ms** | **84,700 IOPS / 1.49 ms / p99 3.56 ms** | **5.9× IOPS, 51× better p99** |
| **B array (64 GiB rand read)** | 739 IOPS | **1,772 IOPS** | **2.4×** |
| **C rand write (64 GiB)** | 806 IOPS | **462 IOPS** | **0.57× — worse** |
| D sequential read | 286 MB/s | **373 MiB/s** | 1.3× — *at the FC ceiling* |

### The array on its own (local, no cache, no fabric)

| Test | Result |
|------|--------|
| 4K random read, QD32 × 4 | **2,503 IOPS** |
| 1 MiB sequential read, QD8 | **1,219 MiB/s** (1,278 MB/s), 6.5 ms avg |

### Cache behaviour during each run (`status --delta 60`)

| During | Read hit ratio | Promotions | Turnover |
|--------|---------------|------------|----------|
| A3 (8 GiB working set) | **100.0 %** — 4,813,473 hits, **0 misses** | 2 blocks | 540 h |
| B (64 GiB working set) | 35.2 % | 60.7 MB/s | **4.5 min** ⚠ |
| C (random write) | write hit 49.7 % | 13.0 MB/s | 20.7 min |
| D (sequential read) | 34.1 % | **144.8 MB/s** | **1.9 min** ⚠ |

## Finding 1 — a background controller task invalidated an entire round

The first set of local measurements produced numbers that made no
physical sense: **327 IOPS** random and **16.6 MiB/s** sequential —
slower than a single disk, from eight spindles.

The cause was **Patrol Read**, which had started on schedule at 04:00
that morning and was still scanning every sector of all eight drives
(`Current State: Active`, `PDs completed: 0`). Repeating the identical
tests with it stopped:

| Test | During Patrol Read | Clean | Factor |
|------|-------------------|-------|--------|
| 4K random read | 327 IOPS | **2,503 IOPS** | **7.6×** |
| Sequential read | 16.6 MiB/s | **1,219 MiB/s** | **73×** |

Seventy-three times. Without that check, the documentation would have
recorded a RAID 6 array as slower than one of its own drives.

**This is now a mandatory pre-flight step in
[benchmark-protocol.md](benchmark-protocol.md):** before any
measurement, confirm the controller is idle —

```bash
MegaCli64 -LDBI  -ShowProg -Lall -a0   # background initialisation
MegaCli64 -AdpPR -Info     -aALL       # patrol read
MegaCli64 -LDCC  -ShowProg -Lall -a0   # consistency check
MegaCli64 -LDRecon -ShowProg -Lall -a0 # reconstruction
```

Everything measured while one of these runs describes the array *under
scan*, not the array.

## Finding 2 — a faster array makes the cache faster, too

The prediction recorded before the run was that the cache path would be
*"roughly unchanged — same RAM, same FC path"*. It was wrong by 5.9×.

```text
A3 hot, RAID 0 origin :  14,400 IOPS | avg 8.9 ms  | p99 183 ms  | 97.6 % hits
A3 hot, RAID 6 origin :  84,700 IOPS | avg 1.49 ms | p99 3.56 ms | 100 % hits
```

Two mechanisms, and neither is the RAM getting faster:

1. **Misses share the queue with hits.** On the 2-disk origin a miss
   cost ~270 ms and blocked everything queued behind it, so a 2.4 %
   miss rate dragged the whole distribution — hence p99 of 183 ms. On
   eight spindles a miss costs ~75 ms, the tail collapses, and the
   distribution lifts as a whole.
2. **A faster origin warms the cache faster.** RAID 0 needed three
   passes to reach 97.6 %; RAID 6 reached 100 % — literally zero misses
   — by the third. With no misses at all there is nothing left to drag.

**A cache is only as fast as the storage it is hiding.** That is not
intuitive, and it is the single most useful thing this comparison
produced.

## Finding 3 — RAID 6 is *worse* than RAID 0 at random writes

| | RAID 0 | RAID 6 |
|---|--------|--------|
| 4K random write | 806 IOPS | **462 IOPS** (−43 %) |
| avg latency | 159 ms | **276 ms** |
| p99 | 401 ms | **776 ms** |

Four times the spindles, and it still loses. RAID 0 writes a block and
is done; RAID 6 must read the old block, read both parity blocks,
compute the new parity and write three things back. Eight drives cannot
outrun six times the work per operation.

Practical reading: this array is built for **capacity, redundancy and
read throughput**, and its workload — an archive that writes
sequentially and VMs that mostly read — fits that. A write-heavy
database would not belong here.

## Finding 4 — the bottleneck is now the fabric, on every profile

```text
sequential, array locally   1,219 MiB/s
sequential, through 4 Gb FC   373 MiB/s   (peak 398 — the link's ceiling)
────────────────────────────────────────
unusable through the fabric      69 %
```

And the cached path reached the same wall from the other side: A3 ran
at 331 MiB/s with peaks of 337 MiB/s — the **cache** is now fast enough
to saturate the link on its own.

So the case for 8 Gb HBAs is no longer an assumption. Three independent
measurements point at it: the SSD tier (Field Test #7), the RAID 6
array, and the RAM cache. All three exceed what a 4 Gb link can carry.
The switch (Brocade 300) already supports 8 Gb and the primary Lenovo
array has 16 Gb ports throttled to 4 Gb by the SFPs alone — replacing
switch-side SFPs alone would double *that* array's link with no other
change.

## Finding 5 — `smq` does not fully bypass sequential reads either

During run D — a pure 1 MiB sequential read — the cache promoted
**144.8 MB/s**, roughly 39 % of the stream, and turned over completely
every 1.9 minutes. Combined with the sequential-write finding in Field
Test #5 Part 1, the picture is:

> Sequential bypass in `smq` is partial and workload-dependent. Do not
> assume a streaming workload will leave a cache untouched — measure it.

## Predictions, scored

Written down before the measurements so they could be judged honestly:

| Prediction | Actual | |
|-----------|--------|---|
| B: 3–4× better | 2.4× | ⚠️ optimistic — the chain costs ~29 % (2,503 local → 1,772 through FC) |
| C: "uncertain, may barely improve" | **43 % worse** | ❌ right to hedge, wrong on direction |
| D locally: > 800 MB/s | 1,219 MB/s | ✅ |
| A3: "roughly unchanged" | **5.9× better** | ❌ the reasoning ignored queue coupling |

One of four. Which is the argument for writing predictions down at all:
being wrong in public is how the reasoning gets corrected, and Finding
2 exists only because the prediction failed loudly enough to demand an
explanation.

---

# Field Test #6 — Power loss during array initialisation

Date: 2026-08-13 · Yellowstone Cache **v0.4.0-alpha**

The shortest incident so far, and the one with a condition none of the
previous tests covered: the storage node lost power **while the RAID 6
array underneath was still being initialised.**

## What happened

While swapping the power supplies, both cords were pulled at once and
the server went down instantly — no shutdown, no flush, nothing.

State at the moment of the outage:

- RAID 6 (8 × 8 TB) at **49 % background initialisation** — parity for
  the remaining half of the array was not yet computed
- Yellowstone cache attached, LIO exporting the LUN
- Array otherwise empty (data migration not yet performed)

## Recovery

```text
Background Initialization on VD #1 ... Complete 76% in 1089 Minutes   ← resumed
PS Redundancy | 74h | ok | 7.1 | Fully Redundant                      ← new PSUs
yellowstone repair            → action: recreate
yellowstone repair --apply    → 'TestDisk' cache recreated, LIO up
```

The datastore reappeared on the hosts by itself, as in every previous
recovery.

| Check | Outcome |
|-------|---------|
| Controller background init | **resumed from where it stopped** — progress is held in controller NVRAM, not restarted from 0 % |
| Controller write-back cache | protected by the BBU (verified healthy before the array was built) and flushed on power-up |
| Cache layer | rebuilt by `repair --apply` — third unplanned recovery, same single command |
| Data | none at risk (array empty), but writethrough means none would have been in any case |
| Operator error tolerance | full recovery from a mistake that would normally mean a long afternoon |

## Why it is worth recording

1. **An initialising array is the most fragile state a RAID 6 can be
   in** — parity is incomplete, so a disk failure during that window
   cannot be reconstructed. Losing power in exactly that state and
   coming back cleanly is a useful data point, not a trivial one.
2. **BGI progress survives power loss.** Worth knowing before anyone
   panics and restarts an initialisation that was already 76 % done.
3. **The recovery procedure did not care what state the array was in.**
   `repair` compares state, saveconfig and the kernel — the array's
   internal condition is simply not one of its inputs, which is why the
   same single command has now handled a datacenter blackout, an
   unexplained host reset and a pulled power cord.

## Power path closed out in the same window

Both power supplies were replaced — the leading suspect from Field Test
#4 — and the two feeds were traced and confirmed to run from **separate
breaker panels**: one generator-backed, one on UPS.

That diversity changes the standing diagnosis. A single upstream
electrical event can no longer explain a simultaneous loss of both
rails, because the two supplies no longer share an upstream. So if the
unexplained reset ever repeats, the remaining candidates are internal:
the power distribution board or the mainboard.

Measurement from here is simply elapsed time. Previous behaviour: 13
days of flawless operation, then a reset out of nowhere. The clock
starts again.

---

# Field Test #7 — SSD tier: where the bottleneck actually is

Date: 2026-08-14

A second LUN was added to the same LIO target: two used consumer SATA
SSDs in RAID 0, **deliberately without a Yellowstone cache** (RAM in
front of SSD is marginal, and the layer would have to be reassembled
after every reboot for little gain).

That makes it a useful control: the same fabric, the same host, the
same fio profiles — but no caching anywhere in the path. Whatever it
measures is the storage and the chain, nothing else.

## Configuration

| | |
|---|---|
| Drives | 2 × Transcend TS480GSSD220S, 480 GB, used (90 % / 91 % life remaining, ~15 TB / ~13 TB written) |
| Array | RAID 0, 893 GB usable, 64 KB strip, PERC H700 |
| Over-provisioning | **none** — the VD was created at full capacity |
| Fabric | 4 Gb FC → VMware ESXi 7.0, VMFS 6, no Yellowstone cache |
| Guest | cloned VM, raw 100 GB virtual disk, unlimited IOPS |

## Measurements

Local (`/dev/sdc` on the storage node — the array's own capability):

| Test | Result | Limited by |
|------|--------|------------|
| 4K random read, QD32 × 4 jobs | **67,100 IOPS** / 262 MiB/s, 1.89 ms avg, 99.9 % util | the drives |
| 1 MiB sequential read, QD8 | **953 MiB/s**, 8.3 ms avg (σ 182 µs) | the drives |

Through the fabric, from the guest:

| Test | Result | Limited by |
|------|--------|------------|
| 1 MiB sequential write, **WriteThrough** | **57 MiB/s**, p50 64 ms but **p90 451 ms**, bandwidth swinging 4–136 MB/s | **the cache policy** |
| 1 MiB sequential write, **WriteBack** | **~366 MiB/s sustained, no drops** | **the FC link** |

## Finding 1 — a cache policy cost 6× write throughput

WriteThrough was chosen deliberately, on the reasoning that these are
consumer SSDs without power-loss protection and that the FC link would
mask any performance difference anyway. **Both halves of that reasoning
were wrong**, and the measurement is what showed it.

The failure signature was distinctive: median latency 64 ms but p90 at
**451 ms**, and throughput oscillating between 4 and 136 MB/s. That is
not a slow device — that is a device being starved of parallelism.

Why it happens: under WriteThrough the controller must wait for each
write to be acknowledged by the drive before acknowledging the host, so
a guest queue depth of 8 means **at most 8 writes in flight to the
array**. Under WriteBack the controller acknowledges immediately and
then drives the SSDs with a far deeper queue of its own — the drives
work in parallel instead of in single file.

So WriteBack is not merely "buffering". It decouples the host's queue
depth from the drives', which is exactly what SSDs need.

**On the safety argument:** the BBU protects the *controller's* cache.
The risk from a consumer SSD's own volatile write buffer exists in
both modes and is unaffected by this setting. WriteThrough was
therefore buying nothing while costing 6×. The VD is also configured
*No Write Cache if Bad BBU*, so it degrades to WriteThrough by itself
if the battery ever fails.

## Finding 2 — the bottleneck moved to the fabric

With the policy fixed, sustained writes settled at **366 MiB/s** — and
a 4 Gb FC link carries roughly 380–400 MB/s per direction. The array is
no longer the constraint; the link is.

The whole picture across layers:

```text
local sequential read     953 MiB/s   ← the drives can do this
through 4 Gb FC           366 MiB/s   ← this is what arrives
```

Note also that a VM clone from the QNAP array to this SSD LUN ran at
~245 MB/s in each direction simultaneously. That is only possible
because **Fibre Channel is full duplex** — a 4 Gb link carries ~400
MB/s *each way* at once, not 400 MB/s in total. (An earlier reading of
these numbers assumed the directions shared one budget and concluded,
wrongly, that VAAI offload must have been involved. VAAI XCOPY cannot
span two different arrays.)

**Upgrade implication, quantified rather than assumed:**

| Profile | 4 Gb today | 8 Gb would give | Worth it? |
|---------|-----------|-----------------|-----------|
| Sequential | capped at ~380 MB/s | ~760 MB/s | **yes — the drives already exceed the link** |
| 4K random | 268 MB/s at 67k IOPS | unchanged | **no — never approaches the ceiling** |

The switch (Brocade 300) already supports 8 Gb, but link speed is set
by the slowest element: with 4 Gb HBAs at both ends, 8 Gb SFPs change
nothing. Both ends would need replacing.

## Finding 3 — what was left on the table

Over-provisioning was discussed and then skipped when the VD was
created at full capacity. On used consumer SSDs behind a controller
that does not pass TRIM through a RAID volume, the FTL considers every
block occupied, so writes carry maximum write amplification.

WriteBack masked this well enough that it stopped being the limiting
factor — but if sustained write performance ever degrades, the fix is
known: destroy the VD, `blkdiscard` both drives to reset the FTL, and
recreate leaving 15–20 % unallocated.

## Lessons

1. **Measure the layer, not the assumption.** WriteThrough was chosen
   from reasoning that sounded sound and was wrong by a factor of six.
   One 60-second test found it.
2. **A bottleneck is never removed, only moved.** Drives → cache policy
   → fabric, twice in one afternoon. The value is in knowing which one
   you are standing on.
3. **Measure locally and through the fabric.** Either number alone is
   misleading: 953 MB/s local overstates what applications get, 366
   MB/s through FC understates what the hardware can do. The gap
   between them is the price of the chain — and the business case for
   any upgrade.
4. **Fibre Channel is full duplex.** Summing both directions against
   one budget produces conclusions that are not merely wrong but
   inventive.

---

# Field Test #8 — Guest-to-guest copy: read-modify-write, measured

Date: 2026-08-16

Two VMs (Windows 10 and Server 2012) on the **same ESXi host**, both
with their virtual disks on the 48 TB Yellowstone-cached datastore,
connected to each other through vmxnet3. A 10 GB file was copied over
SMB from one guest to the other.

The intent was a casual sanity check. It turned into the first direct
measurement of the RAID 6 write penalty, and a correction to Field
Test #7.

## The number that could not be true

Windows reported **1.06 GB/s**, sustained, with 7.93 GB still to go.

That is 8.5 Gbit/s across a 4 Gb link that carries roughly 380 MB/s per
direction. No arrangement of caching makes that number a storage
throughput.

What actually produced it:

```text
VM A: file already resident in the Windows page cache (RAM)
  ↓   vmxnet3, same host — a memory copy, never reaches a physical NIC
VM B: received into the write buffer (RAM)
  ↓   only from here does anything reach storage
FC 4 Gb → LIO → dm-cache (writethrough) → RAID 6
```

The first two hops are RAM to RAM. The dialog was reporting the rate at
which data was *accepted*, not the rate at which it was *stored*.

**A hypothesis worth recording because it was wrong:** that the data
never crossed the fabric at all — same host, same datastore, therefore
VMware handles it internally. That holds for the network hop and fails
for the storage hop. The vmdk blocks physically reside on the array,
and the only path from the host to those blocks is the FC link; there
is no second cable. ESXi has no read cache for VMFS data (CBRC exists
only for VDI linked clones and is off by default).

Rather than argue the point, a falsifiable test was defined in advance:
if the data bypassed the fabric, Yellowstone's counters would not move
at all.

## What the cache saw

`yellowstone status TestDisk --delta 10`, during the copy:

```text
Read IOPS             : 1.0
Write IOPS            : 4222.6
Read hit ratio        : 100.0% (10 hits / 0 misses)
Write hit ratio       : 91.0%
Promotion rate        : 8.43 MB/s (337 blocks)
Demotions             : 337
Full cache turnover   : 32.1 min
Cache usage           : 100.0%
Dirty blocks          : 0
```

Both halves of the explanation are in those two lines:

- **Read IOPS 1.0** — reads genuinely did not reach storage. The source
  file was in the guest's page cache, which is why 1.06 GB/s was
  achievable at all.
- **Write IOPS 4222.6** — writes did reach storage. The counters moved,
  so the fabric was in the path.

## What iostat saw

`iostat -x 5 /dev/mapper/TestDiskCached`, selected intervals:

| Interval | `w/s` | `wkB/s` | MiB/s | `wareq-sz` | `w_await` | `%util` |
|---|---|---|---|---|---|---|
| 2 | 3351.6 | 263,238 | **257** | 78.5 KB | 3.39 ms | 78.9 % |
| 3 | 3378.6 | 268,622 | **262** | 79.5 KB | 2.23 ms | 77.0 % |
| 4 | 2693.2 | 213,709 | 209 | 79.4 KB | 9.21 ms | 90.0 % |
| 5 | 2144.2 | 170,238 | 166 | 79.4 KB | 16.95 ms | 94.5 % |
| 7 | 1847.4 | 141,210 | 138 | 76.4 KB | 12.79 ms | 93.1 % |
| 8 | 931.4 | 62,140 | **61** | 66.7 KB | 27.21 ms | 96.5 % |
| 15 | 1038.8 | 64,120 | **63** | 61.7 KB | 6.98 ms | 93.0 % |

Peak **262 MiB/s**, decaying to **60–80 MiB/s** and staying there.

The FC ceiling is ~380 MB/s. The write path never came near it.

One interval caught the read side, once the destination file began
being read back:

```text
r/s 3775.80   rkB/s 296310 (289 MiB/s)   r_await 0.07 ms   rareq-sz 78.5 KB
```

**70 microseconds.** That is the RAM cache behaving exactly as
designed — and 289 MiB/s is close enough to the link ceiling to be
constrained by it.

## Finding 1 — read-modify-write, finally visible

The write signature is unambiguous once the four numbers are read
together:

| Observation | Value |
|---|---|
| average write size (`wareq-sz`) | **79 KB** |
| RAID 6 full stripe (6 data × 64 KB) | **384 KB** |
| device utilisation (`%util`) | **92–97 %** |
| throughput delivered at that utilisation | **60–80 MiB/s** |
| latency (`w_await`) over the run | **3.4 ms → 27 ms** |

A 79 KB write is roughly a fifth of a stripe. RAID 6 cannot place it
directly: the controller must read the old data, the old P parity and
the old Q parity, recompute both, and write everything back. One
logical write becomes on the order of six physical operations. That is
why the device sits at 96 % utilisation while delivering 60 MB/s, and
why latency climbs eightfold as the queue builds.

**Where this was previously looked for, wrongly:** an earlier
suggestion was to watch reads on `sdb` during a write test and infer
RMW from them. That cannot work — RMW happens between the controller
and the physical disks, *below* the virtual disk Linux sees. The
kernel never observes those reads. It is visible only indirectly,
through the ratio of `%util` to `wkB/s`, which is what this capture
shows.

## Finding 2 — under writethrough, the cache is not in the write path

Write hit ratio was 91 % and dirty blocks 0. Both are consistent and
neither helps: under writethrough **every write must reach the origin**
whether it hits in cache or not. The cache updates its copy and the
guest still waits for RAID 6.

A high write hit ratio is therefore not a performance indicator in this
mode. It only means the blocks being written were already resident.

## Finding 3 — cache churn during a sequential write, quantified

```text
Cache usage        : 100.0%
Promotion rate     : 337 blocks
Demotions          : 337
Full cache turnover: 32.1 min
```

Promotions and demotions are **identical**. The cache is full, so every
new block admitted evicts an existing one. During a 10 GB sequential
copy that is pure loss: the copied blocks will never be read a second
time, and they are displacing blocks that would have been.

This is the first *measured* instance of the case `migration_threshold`
was introduced for. Field Test #5 showed the same effect from a
synthetic prep write; this one arrived from ordinary administrative
work.

**It was not in effect during this test.** The installed binary was
0.4.0-alpha; `migration_threshold` ships in 0.4.1-alpha and had not yet
been deployed to the node. The measurement therefore stands as the
"before" reading, with a repeat at 512 to follow.

## Finding 4 — narrowing the 8 Gb upgrade case from Field Test #7

Field Test #7 concluded that an 8 Gb fabric would roughly double
throughput. That conclusion was drawn from sequential *read* profiles
and was stated too broadly. This test separates the two directions:

| Path | Measured today | Limited by | 8 Gb helps? |
|---|---|---|---|
| Read (cache hit) | 289 MiB/s, 0.07 ms | **the link** | **yes** |
| Write | 262 MiB/s peak, 60–80 sustained | **RAID 6 RMW** | **no** |

Doubling the link cannot help a path that never reached the current
ceiling. Whether the upgrade is worth it therefore depends on the
read/write ratio of the real workload — not on this test, which at 4222
writes against 1 read is the least favourable case the FC argument
could be given.

**Pending:** `iostat -x 60` across a normal working day, to obtain that
ratio before the purchase is proposed.

## What this suggests about the write path

The write bottleneck has a known shape and a known family of fixes:

1. **Larger writes.** 79 KB against a 384 KB stripe is the root of it.
   Nothing in this stack controls the guest's I/O size directly, but a
   smaller stripe would reduce the mismatch — at the cost of rebuilding
   the array.
2. **`migration_threshold`.** Does not address RMW; it limits the
   collateral damage to cache contents while RMW is happening.
3. **An SSD cache in writeback.** This is the fix that actually
   addresses the latency: the SSD would absorb 79 KB writes at its own
   speed and destage to the array independently, instead of making the
   guest wait for a parity cycle. Field Test #7 measured that
   difference on the SSD tier itself — 366 MiB/s writeback against 57
   writethrough.

   **Blocked until warm assemble exists.** `create` currently zeroes
   cache metadata on every assembly, so dirty blocks held on an SSD
   would be lost across a reboot. Until the cache can be reattached
   with its metadata intact, writeback on a persistent cache device is
   data loss waiting for a power cut, not a performance feature.

Note also that a *combined* RAM + SSD cache — raised as a possibility
before this test — is not something dm-cache offers. One origin takes
exactly one cache device. Stacking two dm-cache layers is possible in
principle and doubles the assembly and recovery surface for no measured
benefit.

## Lessons

1. **A progress dialog reports acceptance, not persistence.** 1.06 GB/s
   was a true measurement of the wrong thing.
2. **Define the falsifying observation before arguing.** "The counters
   will not move" took ten seconds to check and ended the question.
   The XCOPY error in Field Test #7 came from reasoning where a
   measurement was available.
3. **A bottleneck is invisible in the place you expect it.** RMW does
   not appear as reads on the virtual disk. It appears as high `%util`
   with low throughput.
4. **Narrowing an earlier conclusion is part of the work.** Field Test
   #7's upgrade case was not wrong so much as unqualified. The cost of
   leaving it unqualified would have been ~400 EUR spent against the
   wrong wall.

---

# Field Test #9 — A working day, measured layer by layer

Date: 2026-08-17 (capture ~10:40–16:00, 321 intervals of 60 s = 5.35 h)

`iostat -x 60` left running across a normal Monday, with **no device
filter** — so every layer was captured at once: what LIO exports, what
the RAM cache serves, what the array actually does, and the second
(uncached) LUN.

The intent was narrow: obtain the read/write ratio needed to decide the
8 Gb fabric upgrade. It also produced the first end-to-end latency
decomposition of the stack, and caught a methodological error that had
already distorted the previous day's conclusions.

## Device map, confirmed from the data

| Device | What it is | Confirmed how |
|---|---|---|
| `dm-3` | `TestDiskCached` — what LIO exports | matches `--delta` counters to 0.3 % |
| `dm-2` | dm-cache data device, on `brd` (RAM) | `dm-2` + `sdb` ≈ `dm-3` reads, at 0.010 ms |
| `sdb` | the 48 TB RAID 6 array (origin) | |
| `sdc` | SSD RAID 0, second LUN, **no cache** | HAProxy + nginx reverse proxy |

`dm-2` had been assumed to be the cache data device in the morning's
analysis. The day's figures confirm it: 7.71 MiB/s at **0.010 ms** from
`dm-2`, 0.69 MiB/s at 12.9 ms from `sdb`, summing to slightly more than
the 8.04 MiB/s `dm-3` delivered to the host. The excess is promotions —
blocks read from the origin into the cache which never reach the
initiator.

## The read path, three layers, measured

```text
guest sees (dm-3)   8.04 MiB/s    r_await p50  0.08 ms
   ├── cache hit    7.71 MiB/s    r_await      0.010 ms   ← RAM
   └── array        0.69 MiB/s    r_await p50 12.77 ms    ← RAID 6
```

**160× at the median.** That single ratio is the clearest statement of
what this tool does that the project has produced so far.

A recurring pattern in the log makes it visible in isolation. Intervals
187, 219, 224, 240, 246, 267 and 289 all show almost exactly the same
figures:

```text
dm-3 read 37.1 MiB/s   sdb read 0.0   r_await 0.03 ms   %util 1.4–1.9 %
```

Some periodic job reading the same working set. It is served entirely
from RAM at 30 µs, and the array does not notice it happened.

## Totals for the day

| | `dm-3` | `sdc` | total |
|---|---|---|---|
| Read | **158.6 GB** | 3.9 GB | **162.5 GB** |
| Written | 4.5 GB | ~0 | 4.5 GB |
| Served from the array | 13.7 GB (**8.6 %**) | — | |

**91.4 % of read bytes came from cache.** The read:write ratio by volume
is **35 : 1**.

Per-interval distribution on `dm-3`:

| | avg | p50 | p95 | max |
|---|---|---|---|---|
| read MiB/s | 8.04 | 0.01 | 37.12 | **74.76** |
| write MiB/s | 0.23 | 0.08 | 0.23 | 14.69 |
| read IOPS | 116 | 2 | 482 | 1938 |
| write IOPS | 15.7 | 11.9 | 26.2 | 208 |
| `r_await` ms | 0.47 | **0.08** | 2.17 | 7.30 |
| `%util` | 2.4 | 0.3 | 7.2 | 98.7 |

`%util` exceeded 50 % in **6 of 321 intervals — 1.9 % of the day**.

## Finding 1 — the fabric is not the daytime constraint

Peak minute across **both** LUNs together: **75.5 MiB/s**, of which the
SSD LUN contributed 0.7. A 4 Gb link carries roughly 380 MB/s per
direction.

```text
peak read  75.5 MiB/s  =  19.9 % of the link
peak write 14.7 MiB/s  =   3.9 % of the link (opposite direction)
```

Directions are counted separately: Fibre Channel is full duplex, and
summing them against one budget is the error made in Field Test #7.

At 60-second granularity, across a full working day, the link never
exceeded a fifth of its capacity. **The proposed ~400 EUR upgrade —
16 × 8 Gb SFP plus 2 × QLE2560 — is not supported by daytime traffic.**

This narrows Field Test #8, Finding 4 further. That test separated reads
(link-bound) from writes (RAID-bound). This one shows that under real
production load, neither direction approaches the link at all.

## Finding 2 — the cumulative counters were measuring us

The morning's `yellowstone status` reported, over 3.82 days of uptime:

```text
Write IOPS ≈ 1006/s      write hit ratio 3.92 %
Read  IOPS ≈ 153/s       read  hit ratio 72.4 %
```

The working day measured **15.7 write IOPS** — a factor of **64** lower.

The explanation is uncomfortable: those counters were dominated by **our
own benchmarking**. Field Test #5 Part 2 on 15.08, Field Test #8 on
16.08, and the fio runs around them all wrote into the same cumulative
registers. An analysis was then built on top of them — including a claim
that the workload is "latency-bound on writes, 1006 small writes per
second" — which described the test harness, not the users.

Field Test #3 already documented this exact failure and stated the rule:
*"cumulative counters after several days do not describe any real
state."* The rule was written, published, and then walked into again
three weeks later in the same project. `status --delta` exists precisely
because of it, and was not used for the sizing question.

**Practical consequence:** any figure quoted for capacity planning must
come from `--delta` or from an interval capture, and must state the
window it covers. A cumulative counter is a lifetime total on a machine
that has been used for experiments — it is a history of the operator, not
of the workload.

## Finding 3 — the placement of the second LUN is correct

`sdc` carried 3.9 GB of reads in 5.35 hours — 2.4 % of total traffic.
That is not underuse; a reverse proxy pair is network-bound and touches
disk only for configuration and logs.

The pair also sits on **RAID 0, deliberately**. HAProxy and nginx are the
two most easily rebuilt services in the estate: losing that array costs
configuration, not data. Stateless services on the array without
redundancy, stateful ones on RAID 6 — worth recording because it was a
choice, not an accident.

## The replication window — measured the following night

The capture was left running and eventually covered **23.33 hours
(1400 intervals)**, including the full replication window. What follows
replaces the "not measured" section that stood here originally.

### The window

One clear block stands out: **intervals 511–790, 280 minutes ≈ 4 h 40 m**,
roughly 18:15–22:55. Yellowstone is quiet before and after; the job moves
on to the other datastores, and the complete cycle across the estate takes
about 1.5 days.

| | |
|---|---|
| Read through LIO | **273.3 GB** |
| Of which from the array | 173.2 GB (63 %) |
| Average rate | **16.1 MiB/s** |
| **Peak minute** | **113.9 MiB/s** |
| `sdb %util` average | **2.2 %** |
| `sdb %util` maximum | 31.6 % |

Whole-capture extremes across **both** LUNs together:

```text
peak read  113.9 MiB/s = 30.0 % of the 4 Gb link
peak write  28.2 MiB/s =  7.4 % (opposite direction)
```

### Why the peak is exactly what it is

The 48 TB datastore is shared by all three ESXi hosts. Each host backs up
its own VMs **sequentially**, but all three read from the same datastore
**concurrently**:

```text
39.8 MB/s per stream × 3 hosts = 119 MB/s
measured peak                  = 113.9 MiB/s
```

That is the operator's description of the schedule and the log agreeing to
within a few percent, from two independent directions.

### Finding 1 revised — the fabric case is closed, not narrowed

Earlier in this document the daytime measurement was said to close only
the user-traffic question, leaving the backup window open as the last case
for 8 Gb. It is now measured, and it does not support the upgrade either:
**30 % of the link at its single busiest minute**, during the full
replication of every VM in the estate.

Nor is the array a constraint: 2.2 % average utilisation while it happens.

The **~400 EUR fabric upgrade is not justified by any workload this
installation runs.** No further measurement is pending on that question.

### Finding 4 — the target is the constraint, measured directly

A controlled A/B was run afterwards. **Both runs were ordinary full hot
replicas** — plain `--replica`, no CBT involved — so the only variable
between them was the **destination**. (The target folder happens to be
named `test-cbt`; that is a name, not a mode.)

| | → Yellowstone 48T | → QNAP 116TB |
|---|---|---|
| Elapsed | **365 s** | 468 s |
| Full file speed | **140.28 MB/s** | 109.40 MB/s |
| Real data speed | **81.47 MB/s** | 57.60 MB/s |

**Yellowstone is 28 % faster as a backup target** — 41 % on real data.

The comparison is unusually clean, because the two arrays differ in fewer
ways than one would expect:

| | Yellowstone 48T | QNAP TS-883XU-RP 116TB |
|---|---|---|
| Spindles | **same count (8)** | **same count (8)** |
| Source VM, host, HBA | identical | identical |
| Fabric | 4 Gb FC | 4 Gb FC |
| System RAM | **64 GB ECC** | **8 GB ECC** |
| Cache in front | 16 GB of that RAM | 2 × 512 GB NVMe |
| Cache mode | writethrough | **read-only** |
| Controller write cache | 512 MB, **BBU-backed** | none |
| CPU | Xeon X5650 era | Xeon E-2124, 4c @ 3.3 GHz |
| VMs hosted on it | **more** | fewer |

So the difference is not the disks, not the link, and not the production
load — Yellowstone carried *more* running VMs while winning. It is the
storage stack above the platters.

Three candidate explanations, in order of likely weight:

1. **Memory.** 8 GB on the QNAP has to serve QTS, every running service,
   pool metadata for 116 TB *and* write buffering. Yellowstone dedicates
   twice the QNAP's entire system memory to cache alone.
2. **The NVMe cache contributes nothing to this workload.** It is
   read-only; a backup target is a write workload. Two NVMe devices sit
   idle while the platters take everything.
3. **Yellowstone has a battery-backed writeback cache on the controller.**
   The H700 acknowledges a write once it reaches its own 512 MB, so the
   host does not wait for platters. Without BBU protection a NAS has to
   be more conservative about acknowledging.

**A fourth explanation was considered and discarded:** that the QNAP
computes RAID 6 parity in software while the H700 has a dedicated XOR
engine. The TS-883XU-RP runs an **Intel Xeon E-2124, 4 cores at 3.3 GHz**,
which generates RAID 6 syndromes at multiple GB/s. Parity is not the
constraint, and the hypothesis was dropped once the CPU was looked up
rather than assumed.

**What would settle it:** the QNAP's CPU and memory utilisation during a
replication run. Not yet measured, so not claimed.

### What the array actually did while receiving

The `iostat` capture was still running during the A/B, so the write side
of the Yellowstone run is recorded minute by minute:

| | `dm-3` (what LIO exports) | `sdb` (the array) |
|---|---|---|
| Writes/s | **22,118** | **2,067** |
| Average write size | **3.9 KB** | **41.9 KB** |
| Merged (`%wrqm`) | — | **90.7 %** |
| `w_await` | 4.49 ms | 3.40 ms |
| Queue depth | **99.2** | 0.9 |
| `%util` | — | **31.6 %** |

30.6 GB in seven minutes, peaking at 84.5 MiB/s.

Three things follow:

1. **XSIBackup issues ~4 KB writes.** The "1 MB block size" in its help
   text is the comparison granularity, not the I/O size. Twenty-two
   thousand small writes per second.
2. **The block layer merges 90.7 % of them** — 22,118 requests become
   2,067, a ratio of **10.7 : 1**. Without that, the array would face
   22 k IOPS of 4 KB writes, which eight spindles cannot approach. This
   is the same mechanism first seen in Field Test #9's daytime capture,
   here in its most extreme form.
3. **The array sat at 31 % utilisation.** Yellowstone absorbed 84.5 MiB/s
   using a third of its capacity. It was never the constraint.

Nor was anything else in the path: the source is an SSD datastore, the
target had headroom, and the link ran at 22 %. With a queue depth of 99
and 84.5 MiB/s coming out the other side, **the limit was XSIBackup
itself** — which is the strongest argument for CBT in this document. CBT
does not make the transfer faster; it removes most of the work.

### Conclusion, stated carefully

Yellowstone was faster in this test — 28 % on elapsed time, 41 % on real
data — and it did so while running at 31 % utilisation and hosting more
VMs than the target it beat.

**But the QNAP was not competing on equal terms.** It has 8 GB of RAM
serving the OS, all services, pool metadata for 116 TB and write
buffering; its NVMe cache is read-only and therefore idle during a write
workload; and it has no battery-backed controller cache to acknowledge
writes early. A TS-883XU-RP with its memory expanded toward the supported
64 GB, or with a read-write cache, might well reverse this result. That
has not been tested and is not being claimed either way.

What the measurement does establish is narrower and more useful:

> Under identical conditions — same source VM, same host, same HBA, same
> 4 Gb fabric, same spindle count — a **self-built cache layer on
> 2010-era hardware performed comparably to, and in this instance better
> than, a current commercial storage appliance.**

That is the honest form of the claim. Not that the approach is superior,
but that it **holds its own against a commercial product**, which for a
tool assembled from `dm-cache`, `brd` and one edited field in a JSON file
is the result worth recording.

Two further consequences fall out of this:

- **Parallelism will not help.** One stream alone reaches 140 MB/s; three
  concurrent streams reach ~38 MB/s each, ~114 MB/s in total. The target
  saturates around 110–140 MB/s regardless of how the work is divided.
  Raising the concurrency setting would divide the same ceiling.
- **Neither target comes close to the fabric.** 140 MB/s of 380 available,
  in the most favourable single-stream case.

### Finding 5 — the real inefficiency is that every cycle is a full one

The backup software is XSIBackup-DC 1.5.1.5, licensed, running
`--replica` without CBT. Every cycle therefore reads every block of every
VM to determine what changed.

The A/B test above makes the cost concrete: that VM's replica took **6 to
8 minutes and read 50 GB**, to transfer a machine that had changed by
perhaps a few hundred megabytes since the previous run. Multiplied across
the estate, that is the 36-hour cycle.

For scale, from this same capture: the 48 TB datastore received **4.5 GB
of writes across a working day** and was **read 273 GB** by the backup.

VMware's Changed Block Tracking removes the scan entirely — the hypervisor
already knows which blocks moved. The vendor's own documentation describes
CBT replicas as "almost instant from the second run".

**It is available and licensed.** `--replica=cbt` was attempted and
returned:

```text
Error code 151 | no matching CTK entry for disk: scsi0:0.fileName
/!\ There aren't any CTK files (-1), run --enable-cbt first, ignoring CBT flag
```

That is not a licensing refusal — the feature is present. It requires
`--enable-cbt`, which in turn requires the VM to be **powered off**: the
`-ctk.vmdk` tracking map is created when the disk is opened, and a running
VM already holds its disks open without it. Note also that the tool failed
*safely*, falling back to a normal replica rather than aborting.

One structural obstacle remains, and it is the operator's retention scheme
rather than the software: each cycle writes to a **new** target folder
(`backp410`, `backp411`, `backp412`, …, with per-host subfolders). A new
folder is a new replication point with sequence zero, so CBT would have
nothing to compare against and every run would still be full. Using three
**fixed** target slots rotated in turn preserves the same three restore
points of the same ages, while letting each slot keep its CBT sequence.

Not yet acted on — recorded so the analysis is not lost.

## What this test did NOT measure

The backup window itself has been closed above. Three questions that were
open when this section was first written have since been answered, and
are recorded here so the sequence of reasoning stays visible:

- **Where the backup writes to** — the QNAP (`116TB`), not the array being
  read. Confirmed by the A/B test paths.
- **Whether the fabric is the constraint** — no, at 30 % peak.
- **Whether the backup pollutes the cache** — **yes, and now observed.**
  During the window the array supplied **63 %** of the bytes read, against
  8.6 % during the working day: the backup is reading precisely what the
  cache does not hold, and admitting it. 273 GB passed through a 16 GB
  cache in 280 minutes, none of it to be read a second time.

  That is the case `migration_threshold` was added for in 0.4.1-alpha, seen
  directly for the first time. It was **not in effect** — the node still
  runs 0.4.0-alpha — so this is the "before" reading.

**Still genuinely unmeasured:**

- the effect of `migration_threshold` (0.4.2-alpha not yet deployed)
- the effect of CBT (requires a maintenance window per VM)
- whether any of this holds in a normal month — see below

## Caveat on the whole test

**This is mid-August.** The operator was on annual leave for part of the
month and a good share of the building with him. There is every reason to
think this is among the quietest working days of the year.

No conclusion here should be treated as final until the same capture is
repeated in September.

## Actions

- [x] Overnight capture across the backup window — done, 23.33 h total
- [x] Establish where the backup writes its target — the QNAP
- [x] Decide on the 8 Gb fabric — **no**, on measured grounds
- [ ] Repeat the working-day capture on a normal September day
- [ ] Deploy 0.4.2-alpha and re-measure with `migration_threshold`
- [ ] Trial `--enable-cbt` + `--replica=cbt` on one expendable VM, in a
      maintenance window (requires the VM powered off)
- [ ] If CBT is adopted: convert the retention scheme from
      "new folder each cycle" to three fixed rotating slots

## Lessons

1. **Run the capture unfiltered.** Naming a single device would have
   produced the same throughput figures and none of the layer
   decomposition — no `dm-2` confirmation, no 160×, no promotion
   accounting.
2. **A published rule is not an applied rule.** Field Test #3's warning
   about cumulative counters was written by the same people who then
   ignored it. Rules need to be built into the tool, not into the
   documentation — which is what `--delta` was, and it still was not
   reached for.
3. **State the window, always.** "1006 write IOPS" and "15.7 write IOPS"
   are both true of this machine. Neither means anything without the
   period attached.
4. **Measuring in the quiet season proves less than it appears to.** The
   numbers are real; their representativeness is not established.

---

# Hardening checklist for the rebuild window

Everything the earlier incidents recommended, collected in one place:

- SMART screening of every used drive before it enters the array
  (`Reallocated_Sector_Ct`, `Current_Pending_Sector`, overall health);
  weakest units go to the shelf as cold spares
- deliberately **mixing drive ages** within the array to avoid
  correlated failures
- `crashkernel=` added and kdump verified after reboot
- `ipmi_watchdog` + `RuntimeWatchdogSec=60` armed
- memtest86+ pass while the node is down anyway
- both PSUs reseated and inspected (Field Test #4 follow-up)
- 4 bays reserved for a future SSD tier (original Dell 3.5″→2.5″
  carriers sourced; over-provision 15–20 % since the controller does
  not pass TRIM through a RAID volume)
- **done:** both PSUs replaced, feeds verified on separate breaker
  panels (Field Test #6)
- **done:** Patrol Read enabled weekly — the array contains five drives
  with 48,086 hours each, all from the same batch, so latent sector
  errors must be found while the array is healthy rather than during a
  rebuild
- **pending:** memtest86+ pass; kdump `crashkernel=` verified active
  after the next boot
- **pending:** 0.4.1-alpha deployed to the node and `migration_threshold`
  re-measured at 512 against the Field Test #8 baseline
- **done:** working-day `iostat -x 60` capture — Field Test #9. Daytime
  peak was 19.9 % of the 4 Gb link, so the ~400 EUR fabric upgrade is not
  justified by user traffic
- **pending:** overnight capture across the **backup window**, which
  Field Test #9 did not cover — the last remaining case for 8 Gb, and the
  prime suspect for cache pollution
- **pending:** repeat the working-day capture in September; the August
  measurement was taken in the quietest month of the year
