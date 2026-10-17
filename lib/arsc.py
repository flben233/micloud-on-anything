from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass
class Pool:
    strings: list[str]
    flags: int
    raw_styles: bytearray | None
    style_offsets: list[int]


def parse_pool(data: bytes, offset: int) -> Pool:
    typ, header_size, size = struct.unpack_from("<HHI", data, offset)
    if typ != 0x0001:
        raise ValueError(f"not a string pool at {offset:#x}: {typ:#x}")
    count, style_count, flags, strings_start, styles_start = struct.unpack_from("<IIIII", data, offset + 8)
    utf8 = bool(flags & 0x100)
    base = offset + strings_start
    strings: list[str] = []
    for i in range(count):
        string_offset = struct.unpack_from("<I", data, offset + 28 + i * 4)[0]
        p = base + string_offset
        if not utf8:
            n = struct.unpack_from("<H", data, p)[0]
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", data, p + 2)[0]
                p += 4
            else:
                p += 2
            strings.append(data[p:p + n * 2].decode("utf-16-le", "replace"))
        else:
            def read_len(pos: int) -> tuple[int, int]:
                a = data[pos]
                if a & 0x80:
                    return ((a & 0x7F) << 8) | data[pos + 1], pos + 2
                return a, pos + 1

            _, p = read_len(p)
            n, p = read_len(p)
            strings.append(data[p:p + n].decode("utf-8", "replace"))
    raw_styles = None
    style_offsets: list[int] = []
    if style_count:
        style_offsets = [struct.unpack_from("<I", data, offset + 28 + count * 4 + i * 4)[0] for i in range(style_count)]
        raw_styles = bytearray(data[offset + styles_start:offset + size])
    return Pool(strings, flags, raw_styles, style_offsets)


def build_pool(strings: list[str], raw_styles: bytearray | None, style_offsets: list[int]) -> bytes:
    count = len(strings)
    style_count = len(style_offsets) if raw_styles else 0
    blob = bytearray()
    offsets: list[int] = []
    for value in strings:
        offsets.append(len(blob))
        encoded = value.encode("utf-8")
        utf16_length = len(value.encode("utf-16-le")) // 2

        def write_len(n: int) -> None:
            if n > 0x7F:
                blob.append((n >> 8) | 0x80)
                blob.append(n & 0xFF)
            else:
                blob.append(n)

        write_len(utf16_length)
        write_len(len(encoded))
        blob += encoded
        blob.append(0)
    while len(blob) % 4:
        blob.append(0)
    style_blob = bytes(raw_styles) if raw_styles else b""
    strings_start = 28 + 4 * count + 4 * style_count
    styles_start = strings_start + len(blob) if style_count else 0
    total = styles_start + len(style_blob) if style_count else strings_start + len(blob)
    out = bytearray(struct.pack("<HHIIIIII", 0x0001, 28, total, count, style_count, 0x100, strings_start, styles_start))
    for value in offsets:
        out += struct.pack("<I", value)
    for value in style_offsets:
        out += struct.pack("<I", value)
    out += blob
    out += style_blob
    if len(out) != total:
        raise ValueError("bad string pool size")
    return bytes(out)


def find_packages(data: bytes) -> list[tuple[int, int, int]]:
    header_size = struct.unpack_from("<H", data, 2)[0]
    offset = header_size
    result: list[tuple[int, int, int]] = []
    while offset + 8 <= len(data):
        chunk_type, _, chunk_size = struct.unpack_from("<HHI", data, offset)
        if chunk_type == 0x0200:
            package_id = struct.unpack_from("<I", data, offset + 8)[0]
            result.append((offset, chunk_size, package_id))
        if chunk_size == 0:
            break
        offset += chunk_size
    return result


def walk_entries(chunk: bytes, offset: int):
    flags = chunk[offset + 9]
    entry_count, entries_start = struct.unpack_from("<II", chunk, offset + 12)
    header_size = struct.unpack_from("<H", chunk, offset + 2)[0]
    header_end = offset + header_size
    if flags == 0x2:
        for i in range(entry_count):
            value = struct.unpack_from("<H", chunk, header_end + i * 2)[0]
            if value == 0xFFFF:
                continue
            yield offset + entries_start + value * 4, False, True
    elif flags == 0x1:
        for i in range(entry_count):
            value = struct.unpack_from("<I", chunk, header_end + i * 4)[0]
            entry_offset = offset + entries_start + (value >> 16) * 4
            entry_size, entry_flags = struct.unpack_from("<HH", chunk, entry_offset)
            yield entry_offset, bool(entry_flags & 1), False
    else:
        raise ValueError(f"unsupported type flags {flags:#x} at {offset}")


def remap_package(chunk: bytes, delta: int) -> tuple[bytes, int, int]:
    buf = bytearray(chunk)
    header_size = struct.unpack_from("<H", chunk, 2)[0]
    offset = header_size
    remapped = 0
    values = 0
    while offset + 8 <= len(chunk):
        chunk_type, _, chunk_size = struct.unpack_from("<HHI", chunk, offset)
        if chunk_type == 0x0201:
            for entry_offset, is_complex, is_compact in walk_entries(chunk, offset):
                if is_complex:
                    count = struct.unpack_from("<I", chunk, entry_offset + 12)[0]
                    for m in range(count):
                        map_offset = entry_offset + 16 + m * 12
                        values += 1
                        if chunk[map_offset + 7] == 0x03:
                            old = struct.unpack_from("<I", chunk, map_offset + 8)[0]
                            struct.pack_into("<I", buf, map_offset + 8, old + delta)
                            remapped += 1
                elif is_compact:
                    values += 1
                    if chunk[entry_offset + 3] == 0x03:
                        old = struct.unpack_from("<I", chunk, entry_offset + 4)[0]
                        struct.pack_into("<I", buf, entry_offset + 4, old + delta)
                        remapped += 1
                else:
                    values += 1
                    if chunk[entry_offset + 11] == 0x03:
                        old = struct.unpack_from("<I", chunk, entry_offset + 12)[0]
                        struct.pack_into("<I", buf, entry_offset + 12, old + delta)
                        remapped += 1
        if chunk_size == 0:
            break
        offset += chunk_size
    return bytes(buf), remapped, values


def verify_pool(data: bytes, limits: dict[int, int]) -> list[str]:
    problems: list[str] = []
    strings = parse_pool(data, struct.unpack_from("<H", data, 2)[0]).strings
    for offset, chunk_size, package_id in find_packages(data):
        chunk = data[offset:offset + chunk_size]
        header_size = struct.unpack_from("<H", chunk, 2)[0]
        offset2 = header_size
        bad = 0
        total = 0
        while offset2 + 8 <= len(chunk):
            chunk_type, _, size2 = struct.unpack_from("<HHI", chunk, offset2)
            if chunk_type == 0x0201:
                for entry_offset, is_complex, is_compact in walk_entries(chunk, offset2):
                    targets = []
                    if is_complex:
                        count = struct.unpack_from("<I", chunk, entry_offset + 12)[0]
                        targets = [(entry_offset + 16 + m * 12 + 7, entry_offset + 16 + m * 12 + 8) for m in range(count)]
                    elif is_compact:
                        targets = [(entry_offset + 3, entry_offset + 4)]
                    else:
                        targets = [(entry_offset + 11, entry_offset + 12)]
                    for type_offset, data_offset in targets:
                        if chunk[type_offset] == 0x03:
                            total += 1
                            if struct.unpack_from("<I", chunk, data_offset)[0] >= limits[package_id]:
                                bad += 1
            if size2 == 0:
                break
            offset2 += size2
        if bad:
            problems.append(f"package {package_id:#x}: {bad}/{total} string indexes out of bounds")
    expected = max(limits.values()) if limits else 0
    if len(strings) != expected:
        problems.append(f"string count {len(strings)} != {expected}")
    return problems


def merge_apks(rtmc_arsc: bytes, extres_arsc: bytes, miuisys_arsc: bytes) -> tuple[bytes, dict[str, int]]:
    rtmc_pool = parse_pool(rtmc_arsc, struct.unpack_from("<H", rtmc_arsc, 2)[0])
    extres_pool = parse_pool(extres_arsc, struct.unpack_from("<H", extres_arsc, 2)[0])
    miuisys_pool = parse_pool(miuisys_arsc, struct.unpack_from("<H", miuisys_arsc, 2)[0])
    b = rtmc_pool.strings
    e = extres_pool.strings
    m = miuisys_pool.strings
    nb, ne = len(b), len(e)
    raw_styles = extres_pool.raw_styles
    if raw_styles is not None:
        for style_offset in extres_pool.style_offsets:
            p = style_offset
            while True:
                name = struct.unpack_from("<I", raw_styles, p)[0]
                if name == 0xFFFFFFFF:
                    break
                struct.pack_into("<I", raw_styles, p, name + nb)
                p += 12
    new_pool = build_pool(b + e + m, raw_styles, extres_pool.style_offsets)
    chunks: dict[tuple[str, int], bytes] = {}
    for tag, data in (("rtmc", rtmc_arsc), ("extres", extres_arsc), ("miuisys", miuisys_arsc)):
        for offset, size, package_id in find_packages(data):
            chunks[(tag, package_id)] = data[offset:offset + size]
    p60 = chunks[("rtmc", 0x60)]
    p11, r11, v11 = remap_package(chunks[("extres", 0x11)], nb)
    p12, r12, v12 = remap_package(chunks[("miuisys", 0x12)], nb + ne)
    new_arsc = bytearray(struct.pack("<HHII", 0x0002, 12, 0, 3))
    new_arsc += new_pool
    new_arsc += p60
    new_arsc += p11
    new_arsc += p12
    struct.pack_into("<I", new_arsc, 4, len(new_arsc))
    result = bytes(new_arsc)
    problems = verify_pool(result, {0x60: nb, 0x11: nb + ne, 0x12: nb + ne + len(m)})
    if problems:
        raise ValueError("; ".join(problems))
    return result, {"rtmc": len(b), "extres": len(e), "miuisys": len(m), "remap_11": r11, "remap_12": r12, "values_11": v11, "values_12": v12}
