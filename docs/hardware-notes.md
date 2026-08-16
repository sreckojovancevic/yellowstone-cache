# Hardware notes — PERC H700 / PowerEdge R510

Findings from building and operating the array underneath Yellowstone.
None of this is Yellowstone-specific, but all of it cost time to work
out, so it is written down.

Items still in progress are marked as such rather than written up as
conclusions — a note that claims more than was actually verified is
worse than no note.

---

## MegaCli cannot address drives that report no enclosure ID

**Symptom.** Two SATA SSDs installed in the backplane were visible to
the OS and to `smartctl`, healthy, `Unconfigured(good)` — but every
attempt to build an array from them failed:

```text
# addressing them like every other drive in the chassis
-CfgLdAdd -r0 "[32:10,32:11]"  →  Device at [32 : 10] is not Disk
-CfgLdAdd -r0 "[252:10,252:11]" →  Device at [252 : 10] is not Disk
-CfgLdAdd -r0 "[:10,:11]"      →  Mix of configured and unconfigured
                                   drives are not possible
```

**Cause.** The drives report no enclosure:

```text
Enclosure Device ID: N/A          ← the two SSDs
Slot Number: 10
Firmware state: Unconfigured(good), Spun Up

Enclosure Device ID: 32           ← every HDD and the boot drive
Slot Number: 0
```

`-EncInfo` confirmed it: the backplane enclosure (device ID 32)
enumerated 9 physical drives — the eight array HDDs plus the boot
drive — and simply did not include the SSDs, even though all of them
report `Connected Port Number: 0(path0)`.

Moving the SSDs to different bays changed the reported slot numbers but
**not** the missing enclosure ID, so the bays were not the cause.

**The actual blocker is a MegaCli parser inconsistency, not the RAID
level and not the hardware.** Two different code paths handle the drive
list differently:

| Form | Empty enclosure field | Result |
|------|----------------------|--------|
| `-CfgLdAdd -r0 "[:10]"` | single element | **works** |
| `-CfgLdAdd -r0 "[:10,:11]"` | list | selects every drive in the system, then refuses because the set mixes configured and unconfigured |
| `-LDRecon ... -PhysDrv"[:11]"` | named parameter | **works** |

**Workaround that got past the blocker.** Create the array from one
drive, then add the second through reconstruction (online capacity
expansion):

```bash
# 1. single-drive RAID 0 — the single-element form parses correctly
MegaCli64 -CfgLdAdd -r0 "[:10]" WT NORA Direct -a0     → Created VD 2

# 2. add the second drive to that VD via the -PhysDrv path
MegaCli64 -LDRecon -Start -r0 -Add -PhysDrv"[:11]" -L2 -a0
                                        → Start Reconstruction Success

# 3. watch it
MegaCli64 -LDRecon -ShowProg -L2 -a0
```

> **Status: reconstruction accepted and running — not yet verified to
> completion.** What is established so far is that the `-PhysDrv` path
> accepts an address the positional list form rejects. Whether the
> reconstruction finishes cleanly and yields a working ~893 GB volume
> is still pending; this note will be updated with the outcome either
> way. (Two background operations were running concurrently on the
> controller — BGI on the RAID 6 array and this reconstruction — so it
> is slower than it would be alone.)

**Rule of thumb:** when MegaCli rejects a drive list, try the same
drives through a `-PhysDrv` parameter instead. It is a different
parser and tolerates addresses the positional form does not.

**Fallback if even that fails:** the H700 has no JBOD/passthrough mode,
so every disk must live in some virtual drive — but nothing stops you
from creating one single-drive RAID 0 per disk and striping them in the
OS with `mdadm` or LVM. Same result, different layer doing the work.

---

## Consequence: no enclosure means no slot LEDs

Because the SES enclosure does not enumerate those bays, the controller
cannot drive their indicator LEDs or respond to `-PdLocate`. If one of
those SSDs fails there will be no amber light pointing at the bay.

Mitigation: record which serial is in which bay, because the serial
number is all you will have.

```text
slot 10 → E784241861
slot 11 → E784241907
```

---

## Cache policy differs between the HDD array and the SSD array

Same controller, opposite settings, for reasons worth stating:

| | HDD RAID 6 | SSD RAID 0 |
|---|---|---|
| Write policy | `WB` (WriteBack) | `WB` — *see below; `WT` was tried first and cost 6×* |
| Read policy | `ADRA` (adaptive read-ahead) | `NORA` (none) |
| I/O policy | `Direct` | `Direct` |

- **WriteBack on the HDD array** is what makes RAID 6 small random
  writes bearable, and it is safe because the BBU was verified healthy
  (`isSOHGood: Yes`) before the array was built. The VD is also set to
  *No Write Cache if Bad BBU*, so it degrades to WriteThrough by itself
  if the battery ever fails.
- **WriteBack on the SSD array too — after measurement corrected an
  earlier decision.** WriteThrough was chosen first, reasoning that
  consumer SSDs lack power-loss protection and that the FC link would
  hide any difference. Both halves were wrong: sustained writes ran at
  **57 MiB/s under WriteThrough and ~366 MiB/s under WriteBack** — a 6×
  difference on the same hardware, minutes apart (Field Test #7).

  The mechanism is not buffering. Under WriteThrough the controller
  waits for each write to be acknowledged by the drive before
  acknowledging the host, so a guest queue depth of 8 means at most 8
  writes in flight to the array. Under WriteBack the controller
  acknowledges immediately and drives the SSDs with its own much deeper
  queue — the drives work in parallel rather than in single file. SSDs
  need queue depth the way spinning disks need sequential access.

  On safety: the BBU protects the *controller's* cache. The risk from a
  consumer SSD's own volatile buffer is identical in both modes, so
  WriteThrough was buying nothing. *No Write Cache if Bad BBU* remains
  set, so the VD degrades to WriteThrough by itself if the battery
  fails.
- **No read-ahead on SSDs.** Read-ahead pays off on spinning disks
  because it avoids a seek. An SSD has no seek to avoid, so speculative
  reads only consume controller bandwidth when they miss.
- **Direct on both** because a 16 GiB RAM cache sits above the array —
  the controller's 512 MiB of cache adds nothing to reads and is better
  spent on writes.

The reasoning originally written here was *"when the link is the
bottleneck, pick the safer policy — it is free."* It is kept as a
reminder that plausible reasoning is not measurement. The safer policy
was not free; it cost 6× and bought no additional safety, and only a
60-second fio run revealed it.

---

## Background operations: what survives a power loss

- **Background initialisation (BGI)** keeps its progress in controller
  NVRAM. After both power cords were pulled at 49 %, it resumed at 49 %
  and carried on to 76 % — it did not restart. Verified in
  [field-test.md](field-test.md) #6.
- **An uninitialised RAID 6 has no valid parity.** Until BGI reaches
  100 %, a drive failure cannot be reconstructed correctly. Treat that
  window as the most fragile state the array will ever be in.
- Raising `BgiRate` while the array is still empty shortens that window
  considerably; lower it again before production load returns.

```bash
MegaCli64 -AdpGetProp -BgiRate -aALL
MegaCli64 -AdpSetProp -BgiRate 80 -aALL   # empty array
MegaCli64 -AdpSetProp -BgiRate 30 -aALL   # back to normal
```

- **Patrol Read** matters more than usual on an array built from used
  drives — five of the eight in this system carry 48,086 hours each,
  all from the same batch. Latent sector errors must be found while the
  array is healthy, not discovered during a rebuild when they are
  needed for reconstruction.

```bash
MegaCli64 -AdpPR -SetDelay 168 -aALL      # weekly
MegaCli64 -AdpPR -Info -aALL
```

---

## Drive screening before building an array

Every used drive was screened first. The three attributes that decide
whether a drive goes into the array, onto the shelf, or in the bin:

```bash
for i in $(seq 0 15); do
  echo "=== slot $i ==="
  sudo smartctl -a -d megaraid,$i /dev/bus/0 2>/dev/null | \
    grep -E "Device Model|Serial|Power_On_Hours|Reallocated_Sector|Current_Pending|SMART overall"
done
```

- `Reallocated_Sector_Ct` > 0 — the drive has already run out of spare
  sectors somewhere
- `Current_Pending_Sector` > 0 — sectors it cannot read and has not yet
  remapped; the worst sign of the three
- `Power_On_Hours` — not a defect, but **identical hours across several
  drives means they will age out together**, which is the failure mode
  parity is worst at surviving

For SSDs the equivalent is remaining endurance, which matters far more
than reallocated blocks:

```bash
sudo smartctl -a -d megaraid,10 /dev/bus/0 | \
  grep -iE "Remaining_Lifetime|Wear_Leveling|Host_Writes|Percent"
```

The two used SSDs in this system reported 90 % and 91 % life remaining
after ~15 TB and ~13 TB written — roughly 130 TB of writes left each,
which is years of headroom for the intended workload.
