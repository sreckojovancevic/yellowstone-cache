# L2 cache SSD — condition record

Endurance and wear baseline for the SSD intended as the L2 cache device
(see [design-l2.md](design-l2.md)). Recorded **before** the drive entered
service, so that wear in its new role can be separated from 4.7 years of
prior use.

A cache device is written far harder than an ordinary data disk. Without
a zero point, "is it wearing out?" has no answer.

## Drive

| | |
|---|---|
| Model | Crucial MX500 1 TB (`CT1000MX500SSD1`) |
| Serial | `1920E203F160` |
| Firmware | `M3CR023` (see note below — `M3CR046` not applicable to this hardware revision) |
| Controller | SM2258 |
| Interface | SATA/600, NCQ, TRIM, queue depth 32 |
| Rated TBW | 360 TB |
| Prior role | Windows data partition (D:), workstation |

## Baseline — 2026-08-17 11:53, immediately before install

Taken after the data was offloaded and after a full-device TRIM, while
the drive was still on a plain SATA port.

| Attr | Name | Raw | Reading |
|---|---|---|---|
| — | Power On Hours | 41,596 | **4.7 years** |
| — | Power On Count | 14,099 | |
| `F6` | Cumulative Host Sectors Written | **23,484,508,511** | **12.02 TB** — 3.3 % of rated TBW |
| `F7` | Host Program NAND Pages | **396,011,197** | |
| `F8` | FTL Program NAND Pages | **1,061,388,586** | |
| `AD` | Average Block Erase Count | **57** | |
| `CA` | Lifetime Remaining | 3 (norm. 97) | **97 %** |
| `05` | Reallocated NAND Block Count | 0 | |
| `AB` / `AC` | Program Fail / Erase Fail | 0 / 0 | |
| `C5` | Current Pending ECC Count | 0 | |
| `BB` | Reported Uncorrectable Errors | 0 | |
| `C7` | UDMA CRC Error Count | 0 | cable and link clean |
| `AE` | Unexpected Power Loss Count | **72** | survived without a single reallocation |
| `B4` | Unused Spare NAND Blocks | 45 | |

### Write amplification at baseline

```text
WAF = (F7 + F8) / F7 = (396,011,197 + 1,061,388,586) / 396,011,197 = 3.68x
```

**3.68× is high.** A healthy figure is 1.5–2.5. For every page the host
wrote, the FTL wrote 2.68 more of its own. The drive spent its whole life
without free space to work with — which is what the preparation below is
meant to fix.

Note this is a *lifetime* average carrying 4.7 years of history. It cannot
be moved by anything done in one afternoon; only interval measurements
taken later will show whether the preparation worked.

## Preparation performed before install

Order matters, and this was the only opportunity: **the PERC H700 does not
pass TRIM through a RAID volume**, so once the drive is behind the
controller its FTL can never again be told that a block is free.

1. Data offloaded
2. Full-device TRIM from Windows — single NTFS volume over the whole
   drive, quick format, then
   `Optimize-Volume -DriveLetter D -ReTrim -Verbose`
   (ATA Sanitize was unavailable — the drive reported "firmware not
   determined" in Storage Executive while offline. TRIM achieves the same
   thing for this purpose: the FTL's view of free space is what matters,
   not erasing the NAND.)
3. Volume deleted, drive set offline
4. **VD on the H700 created at 700 GB**, leaving ~300 GB of the LBA range
   permanently unaddressed.

Total over-provisioning: **~36 %**, factory OP included.

### What was attempted and did not work

Firmware `M3CR046` and Flex Capacity were both intended and neither was
possible: **the MX500 exists in two hardware revisions**, and on this unit
Storage Executive offers only Momentum Cache — no firmware flash, no
capacity adjustment. Worth knowing before buying another MX500 for this
role: check the revision if the vendor tooling matters.

Neither turned out to be necessary:

- **Firmware** — `M3CR023` is stable and the drive is healthy. Nice to
  have, not a prerequisite for a writethrough cache device.
- **Flex Capacity** — an under-sized VD achieves the same result. Flex
  Capacity has the drive enforce the reservation via ATA Set Max Address
  (equivalent to `hdparm -N p1367187500`); an under-sized VD has the
  controller enforce it. Since nothing else will ever write to this
  drive, the outcome is identical: those LBAs are never addressed, so the
  FTL keeps the blocks as spare.
- **Momentum Cache** — deliberately left off. It is a RAM writeback cache
  in the Windows driver, the same idea as Yellowstone but with the safety
  trade this project refuses to make (`cache_mode=writeback` is rejected
  at config load since 0.4.2-alpha).

**The step that could not have been skipped is the TRIM.** Shrinking the
addressable range frees nothing by itself — the FTL must first know those
blocks hold no valid data. Without step 2, a smaller VD reserves nothing
at all. And step 2 was only possible while the drive was on a plain SATA
port, because the H700 does not pass TRIM through a RAID volume.

## Registered prediction

Written before any measurement, to be scored honestly.

> After one month in service as an L2 cache, **interval** write
> amplification — computed between two readings as
> `1 + ΔF8/ΔF7` — will be **below 2.0**, against a lifetime figure of
> 3.68×.

If it holds, the TRIM and Flex Capacity did their job and there is a
measured number to show for it. If it does not, then the workload itself
generates that amplification and 36 % over-provisioning was not enough —
which is equally worth knowing before buying a drive for this role again.

Expected write volume in the new role, from the Field Test #8 workload
(promotions ~2.85 MiB/s, plus write hits once the cache is large):

| Load | Per year | Remaining TBW lasts |
|---|---|---|
| 250 GB/day | 91 TB | ~3.8 years |
| 400 GB/day | 146 TB | ~2.4 years |

For scale: the drive wrote 12 TB in 4.7 years. In this role it will write
that much in about a month.

## Reading SMART once the drive is behind the H700

An earlier assumption in this project was that SMART would be largely
inaccessible behind the RAID controller. That is wrong — `smartctl`
speaks to drives behind LSI/MegaRAID controllers directly:

```sh
smartctl -a -d megaraid,N /dev/sda
```

`N` is the physical drive's Device ID from
`MegaCli64 -PDList -aALL | grep "Device Id"`. All attributes are
available, so the readings below can be taken without removing the drive.

## Subsequent readings

| Date | `F6` sectors | `F7` | `F8` | interval WAF | `AD` | `CA` | Note |
|---|---|---|---|---|---|---|---|
| 2026-08-17 | 23,484,508,511 | 396,011,197 | 1,061,388,586 | — | 57 | 97 % | baseline, pre-install |
| | | | | | | | |
| | | | | | | | |

Interval WAF between two rows: `1 + (F8₂ − F8₁) / (F7₂ − F7₁)`
