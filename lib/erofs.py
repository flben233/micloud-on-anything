import struct, sys
import lz4.block

# z_advise bits
ADV_COMPACTED_2B = 0x0001
ADV_BIG_PCLUSTER_1 = 0x0002
ADV_BIG_PCLUSTER_2 = 0x0004
ADV_INLINE_PCLUSTER = 0x0008      # tailpacking: compressed tail inline after indexes
ADV_INTERLACED_PCLUSTER = 0x0010
ADV_FRAGMENT_PCLUSTER = 0x0020    # tail (or whole file) stored in packed inode

# lcluster types
T_PLAIN, T_HEAD1, T_NONHEAD, T_HEAD2 = 0, 1, 2, 3
CBLKCNT = 1 << 11                 # Z_EROFS_LI_D0_CBLKCNT
LI_PARTIAL_REF = 1 << 15

# map flags
F_META, F_MAPPED, F_ENCODED, F_FULL, F_FRAGMENT, F_PARTIAL = 1, 2, 4, 8, 16, 32

# algorithm formats
ALG_LZ4, ALG_LZMA, ALG_DEFLATE, ALG_ZSTD = 0, 1, 2, 3
ALG_SHIFTED, ALG_INTERLACED = 4, 5

class Erofs:
    def __init__(self, path):
        self.f = open(path, 'rb')
        sb = self.f.read(1024 + 144)[1024:]
        magic, = struct.unpack_from('<I', sb, 0)
        assert magic == 0xE0F5E1E2, hex(magic)
        self.blkszbits = sb[12]
        self.blksz = 1 << self.blkszbits
        self.rootnid, = struct.unpack_from('<H', sb, 14)
        self.meta_blkaddr, = struct.unpack_from('<I', sb, 40)
        self.feature_incompat, = struct.unpack_from('<I', sb, 80)
        self.u1, = struct.unpack_from('<H', sb, 84)
        self.packed_nid, = struct.unpack_from('<Q', sb, 96)
        self._packed = None

    def read_at(self, off, n):
        self.f.seek(off)
        return self.f.read(n)

    def read_blk(self, blk, n=1):
        return self.read_at(blk * self.blksz, self.blksz * n)

    def inode_meta_off(self, nid):
        slotbits = self.blkszbits - 5
        blkaddr = self.meta_blkaddr + (nid >> slotbits)
        slotoff = (nid & ((1 << slotbits) - 1)) * 32
        return blkaddr * self.blksz + slotoff

    def read_inode(self, nid):
        off = self.inode_meta_off(nid)
        self.f.seek(off)
        data = self.f.read(64)
        i_format, = struct.unpack_from('<H', data, 0)
        version = i_format & 1
        datalayout = (i_format >> 1) & 7
        xattr_icount, = struct.unpack_from('<H', data, 2)
        i_mode, = struct.unpack_from('<H', data, 4)
        i_nb, = struct.unpack_from('<H', data, 6)
        if version == 0:
            i_size, = struct.unpack_from('<I', data, 8)
            i_u, = struct.unpack_from('<I', data, 16)  # compact: size@8, mtime@12, i_u@16
            isize = 32
        else:
            i_size, = struct.unpack_from('<Q', data, 8)
            i_u, = struct.unpack_from('<I', data, 16)
            isize = 64
        xattr_size = 0 if xattr_icount == 0 else 12 + 4 * (xattr_icount - 1)
        return dict(nid=nid, version=version, datalayout=datalayout, mode=i_mode,
                    size=i_size, i_u=i_u, i_nb=i_nb, meta_off=off, isize=isize,
                    xattr_size=xattr_size)

    # ---------- compressed file support (from erofs-utils zmap.c/decompress.c) ----------

    def z_fill_lazy(self, ino):
        if 'z_advise' in ino:
            return
        pos = (ino['meta_off'] + ino['isize'] + ino['xattr_size'] + 7) & ~7
        h = self.read_at(pos, 8)
        if h[7] & 0x80:  # fragment inode: whole file in packed inode
            ino['z_advise'] = ADV_FRAGMENT_PCLUSTER
            ino['fragmentoff'] = struct.unpack_from('<Q', h, 0)[0] ^ (1 << 63)
            ino['tailhead_lcn'] = 0
            ino['idata_size'] = 0
            return
        advise, = struct.unpack_from('<H', h, 4)
        ino['z_advise'] = advise
        ino['lclusterbits'] = self.blkszbits + (h[7] & 15)
        ino['algtype'] = (h[6] & 15, h[6] >> 4)
        ino['idata_size'] = 0
        if advise & ADV_FRAGMENT_PCLUSTER:
            ino['fragmentoff'], = struct.unpack_from('<I', h, 0)
        elif advise & ADV_INLINE_PCLUSTER:
            ino['idata_size'], = struct.unpack_from('<H', h, 2)
        if ino['datalayout'] == 3:
            if (not (advise & ADV_BIG_PCLUSTER_1)) != (not (advise & ADV_BIG_PCLUSTER_2)):
                raise ValueError('big pcluster head1/2 inconsistent nid %d' % ino['nid'])
        ino['tailhead_lcn'] = None
        if ino['idata_size'] or (advise & ADV_FRAGMENT_PCLUSTER):
            self.z_map_fo(ino, ino['size'] - 1, findtail=True)

    def _decode_bits(self, pack, bitpos, lobits):
        v = int.from_bytes(pack[bitpos >> 3:(bitpos >> 3) + 4], 'little') >> (bitpos & 7)
        return v & ((1 << lobits) - 1), (v >> lobits) & 3

    def z_load_compact(self, ino, m, lcn):
        ebase = 8 + ((ino['meta_off'] + ino['isize'] + ino['xattr_size'] + 7) & ~7)
        lcbits = ino['lclusterbits']
        totalidx = (ino['size'] + self.blksz - 1) >> self.blkszbits
        advise = ino['z_advise']
        if lcn >= totalidx or lcbits > 14:
            raise ValueError('lcn %d >= totalidx %d or lcbits %d' % (lcn, totalidx, lcbits))
        m['lcn'] = lcn
        c4b_init = ((32 - ebase % 32) // 4) & 7
        c2b = 0
        if (advise & ADV_COMPACTED_2B) and c4b_init < totalidx:
            c2b = ((totalidx - c4b_init) // 16) * 16
        pos = ebase
        shift = 2
        l = lcn
        if l >= c4b_init:
            pos += c4b_init * 4
            l -= c4b_init
            if l < c2b:
                shift = 1
            else:
                pos += c2b * 2
                l -= c2b
        pos += l << shift
        if shift == 2 and lcbits <= 14:
            vcnt = 2
        elif shift == 1 and lcbits <= 12:
            vcnt = 16
        else:
            raise NotImplementedError('compacted lcluster lcbits=%d shift=%d' % (lcbits, shift))
        packsize = vcnt << shift
        packoff = pos & ~(packsize - 1)
        m['nextpackoff'] = packoff + packsize
        lobits = max(lcbits, 12)
        encodebits = ((packsize - 4) * 8) // vcnt
        pack = self.read_at(packoff, packsize)
        i = (pos - packoff) >> shift
        lo, t = self._decode_bits(pack, encodebits * i, lobits)
        m['type'] = t
        big_pc = advise & ADV_BIG_PCLUSTER_1
        if t == T_NONHEAD:
            m['clusterofs'] = 1 << lcbits
            if lo & CBLKCNT:
                if not big_pc:
                    raise ValueError('CBLKCNT without big pcluster nid %d' % ino['nid'])
                m['cblks'] = lo & ~CBLKCNT
                m['delta0'] = 1
                return
            if i + 1 != vcnt:
                m['delta0'] = lo
                return
            # last entry in pack stores delta[1]; derive delta[0] from previous
            lo2, t2 = self._decode_bits(pack, encodebits * (i - 1), lobits)
            if t2 != T_NONHEAD:
                lo2 = 0
            elif lo2 & CBLKCNT:
                lo2 = 1
            m['delta0'] = lo2 + 1
            return
        m['clusterofs'] = lo
        m['delta0'] = 0
        if not big_pc:
            nblk = 1
            while i > 0:
                i -= 1
                lo2, t2 = self._decode_bits(pack, encodebits * i, lobits)
                if t2 == T_NONHEAD:
                    i -= lo2
                if i >= 0:
                    nblk += 1
        else:
            nblk = 0
            while i > 0:
                i -= 1
                lo2, t2 = self._decode_bits(pack, encodebits * i, lobits)
                if t2 == T_NONHEAD:
                    if lo2 & CBLKCNT:
                        i -= 1
                        nblk += lo2 & ~CBLKCNT
                        continue
                    if lo2 <= 1:
                        raise ValueError('bad big pcluster d0 nid %d' % ino['nid'])
                    i -= lo2 - 2
                    continue
                nblk += 1
        base, = struct.unpack_from('<I', pack, packsize - 4)
        m['pblk'] = base + nblk

    def z_load_full(self, ino, m, lcn):
        base = (ino['meta_off'] + ino['isize'] + ino['xattr_size'] + 7) & ~7
        pos = base + 16 + lcn * 8  # FULL_INDEX_START = round_up8(end)+8(header)+8
        di = self.read_at(pos, 8)
        advise, clusterofs = struct.unpack_from('<HH', di, 0)
        m['lcn'] = lcn
        m['nextpackoff'] = pos + 8
        t = advise & 3
        m['type'] = t
        if t == T_NONHEAD:
            d0, d1 = struct.unpack_from('<HH', di, 4)
            m['clusterofs'] = 1 << ino['lclusterbits']
            if d0 & CBLKCNT:
                if not (ino['z_advise'] & (ADV_BIG_PCLUSTER_1 | ADV_BIG_PCLUSTER_2)):
                    raise ValueError('CBLKCNT w/o big pcluster nid %d' % ino['nid'])
                m['cblks'] = d0 & ~CBLKCNT
                d0 = 1
            m['delta0'] = d0
            m['delta1'] = d1
        else:
            m['partialref'] = bool(advise & LI_PARTIAL_REF)
            m['clusterofs'] = clusterofs
            m['pblk'], = struct.unpack_from('<I', di, 4)

    def z_load_from_disk(self, ino, m, lcn):
        if ino['datalayout'] == 3:
            self.z_load_compact(ino, m, lcn)
        else:
            self.z_load_full(ino, m, lcn)
        if m['type'] > 3:
            raise ValueError('unknown type %d @ lcn %d nid %d' % (m['type'], lcn, ino['nid']))
        if m['type'] != T_NONHEAD and m['clusterofs'] >= (1 << ino['lclusterbits']):
            raise ValueError('bad clusterofs @ lcn %d nid %d' % (lcn, ino['nid']))

    def z_lookback(self, ino, m, lookback):
        while m['lcn'] >= lookback:
            lcn = m['lcn'] - lookback
            self.z_load_from_disk(ino, m, lcn)
            if m['type'] == T_NONHEAD:
                lookback = m['delta0']
                if not lookback:
                    break
                continue
            m['headtype'] = m['type']
            m['la'] = (lcn << ino['lclusterbits']) | m['clusterofs']
            return
        raise ValueError('bogus lookback %d @ lcn %d nid %d' % (lookback, m['lcn'], ino['nid']))

    def z_compressedlen(self, ino, m, initial_lcn):
        advise = ino['z_advise']
        big1 = advise & ADV_BIG_PCLUSTER_1
        big2 = advise & ADV_BIG_PCLUSTER_2
        lcn = m['lcn'] + 1
        if ((m['headtype'] == T_HEAD1 and not big1) or
                (m['headtype'] in (T_PLAIN, T_HEAD2) and not big2) or
                (lcn << ino['lclusterbits']) >= ino['size']):
            m['cblks'] = 1
        if m['cblks']:
            return m['cblks'] * self.blksz
        self.z_load_from_disk(ino, m, lcn)
        if m['type'] == T_NONHEAD:
            if m['delta0'] != 1:
                raise ValueError('bogus CBLKCNT @ lcn %d nid %d' % (lcn, ino['nid']))
            if m['cblks']:
                return m['cblks'] * self.blksz
        elif m['type'] < 4:
            return self.blksz
        raise ValueError('no CBLKCNT @ lcn %d nid %d' % (lcn, ino['nid']))

    def z_map_fo(self, ino, la, findtail=False):
        self.z_fill_lazy(ino)
        advise = ino['z_advise']
        fragment = advise & ADV_FRAGMENT_PCLUSTER
        ztp = ino.get('idata_size', 0)
        lcbits = ino['lclusterbits']
        size = ino['size']
        m = {'cblks': 0, 'partialref': False, 'headtype': None}
        ofs = size - 1 if findtail else la
        if fragment and not findtail and not ino['tailhead_lcn']:
            return dict(la=0, llen=size, pa=0, plen=0, algfmt=None,
                        flags=F_MAPPED | F_FRAGMENT, lcn=0)
        initial_lcn = ofs >> lcbits
        endoff = ofs & ((1 << lcbits) - 1)
        self.z_load_from_disk(ino, m, initial_lcn)
        if findtail and ztp:
            ino['z_fragmentoff'] = m['nextpackoff']
        flags = F_MAPPED | F_ENCODED
        end = (m['lcn'] + 1) << lcbits
        la_out = None
        if m['type'] in (T_PLAIN, T_HEAD1, T_HEAD2):
            if endoff >= m['clusterofs']:
                m['headtype'] = m['type']
                la_out = (m['lcn'] << lcbits) | m['clusterofs']
                if ztp and end > size:
                    end = size
            else:
                if not m['lcn']:
                    raise ValueError('invalid lcn 0 nid %d' % ino['nid'])
                end = (m['lcn'] << lcbits) | m['clusterofs']
                flags |= F_FULL
                m['delta0'] = 1
                self.z_lookback(ino, m, m['delta0'])
                la_out = m['la']
        elif m['type'] == T_NONHEAD:
            self.z_lookback(ino, m, m['delta0'])
            la_out = m['la']
        else:
            raise ValueError('unknown type %d' % m['type'])
        if m['partialref']:
            flags |= F_PARTIAL
        llen = end - la_out
        if findtail:
            ino['tailhead_lcn'] = m['lcn']
            if fragment and ino['datalayout'] == 1:
                ino['fragmentoff'] |= m['pblk'] << 32
        pa = plen = algfmt = None
        if ztp and m['lcn'] == ino['tailhead_lcn']:
            flags |= F_META
            pa = ino['z_fragmentoff']
            plen = ztp
            if (pa % self.blksz) + plen > self.blksz:
                raise ValueError('invalid tailpacking size nid %d' % ino['nid'])
        elif fragment and m['lcn'] == ino['tailhead_lcn']:
            flags = F_MAPPED | F_FRAGMENT
        else:
            pa = m['pblk'] * self.blksz
            plen = self.z_compressedlen(ino, m, initial_lcn)
        if m['headtype'] == T_PLAIN:
            if llen > plen:
                raise ValueError('llen>plen PLAIN nid %d' % ino['nid'])
            algfmt = ALG_INTERLACED if (advise & ADV_INTERLACED_PCLUSTER) else ALG_SHIFTED
        elif m['headtype'] == T_HEAD2:
            algfmt = ino['algtype'][1]
        else:
            algfmt = ino['algtype'][0]
        return dict(la=la_out, llen=llen, pa=pa, plen=plen, algfmt=algfmt,
                    flags=flags, lcn=m['lcn'])

    def packed_read(self, length, pos):
        if self._packed is None:
            if not self.packed_nid:
                raise ValueError('packed inode missing')
            pino = self.read_inode(self.packed_nid)
            self._packed = self.read_file_data(pino)
        return self._packed[pos:pos + length]

    def read_compressed(self, ino):
        # kernel-style backward walk: mapping the last byte of each extent
        # yields the full extent length == natural LZ4 output size
        self.z_fill_lazy(ino)
        size = ino['size']
        out = bytearray(size)
        end = size
        while end > 0:
            mp = self.z_map_fo(ino, end - 1)
            estart = mp['la']
            if estart >= end:
                raise ValueError('bad extent la=%d >= end=%d nid %d' % (estart, end, ino['nid']))
            length = end - estart
            if not (mp['flags'] & F_MAPPED):
                out[estart:end] = bytes(length)  # hole
            elif mp['flags'] & F_FRAGMENT:
                out[estart:end] = self.packed_read(length, ino['fragmentoff'])
            else:
                raw = self.read_at(mp['pa'], mp['plen'])
                alg = mp['algfmt']
                if alg == ALG_INTERLACED:
                    rskip = estart % self.blksz
                    rp = min(self.blksz - rskip, length)
                    out[estart:end] = raw[rskip:rskip + rp] + raw[:length - rp]
                elif alg == ALG_SHIFTED:
                    if length > len(raw):
                        raise ValueError('SHIFTED overrun nid %d' % ino['nid'])
                    out[estart:end] = raw[:length]
                elif alg == ALG_LZ4:
                    margin = 0
                    while margin < len(raw) and raw[margin] == 0:
                        margin += 1
                    if margin >= len(raw):
                        raise ValueError('all-zero pcluster nid %d' % ino['nid'])
                    dec = lz4.block.decompress(raw[margin:], uncompressed_size=length)
                    if len(dec) != length:
                        raise ValueError('lz4 short decode %d != %d nid %d' % (len(dec), length, ino['nid']))
                    out[estart:end] = dec
                else:
                    raise NotImplementedError('algorithm %d nid %d' % (alg, ino['nid']))
            end = estart
        return bytes(out)

    # ---------- generic ----------

    def read_file_data(self, ino):
        size = ino['size']
        dl = ino['datalayout']
        if dl == 0:  # FLAT_PLAIN
            return self.read_blk(ino['i_u'], (size + self.blksz - 1) // self.blksz)[:size]
        if dl == 2:  # FLAT_INLINE
            tail = size % self.blksz
            full = size - tail
            out = b''
            if full:
                out = self.read_blk(ino['i_u'], full // self.blksz)
            self.f.seek(ino['meta_off'] + ino['isize'] + ino['xattr_size'])
            out += self.f.read(tail)
            return out
        if dl in (1, 3):  # COMPRESSED_FULL / COMPRESSED_COMPACT
            return self.read_compressed(ino)
        raise NotImplementedError('datalayout=%d not supported' % dl)

    def listdir(self, nid):
        ino = self.read_inode(nid)
        assert (ino['mode'] & 0xF000) == 0x4000, f'not a dir, mode={hex(ino["mode"])}'
        data = self.read_file_data(ino)
        entries = []
        pos = 0
        while pos < len(data):
            chunk = data[pos:pos + self.blksz]
            if len(chunk) < 12:
                break
            nameoff0, = struct.unpack_from('<H', chunk, 8)
            if nameoff0 < 12 or nameoff0 > len(chunk):
                break
            nde = nameoff0 // 12
            if nde == 0:
                break
            for k in range(nde):
                at = k * 12
                if at + 12 > len(chunk):
                    break
                dnid, nameoff, ftype = struct.unpack_from('<QHB', chunk, at)
                if k + 1 < nde:
                    noff_next, = struct.unpack_from('<H', chunk, (k + 1) * 12 + 8)
                    nm = chunk[nameoff:noff_next]
                else:
                    nm = chunk[nameoff:].split(b'\x00')[0]
                if nm:
                    entries.append((nm.decode('latin1'), dnid, ftype))
            pos += self.blksz
        return entries

    def walk(self, path):
        parts = [p for p in path.strip('/').split('/') if p]
        nid = self.rootnid
        cur = ''
        for p in parts:
            ents = self.listdir(nid)
            hit = [e for e in ents if e[0] == p]
            if not hit:
                raise FileNotFoundError(f'{p} not in {cur} ({[e[0] for e in ents[:15]]}...)')
            nid = hit[0][1]
            cur += '/' + p
        return nid

def main():
    img = sys.argv[1]
    cmd = sys.argv[2]
    e = Erofs(img)
    if cmd == 'ls':
        path = sys.argv[3] if len(sys.argv) > 3 else '/'
        nid = e.walk(path)
        for nm, dnid, ft in e.listdir(nid):
            print(f'{ft}  {nm}  nid={dnid}')
    elif cmd == 'stat':
        nid = e.walk(sys.argv[3])
        ino = e.read_inode(nid)
        e.z_fill_lazy(ino)
        print('nid=%d mode=%o size=%d datalayout=%d i_u=%d' %
              (ino['nid'], ino['mode'], ino['size'], ino['datalayout'], ino['i_u']))
        if 'z_advise' in ino:
            print('z_advise=0x%04x lclusterbits=%d algtype=%s' %
                  (ino['z_advise'], ino['lclusterbits'], ino['algtype']))
    elif cmd == 'extract':
        path = sys.argv[3]
        out = sys.argv[4]
        nid = e.walk(path)
        ino = e.read_inode(nid)
        data = e.read_file_data(ino)
        open(out, 'wb').write(data)
        extra = ''
        if 'z_advise' in ino:
            extra = ' z_advise=0x%04x lcbits=%d alg=%s' % (ino['z_advise'], ino['lclusterbits'], ino['algtype'])
        print(f'extracted {len(data)} bytes -> {out} (datalayout={ino["datalayout"]}{extra})')
    else:
        print('usage: erofs.py <img> ls|stat|extract <path> [out]')

if __name__ == '__main__':
    main()
