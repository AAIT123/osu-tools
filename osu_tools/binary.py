"""Guarded streaming primitives for osu!stable's little-endian binary files."""
import io
import struct

MAX_STRING = 16 * 1024 * 1024
MAX_COUNT = 10_000_000


class FormatError(ValueError):
    """An invalid or unsupported database layout."""


class Reader:
    """Read binary data from bytes or a buffered file, without an eager full read."""
    def __init__(self, source):
        self.f = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source

    def read(self, size: int) -> bytes:
        if size < 0:
            raise FormatError('Negative read size')
        b = self.f.read(size)
        if len(b) != size:
            raise FormatError(f'Truncated file: wanted {size} bytes at offset {self.f.tell()-len(b)}')
        return b

    def skip(self, size: int):
        # Consume to notice truncation (some streams seek past EOF without error).
        while size:
            size -= len(self.read(min(size, 65536)))

    def byte(self):
        return self.read(1)[0]

    def boolean(self):
        return self.byte() != 0

    def short(self):
        return struct.unpack('<H', self.read(2))[0]

    def int(self):
        return struct.unpack('<i', self.read(4))[0]

    def long(self):
        return struct.unpack('<q', self.read(8))[0]

    def single(self):
        return struct.unpack('<f', self.read(4))[0]

    def double(self):
        return struct.unpack('<d', self.read(8))[0]

    def count(self, limit=MAX_COUNT):
        value = self.int()
        if value < 0 or value > limit:
            raise FormatError(f'Invalid count {value} at offset {self.f.tell()}')
        return value

    def uleb128(self):
        n = 0
        for shift in range(0, 70, 7):
            b = self.byte()
            n |= (b & 0x7f) << shift
            if not b & 0x80:
                return n
        raise FormatError('Overlong ULEB128 integer')

    def string(self):
        marker = self.byte()
        if marker == 0:
            return None
        if marker != 0x0b:
            raise FormatError(f'Invalid string marker {marker:#x} at offset {self.f.tell()-1}')
        length = self.uleb128()
        if length > MAX_STRING:
            raise FormatError(f'Oversized string ({length} bytes)')
        return self.read(length).decode('utf-8')

    def eof(self):
        return not self.f.read(1)


class Writer:
    def __init__(self):
        self.parts = []

    def bytes(self):
        return b''.join(self.parts)

    def byte(self, v):
        self.parts.append(struct.pack('<B', v))

    def int(self, v):
        self.parts.append(struct.pack('<i', v))

    def string(self, s):
        if s is None:
            return self.byte(0)
        data = s.encode('utf-8')
        self.byte(0x0b)
        n = len(data)
        while n >= 0x80:
            self.byte((n & 0x7f) | 0x80)
            n >>= 7
        self.byte(n)
        self.parts.append(data)
