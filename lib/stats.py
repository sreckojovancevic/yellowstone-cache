#!/usr/bin/env python3

"""
Yellowstone Cache

Parser za `dmsetup status <name>` izlaz dm-cache target-a.
Format (dm-cache):

  start len cache metadata_block_size used_meta/total_meta
  cache_block_size used_cache/total_cache
  read_hits read_misses write_hits write_misses
  demotions promotions dirty ...features...

Ovaj modul samo parsira — ne izvršava komande i ne prikazuje ništa.
"""


def parse_dmsetup_status(text):
    """
    Parsiraj jednu liniju `dmsetup status` izlaza za cache target.

    Vraća dict sa statistikom ili None ako linija nije cache target.
    """

    fields = text.split()

    if len(fields) < 15 or fields[2] != "cache":
        return None

    def pair(value):
        used, total = value.split("/")
        return int(used), int(total)

    meta_used, meta_total = pair(fields[4])
    cache_used, cache_total = pair(fields[6])

    read_hits = int(fields[7])
    read_misses = int(fields[8])
    write_hits = int(fields[9])
    write_misses = int(fields[10])

    stats = {
        "metadata_block_size": int(fields[3]),
        "metadata_used": meta_used,
        "metadata_total": meta_total,
        "cache_block_size": int(fields[5]),
        "cache_used": cache_used,
        "cache_total": cache_total,
        "read_hits": read_hits,
        "read_misses": read_misses,
        "write_hits": write_hits,
        "write_misses": write_misses,
        "demotions": int(fields[11]),
        "promotions": int(fields[12]),
        "dirty": int(fields[13]),
        "mode": _find_mode(fields[14:]),
    }

    reads = read_hits + read_misses
    writes = write_hits + write_misses

    stats["read_hit_ratio"] = round(read_hits / reads, 4) if reads else 0.0
    stats["write_hit_ratio"] = round(write_hits / writes, 4) if writes else 0.0
    stats["cache_usage_percent"] = (
        round(100.0 * cache_used / cache_total, 2) if cache_total else 0.0
    )

    return stats


def _find_mode(features):
    """Pronađi cache mode među feature poljima."""

    for f in features:
        if f in ("writethrough", "writeback", "passthrough"):
            return f

    return "unknown"


if __name__ == "__main__":

    sample = (
        "0 209715200 cache 8 121/4096 128 512/8192 "
        "76 12 45 3 0 7 5 1 writethrough 2 migration_threshold 2048 "
        "smq 0 rw -"
    )

    from pprint import pprint
    pprint(parse_dmsetup_status(sample))
