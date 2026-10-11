"""轻量 DEX 解析工具。

只实现本项目需要的最小能力：定位 class_def、读出类里的全部方法
(method_idx / access_flags / code_item 偏移) 以及解析方法签名。

改这些字段周围的字节会破坏 dex 头部的两个校验值，所以什么时候重算、
按什么顺序重算，见 fix_checksum()。
"""

from __future__ import annotations

import struct


class DexError(Exception):
    pass


class Dex:
    """只支持标准（小端）dex 容器；Android 上见到的基本都是这种。"""

    def __init__(self, data: bytes):
        self.d = bytearray(data)
        if bytes(self.d[:4]) != b"dex\n":
            raise DexError("not a dex file")
        h = self.d
        self.str_sz, self.str_off = struct.unpack_from("<II", h, 0x38)
        self.typ_sz, self.typ_off = struct.unpack_from("<II", h, 0x40)
        self.pro_sz, self.pro_off = struct.unpack_from("<II", h, 0x48)
        self.fld_sz, self.fld_off = struct.unpack_from("<II", h, 0x50)
        self.mtd_sz, self.mtd_off = struct.unpack_from("<II", h, 0x58)
        self.cls_sz, self.cls_off = struct.unpack_from("<II", h, 0x60)

    # ---------- 原语 ----------

    def uleb(self, off: int):
        r = 0
        s = 0
        while True:
            b = self.d[off]
            off += 1
            r |= (b & 0x7F) << s
            if not b & 0x80:
                break
            s += 7
        return r, off

    def string(self, idx: int) -> str:
        off, = struct.unpack_from("<I", self.d, self.str_off + idx * 4)
        _, p = self.uleb(off)
        e = self.d.index(b"\x00", p)
        return bytes(self.d[p:e]).decode("utf-8", "replace")

    def type(self, idx: int) -> str:
        i, = struct.unpack_from("<I", self.d, self.typ_off + idx * 4)
        return self.string(i)

    def method(self, idx: int):
        """-> (class descriptor, proto_idx, method name)"""
        ci, pi, ni = struct.unpack_from("<HHi", self.d, self.mtd_off + idx * 8)
        return self.type(ci), pi, self.string(ni)

    def proto(self, idx: int):
        """-> (shorty, return type, [param types])"""
        si, ri, po = struct.unpack_from("<III", self.d, self.pro_off + idx * 12)
        params = []
        if po:
            n, = struct.unpack_from("<I", self.d, po)
            p = po + 4
            for _ in range(n):
                ti, = struct.unpack_from("<H", self.d, p)
                p += 2
                params.append(self.type(ti))
        return self.string(si), self.type(ri), params

    # ---------- 类与方法 ----------

    def find_class(self, descriptor: str):
        for i in range(self.cls_sz):
            off = self.cls_off + i * 32
            ci, _af, _sup, _itf, _sf, _ann, cdo, _svo = struct.unpack_from("<IIIIIIII", self.d, off)
            if self.type(ci) == descriptor:
                return i, cdo
        return None, None

    def class_methods(self, class_def_off: int):
        """-> [(method_idx, access_flags, code_off), ...]"""
        if class_def_off == 0:
            return []
        p = class_def_off
        static_fields = self.uleb(p)[0]
        p = self.uleb(p)[1]
        instance_fields = self.uleb(p)[0]
        p = self.uleb(p)[1]
        direct_methods = self.uleb(p)[0]
        p = self.uleb(p)[1]
        virtual_methods = self.uleb(p)[0]
        p = self.uleb(p)[1]

        for _ in range(static_fields + instance_fields):
            _, p = self.uleb(p)  # field_idx_diff
            _, p = self.uleb(p)  # access_flags

        out = []
        for count in (direct_methods, virtual_methods):
            prev = 0
            for _ in range(count):
                diff, p = self.uleb(p)
                acc, p = self.uleb(p)
                code, p = self.uleb(p)
                prev += diff
                out.append((prev, acc, code))
        return out

    def signatures(self, class_def_off: int):
        """-> [(name, return_type, params, code_off, access_flags), ...]"""
        rows = []
        for mi, acc, code in self.class_methods(class_def_off):
            _cls, pi, name = self.method(mi)
            _shorty, ret, params = self.proto(pi)
            rows.append((name, ret, params, code, acc))
        return rows


def fix_checksum(data: bytearray) -> bytearray:
    """按 ART 要求重写 dex 头部的 signature / checksum。

    header.checksum 覆盖 [0x0c:] 也就是**包含** signature 字段，
    header.signature 覆盖 [0x20:] 也就是**排除** checksum 和 signature 自己。
    所以必须先在 0x0c 写 signature、再算 checksum，顺序反了 ART 会直接拒载整个 dex。
    """
    import hashlib
    import zlib

    struct.pack_into("<20s", data, 0x0C, hashlib.sha1(bytes(data[0x20:])).digest())
    struct.pack_into("<I", data, 0x08, zlib.adler32(bytes(data[0x0C:])) & 0xFFFFFFFF)
    return data
