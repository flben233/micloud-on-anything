#!/usr/bin/env python3
"""lpunpack: extract logical partitions (system/vendor/product/...) from a raw super.img.

Implements liblp metadata format parsing (system/core/fs_mgr/liblp/metadata_format.h).
Validates extent units (512B sectors vs 4KiB blocks, v1.2+) by bounds-checking.
"""
import os
import struct
import sys

GEOM_OFFSET = 4096
GEOM_MAGIC = 0x616C4467
# layout: [0:4096] padding | [4096:8192] primary geometry | [8192:12288] backup geometry | [12288:...] primary metadata slots
META_OFFSET = 4096 * 3
META_MAGIC = 0x414C5030
LP_SECTOR = 512

TARGET_TYPE_LINEAR = 0
TARGET_TYPE_ZERO = 1


class Reader:
    def __init__(self, data: bytes):
        self.b = data
        self.o = 0

    def take(self, n: int) -> bytes:
        d = self.b[self.o:self.o + n]
        self.o += n
        return d

    def unpack(self, fmt: str):
        v = struct.unpack_from(fmt, self.b, self.o)
        self.o += struct.calcsize(fmt)
        return v


def main(superfile: str, outdir: str) -> None:
    f = open(superfile, "rb")
    super_size = os.fstat(f.fileno()).st_size

    # ---- geometry ----
    f.seek(GEOM_OFFSET)
    g = f.read(52)
    gmagic, g_struct_size = struct.unpack_from("<II", g, 0)
    assert gmagic == GEOM_MAGIC, f"bad geometry magic {gmagic:#x}"
    metadata_max_size, metadata_slot_count, logical_block_size = struct.unpack_from("<III", g, 40)
    print(f"geometry: metadata_max_size={metadata_max_size} slots={metadata_slot_count} logical_blk={logical_block_size}")

    # ---- primary metadata (slot 0) ----
    f.seek(META_OFFSET)
    meta = f.read(metadata_max_size)
    mmagic, major, minor, header_size = struct.unpack_from("<IHHI", meta, 0)
    assert mmagic == META_MAGIC, f"bad metadata magic {mmagic:#x}"
    tables_size, = struct.unpack_from("<I", meta, 44)
    print(f"metadata: v{major}.{minor} header_size={header_size} tables_size={tables_size}")

    # descriptors start at byte 80 (fixed header), each 12 bytes
    ndesc = (header_size - 80) // 12
    assert ndesc >= 3, f"weird descriptor count {ndesc}"
    descs = []
    for i in range(ndesc):
        off, num, esz = struct.unpack_from("<III", meta, 80 + 12 * i)
        descs.append((off, num, esz))
        print(f"  descriptor[{i}]: off={off} num={num} entry_size={esz}")

    tables_base = header_size  # tables region offset within metadata blob
    part_off, part_num, part_esz = descs[0]
    ext_off, ext_num, ext_esz = descs[1]
    grp_off, grp_num, grp_esz = descs[2]

    partitions = []
    for i in range(part_num):
        base = tables_base + part_off + i * part_esz
        name, attributes, first_extent, num_extents, group_index = struct.unpack_from(
            "<36sIIII", meta, base)
        partitions.append((name.split(b"\0")[0].decode(), attributes, first_extent, num_extents))

    extents = []
    for i in range(ext_num):
        base = tables_base + ext_off + i * ext_esz
        # struct LpMetadataExtent (packed, 24 bytes):
        # u64 num_sectors | u32 target_type | u64 target_data | u32 target_source
        num_sectors, target_type, target_data, target_source = struct.unpack_from(
            "<QIQI", meta, base)
        extents.append((num_sectors, target_type, target_data, target_source))

    # ---- unit detection + overlap validation ----
    def try_unit(unit: int) -> bool:
        used = []
        for _, _, first_extent, num_extents in partitions:
            for e in extents[first_extent:first_extent + num_extents]:
                nsec, ttype, tdata, tsrc = e
                if ttype != TARGET_TYPE_LINEAR:
                    continue
                if tsrc != 0:
                    return False  # multi-device super unsupported
                start = tdata * unit
                end = start + nsec * unit
                if end > super_size:
                    return False
                used.append((start, end))
        used.sort()
        for i in range(1, len(used)):
            if used[i][0] < used[i - 1][1]:
                return False  # overlapping extents -> wrong unit/parsing
        return True

    unit = LP_SECTOR
    if not try_unit(unit):
        assert try_unit(4096), "extent unit detection failed (neither 512 nor 4096 in-bounds)"
        unit = 4096
        print("NOTE: extents appear to use 4096-byte units (v1.2 4KiB logical blocks)")
    print(f"extent unit = {unit} bytes")

    # ---- extract ----
    os.makedirs(outdir, exist_ok=True)
    for name, attributes, first_extent, num_extents in partitions:
        if not name:
            continue
        total = sum(e[0] for e in extents[first_extent:first_extent + num_extents]) * unit
        print(f"partition {name}: {num_extents} extents, {total} bytes ({total/2**30:.2f} GiB)")
        outpath = os.path.join(outdir, name + ".img")
        with open(outpath, "wb") as out:
            for nsec, ttype, tdata, tsrc in extents[first_extent:first_extent + num_extents]:
                out_len = nsec * unit
                if ttype == TARGET_TYPE_ZERO:
                    out.seek(out.tell() + out_len)
                    continue
                assert ttype == TARGET_TYPE_LINEAR, f"unexpected target type {ttype}"
                f.seek(tdata * unit)
                left = out_len
                while left > 0:
                    n = min(left, 1 << 23)
                    d = f.read(n)
                    assert len(d) == n
                    out.write(d)
                    left -= n
        print(f"  -> {outpath}")
    f.close()
    print("done")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
