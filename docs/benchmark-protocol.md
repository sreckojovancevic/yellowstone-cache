# Benchmark protocol — comparing storage backends fairly

A repeatable procedure for measuring a Yellowstone-cached LUN, designed
so that results taken months apart, on different arrays, remain
comparable.

Used for: `RAID0-2disk` (2026-08-10, before rebuild) →
`RAID6-8disk` (after rebuild) → optionally `SSD-RAID10` tier.

## Why a protocol at all

Two mistakes make storage benchmarks worthless:

1. **Mixing what is measured.** With a 16 GiB cache in the path, a test
   file smaller than the cache measures RAM; a file much larger
   measures the array. Both are legitimate — but they must be reported
   separately, never blended.
2. **Changing more than one variable.** Different VM, different guest
   OS, different fio flags, different background load — and the
   comparison collapses. The same cloned VM is moved between arrays
   precisely to keep everything except the storage identical.

## Test subject

A small cloned VM (~40 GB, e.g. `waf_wcl_clone`) — migrates between
datastores in minutes, so the identical guest can be carried from one
array to the next. Only one instance is powered on at a time.

## File sizes — measure two different things

| Test file | Relative to cache | What it actually measures |
|-----------|-------------------|---------------------------|
| **8 GiB** | fits inside the 16 GiB cache | the **cache path** — second pass is served from RAM |
| **64 GiB** | far larger than cache | the **array** — the cache cannot mask the disks |

Report both. A single number is meaningless.

## Preparation (once per array)

```bash
fio --name=prep --filename=/test/f8  --size=8G  --rw=write --bs=1M --direct=1
fio --name=prep --filename=/test/f64 --size=64G --rw=write --bs=1M --direct=1
```

## The four runs

`--direct=1` is mandatory everywhere: without it the guest page cache
serves the reads and the whole test measures the VM's own RAM.

```bash
# A) CACHE PATH — run TWICE: first pass cold (fills), second pass warm
fio --name=r4k-cache --filename=/test/f8 --size=8G --rw=randread --bs=4k \
    --direct=1 --ioengine=libaio --iodepth=32 --numjobs=4 \
    --group_reporting --runtime=60 --time_based

# B) ARRAY PATH — working set far exceeds the cache
fio --name=r4k-array --filename=/test/f64 --size=64G --rw=randread --bs=4k \
    --direct=1 --ioengine=libaio --iodepth=32 --numjobs=4 \
    --group_reporting --runtime=60 --time_based

# C) WRITES — writethrough, so this is the array plus parity cost
fio --name=w4k --filename=/test/f64 --size=64G --rw=randwrite --bs=4k \
    --direct=1 --ioengine=libaio --iodepth=32 --numjobs=4 \
    --group_reporting --runtime=60 --time_based

# D) SEQUENTIAL — smq bypasses this, so it is the raw array
fio --name=seq --filename=/test/f64 --size=64G --rw=read --bs=1M \
    --direct=1 --ioengine=libaio --iodepth=8 \
    --runtime=60 --time_based
```

## Second instrument — cache counters per run

fio reports what the guest saw. `yellowstone status` reports what the
cache actually did. Take a sample immediately before and after **each**
run and record the delta:

```bash
sudo /opt/yellowstone/bin/yellowstone status TestDisk --json
```

Delta of `read_hits` / `read_misses` gives the true hit ratio *for that
test*; delta of `promotions` × 256 KiB gives the data pushed through
the cache. Two independent instruments telling the same story is worth
far more than either alone.

Optionally add a third view on the storage node: `iostat -x 5` during
the run — `dm-2` (cdata) latency shows cache hits, the origin device
shows misses.

## Recording results

Label every result set with the full configuration, because the
hardware will not exist forever:

```text
LABEL: RAID0-2disk / 16 GiB RAM cache / writethrough / PERC H700 / FC to ESXi 7
DATE : 2026-08-10
VM   : waf_wcl_clone (40 GB), single instance powered on
```

| Run | IOPS | Bandwidth | avg latency | p99 latency | cache hit ratio (delta) |
|-----|------|-----------|-------------|-------------|--------------------------|
| A cold (8G) | | | | | |
| A warm (8G) | | | | | |
| B array (64G) | | | | | |
| C write (64G) | | | | | |
| D sequential | | | | | |

## Controlling for background load

The storage node also serves other VMs and periodic replication. To
keep runs comparable:

- run the whole set back to back, in one window
- avoid backup/replication windows
- note the load average and whether other VMs were active
- repeat the set 2–3 times and take the **median**, not the best run

## Known pitfalls

- **Comparing a 2-disk RAID 0 write result to an 8-disk RAID 6 one is
  not a like-for-like performance verdict.** RAID 0 has no parity cost
  and is the fastest possible use of two spindles; RAID 6 pays a parity
  penalty on small random writes but has four times the spindles.
  Expect reads to improve markedly and small random writes to be the
  interesting comparison.
- A 3-disk RAID 6 (if ever built as a stop-gap) is the worst case for
  writes and must not be used as a baseline for the final array.
- Different drive classes (surveillance vs enterprise vs SAS) belong in
  the label, not hidden in a footnote.
