# Yellowstone Cache

**Add a RAM or SSD read cache to an existing Linux LIO storage target —
without touching your data, and without changing your LUN identity.**

Yellowstone is not a new storage system. It is a thin administration
tool that inserts a `dm-cache` layer under an existing LIO (targetcli)
export. The initiator (VMware ESXi, Windows, Linux) sees the exact same
disk before and after — same WWN/NAA ID, same LUN number, same ACLs,
same size. The only thing that changes is speed.

> **Status: alpha.** Running in production on one system since
> 2026-07-19: it has survived a datacenter blackout, an unexplained
> host reset and a full array rebuild, each recovered with a single
> command (see [field tests](docs/field-test.md)). Writethrough only
> for RAM caches — enforced in code. Use at your own risk, and read
> the safety section first.

## The key idea

Most caching solutions require you to rebuild your storage around them:
bcache needs to format the backing device, lvmcache needs everything
inside LVM. Yellowstone deliberately uses `dm-cache`, the only mainline
mechanism that can wrap an **existing block device in place** — zero
bytes of cache metadata are ever written to your data disk.

The LIO integration follows the same principle. Yellowstone never
deletes or recreates a backstore. While LIO is briefly stopped, it
changes exactly **one field** in `/etc/rtslib-fb-target/saveconfig.json`
— the `dev` path — and restores. WWN, LUNs, ACLs and attributes remain
byte-for-byte identical, so ESXi re-detects the same datastore without
a resignature prompt.

Detach (`down`) is the mirror image: the origin device is returned to
LIO in the exact state it would be in if Yellowstone had never existed.

```text
   BEFORE                              AFTER `yellowstone up`
   ------                              ---------------------
   ESXi / initiator                    ESXi / initiator   (same NAA ID)
    |                                   |
   LIO backstore                       LIO backstore      (same WWN/LUN/ACL)
    |                                   |
   /dev/disk/by-id/wwn-...            /dev/mapper/<NAME>Cached
   (RAID / disk)                        |
                                      dm-cache (writethrough, smq)
                                       |              |
                                    /dev/ram0      /dev/disk/by-id/wwn-...
                                    (RAM cache)    (origin - untouched)
```

## Field test results

Not a lab: a live Dell PowerEdge R510 (24 threads, 62 GiB RAM, PERC
H700) exporting over QLogic Fibre Channel to VMware ESXi 7.0, carrying
production VMs. Cache: RAM (brd), writethrough, preallocated.

The numbers below span several weeks and two arrays. Full method and
raw data: [docs/field-test.md](docs/field-test.md) ·
[docs/benchmark-protocol.md](docs/benchmark-protocol.md)

| Metric | Result |
|--------|--------|
| **Cached 4K random read, 8-disk RAID 6 origin** | **84,700 IOPS**, avg 1.49 ms, p99 3.56 ms, 100 % hit ratio |
| Same test, 2-disk RAID 0 origin | 14,400 IOPS, avg 8.9 ms, p99 183 ms — **the cache is only as fast as the storage it hides** |
| Attach downtime (`up`, incl. 12 GiB prealloc) | **9.69 s** |
| ESXi datastore after attach | **re-detected automatically, same NAA, no resignature** |
| Cache hit read latency (iostat, cdata device) | **~0.02 ms** |
| Cache hit latency, end-to-end from the guest (fio, QD1) | **255 µs** (p50 243 µs, p99 392 µs) — vs 10–15 ms for a miss |
| Warm vs cold cache, identical fio run 3 minutes apart | **468 → 14,400 IOPS**, 272 ms → 8.9 ms |
| Cache miss read latency (2-disk RAID 0 origin) | 11–50 ms |
| 1 GiB file copy, read phase served from RAM | **~99 %** (40.6 of 40.7 MB/s) |
| Writethrough verification | cache-layer write MB/s == origin write MB/s, **dirty blocks 0 at all times** |
| After ~30 min mixed workload | 47,330 read hits / 27,217 misses (63.5 % from cold start) |
| Promoted working set | 5,515 blocks ≈ 1.4 GiB (11 % of cache) — sequential streams correctly bypassed |
| Demotions | 0 (no cache pressure) |

Reads served from cache remained at sub-millisecond latency even while
the origin array was at 95–98 % utilization under sequential writes.

**Update:** four days after the first attach, the system survived an
**unplanned datacenter blackout** (generator failure, hard power loss
mid-I/O). Recovery: one command (`repair --apply`), zero data loss,
same NAA, no resignature. See Field Test #2.

**Second unplanned outage (2026-08-06):** the host powered down without
warning after 13 days of uptime (BMC telemetry later showed the main
rails collapsing to standby draw). Recovery was a single
`repair --apply` executed **over SSH from off-site** — no console, no
physical access, zero data loss, datastore re-attached by itself. See
Field Test #4.

**Third recovery (2026-08-13):** both power cords pulled by mistake
during a PSU replacement, while the new RAID 6 array was only 49 %
through its background initialisation — the most fragile state a parity
array can be in. The controller resumed initialisation from where it
stopped, `repair --apply` rebuilt the cache, and the datastore
re-attached itself. See Field Test #6.

**Also measured, on an uncached LUN in the same fabric (Field Test #7):**
a controller cache policy chosen from plausible reasoning cost **6×
write throughput** (57 → 366 MiB/s) until a 60-second fio run exposed
it — after which the bottleneck was no longer the drives but the 4 Gb
FC link itself. Measuring a device locally *and* through the fabric is
what makes the difference between the two visible.

**Worst case matters too:** on a shared LUN also hosting a multi-camera
NVR and a full-scan backup job, the hit ratio drops to ~34 % (video
streams interleave and defeat `smq`'s sequential bypass). Even so, the
16 GiB cache absorbed ~470 of 1,384 requested read IOPS — more than a
2-spindle array could have delivered on its own. Dirty blocks: 0
throughout 9 days and ~6 TB of promotions. See Field Test #3.

Full raw data and interpretation: [docs/field-test.md](docs/field-test.md) ·
Disaster recovery runbook: [docs/recovery.md](docs/recovery.md) ·
Controller/drive findings: [docs/hardware-notes.md](docs/hardware-notes.md)

Not yet built, not yet measured — a design note for a second cache tier
(RAM over SSD), written in advance so the work starts from a plan and
its predictions can be scored honestly:
[docs/design-l2.md](docs/design-l2.md) ·
wear baseline for the cache SSD, recorded before it entered service:
[docs/l2-ssd-baseline.md](docs/l2-ssd-baseline.md)

## Features

- `up NAME` / `down NAME` — attach/detach cache to a LIO backstore in
  one measured downtime window, with automatic rollback on any failure
- `reset NAME` — rebuild the cache (new size, cold start) inside a
  **single** LIO stop/start cycle, so initiators never get a window to
  reconnect and hang the next teardown
- **Preflight busy check** — sampling `/proc/diskstats` on the exported
  device before stopping LIO; refuses (rather than hanging the kernel)
  when an initiator is still driving I/O. `--force` overrides
- `status --delta N` — interval rates instead of cumulative counters:
  IOPS, hit ratio for that window, promotion MB/s and **full cache
  turnover time**, with a warning when the cache recycles in minutes
- RAM cache (brd) or block-device cache (SSD/NVMe) via `cache_type`
- Fixed-size RAM cache with optional full preallocation (no OOM
  surprises later; memory visibly reserved at attach time)
- `repair` — compares three sources of truth (state file, saveconfig,
  kernel dm) and resolves interrupted procedures; dry-run by default,
  also serves as the standard boot procedure after reboot
- `status` — parsed dm-cache statistics: hit ratios, usage, dirty,
  promotions/demotions; `--json` on every command for automation
- Stable device naming: origins are recorded as `/dev/disk/by-id/`
  paths, immune to sdX reordering across reboots
- Single source of truth per layer; no parsing of `targetcli ls`,
  no external Python dependencies (stdlib only)

## Safety design

- **RAM cache is writethrough only — enforced, not documented.**
  A `cache_type=ram` + `cache_mode=writeback` config is rejected at
  load time. Every write is acknowledged only after the origin (RAID)
  has it. Power loss costs you cache warmth, never data.
- Memory is checked before anything is touched: attach refuses unless
  `cache_ram + memory_headroom` is available.
- Every saveconfig.json modification is atomic (temp + rename + fsync)
  and preceded by a timestamped backup.
- Any failure mid-attach triggers rollback: LIO returns to the origin
  device, cache layers are removed.
- The state file (`state/caches.json`) is formally specified
  (`docs/state.md` + JSON Schema) including crash-recovery semantics.

## Quick start

```bash
unzip yellowstone-*.zip -d /opt/
chmod +x /opt/yellowstone/bin/yellowstone /opt/yellowstone/scripts/*.sh
vi /opt/yellowstone/etc/yellowstone.cache     # cache_ram, mode, type

/opt/yellowstone/bin/yellowstone validate     # read-only system check
sudo /opt/yellowstone/bin/yellowstone up <BACKSTORE_NAME>
sudo /opt/yellowstone/bin/yellowstone status <BACKSTORE_NAME>
```

Before `up`/`down` on a live ESXi environment: power off / unregister
VMs and unmount the datastore first — LIO teardown can hang on
in-flight FC/iSCSI commands if an initiator is actively using the LUN.
Since v0.4.0 a preflight check refuses the operation instead of hanging
the kernel; `--force` overrides it if you know better.

To resize or refresh an existing cache, use **`reset`** rather than
`down` followed by `up`: the latter leaves a window in which initiators
reconnect, and the second teardown is the one that hangs.

```bash
vi /opt/yellowstone/etc/yellowstone.cache     # cache_ram = 24G
sudo /opt/yellowstone/bin/yellowstone reset <BACKSTORE_NAME>
```

Full procedure and troubleshooting: `docs/uputstvo.md`.

## Reboot behaviour

dm mappings and RAM do not survive a reboot; the configuration files
do. Nothing is cleaned up at shutdown by design — a power loss never
runs cleanup either, so there is exactly one recovery path:

```bash
yellowstone repair            # shows the plan (typically: recreate)
yellowstone repair --apply    # rebuilds cache, starts LIO
```

Run manually after boot (default; keep `target.service` disabled), or
install the provided systemd units (`systemd/`) to run it
automatically before LIO starts.

## FAQ

**Why not bcache?** bcache writes a superblock to the backing device —
attaching it to an existing disk destroys the data layout. Yellowstone's
core promise is attaching to *existing* storage; dm-cache is the only
mainline mechanism that wraps a device in place. (bcache may appear as
an optional engine for greenfield setups.)

**Why not lvmcache?** Same story: it requires the origin to already be
an LVM logical volume. Existing production LUNs usually aren't.

**Why is RAM + writeback forbidden?** Dirty blocks in writeback exist
only in the cache until flushed. RAM + power loss = silent data loss
for every initiator. This is not a tunable.

**Does sequential I/O pollute the cache?** Partly — and the honest
answer is more useful than the marketing one. The `smq` policy does
bypass detectably-sequential *reads*: a single large file copy in the
first field test promoted almost nothing. But two real workloads defeat
that in practice:

- **Multi-stream video.** An NVR writing and reading a dozen camera
  streams at once produces I/O that is sequential per stream but
  interleaved at the block layer — the detector sees random access and
  promotes it. Video is the worst possible cache tenant (huge volume,
  zero reuse), so give it its own uncached LUN.
- **Sequential writes in writethrough mode.** A 64 GiB sequential
  preparation write filled the cache to 99.7 %. Bypass of sequential
  *reads* does not imply bypass of sequential *writes*.

Both were measured, not assumed — see Field Tests #3 and #5.

**What does the initiator see during `up`/`down`?** A short I/O stall
(ESXi: APD) for the duration of the downtime window — seconds. VMs do
not crash; plan a quiet moment anyway.

## Project layout

```text
bin/yellowstone          CLI (single sys.path entry point)
lib/                     business logic (stdlib only)
lib/cache/               engine interface + dmsetup engine + loader
scripts/                 thin shell layer (dmsetup/targetctl/brd)
etc/yellowstone.cache    configuration
docs/                    admin manual, state file specification
systemd/                 optional auto-mode units
state/, logs/            runtime (not part of the repo)
```

## Roadmap

- Multiple simultaneous caches (brd currently fixed to /dev/ram0)
- Warm-cache assemble for SSD caches (metadata preserved across reboot)
- bcache / lvmcache / dm-writecache engines
- Monitor mode (migration threshold tuning under array pressure)

## Acknowledgements

The idea, the architecture and its design principles are the author's —
in particular the one the whole project rests on: attach a cache to
existing storage without touching the data or the identity of the
exported LUN.

Claude (Anthropic) contributed as an implementation and analysis
partner: extending the codebase, reviewing designs, analysing field-test
data and proposing instrumentation. The `status --delta` view — interval
rates, cache turnover time and the thrashing warning — came out of
analysing the Field Test #3 data and proved itself in Field Test #5,
correctly flagging a 1.9-minute cache turnover under a sequential read.

That collaboration is documented in both directions: of four performance
predictions recorded in advance, one was correct. Finding 2 in Field
Test #5 exists precisely because the reasoning failed loudly enough to
demand an explanation.

All hardware, measurements, production risk and engineering decisions
are the author's.

## License

GPL-2.0 — see [LICENSE](LICENSE).
