#
# This file is part of mymc+, based on mymc by Ross Ridge.
#
# mymc+ is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# mymc+ is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mymc+.  If not, see <http://www.gnu.org/licenses/>.
#

"""Manipulate PS2 memory card images."""

import sys
import array
import struct
from errno import EACCES, ENOENT, EEXIST, ENOTDIR, EISDIR, EROFS, ENOTEMPTY,\
     ENOSPC, EIO, EBUSY
import fnmatch
import traceback

from .round import *
from .ps2mc_ecc import *
from .ps2mc_dir import *
#from .save import ps2save

PS2MC_MAGIC = b"Sony PS2 Memory Card Format "
PS2MC_FAT_ALLOCATED_BIT = 0x80000000
PS2MC_FAT_CHAIN_END = 0xFFFFFFFF
PS2MC_FAT_CHAIN_END_UNALLOC = 0x7FFFFFFF
PS2MC_FAT_CLUSTER_MASK = 0x7FFFFFFF
PS2MC_MAX_INDIRECT_FAT_CLUSTERS = 32
PS2MC_CLUSTER_SIZE = 1024
PS2MC_INDIRECT_FAT_OFFSET = 0x2000

PS2MC_STANDARD_PAGE_SIZE = 512
PS2MC_STANDARD_PAGES_PER_CARD = 16384
PS2MC_STANDARD_PAGES_PER_ERASE_BLOCK = 16

class error(Exception):
    pass

class io_error(error, IOError):
    def __init__(self, *args, **kwargs):
        IOError.__init__(self, *args, **kwargs)

    def __str__(self):
        if getattr(self, "strerror", None) == None:
            return str(self.args)
        if getattr(self, "filename", None) != None:
            return self.filename + ": " + self.strerror
        return self.strerror
    
class path_not_found(io_error):
    def __init__(self, filename):
        io_error.__init__(self, ENOENT, "path not found", filename)

class file_not_found(io_error):
    def __init__(self, filename):
        io_error.__init__(self, ENOENT, "file not found", filename)

class dir_not_found(io_error):
    def __init__(self, filename):
        io_error.__init__(self, ENOENT, "directory not found",
                  filename)

class dir_index_not_found(io_error, IndexError):
    def __init__(self, filename, index):
        msg = "index (%d) past of end of directory" % index
        io_error.__init__(self, ENOENT, msg, filename)
                  
class corrupt(io_error):
    def __init__(self, msg, f = None):
        filename = None
        if f != None:
            filename = getattr(f, "name")
        io_error.__init__(self, EIO, msg, filename)
        
class ecc_error(corrupt):
    def __init__(self, msg, filename = None):
        corrupt.__init__(self, msg, filename)

if sys.byteorder == "big":
    def unpack_32bit_array(s):
        a = array.array('I', s)
        a.byteswap()

    def pack_32bit_array(a):
        a = a[:]
        a.byteswap()
        return a.tobytes()
else:
    def unpack_32bit_array(s):
        #if isinstance(s, str):
        #    a = array.array('L')
        #    a.frombytes(s)
        #    return a
        return array.array('I', s)

    def pack_32bit_array(a):
        return a.tobytes()
    
def unpack_superblock(s):
    sb = struct.unpack("<28s12sHHHHLLLLLL8x128s128sbbxx", s)
    sb = list(sb)
    sb[12] = unpack_32bit_array(sb[12])
    sb[13] = unpack_32bit_array(sb[13])
    return sb

def pack_superblock(sb):
    sb = list(sb)
    sb[12] = pack_32bit_array(sb[12])
    sb[13] = pack_32bit_array(sb[13])
    return struct.pack("<28s12sHHHHLLLLLL8x128s128sbbxx", *sb)

unpack_fat = unpack_32bit_array
pack_fat = pack_32bit_array

class lru_cache(object):
    def __init__(self, length):
        self._lru_list = [[i - 1, None, None, i + 1]
                  for i in range(length + 1)]
        self._index_map = {}

    def dump(self):
        lru_list = self._lru_list
        i = 0
        while i != len(self._lru_list):
            print("%d: %s, " % (i, str(lru_list[i][1])), end=' ') 
            i = lru_list[i][3]
        print()
        print(self._index_map)
            
    def _move_to_front(self, i):
        lru_list = self._lru_list
        first = lru_list[0]
        i2 = first[3]
        if i != i2:
            elt = lru_list[i]
            prev = lru_list[elt[0]]
            next = lru_list[elt[3]]
            prev[3] = elt[3]
            next[0] = elt[0]
            elt[0] = 0
            elt[3] = i2
            lru_list[i2][0] = i
            first[3] = i
        
    def add(self, key, value):
        lru_list = self._lru_list
        index_map = self._index_map
        ret = None
        if key in index_map:
            i = index_map[key]
            # print "add hit ", key, i
            elt = lru_list[i]
        else:
            # print "add miss", key
            i = lru_list[-1][0]
            elt = lru_list[i]
            old_key = elt[1]
            if old_key != None:
                del index_map[old_key]
                ret = (old_key, elt[2])
            index_map[key] = i
            elt[1] = key
        elt[2] = value
        self._move_to_front(i)

        return ret
        
    def get(self, key, default = None):
        i = self._index_map.get(key)
        if i == None:
            # print "get miss", key
            return default
        # print "get hit ", key, i
        ret = self._lru_list[i][2]
        self._move_to_front(i)
        return ret

    def items(self):
        return [(elt[1], elt[2])
            for elt in self._lru_list[1 : -1]
            if elt[2] != None]
        
class fat_chain(object):
    """A class for accessing a file's FAT entries as a simple sequence."""
    
    def __init__(self, lookup_fat, first):
        self.lookup_fat = lookup_fat
        self._first = first
        self.offset = 0
        self._prev = None
        self._cur = first

    def __getitem__(self, i):
        # not iterable
        offset = self.offset
        if i == offset:
            # print "@@@ fat_chain[] cur:", i, self._cur
            return self._cur
        elif i == offset - 1:
            assert self._prev != None
            # print "@@@ fat_chain[] prev:", i, self._prev
            return self._prev
        if i < offset:
            if i == 0:
                # print "@@@ fat_chain[] first", i, self._first
                return self._first
            offset = 0
            prev = None
            cur = self._first
        else:
            prev = self._prev
            cur = self._cur
        # print "@@@ fat_chain[] distance", i - offset
        while offset != i:
            next = self.lookup_fat(cur)
            if next == PS2MC_FAT_CHAIN_END:
                break;
            if next & PS2MC_FAT_ALLOCATED_BIT:
                next &= ~PS2MC_FAT_ALLOCATED_BIT
            else:
                # corrupt
                next = PS2MC_FAT_CHAIN_END
                break

            offset += 1
            prev = cur
            cur = next
        self.offset = offset
        self._prev = prev
        self._cur = cur
        # print "@@@ offset, prev, cur:", offset, prev, cur
        # print "@@@ fat_chain[]", i, next
        return next

    def __len__(self):
        old_prev = self._prev
        old_cur = self._cur
        old_offset = self.offset
        i = self.offset
        while self[i] != PS2MC_FAT_CHAIN_END:
            i += 1
        self._prev = old_prev
        self._cur = old_cur
        self.offset = old_offset
        return i
        
class ps2mc_file(object):
    """A file-like object for accessing a file in memory card image."""
    
    def __init__(self, mc, dirloc, first_cluster, length, mode,
             name = None):
        # print "ps2mc_file.__init__", name, self
        self.mc = mc
        self.length = length
        self.first_cluster = first_cluster
        self.dirloc = dirloc
        self.fat_chain = None
        self._pos = 0
        self.buffer = None
        self.buffer_cluster = None
        self.softspace = 0
        if name == None:
            self.name = "<ps2mc_file>"
        else:
            self.name = name
        self.closed = False

        if mode == None or len(mode) == 0:
            mode = "rb"
        self.mode = mode
        self._append = False
        self._write = False
        if mode[0] == "a":
            self._append = True
        elif mode[0] != "w" or ("+" not in self.mode):
            self._write = True

    def _find_file_cluster(self, n):
        if self.fat_chain == None:
            self.fat_chain = self.mc.fat_chain(self.first_cluster)
        return self.fat_chain[n]
        
    def read_file_cluster(self, n):
        if n == self.buffer_cluster:
            return self.buffer
        cluster = self._find_file_cluster(n)
        # print "@@@ read_file_cluster", self.dirloc, n, cluster, repr(self.name)
        if cluster == PS2MC_FAT_CHAIN_END:
            return None
        self.buffer = self.mc.read_allocatable_cluster(cluster)
        self.buffer_cluster = n
        return self.buffer 

    def _extend_file(self, n):
        mc = self.mc
        cluster = mc.allocate_cluster()
        # print "@@@ extending file", n, cluster
        if cluster == None:
            return None
        if n == 0:
            self.first_cluster = cluster
            self.fat_chain = None
            # print "@@@ linking", self.dirloc, "->", cluster
            mc.update_dirent(self.dirloc, self, cluster,
                     None, False)
        else:
            prev = self.fat_chain[n - 1]
            # print "@@@ linking", prev, "->", cluster
            mc.set_fat(prev, cluster | PS2MC_FAT_ALLOCATED_BIT)
        return cluster
    
    def write_file_cluster(self, n, buf):
        mc = self.mc
        cluster = self._find_file_cluster(n)
        if cluster != PS2MC_FAT_CHAIN_END:
            mc.write_allocatable_cluster(cluster, buf)
            self.buffer = buf
            self.buffer_cluster = n
            return True

        cluster_size = mc.cluster_size
        file_cluster_end = div_round_up(self.length, cluster_size)

        if (cluster < file_cluster_end
            or len(self.fat_chain) != file_cluster_end):
            raise corrupt("file length doesn't match cluster"
                    " chain length", mc.f)

        for i in range(file_cluster_end, n):
            cluster = self._extend_file(i)
            if cluster == None:
                if i != file_cluster_end:
                    self.length = (i - 1) * cluster_size
                    mc.update_dirent(self.dirloc, self,
                             None, self.length,
                             True)
                return False
            mc.write_allocatable_cluster(cluster,
                             [b"\0"] * cluster_size)
        
        cluster = self._extend_file(n)
        if cluster == None:
            return False

        mc.write_allocatable_cluster(cluster, buf)
        self.buffer = buf
        self.buffer_cluster = n
        return True
    
    def update_notify(self, first_cluster, length):
        if self.first_cluster != first_cluster:
            self.first_cluster = first_cluster
            self.fat_chain = None
        self.length = length
        self.buffer = None
        self.buffer_cluster = None
        
    def read(self, size = None, eol = None):
        if self.closed:
            raise ValueError("file is closed")

        pos = self._pos
        cluster_size = self.mc.cluster_size
        if size == None:
            size = self.length
        size = max(min(self.length - pos, size), 0)
        ret = b""
        while size > 0:
            off = pos % cluster_size
            l = min(cluster_size - off, size)
            buf = self.read_file_cluster(pos // cluster_size)
            if buf == None:
                break
            if eol != None:
                i = buf.find(eol, off, off + l)
                if i != -1:
                    l = off - i + 1
                    size = l
            pos += l
            self._pos = pos
            ret += buf[off : off + l]
            size -= l
        return ret

    def write(self, out, _set_modified = True):
        if self.closed:
            raise ValueError("file is closed")
    
        cluster_size = self.mc.cluster_size
        pos = self._pos
        if self._append: 
            pos = self.length
        elif not self._write:
            raise io_error(EACCES, "file not opened for writing",
                     self.name)

        size = len(out)
        # print "@@@ write", pos, size
        i = 0
        while size > 0:
            cluster = pos // cluster_size
            off = pos % cluster_size
            l = min(cluster_size - off, size)
            s = out[i : i + l]
            pos += l
            if l == cluster_size:
                buf = s
            else:
                buf = self.read_file_cluster(cluster)
                if buf == None:
                    buf = b"\0" * cluster_size
                buf = buf[:off] + s + buf[off + l:]
            if not self.write_file_cluster(cluster, buf):
                raise io_error(ENOSPC,
                         "out of space on image",
                         self.name)
            self._pos = pos
            # print "@@@ pos", pos
            new_length = None
            if pos > self.length:
                new_length = self.length = pos
            self.mc.update_dirent(self.dirloc, self, None,
                          new_length, _set_modified)

            i += l
            size -= l

    def close(self):
        # print "ps2mc_file.close", self.name, self
        if self.mc != None:
            self.mc.notify_closed(self.dirloc, self)
            self.mc = None
        self.fat_chain = None
        self.buffer = None

    def __next__(self):
        r = self.readline()
        if r == "":
            raise StopIteration
        return r

    def readline(self, size = None):
        return self.read(size, "\n")
        
    def readlines(self, sizehint):
        return [line for line in self]

    def seek(self, offset, whence = 0):
        if self.closed:
            raise ValueError("file is closed")

        if whence == 1:
            base = self._pos
        elif whence == 2:
            base = self.length
        else:
            base = 0
        pos = max(base + offset, 0)
        self._pos = pos

    def tell(self):
        if self.closed:
            raise ValueError("file is closed")
        return self._pos

    def __enter__(self):
        return

    def __exit__(self, a, b, c):
        self.close()
        return
    
    # def __del__(self):
    #    # print "ps2mc_file.__del__", self
    #    if self.mc != None:
    #        self.mc.notify_closed(self.dirloc, self)
    #        self.mc = None
    #    self.fat_chain = None
        
class ps2mc_directory(object):
    """A sequence and iterator object for directories."""
    
    def __init__(self, mc, dirloc, first_cluster, length,
             mode = "rb", name = None):
        self.f = ps2mc_file(mc, dirloc, first_cluster,
                    length * PS2MC_DIRENT_LENGTH, mode, name)

    def __iter__(self):
        start = self.tell()
        if start != 0:
            start -= 1
            self.seek(start)
        self._iter_end = start
        return self

    def write_raw_ent(self, index, ent, set_modified):
        # print "@@@ write_raw_ent", index
        self.seek(index)
        self.f.write(pack_dirent(ent),
                 _set_modified = set_modified)

    def __next__(self):
        # print "@@@ next", self.tell(), self.f.name
        dirent = self.f.read(PS2MC_DIRENT_LENGTH)
        if dirent == b"":
            if 0 == self._iter_end:
                raise StopIteration
            self.seek(0)
            dirent = self.f.read(PS2MC_DIRENT_LENGTH)
        elif self.tell() == self._iter_end:
            raise StopIteration
        return unpack_dirent(dirent)

    def seek(self, offset, whence = 0):
        self.f.seek(offset * PS2MC_DIRENT_LENGTH, whence)

    def tell(self):
        return self.f.tell() // PS2MC_DIRENT_LENGTH

    def __len__(self):
        return self.f.length // PS2MC_DIRENT_LENGTH
    
    def __getitem__(self, index):
        # print "@@@ getitem", index, self.f.name
        self.seek(index)
        dirent = self.f.read(PS2MC_DIRENT_LENGTH)
        if len(dirent) != PS2MC_DIRENT_LENGTH:
            raise dir_index_not_found(self.f.name, index)
        return unpack_dirent(dirent)

    def __setitem__(self, index, new_ent):
        ent = self[index]
        mode = ent[0]
        if (mode & DF_EXISTS) == 0:
            return
        if new_ent[0] != None:
            mode = ((new_ent[0] & ~(DF_FILE | DF_DIR | DF_EXISTS))
                | (mode & (DF_FILE | DF_DIR | DF_EXISTS)))
            ent[0] = mode
        if new_ent[1] != None:
            ent[1] = new_ent[1]
        if new_ent[3] != None:
            ent[3] = new_ent[3]
        if new_ent[6] != None:
            ent[6] = new_ent[6]
        if new_ent[7] != None:
            ent[7] = new_ent[7]
        self.write_raw_ent(index, ent, False)

    def close(self):
        # print "ps2mc_directory.close", self
        self.f.close()
        self.f = None

    def __del__(self):
        # print "ps2mc_directory.__del__", self
        if self.f != None:
            self.f.close()
            self.f = None
            
class _root_directory(ps2mc_directory):
    """Wrapper for the cached root directory object.

    The close() method is disabled so the cached object can be reused."""
    
    def __init__(self, mc, dirloc, first_cluster, length,
             mode = "r+b", name = "/"):
        ps2mc_directory.__init__(self, mc, dirloc, first_cluster,
                     length, mode, name)

    def close(self):
        pass

    def real_close(self):
        ps2mc_directory.close(self)
        
class ps2mc(object):
    """A PlayStation 2 memory card filesystem implementation.

    The close() method must be called when the object is no longer needed,
    otherwise cycles that can't be collected by the garbage collector
    will remain."""
    
    open_files = None
    fat_cache = None
    
    def _calculate_derived(self):
        self.spare_size = div_round_up(self.page_size, 128) * 4
        self.raw_page_size = self.page_size + self.spare_size
        self.cluster_size = self.page_size * self.pages_per_cluster
        self.entries_per_cluster = self.page_size * self.pages_per_cluster // 4

        limit = (min(self.good_block2, self.good_block1)
             * self.pages_per_erase_block
             // self.pages_per_cluster
             - self.allocatable_cluster_offset)
        self.allocatable_cluster_limit = limit

    def __init__(self, f, ignore_ecc = False, params = None):
        self.open_files = {}
        self.fat_cache = lru_cache(12)
        self.alloc_cluster_cache = lru_cache(64)
        self.modified = False
        self.f = None
        self.rootdir = None
        
        f.seek(0)
        s = f.read(0x154)
        if len(s) != 0x154 or not s.startswith(PS2MC_MAGIC):
            if (params == None):
                raise corrupt("Not a PS2 memory card image",
                        f)
            self.f = f
            self.format(params)
        else:
            sb = unpack_superblock(s)
            self.version = sb[1]
            self.page_size = sb[2]
            self.pages_per_cluster = sb[3]
            self.pages_per_erase_block = sb[4]
            self.clusters_per_card = sb[6]
            self.allocatable_cluster_offset = sb[7]
            self.allocatable_cluster_end = sb[8]
            self.rootdir_fat_cluster = sb[9]
            self.good_block1 = sb[10]
            self.good_block2 = sb[11]
            self.indirect_fat_cluster_list = sb[12]
            self.bad_erase_block_list = sb[13]

            self._calculate_derived()

            self.f = f
            self.ignore_ecc = False

            try:
                self.read_page(0)
                self.ignore_ecc = ignore_ecc
            except ecc_error:
                # the error might be due the fact the file
                # image doesn't contain ECC data
                self.spare_size = 0
                self.raw_page_size = self.page_size
                ignore_ecc = True

        # sanity check
        root = self._directory(None, 0, 1)
        dot = root[0]
        dotdot = root[1]
        root.close()
        if (dot[8] != b"." or dotdot[8] != b".."
            or not mode_is_dir(dot[0]) or not mode_is_dir(dotdot[0])):
            raise corrupt("Root directory damaged.")
        
        self.fat_cursor = 0
        self.curdir = (0, 0)

    def write_superblock(self):
        s = pack_superblock((PS2MC_MAGIC,
                     self.version,
                     self.page_size,
                     self.pages_per_cluster,
                     self.pages_per_erase_block,
                     0xFF00,
                     self.clusters_per_card,
                     self.allocatable_cluster_offset,
                     self.allocatable_cluster_end,
                     self.rootdir_fat_cluster,
                     self.good_block1,
                     self.good_block2,
                     self.indirect_fat_cluster_list,
                     self.bad_erase_block_list,
                     2,
                     0x2B))
        s += b"\x00" * (self.page_size - len(s))
        self.write_page(0, s)

        page = b"\xFF" * self.raw_page_size
        self.f.seek(self.good_block2 * self.pages_per_erase_block
                * self.raw_page_size)
        for i in range(self.pages_per_erase_block):
            self.f.write(page)

        self.modified = False
        return
        
    def format(self, params):
        """Create (format) a new memory card image."""
        
        (with_ecc, page_size,
         pages_per_erase_block, param_pages_per_card) = params

        if pages_per_erase_block < 1:
            raise error("invalid pages per erase block (%d)"
                      % page_size)
            
        pages_per_card = round_down(param_pages_per_card,
                        pages_per_erase_block)
        cluster_size = PS2MC_CLUSTER_SIZE
        pages_per_cluster = cluster_size // page_size
        clusters_per_erase_block = pages_per_erase_block // pages_per_cluster
        erase_blocks_per_card = pages_per_card // pages_per_erase_block
        clusters_per_card = pages_per_card // pages_per_cluster
        epc = cluster_size // 4

        if (page_size < PS2MC_DIRENT_LENGTH
            or pages_per_cluster < 1
            or pages_per_cluster * page_size != cluster_size):
            raise error("invalid page size (%d)" % page_size)
        
        good_block1 = erase_blocks_per_card - 1
        good_block2 = erase_blocks_per_card - 2
        first_ifc = div_round_up(PS2MC_INDIRECT_FAT_OFFSET,
                     cluster_size)

        allocatable_clusters = clusters_per_card - (first_ifc + 2)
        fat_clusters = div_round_up(allocatable_clusters, epc)
        indirect_fat_clusters = div_round_up(fat_clusters, epc)
        if indirect_fat_clusters > PS2MC_MAX_INDIRECT_FAT_CLUSTERS:
            indirect_fat_clusters = PS2MC_MAX_INDIRECT_FAT_CLUSTERS
            fat_clusters = indirect_fat_clusters * epc
        allocatable_clusters = fat_clusters * epc

        allocatable_cluster_offset = (first_ifc
                          + indirect_fat_clusters
                          + fat_clusters)
        allocatable_cluster_end = (good_block2
                       * clusters_per_erase_block
                       - allocatable_cluster_offset)
        if allocatable_cluster_end < 1:
            raise error("memory card image too small"
                      " to be formatted")

        ifc_list = unpack_fat(b"\0\0\0\0"
                      * PS2MC_MAX_INDIRECT_FAT_CLUSTERS)
        for i in range(indirect_fat_clusters):
            ifc_list[i] = first_ifc + i

        self.version = b"1.2.0.0"
        self.page_size = page_size
        self.pages_per_cluster = pages_per_cluster
        self.pages_per_erase_block = pages_per_erase_block
        self.clusters_per_card = clusters_per_card
        self.allocatable_cluster_offset = allocatable_cluster_offset
        self.allocatable_cluster_end = allocatable_clusters
        self.rootdir_fat_cluster = 0
        self.good_block1 = good_block1
        self.good_block2 = good_block2
        self.indirect_fat_cluster_list = ifc_list
        bebl = b"\xFF\xFF\xFF\xFF" * 32
        self.bad_erase_block_list = unpack_32bit_array(bebl)
        
        self._calculate_derived()

        self.ignore_ecc = not with_ecc
        erased = b"\0" * page_size
        if not with_ecc:
            self.spare_size = 0
            self.raw_page_size = self.page_size
        else:
            ecc = b"".join([bytes(s) for s in ecc_calculate_page(erased)])
            erased += ecc + b"\0" * (self.spare_size - len(ecc))

        self.f.seek(0)
        for page in range(pages_per_card):
            self.f.write(erased)

        self.modified = True
        
        first_fat_cluster = first_ifc + indirect_fat_clusters
        remainder = fat_clusters % epc
        for i in range(indirect_fat_clusters):
            base = first_fat_cluster + i * epc
            buf = unpack_fat(list(range(base, base + epc)))
            if (i == indirect_fat_clusters - 1
                and remainder != 0):
                del buf[remainder:]
                buf.fromlist([0xFFFFFFFF] * (epc - remainder))
            self._write_fat_cluster(ifc_list[i], buf)

        
        # go through the fat backwards for better cache usage
        for i in range(allocatable_clusters - 1,
                   allocatable_cluster_end - 1, -1):
            self.set_fat(i, PS2MC_FAT_CHAIN_END)
        for i in range(allocatable_cluster_end - 1, 0, -1):
            self.set_fat(i, PS2MC_FAT_CLUSTER_MASK)
        self.set_fat(0, PS2MC_FAT_CHAIN_END)

        self.allocatable_cluster_end = allocatable_cluster_end
        
        now = tod_now()
        s = pack_dirent((DF_RWX | DF_DIR | DF_0400 | DF_EXISTS,
                 0, 2, now,
                 0, 0, now, 0, b"."))
        s += b"\0" * (cluster_size - len(s))
        self.write_allocatable_cluster(0, s)
        dir = self._directory((0, 0), 0, 2, "wb", "/")
        dir.write_raw_ent(1, (DF_WRITE | DF_EXECUTE | DF_DIR | DF_0400
                      | DF_HIDDEN | DF_EXISTS,
                      0, 0, now,
                      0, 0, now, 0, b".."), False)
        dir.close()

        self.flush()

    def read_page(self, n):
        # print "@@@ page", n
        f = self.f
        f.seek(self.raw_page_size * n)
        page = f.read(self.page_size)
        if len(page) != self.page_size:
            raise corrupt("attempted to read past EOF"
                    " (page %05X)" % n, f)
        if self.ignore_ecc:
            return page
        spare = f.read(self.spare_size)
        if len(spare) != self.spare_size:
            raise corrupt("attempted to read past EOF"
                    " (page %05X)" % n, f)
        if n == 0 and spare == b'\xff' * 16:
            raise ecc_error("ECC data absent")
        (status, page, spare) = ecc_check_page(page, spare)
        if status == ECC_CHECK_FAILED:
            raise ecc_error("Unrecoverable ECC error (page %d)"
                      % n)
        return page

    def write_page(self, n, buf):
        f = self.f
        f.seek(self.raw_page_size * n)
        self.modified = True
        if len(buf) != self.page_size:
            raise error("internal error: write_page:"
                      " %d != %d" % (len(buf), self.page_size))
        f.write(buf)
        if self.spare_size != 0:
            a = array.array('B')
            for s in ecc_calculate_page(buf):
                a.fromlist(s)
            a.tofile(f)
            f.write(b"\0" * (self.spare_size - len(a)))
            
    def read_cluster(self, n):
        pages_per_cluster = self.pages_per_cluster
        cluster_size = self.cluster_size
        if self.spare_size == 0:
            self.f.seek(cluster_size * n)
            return self.f.read(cluster_size)
        n *= pages_per_cluster
        if pages_per_cluster == 2:
            return self.read_page(n) + self.read_page(n + 1)
        return "".join(map(self.read_page,
                   list(range(n, n + pages_per_cluster))))

    def write_cluster(self, n, buf):
        pages_per_cluster = self.pages_per_cluster
        cluster_size = self.cluster_size
        if self.spare_size == 0:
            self.f.seek(cluster_size * n)
            if len(buf) != cluster_size:
                raise error("internal error: write_cluster:"
                          " %d != %d" % (len(buf),
                                 cluster_size))
            return self.f.write(buf)
        n *= pages_per_cluster
        pgsize = self.page_size
        for i in range(pages_per_cluster):
            self.write_page(n + i, buf[i * pgsize
                           : i * pgsize + pgsize])


    def _add_fat_cluster_to_cache(self, n, fat, dirty):
        old = self.fat_cache.add(n, [fat, dirty])
        if old != None:
            (n, [fat, dirty]) = old
            if dirty:
                self.write_cluster(n, pack_fat(fat))

    def _read_fat_cluster(self, n):
        v = self.fat_cache.get(n)
        if v != None:
            # print "@@@ fat hit", n
            return v[0]
        # print "@@@ fat miss", n
        fat = unpack_fat(self.read_cluster(n))
        self._add_fat_cluster_to_cache(n, fat, False)
        return fat

    def _write_fat_cluster(self, n, fat):
        self._add_fat_cluster_to_cache(n, fat, True)

    def flush_fat_cache(self):
        if self.fat_cache == None:
            return
        for (n, v) in list(self.fat_cache.items()):
            [fat, dirty] = v
            if dirty:
                self.write_cluster(n, pack_fat(fat))
                v[1] = False

    def _add_alloc_cluster_to_cache(self, n, buf, dirty):
        old = self.alloc_cluster_cache.add(n, [buf, dirty])
        if old != None:
            (n, [buf, dirty]) = old
            if dirty:
                n += self.allocatable_cluster_offset
                self.write_cluster(n, buf)
        
    def read_allocatable_cluster(self, n):
        a = self.alloc_cluster_cache.get(n)
        if a != None:
            # print "@@@ cache hit", n
            return a[0]
        # print "@@@ cache miss", n
        buf = self.read_cluster(n + self.allocatable_cluster_offset)
        self._add_alloc_cluster_to_cache(n, buf, False)
        return buf
        
    def write_allocatable_cluster(self, n, buf):
        self._add_alloc_cluster_to_cache(n, buf, True)

    def flush_alloc_cluster_cache(self):
        if self.alloc_cluster_cache == None:
            return
        for (n, a) in list(self.alloc_cluster_cache.items()):
            [buf, dirty] = a
            if dirty:
                n += self.allocatable_cluster_offset
                self.write_cluster(n, buf)
                a[1] = False

    def read_fat_cluster(self, n):
        indirect_offset = n % self.entries_per_cluster
        dbl_offset = n // self.entries_per_cluster
        indirect_cluster = self.indirect_fat_cluster_list[dbl_offset]
        indirect_fat = self._read_fat_cluster(indirect_cluster)
        cluster = indirect_fat[indirect_offset]
        return (self._read_fat_cluster(cluster), cluster)
                          
    def read_fat(self, n):
        if n < 0 or n >= self.allocatable_cluster_end:
            raise io_error(EIO,
                     "FAT cluster index out of range"
                     " (%d)" % n)
        offset = n % self.entries_per_cluster
        fat_cluster = n // self.entries_per_cluster
        (fat, cluster) = self.read_fat_cluster(fat_cluster)
        return (fat, offset, cluster)

    def lookup_fat(self, n):
        (fat, offset, cluster) = self.read_fat(n)
        return fat[offset]

    def set_fat(self, n, value):
        (fat, offset, cluster) = self.read_fat(n)
        fat[offset] = value
        self._write_fat_cluster(cluster, fat)
        
    def allocate_cluster(self):
        epc = self.entries_per_cluster
        allocatable_cluster_limit = self.allocatable_cluster_limit
        
        end = div_round_up(allocatable_cluster_limit, epc)
        remainder = allocatable_cluster_limit % epc
            
        while self.fat_cursor < end:
            (fat, cluster) = self.read_fat_cluster(self.fat_cursor)
            if (self.fat_cursor == end - 1
                and remainder != 0):
                n = min(fat[:remainder])
            else: 
                n = min(fat)
            if (n & PS2MC_FAT_ALLOCATED_BIT) == 0:
                offset = fat.index(n)
                fat[offset] = PS2MC_FAT_CHAIN_END
                self._write_fat_cluster(cluster, fat)
                ret = self.fat_cursor * epc + offset
                # print "@@@ allocated", ret
                return ret
            self.fat_cursor += 1
        return None
    
    def fat_chain(self, first_cluster):
        return fat_chain(self.lookup_fat, first_cluster)

    def file(self, dirloc, first_cluster, length, mode, name = None):
        """Create a new file-like object for a file."""
        
        f = ps2mc_file(self, dirloc, first_cluster, length, mode, name)
        if dirloc == None:
            return
        open_files = self.open_files
        if dirloc not in open_files:
            open_files[dirloc] = [None, set([f])]
        else:
            open_files[dirloc][1].add(f)
        return f

    def directory(self, dirloc, first_cluster, length,
              mode = None, name = None):
        return ps2mc_directory(self, dirloc, first_cluster, length,
                       mode, name)
    
    def _directory(self, dirloc, first_cluster, length,
               mode = None, name = None):
        # print "@@@ _directory", dirloc, first_cluster, length
        if first_cluster != 0:
            return self.directory(dirloc, first_cluster, length,
                          mode, name)
        if dirloc == None:
            dirloc = (0, 0)
        assert dirloc == (0, 0)
        if self.rootdir != None:
            return self.rootdir
        dir = _root_directory(self, dirloc, 0, length, "r+b", "/")
        l = dir[0][2]
        if l != length:
            dir.real_close()
            dir = _root_directory(self, dirloc, 0, l, "r+b", "/")
        self.rootdir = dir
        return dir

    def _get_parent_dirloc(self, dirloc):
        """Get the dirloc of the parent directory of the
        file or directory refered to by dirloc"""
        
        cluster = self.read_allocatable_cluster(dirloc[0])
        ent = unpack_dirent(cluster[:PS2MC_DIRENT_LENGTH])
        return (ent[4], ent[5])

    def _dirloc_to_ent(self, dirloc):
        """Get the directory entry of the file or directory
        refered to by dirloc"""
        
        dir = self._directory(None, dirloc[0], dirloc[1] + 1,
                      name = "_dirloc_to_ent temp")
        ent = dir[dirloc[1]]
        dir.close()
        return ent

    def _opendir_dirloc(self, dirloc, mode = "rb"):
        """Open the directory that is refered to by dirloc"""
        
        ent = self._dirloc_to_ent(dirloc)
        return self._directory(dirloc, ent[4], ent[2],
                       name = "_opendir_dirloc temp")

    def _opendir_parent_dirloc(self, dirloc, mode = "rb"):
        """Open the directory that contains the file or directory
        refered to by dirloc"""
        
        return self._opendir_dirloc(self._get_parent_dirloc(dirloc),
                        mode)
        
    def update_dirent_all(self, dirloc, thisf, new_ent):
        # print "@@@ update_dirent", dirloc
        # print "@@@ new_ent", new_ent
        opened = self.open_files.get(dirloc, None)
        if opened == None:
            files = []
            dir = None
        else:
            dir, files = opened
        if dir == None:
            dir = self._opendir_parent_dirloc(dirloc, "r+b")
            if opened != None:
                opened[0] = dir
        
        ent = dir[dirloc[1]]
        # print "@@@ old_ent", ent
        
        is_dir = ent[0] & DF_DIR

        if is_dir and thisf != None and new_ent[2] != None:
            new_ent = list(new_ent)
            new_ent[2] //= PS2MC_DIRENT_LENGTH
            
        # print "len: ", ent[2], new_ent[2]

        modified = changed = notify = False
        for i in range(len(ent)):
            new = new_ent[i]
            if new != None:
                if new != ent[i]:
                    ent[i] = new
                    changed = True
                    if i == 6:
                        modified = True
                    if i in [2, 4]:
                        notify = True
                        
        # Modifying a file causes the modification time of
        # both the file and the file's directory to updated,
        # however modifying a directory never updates the
        # modification time of the directory's parent.
        if changed:
            dir.write_raw_ent(dirloc[1], ent,
                      (modified and not is_dir))

        
        if notify:
            for f in files:
                if f != thisf:
                    f.update_notfiy(ent[4], ent[2])
        if opened == None:
            dir.close()

    def update_dirent(self, dirloc, thisf, first_cluster, length,
              modified):
        if modified:
            modified = tod_now()
        else:
            if first_cluster == None and length == None:
                return
            modified = None
        self.update_dirent_all(dirloc, thisf,
                       (None, None, length, None,
                    first_cluster, None, modified, None,
                    None))
            
    def notify_closed(self, dirloc, thisf):
        if self.open_files == None or dirloc == None:
            return
        a  = self.open_files.get(dirloc, None)
        if a == None:
            return
        self.flush()
        dir, files = a
        files.discard(thisf)
        if len(files) == 0:
            # print "@@@ notify_closed", dir
            if dir != None:
                dir.close()
            del self.open_files[dirloc]
            
    def search_directory(self, dir, name):
        """Search dir for name."""

        # start the search where the last search ended.
        start = dir.tell() - 1
        if start == -1:
            start = 0
        for i in list(range(start, len(dir))) + list(range(0, start)):
            try:
                ent = dir[i]
            except IndexError:
                raise corrupt("Corrupt directory", dir.f)
                
            if ent[8].decode("ascii") == name and (ent[0] & DF_EXISTS):
                return (i, ent)
        return (None, None)

    def create_dir_entry(self, parent_dirloc, name, mode):
        """Create a new directory entry in a directory."""
        
        # print "@@@ create_dir_ent", parent_dirloc, name
        dir_ent = self._dirloc_to_ent(parent_dirloc)
        dir = self._directory(parent_dirloc, dir_ent[4], dir_ent[2],
                      "r+b")
        l = len(dir)
        # print "@@@ len", l
        assert l >= 2
        for i in range(l):
            ent = dir[i]
            if (ent[0] & DF_EXISTS) == 0:
                break
        else:
            i = l
            
        dirloc = (dir_ent[4], i)
        # print "@@@ dirloc", dirloc
        now = tod_now()
        if mode & DF_DIR:
            mode &= ~DF_FILE
            cluster = self.allocate_cluster()
            length = 1
        else:
            mode |= DF_FILE
            mode &= ~DF_DIR
            cluster = PS2MC_FAT_CHAIN_END
            length = 0
        ent[0] = mode | DF_EXISTS
        ent[1] = 0
        ent[2] = length
        ent[3] = now
        ent[4] = cluster
        ent[5] = 0
        ent[6] = now
        ent[7] = 0
        ent[8] = name[:32].encode("ascii")
        dir.write_raw_ent(i, ent, True)
        dir.close()

        if mode & DF_FILE:
            # print "@@@ ret", dirloc, ent
            return (dirloc, ent)

        dirent = pack_dirent((DF_RWX | DF_0400 | DF_DIR | DF_EXISTS,
                      0, 0, now, dirloc[0], dirloc[1],
                      now, 0, b"."))
        dirent += b"\0" * (self.cluster_size - PS2MC_DIRENT_LENGTH)
        self.write_allocatable_cluster(cluster, dirent)
        dir = self._directory(dirloc, cluster, 1, "wb",
                      name = "<create_dir_entry temp>")
        dir.write_raw_ent(1, (DF_RWX | DF_0400 | DF_DIR | DF_EXISTS,
                      0, 0, now,
                      0, 0,
                      now, 0, b".."), False)
        dir.close()
        ent[2] = 2
        # print "@@@ ret", dirloc, ent
        return (dirloc, ent)

    def delete_dirloc(self, dirloc, truncate, name):
        """Delete or truncate the file or directory given by dirloc."""
        
        if dirloc == (0, 0):
            raise io_error(EACCES,
                     "cannot remove root directory",
                     name)
        if dirloc[1] in [0, 1]:
            raise io_error(EACCES,
                     'cannot remove "." or ".." entries',
                     name)

        if dirloc in self.open_files:
            raise io_error(EBUSY,
                     "cannot remove open file", filename)

        epc = self.entries_per_cluster

        ent = self._dirloc_to_ent(dirloc)
        cluster = ent[4]
        if truncate:
            ent[2] = 0
            ent[4] = PS2MC_FAT_CHAIN_END
            ent[6] = tod_now()
        else:
            ent[0] &= ~DF_EXISTS
        self.update_dirent_all(dirloc, None, ent)
        
        while cluster != PS2MC_FAT_CHAIN_END:
            if cluster // epc < self.fat_cursor:
                self.fat_cursor = cluster // epc
            next_cluster = self.lookup_fat(cluster)
            if next_cluster & PS2MC_FAT_ALLOCATED_BIT == 0:
                # corrupted
                break
            next_cluster &= ~PS2MC_FAT_ALLOCATED_BIT
            self.set_fat(cluster, next_cluster)
            if next_cluster == PS2MC_FAT_CHAIN_END_UNALLOC:
                break
            cluster = next_cluster
            
    def path_search(self, pathname):
        """Parse and resolve a pathname.

        Return a tuple containing a tuple containing three
        values.  The first is either the dirloc of the file or
        directory, if it exists, otherwise it's the dirloc the
        pathname's parent directory, if that exists otherwise
        it's None.  The second component is directory entry
        for pathname if it exists, otherwise None.  The third
        is a boolean value that's true if the pathname refers
        a directory."""
        
        components = pathname.split("/")
        if len(components) < 1:
            # could return curdir
            return (None, None, False)

        dirloc = self.curdir
        if components[0] == "":
            dirloc = (0, 0)
        if dirloc == (0, 0):
            rootent = self.read_allocatable_cluster(0)
            ent = unpack_dirent(rootent[:PS2MC_DIRENT_LENGTH])
            dir_cluster = 0
            dir = self._directory(dirloc, dir_cluster, ent[2],
                          name = "<path_search temp>")
        else:
            ent = self._dirloc_to_ent(dirloc)
            dir = self._directory(dirloc, ent[4], ent[2],
                          name = "<path_search temp>")

        for s in components:
            # print "@@@", dirloc, repr(s), dir == None, ent
            if s == "":
                continue
            
            if dir == None:
                # tried to traverse a file or a
                # non-existent directory
                return (None, None, False)
            
            if s == "" or s == ".":
                continue
            if s == "..":
                dotent = dir[0]
                dir.close()
                dirloc = (dotent[4], dotent[5])
                ent = self._dirloc_to_ent(dirloc)
                dir = self._directory(dirloc, ent[4], ent[2],
                              name
                              = "<path_search temp>")
                continue

            dir_cluster = ent[4]
            (i, ent) = self.search_directory(dir, s)
            dir.close()
            dir = None

            if ent == None:
                continue
            
            dirloc = (dir_cluster, i)
            if ent[0] & DF_DIR:
                dir = self._directory(dirloc, ent[4], ent[2],
                              name
                              = "<path_search temp>")

        if dir != None:
            dir.close()
            
        return (dirloc, ent, dir != None)

    def open(self, filename, mode = "r"):
        """Open a file, returning a new file-like object for it."""
        
        (dirloc, ent, is_dir) = self.path_search(filename)
        # print "@@@ open", (dirloc, ent)
        if dirloc == None or (ent == None and is_dir):
            raise path_not_found(filename)
        if is_dir:
            raise io_error(EISDIR, "not a regular file",
                     filename)
        if ent == None:
            if mode[0] not in "wa":
                raise file_not_found(filename)
            name = filename.split("/")[-1]
            (dirloc, ent) = self.create_dir_entry(dirloc, name,
                                  DF_FILE | DF_RWX
                                  | DF_0400);
            self.flush()
        elif mode[0] == "w":
            self.delete_dirloc(dirloc, True, filename)
            ent[4] = PS2MC_FAT_CHAIN_END
            ent[2] = 0
        return self.file(dirloc, ent[4], ent[2], mode, filename)

    def dir_open(self, filename, mode = "rb"):
        (dirloc, ent, is_dir) = self.path_search(filename)
        if dirloc == None:
            raise path_not_found(filename)
        if ent == None:
            raise dir_not_found(filename)
        if not is_dir:
            raise io_error(ENOTDIR, "not a directory", filename)
        return self.directory(dirloc, ent[4], ent[2], mode, filename)

    def mkdir(self, filename):
        (dirloc, ent, is_dir) = self.path_search(filename)
        if dirloc == None:
            raise path_not_found(filename)
        if ent != None:
            raise io_error(EEXIST, "directory exists", filename)
        a = filename.split("/")
        name = a.pop()
        while name == "":
            name = a.pop()
        self.create_dir_entry(dirloc, name, DF_DIR | DF_RWX | DF_0400)
        self.flush()

    def _is_empty(self, dirloc, ent, filename):
        """Check if a directory is empty."""
        
        dir = self._directory(dirloc, ent[4], ent[2], "rb",
                      filename)
        try:
            for i in range(2, len(dir)):
                if dir[i][0] & DF_EXISTS:
                    return False
        finally:
            dir.close()
        return True
        
    def remove(self, filename):
        """Remove a file or empty directory."""
        
        (dirloc, ent, is_dir) = self.path_search(filename)
        if dirloc == None:
            raise path_not_found(filename)
        if ent == None:
            raise file_not_found(filename)
        if is_dir:
            if ent[4] == 0:
                raise io_error(EACCES,
                         "cannot remove"
                         " root directory")
            if not self._is_empty(dirloc, ent, filename):
                raise io_error(ENOTEMPTY,
                         "directory not empty",
                         filename)
        self.delete_dirloc(dirloc, False, filename)
        self.flush()

    def chdir(self, filename):
        (dirloc, ent, is_dir) = self.path_search(filename)
        if dirloc == None:
            raise path_not_found(filename)
        if ent == None:
            raise dir_not_found(filename)
        if not is_dir:
            raise io_error(ENOTDIR, "not a directory", filename)
        self.curdir = dirloc

    def get_mode(self, filename):
        """Get mode bits of a file.

        Returns None if the filename doesn't exist, rather than
        throwing a error."""
        
        (dirloc, ent, is_dir) = self.path_search(filename)
        if ent == None:
            return None
        return ent[0]
    
    def get_dirent(self, filename):
        """Get the raw directory entry tuple for a file."""
        
        (dirloc, ent, is_dir) = self.path_search(filename)
        if dirloc == None:
            raise path_not_found(filename)
        if ent == None:
            raise file_not_found(filename)
        return ent

    def set_dirent(self, filename, new_ent):
        """Set various directory entry fields of a file.

        Not all fields can be changed.  If a field in new_ent
        is set to None then is not changed."""
        
        (dirloc, ent, is_dir) = self.path_search(filename)
        if dirloc == None:
            raise path_not_found(filename)
        if ent == None:
            raise file_not_found(filename)
        dir = self._opendir_parent_dirloc(dirloc)
        try:
            dir[dirloc[1]] = new_ent
        finally:
            dir.close()
        self.flush()
        return ent

    def import_save_file(self, sf, ignore_existing, dirname = None):
        """Copy the contents a ps2_save_file object to a directory.

        If ingore_existing is true and the directory being imported
        to already exists then False is returned instead of raising
        an error.  If dirname is given then the save file is copied
        to that directory instead of the directory specified by
        the save file.
        """
        
        dir_ent = sf.get_directory()
        if dirname == None:
            dir_ent_name = dir_ent[8].decode("ascii")
            dirname = "/" + dir_ent_name
        else:
            if dirname == "":
                raise path_not_found(dirname)
            
            # remove trailing slashes
            dirname = dirname.rstrip("/")
            if dirname == "":
                dirname = "/"
            dir_ent_name = dirname.split("/")[0]

        (root_dirloc, ent, is_dir) = self.path_search(dirname)
        if root_dirloc == None:
            raise path_not_found(dirname)
        if ent != None:
            if ignore_existing:
                return False
            raise io_error(EEXIST, "directory exists", dirname)
        mode = DF_DIR | (dir_ent[0] & ~DF_FILE)

        (dir_dirloc, ent) = self.create_dir_entry(root_dirloc,
                              dir_ent_name,
                              mode)
        try:
            assert dirname != "/"
            dirname = dirname + "/"
            for i in range(dir_ent[2]):
                (ent, data) = sf.get_file(i)
                mode = DF_FILE | (ent[0] & ~DF_DIR)
                (dirloc, ent) = self.create_dir_entry(dir_dirloc, ent[8].decode("ascii"), mode)
                # print "@@@ file", dirloc, ent[4], ent[2]
                f = self.file(dirloc, ent[4], ent[2], "wb", dirname + ent[8].decode("ascii"))
                try:
                    f.write(data)
                finally:
                    f.close()
        except EnvironmentError:
            type, what, where = sys.exc_info()
            try:
                try:
                    for i in range(dir_ent[2]):
                        (ent, data) = sf.get_file(i)
                        # print "@@@ remove", ent[8]
                        self.remove(dirname + ent[8])
                except EnvironmentError as why:
                    # print "@@@ failed", why
                    pass
            
                try:
                    # print "@@@ remove dir", dirname
                    self.remove(dirname)
                except EnvironmentError as why:
                    # print "@@@ failed", why
                    pass
                raise type(what, where)
            finally:
                del where

        # set modes and timestamps to those of the save file
        
        dir = self._opendir_dirloc(dir_dirloc, "r+b")
        try:
            for i in range(dir_ent[2]):
                dir[i + 2] = sf.get_file(i)[0]
        finally:
            dir.close()
            
        dir = self._opendir_dirloc(root_dirloc, "r+b")
        try:
            dir[dir_dirloc[1]] = dir_ent
        finally:
            dir.close()

        self.flush()
        return True

    def export_save_file(self, filename):
        (dir_dirloc, dirent, is_dir) = self.path_search(filename)
        if dir_dirloc is None:
            raise path_not_found(filename)
        if dirent is None:
            raise dir_not_found(filename)
        if not is_dir:
            raise io_error(ENOTDIR, "not a directory", filename)
        if dir_dirloc == (0, 0):
            raise io_error(EACCES, "can't export root directory", filename)
        sf = ps2save.PS2SaveFile()
        files = []
        f = None
        dir = self._directory(dir_dirloc, dirent[4], dirent[2], "rb", filename)
        try:
            for i in range(2, dirent[2]):
                ent = dir[i]
                if not mode_is_file(ent[0]):
                    print ("warning: %s/%s is not a file, ingored." % (dirent[8], ent[8]))
                    continue
                f = self.file((dirent[4], i), ent[4], ent[2], "rb")
                data = f.read(ent[2])
                f.close()
                assert len(data) == ent[2]
                files.append((ent, data))
        finally:
            if f is not None:
                f.close()
            dir.close()
        dirent[2] = len(files)
        sf.set_directory(dirent)
        for (i, (ent, data)) in enumerate(files):
            sf.set_file(i, ent, data)
        return sf

    def _remove_dir(self, dirloc, ent, dirname):
        """Recurse over a directory tree to remove it.
        If not "", dirname must end with a slash (/)."""

        first_cluster = ent[4]
        length = ent[2]
        dir = self._directory(dirloc, first_cluster, length,
                      "rb", dirname)
        try:
            ents = list(enumerate(dir))
        finally:
            dir.close()
        for (i, ent) in ents[2:]:
            mode = ent[0]
            if not (mode & DF_EXISTS):
                continue
            if mode & DF_DIR:
                self._remove_dir((first_cluster, i), ent,
                         dirname + ent[8] + "/")
            else:
                # print "deleting", dirname + ent[8]
                self.delete_dirloc((first_cluster, i), False,
                           dirname + ent[8].decode("utf-8"))
        self.delete_dirloc(dirloc, False, dirname)
        
    def rmdir(self, dirname):
        """Recursively delete a directory."""
        
        (dirloc, ent, is_dir) = self.path_search(dirname)
        if dirloc == None:
            raise path_not_found(dirname)
        if ent == None:
            raise dir_not_found(dirname)
        if not is_dir:
            raise io_error(ENOTDIR, "not a directory", dirname)
        if dirloc == (0, 0):
            raise io_error(EACCES, "can't delete root directory",
                     dirname)

        if dirname != "" and dirname[-1] != "/":
            dirname += "/"
        self._remove_dir(dirloc, ent, dirname)

    def get_free_space(self):
        """Returns the amount of free space in bytes."""
        
        free = 0
        for i in range(self.allocatable_cluster_end):
            if (self.lookup_fat(i) & PS2MC_FAT_ALLOCATED_BIT) == 0:
                free += 1
        return free * self.cluster_size

    def get_allocatable_space(self):
        """Returns the total amount of allocatable space in bytes."""
        return self.allocatable_cluster_limit * self.cluster_size
    
    def _check_file(self, fat, first_cluster, length):
        cluster = first_cluster
        i = 0
        while cluster != PS2MC_FAT_CHAIN_END:
            if cluster < 0 or cluster >= len(fat):
                return "invalid cluster in chain"
            if fat[cluster]:
                return "cross linked chain"
            i += 1
            # print cluster,
            fat[cluster] = 1
            next = self.lookup_fat(cluster)
            if next == PS2MC_FAT_CHAIN_END:
                break
            if (next & PS2MC_FAT_ALLOCATED_BIT) == 0:
                return "unallocated cluster in chain"
            cluster = next & ~PS2MC_FAT_ALLOCATED_BIT
        file_cluster_end = div_round_up(length, self.cluster_size)
        if i < file_cluster_end:
            return "chain ends before end of file"
        elif i > file_cluster_end:
            return "chain continues after end of file"
        return None

    def _check_dir(self, fat, dirloc, dirname, ent):
        why = self._check_file(fat, ent[4],
                       ent[2] * PS2MC_DIRENT_LENGTH)
        if why != None:
            print("bad directory:", dirname + ":", why)
            return False
        ret = True
        first_cluster = ent[4]
        length = ent[2]
        dir = self._directory(dirloc, first_cluster, length,
                      "rb", dirname)
        dot_ent = dir[0]
        if dot_ent[8].decode("ascii") != ".":
            print("bad directory:", dirname + ': missing "." entry')
            ret = False
        if (dot_ent[4], dot_ent[5]) != dirloc:
            print("bad directory:", dirname + ': bad "." entry')
            ret = False
        if dir[1][8].decode("ascii") != "..":
            print("bad directory:", (dirname
                         + ': missing ".." entry'))
            ret = False
        for i in range(2, length):
            ent = dir[i]
            mode = ent[0]
            if not (mode & DF_EXISTS):
                continue
            if mode & DF_DIR:
                if not self._check_dir(fat, (first_cluster, i),
                               dirname + ent[8].decode("ascii") + "/", ent):
                    ret = False
            else:
                why = self._check_file(fat, ent[4], ent[2])
                if why != None:
                    print("bad file:", (dirname + ent[8].decode("ascii") + ":"), why)
                    ret = False
                
        dir.close()
        return ret
        
    def check(self):
        """Run a simple file system check.

        Any problems found are reported to stdout."""
        
        ret = True

        fat_len = int(str(self.allocatable_cluster_end)) 
        if not isinstance(fat_len, int):
            raise error("Memory card image too big to check.")

        fat = array.array('B', [0]) * fat_len

        cluster = self.read_allocatable_cluster(0)
        ent = unpack_dirent(cluster[:PS2MC_DIRENT_LENGTH])
        ret = self._check_dir(fat, (0, 0), "/", ent)

        lost_clusters = 0
        for i in range(self.allocatable_cluster_end):
            a = self.lookup_fat(i)
            if (a & PS2MC_FAT_ALLOCATED_BIT) and not fat[i]:
                print(i, end=' ')
                lost_clusters += 1
        if lost_clusters > 0:
            print()
            print("found", lost_clusters, "lost clusters")
            ret = False
            
        return ret

    def _glob(self, dirname, components):
        pattern = components[0]
        if len(components) == 1:
            if pattern == "":
                return [dirname]
            dir = self.dir_open(dirname)
            try:
                return [dirname + ent[8].decode("ascii")
                    for ent in dir
                    if ((ent[0] & DF_EXISTS) and (ent[8].decode("ascii") not in [".", ".."]
                         or ent[8].decode("ascii") == pattern)
                        and fnmatch.fnmatchcase(ent[8].decode("ascii"), pattern))]
            finally:
                dir.close()
        if pattern == "":
            return self._glob(dirname + "/", components[1:])
        if dirname == "":
            dir = self.dir_open(".")
        else:
            dir = self.dir_open(dirname)
        try:
            ret = []
            for ent in dir:
                name = ent[8].decode("ascii")
                if ((ent[0] & DF_EXISTS) == 0
                    or (ent[0] & DF_DIR) == 0):
                    continue
                if name == "." or name == "..":
                    if pattern != name:
                        continue
                elif not fnmatch.fnmatchcase(name, pattern):
                    continue
                ret += self._glob(dirname + name + "/",
                          components[1:])
        finally:
            dir.close()
        return ret
        
    def glob(self, pattern):
        if pattern == "":
            return []
        ret = self._glob("", pattern.split("/"))
        # print pattern, "->", ret
        return self._glob("", pattern.split("/"))

    def get_icon_sys(self, dirname):
        """Get contents of a directory's icon.sys file, if it exits."""

        icon_sys = dirname + "/icon.sys"
        mode = self.get_mode(icon_sys)
        if mode == None or not mode_is_file(mode):
            return None
        f = self.open(icon_sys, "rb")
        s = f.read(964)
        f.close()
        if len(s) == 964 and s[0:4] == b"PS2D":
            return s
        return None

    def dir_size(self, dirname):
        """Calculate the total size of the contents of a directory."""

        dir = self.dir_open(dirname)
        try:
            length = round_up(len(dir) * PS2MC_DIRENT_LENGTH,
                      self.cluster_size)
            for ent in dir:
                name = ent[8].decode("ascii")
                if mode_is_file(ent[0]):
                    length += round_up(ent[2], self.cluster_size)
                elif mode_is_dir(ent[0]) and name not in [".", ".."]:
                    length += self.dir_size(dirname + "/" + name)
        finally:
            dir.close()
        return length
            
    def flush(self):
        self.flush_alloc_cluster_cache()
        self.flush_fat_cache()
        if self.modified:
            self.write_superblock()
        self.f.flush()
        
    def close(self):
        """Close all open files.

        Disconnects, but doesn't close the file object used
        access the raw image.  After this method has been
        called on a ps2mc object, it can no longer be used."""
        
        # print "ps2mc.close"
        try:
            f = self.f
            if f == None or getattr(f, "closed", False):
                # print "closed"
                return
            open_files = self.open_files
            # print "open_files", open_files
            if open_files != None:
                # this is complicated by the fact as
                # files are closed they will remove
                # themselves from the list of open files
                for (dir, files) in list(open_files.values()):
                    for f in list(files):
                        f.close()
                while len(open_files) > 0:
                    (k, v) = open_files.popitem()
                    (dir, files) = v
                    if dir != None:
                        dir.close()
            if self.rootdir != None:
                self.rootdir.close()
            if self.fat_cache != None:
                self.flush()
        finally:
            self.open_files = None
            self.fat_cache = None
            self.f = None
            self.rootdir = None

    def __del__(self):
        # print "ps2mc.__del__"
        try:
            self.close()
        except:
            sys.stderr.write("ps2mc.__del__: \n")
            traceback.print_exc()
