# Yellowstone Cache

**Add a RAM or SSD read cache to an existing Linux LIO storage target —
without touching your data, and without changing your LUN identity.**

Yellowstone is not a new storage system. It is a thin administration
tool that inserts a `dm-cache` layer under an existing LIO (targetcli)
export. The initiator (VMware ESXi, Windows, Linux) sees the exact same
disk before and after — same WWN/NAA ID, same LUN number, same ACLs,
same size. The only thing that changes is speed.

> **Status: alpha.** Tested on one production-like system (see field
> test below). Writethrough only for RAM caches — enforced in code.
> Use at your own risk, read the safety section first.

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

## Field test results (v0.3.5-alpha)

Test rig: Dell PowerEdge R510 (24 threads, 62 GiB RAM), PERC H700,
2-disk RAID 0 volume (temporary), QLogic FC target to VMware ESXi 7.0.
Cache: 12 GiB RAM (brd), writethrough, preallocated.
Workload: Windows NVR VM boot + 1 GiB file copy, Alpine VM with
containers (PHP + MySQL site).

| Metric | Result |
|--------|--------|
| Attach downtime (`up`, incl. 12 GiB prealloc) | **9.69 s** |
| ESXi datastore after attach | **re-detected automatically, same NAA, no resignature** |
| Cache hit read latency (iostat, cdata device) | **~0.02 ms** |
| Cache miss read latency (2-disk RAID 0 origin) | 11–50 ms |
| 1 GiB file copy, read phase served from RAM | **~99 %** (40.6 of 40.7 MB/s) |
| Writethrough verification | cache-layer write MB/s == origin write MB/s, **dirty blocks 0 at all times** |
| After ~30 min mixed workload | 47,330 read hits / 27,217 misses (63.5 % from cold start) |
| Promoted working set | 5,515 blocks ≈ 1.4 GiB (11 % of cache) — sequential streams correctly bypassed |
| Demotions | 0 (no cache pressure) |

Reads served from cache remained at sub-millisecond latency even while
the origin array was at 95–98 % utilization under sequential writes.

## Features

- `up NAME` / `down NAME` — attach/detach cache to a LIO backstore in
  one measured downtime window, with automatic rollback on any failure
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
in-flight FC/iSCSI commands if an initiator is actively using the LUN
(see `docs/uputstvo.md` for the full procedure and troubleshooting).

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

**Does the sequential workload pollute the cache?** No — the smq
policy deliberately bypasses sequential I/O (large copies, NVR/video
streams go straight to the array). Confirmed in the field test: a
sustained sequential copy promoted almost nothing.

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
- Preflight check for active initiator sessions before `up`/`down`
- Monitor mode (migration threshold tuning under array pressure)

## License
GPL-2.0 — see [LICENSE](LICENSE).
