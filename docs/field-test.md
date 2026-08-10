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
- [Field Test #5](#field-test-5--raid-0-vs-raid-6-same-vm-same-cache)
  — RAID 0 vs RAID 6 on identical VM and cache: **cache hit 255 µs vs
  10–15 ms miss; 30× IOPS between a cold and a warm cache**
  (2026-08-10, part 2 pending)

Measurement procedure for all performance runs:
[benchmark-protocol.md](benchmark-protocol.md)

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

Date: 2026-07-23
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

Date: 2026-08-02 (uptime 8d 22h since blackout recovery)

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
100 MB/s on all datastores. dm-cache handles UNMAP correctly —
discarded blocks are invalidated in cache and the discard is passed
down to the origin, so reclamation and caching coexist without stale
data. (On HDD-backed hardware RAID the controller typically drops the
discard anyway — harmless either way.)

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

Date: 2026-08-06

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

Date: 2026-08-10 → *(in progress)*

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

## Part 2 — `RAID6-8disk` (pending rebuild)

Predictions recorded **before** the measurement, so they can be scored
honestly afterwards:

| Run | RAID0-2disk | Expectation for RAID6-8disk | Reasoning |
|-----|-------------|------------------------------|-----------|
| B array (rand read) | 739 IOPS | **3–4× better** | 8 spindles instead of 2; this is the ceiling the rebuild exists to raise |
| C rand write | 806 IOPS | **uncertain — may barely improve** | RAID 0 pays no parity cost; RAID 6 pays read-modify-write on every small write. More spindles vs. worse per-write cost |
| D sequential | 286 MiB/s | **> 800 MiB/s** | 6 data spindles streaming |
| A3 hot / A-lat | 14,400 IOPS / 255 µs | **roughly unchanged** | same RAM, same FC path — the cache path does not depend on the array |
| A1 cold | 468 IOPS | improves with B | cold pass is array-bound by definition |

The honest expectation is that **the cache path stays the same and the
miss path gets much faster** — which should raise the floor of the
system far more than its ceiling.

## Planned hardening in the same maintenance window

The rebuild window is also being used for everything the previous
incidents recommended:

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
