# Design note — two-tier cache (RAM over SSD)

> **Status: DESIGN ONLY. Nothing in this document has been measured.**
>
> This is a reference note, written before the hardware exists, so that
> when the second SSD is installed the work starts from a plan instead
> of from improvisation. Predictions in the test plan below are
> **registered in advance** and are to be scored honestly afterwards,
> the same way as in Field Test #5.
>
> Nothing here belongs in `field-test.md` until it has been run.

Date written: 2026-08-16
Prerequisite hardware: one additional SSD (~512 GB) dedicated to cache
Origin of the idea: Srećko, 2026-08-16, following Field Test #8

---

## 1. Why this is worth building

Two measurements point at the same place from different directions.

**Field Test #8, Finding 1 — the write path is stuck on RAID 6.**
Average guest write 79 KB against a 384 KB stripe means every logical
write becomes a read-modify-write cycle: read old data, old P, old Q,
recompute, write back. Measured result: the array at 92–97 % utilisation
while delivering 60–80 MiB/s, with latency climbing from 3.4 ms to 27 ms.

**Field Test #5, Finding 2 — misses drag hits down with them.**
Replacing the array underneath the cache made the *cache itself* 5.9×
faster, because cache hits queue behind cache misses on the same
device. The miss path is not a separate concern from the hit path.

An SSD tier between the RAM cache and the array attacks both:

- **Misses** go from RAID 6 random (order 10³ IOPS) to SSD (order 10⁴).
- **Hits** get faster as a side effect, by the Field Test #5 mechanism.
- **Writes** — only if the SSD tier runs writeback. See §3.

A previous assessment in this project ("more cache will not help, the
link is the wall") was correct for *sequential reads* and wrong for the
random path. Recorded here so the correction is not silently absorbed.

---

## 2. Device chain

```text
LIO storage object "TestDisk"
        dev = /dev/mapper/TestDiskCached
                    │
                    ▼
   ┌─────────────────────────────────┐
   │ L1  dm-cache   TestDiskCached   │  RAM (brd), writethrough
   │     origin = /dev/mapper/…L2    │  16 GB, block 256 KB
   └─────────────────────────────────┘
                    │
                    ▼
   ┌─────────────────────────────────┐
   │ L2  dm-cache   TestDiskL2       │  SSD, writethrough (phase 1)
   │     origin = /dev/disk/by-id/…  │  ~512 GB
   └─────────────────────────────────┘
                    │
                    ▼
        /dev/disk/by-id/…   RAID 6, 48 TB   ← the origin. Never touched.
```

The single-field principle is unchanged: LIO's `saveconfig.json` still
has exactly one `dev` value rewritten, and the LUN's `wwn` — which is
what ESXi uses for datastore identity — is never touched. The stack
underneath the mapper device is invisible to the initiator.

---

## 3. Three configurations, and the boundary between them

| # | Configuration | Reads | Writes | Origin state | Build cost |
|---|---|---|---|---|---|
| 1 | RAM only (today) | hot 16 GB @ 70 µs | RAID 6 RMW | **always current** | — |
| 2 | RAM + SSD, **both writethrough** | + ~512 GB @ SSD latency; random miss path ~10× | RAID 6 RMW, unchanged | **always current** | stacking, ordering, repair |
| 3 | RAM + SSD, **SSD writeback** | as above | **acknowledged at SSD speed** | **lags behind** | + warm assemble, + flush on teardown |

### The boundary

Configuration 2 preserves the property the whole tool is built on:
**the origin is always complete and current.** Both cache layers are
disposable. If everything fails, LIO is pointed back at the raw array
and the data is there, up to date. There are no dirty blocks anywhere,
so there is nothing to lose.

Configuration 3 removes that property:

- the array **lags behind** whatever is dirty on the SSD;
- a crash with dirty blocks leaves the raw origin **inconsistent** —
  recovery *requires* successfully reassembling the cache;
- SSD failure is data loss, not an inconvenience.

That is not an argument against configuration 3. It is an argument
that the step must be taken deliberately, with warm assemble in place
first, and never as a side effect of a config edit.

**The one-sentence version, worth keeping in mind while writing the
repair code:** under writethrough, *"when in doubt, tear down and
rebuild"* is always safe; under writeback, it is never safe.

**Enforced in code since 0.4.2-alpha:** `cache_mode = writeback` is
refused at config load time for *any* cache type, not only for RAM. The
error names warm assemble as the missing prerequisite. Before that
version the tool would have accepted `cache_type=device` +
`writeback` without a word and destroyed the datastore on the first
reboot — via `repair --apply` from systemd, unattended.

### Recommendation

Build configuration 2 first. It is the same engineering — stacking,
assembly ordering, a wider repair matrix — without introducing a single
new way to lose data. Once two-tier assembly has survived a few weeks
and at least one unplanned reboot in production, writeback becomes one
config field with warm assemble as its precondition.

If configuration 3 is ever adopted, **L2 must be a RAID 1 pair, not a
single drive.** Under writethrough an SSD death costs a warm cache;
under writeback it costs the datastore.

---

## 4. Configuration shape

Each tier independently enabled, so the existing single-tier setup
remains valid and untouched:

```ini
[cache]
enable      = yes
cache_type  = ram
cache_ram   = 16G
cache_mode  = writethrough
migration_threshold = 2048

[cache.l2]
enable              = no                      ; off by default
cache_device        = /dev/disk/by-id/...     ; by-id, never /dev/sdX
cache_mode          = writethrough            ; writeback rejected until
                                              ; warm assemble exists
migration_threshold = 2048
block_size          = 256K
```

Validation rules to enforce at load time, alongside the existing ones:

- `[cache.l2] enable = yes` with `[cache] enable = no` → **reject**.
  L2 alone is a valid idea but a different feature; do not allow it to
  arrive by accident through a half-edited file.
- `[cache.l2] cache_mode = writeback` → **reject** with an explicit
  message naming warm assemble as the missing prerequisite. This
  mirrors the existing hard rule that `cache_type=ram` + `writeback` is
  refused at load time.
- `cache_device` must not be the origin, must not be a partition of the
  origin, and must not be in use by another cache.
- both tiers' `migration_threshold` validated in the existing
  64–1 048 576 sector range.

---

## 5. Assembly and teardown order

**Assembly — bottom up.** L1's origin is L2's mapper device, so L2 must
exist first.

```text
1. preflight: idle check on the device LIO currently exports
2. lio_stop
3. create L2  (SSD cache over by-id origin)
4. create L1  (RAM cache over /dev/mapper/…L2)
5. state: record the full chain, phase=attaching
6. saveconfig: dev → /dev/mapper/…Cached
7. lio_start; phase=active
```

Step 5 stays before step 6, for the same reason as today: a crash
between repoint and state write would leave `saveconfig` pointing at a
device the state file does not know about.

**Teardown — top down**, strictly the reverse:

```text
1. preflight
2. lio_stop
3. state: phase=detaching
4. saveconfig: dev → origin (from state, by-id)
5. remove L1
6. remove L2
7. destroy RAM disk
8. lio_start; unregister
```

Under configuration 3 an extra step is required between 4 and 5:
switch L2 to the `cleaner` policy and wait for dirty blocks to reach
zero. With 512 GB of cache this can take minutes and must be reported
with progress, not run silently. `down` and `reset` both change shape
because of it — another reason to defer configuration 3.

---

## 6. State schema v2

`state.origin` becomes a chain rather than a single path. Proposed
shape, with automatic migration from v1 (a v1 record is a chain of
length one):

```json
{
  "version": 2,
  "caches": {
    "TestDisk": {
      "phase": "active",
      "origin": "/dev/disk/by-id/...",
      "layers": [
        { "level": 2, "dm_name": "TestDiskL2",
          "cache_type": "device", "cache_device": "/dev/disk/by-id/...",
          "mode": "writethrough", "block_size": 524288 },
        { "level": 1, "dm_name": "TestDiskCached",
          "cache_type": "ram", "cache_ram": 17179869184,
          "mode": "writethrough", "block_size": 524288 }
      ]
    }
  }
}
```

`layers` is ordered bottom-up, which is also assembly order; teardown
walks it in reverse. `origin` remains the anchor that `repair` trusts
above all other sources — after attach, `saveconfig` points at the top
of the stack and is useless for recovering the true origin.

`block_size` is recorded per layer because warm assemble (configuration
3) will need to verify it matches on reassembly; a mismatch there
corrupts mappings silently.

---

## 7. Repair — generalising `decide_action`

The naive approach is to add a second boolean and enumerate 3 × 2 × 2 ×
2 = 24 rows. Better: collapse the layers into a **three-valued
`dm_state`**, which keeps `decide_action` a pure function of three
small values and keeps the table readable.

```python
DM_NONE    = "none"      # no layer present
DM_PARTIAL = "partial"   # some layers present, not all
DM_FULL    = "full"      # every layer in state is present
```

| `phase` | `dev_on_top` | `dm_state` | Action |
|---|---|---|---|
| attaching | yes | full | `finish_attach` |
| attaching | yes | partial | `rollback_attach` |
| attaching | yes | none | `rollback_attach` |
| attaching | no | full / partial | `cleanup` |
| attaching | no | none | `forget` |
| active | yes | full | `healthy` |
| active | yes | partial | `recreate` (tear down remnants first) |
| active | yes | none | `recreate` (the ordinary post-reboot case) |
| active | no | full / partial | `cleanup` |
| active | no | none | `forget` |
| detaching | yes | any | `finish_detach` |
| detaching | no | full / partial | `finish_detach` |
| detaching | no | none | `forget` |

Two things this preserves from the current implementation:

- `decide_action` stays **testable without root** — it takes three
  values and returns a string.
- Cleanup still touches **only dm names derived from the state
  record** (`dm_name`, `-cmeta`, `-cdata`, per layer). No pattern
  matching over `dmsetup ls`, ever.

`recreate` gains one rule: a partial stack is never repaired in place.
Remaining layers are removed and the chain is rebuilt from the bottom.
Under writethrough this is free. **Under writeback it is data loss** —
which is precisely why configuration 3 needs a different repair path,
not an extended one.

---

## 8. Warm assemble

**Correction to an earlier framing in this document.** Warm assemble was
first written down here purely as a precondition for writeback. That was
wrong in an important way: it is *also* a writethrough feature, and in
writethrough it carries **no data risk at all**, because dirty blocks
never exist. The worst a failed warm assemble can do under writethrough
is fall back to a cold cache.

The distinction only became obvious once cache size entered the picture:

| Cache | Warm-up at ~2.85 MiB/s promotion | Value of surviving a reboot |
|---|---|---|
| 16 GB RAM | ~30 minutes | negligible |
| ~700 GB SSD | **days** | **the main reason to build it** |

At 16 GB it did not matter. At 700 GB, throwing the cache away on every
reboot means it is effectively never warm. So warm assemble should move
**ahead** of writeback in the plan, and be built for writethrough first,
where it is safe by construction.

Requirements below apply to both; items 4, 5 and 6 are what writeback
adds on top.

1. **Do not zero metadata on assembly.** `create` currently zeroes the
   `-cmeta` device every time, which is correct for a RAM cache and
   fatal for a persistent one. Needs a distinct "reattach" path.
2. **Metadata must live on the SSD**, not in RAM, and must survive the
   node. Its size must be recorded in state.
3. **Validate before loading:** cache block size, cache device size and
   origin size must match what the metadata was created with. A
   mismatch must refuse loudly; dm-cache will not always catch it.
4. **Handle `needs_check`.** If the flag is set in the superblock,
   run `cache_check` from thin-provisioning-tools and refuse to
   assemble on failure. `cache_repair` only on explicit operator
   instruction — never automatically.
5. **Flush on teardown** via the `cleaner` policy, with progress
   reporting and a timeout that fails safe rather than proceeding.
6. **`repair` must distinguish** "cache metadata present and clean"
   from "present with dirty blocks". Only the first may be discarded.

---

## 9. Test plan for when the SSD arrives

Follow `benchmark-protocol.md` throughout — including the mandatory
controller-idle pre-flight check, since Field Test #5 lost an entire
round to an active Patrol Read (a factor of 73).

**Baseline first.** Re-run the Field Test #8 capture on the current
single-tier setup, on an idle controller, so the comparison is against
a clean number rather than against a measurement taken during
production work.

Measurements, each cold / warm / hot:

| # | Profile | What it isolates |
|---|---|---|
| T1 | 4K random read, working set ~100 GB, QD32 | the miss path — the main reason for L2 |
| T2 | 4K random read, working set ~8 GB, QD32 | L1 hits, to test the Field Test #5 mechanism |
| T3 | 1 MiB sequential read, QD8 | expected to stay link-bound |
| T4 | 1 MiB sequential write, QD8 | the RMW path, unchanged under writethrough |
| T5 | 10 GB guest-to-guest copy | direct comparison with Field Test #8 |
| T6 | reboot, then `repair --apply` | two-tier cold assembly time |

Collect for every run: `yellowstone status --delta 60` on **both**
tiers, and `iostat -x` on the mapper device, the SSD and the array.

### Predictions, registered in advance

1. **T4 and T5 write throughput unchanged** from Field Test #8 within
   ±10 %. Under writethrough every write still reaches RAID 6; L2
   cannot help. If this prediction fails, the model of the write path
   is wrong and everything above needs revisiting.
2. **T1 improves by more than 10×** over the uncached RAID 6 random
   read baseline.
3. **T2 improves measurably** — the Field Test #5 mechanism — but by
   far less than T1. Guess: 20–50 %.
4. **T3 unchanged**, capped around 380 MB/s by the 4 Gb link.
5. **T6 adds less than 30 s** to assembly time versus single-tier.
6. **Both tiers thrash during T5.** A sequential copy pollutes L1 *and*
   L2; `migration_threshold` will need tuning on both, and the correct
   value is unlikely to be the same for a 16 GB tier and a 512 GB one.

Score these honestly afterwards. Field Test #5 scored 1 of 4 correct,
and the three failures were where the useful findings came from.

---

## 10. Open questions

- **Is L1 still worth it above L2?** RAM at 70 µs versus SSD at perhaps
  250 µs is a real gap, but small relative to fabric and target
  latency. T2 is the test that answers it. A negative answer would be a
  useful result: one tier is far simpler than two.
- **Block size for a 512 GB tier.** 256 KB gives ~2 M blocks and
  metadata in the tens of MB, which is manageable — but a larger block
  reduces metadata at the cost of coarser admission and more read
  amplification on partial hits. Not obvious; worth one A/B.
- **`migration_threshold` interaction between tiers.** An L1 miss
  generates an L2 access, which may trigger an L2 promotion. The two
  admission policies are unaware of each other. Prediction 6 above is
  the first probe at this.
- **Over-provisioning.** The controller does not pass TRIM through a
  RAID volume, so a cache SSD created at full capacity will carry
  maximum write amplification. Leave 15–20 % unallocated at creation —
  the same conclusion as Field Test #7, Finding 3, which was skipped
  once already. **Resolved for the first drive:** see
  [l2-ssd-baseline.md](l2-ssd-baseline.md) — full TRIM plus Flex
  Capacity to 700 GB, ~36 % total over-provisioning, with the drive's
  measured lifetime WAF of 3.68× recorded as the number to beat.
