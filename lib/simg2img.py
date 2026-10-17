#!/usr/bin/env python3
"""simg2img: convert Android sparse image to raw image. Streaming, low memory."""
import struct
import sys

SPARSE_MAGIC = 0xED26FF3A
CHUNK_TYPE_RAW = 0xCAC1
CHUNK_TYPE_FILL = 0xCAC2
CHUNK_TYPE_DONT_CARE = 0xCAC3
CHUNK_TYPE_CRC32 = 0xCAC4
BUF = 1 << 23  # 8 MiB


def main(src: str, dst: str) -> None:
    f = open(src, "rb")
    magic, major, minor, file_hdr_sz, chunk_hdr_sz, blk_sz, total_blks, total_chunks, crc32 = struct.unpack(
        "<IHHHHIIII", f.read(28)
    )
    assert magic == SPARSE_MAGIC, f"not sparse: {magic:#x}"
    if file_hdr_sz > 28:
        f.seek(file_hdr_sz - 28, 1)
    print(f"sparse v{major}.{minor} blk_sz={blk_sz} total_blks={total_blks} chunks={total_chunks}", flush=True)

    out = open(dst, "wb")
    out_off = 0
    raw_buf = (b"\x00" * 4) * 1  # placeholder
    for i in range(total_chunks):
        ch = f.read(chunk_hdr_sz)
        if len(ch) < chunk_hdr_sz:
            raise EOFError(f"chunk {i} header truncated")
        chunk_type, reserved, sz_blks, total_sz = struct.unpack("<HHII", ch[:12])
        data_sz = total_sz - chunk_hdr_sz
        out_len = sz_blks * blk_sz
        if chunk_type == CHUNK_TYPE_RAW:
            left = data_sz
            assert data_sz == out_len, f"chunk {i}: raw data_sz {data_sz} != out_len {out_len}"
            while left > 0:
                n = min(left, BUF)
                d = f.read(n)
                assert len(d) == n, f"chunk {i}: short read"
                out.write(d)
                left -= n
            out_off += out_len
        elif chunk_type == CHUNK_TYPE_FILL:
            pat = f.read(4)
            assert data_sz == 4
            fill = pat * (BUF // 4)
            written = 0
            while written < out_len:
                n = min(BUF, out_len - written)
                out.write(fill[:n])
                written += n
            out_off += out_len
        elif chunk_type == CHUNK_TYPE_DONT_CARE:
            if data_sz:
                f.seek(data_sz, 1)
            out.seek(out_off + out_len)  # leave hole (zeros)
            out_off += out_len
        elif chunk_type == CHUNK_TYPE_CRC32:
            assert data_sz == 4
            f.seek(data_sz, 1)
        else:
            raise ValueError(f"chunk {i}: unknown type {chunk_type:#x}")
    out.close()
    expected = total_blks * blk_sz
    assert out_off == expected, f"size mismatch: {out_off} != {expected}"
    print(f"OK raw_size={out_off} ({out_off/2**30:.2f} GiB)", flush=True)
    f.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
