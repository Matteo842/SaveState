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

"""Interface for working with PS2 icon.sys files."""

import struct
from . import utils
from .sjistab import shift_jis_normalize_table
import sys


class Error(Exception):
    """Base for all exceptions specific to this module."""
    pass

class Corrupt(Error):
    """Corrupt icon file."""

    def __init__(self, msg):
        super().__init__(self, "Corrupt icon.sys: " + msg)


_PS2_ICON_SYS_MAGIC = b"PS2D"

_icon_sys_struct = struct.Struct("<4sHHII"
                                 "4I4I4I4I" # background colors 
                                 "4f4f4f" # light dirs
                                 "4f4f4f4f" # light colors
                                 "68s64s64s64s512s")

assert _icon_sys_struct.size == 964

#
# Table of graphically similar ASCII characters that can be used
# as substitutes for Unicode characters.
#
char_substs = {
    u'\u00a2': u"c",
    u'\u00b4': u"'",
    u'\u00d7': u"x",
    u'\u00f7': u"/",
    u'\u2010': u"-",
    u'\u2015': u"-",
    u'\u2018': u"'",
    u'\u2019': u"'",
    u'\u201c': u'"',
    u'\u201d': u'"',
    u'\u2032': u"'",
    u'\u2212': u"-",
    u'\u226a': u"<<",
    u'\u226b': u">>",
    u'\u2500': u"-",
    u'\u2501': u"-",
    u'\u2502': u"|",
    u'\u2503': u"|",
    u'\u250c': u"+",
    u'\u250f': u"+",
    u'\u2510': u"+",
    u'\u2513': u"+",
    u'\u2514': u"+",
    u'\u2517': u"+",
    u'\u2518': u"+",
    u'\u251b': u"+",
    u'\u251c': u"+",
    u'\u251d': u"+",
    u'\u2520': u"+",
    u'\u2523': u"+",
    u'\u2524': u"+",
    u'\u2525': u"+",
    u'\u2528': u"+",
    u'\u252b': u"+",
    u'\u252c': u"+",
    u'\u252f': u"+",
    u'\u2530': u"+",
    u'\u2533': u"+",
    u'\u2537': u"+",
    u'\u2538': u"+",
    u'\u253b': u"+",
    u'\u253c': u"+",
    u'\u253f': u"+",
    u'\u2542': u"+",
    u'\u254b': u"+",
    u'\u25a0': u"#",
    u'\u25a1': u"#",
    u'\u3001': u",",
    u'\u3002': u".",
    u'\u3003': u'"',
    u'\u3007': u'0',
    u'\u3008': u'<',
    u'\u3009': u'>',
    u'\u300a': u'<<',
    u'\u300b': u'>>',
    u'\u300c': u'[',
    u'\u300d': u']',
    u'\u300e': u'[',
    u'\u300f': u']',
    u'\u3010': u'[',
    u'\u3011': u']',
    u'\u3014': u'[',
    u'\u3015': u']',
    u'\u301c': u'~',
    u'\u30fc': u'-',
}


def shift_jis_conv(src, encoding=None):
    """Convert Shift-JIS strings to a graphically similar representation.

    If encoding is "unicode" then a Unicode string is returned, otherwise
    a string in the encoding specified is returned.  If necessary,
    graphically similar characters are used to replace characters not
    exactly    representable in the desired encoding.
    """

    if encoding is None:
        encoding = sys.getdefaultencoding()
    if encoding == "shift_jis":
        return src
    u = src.decode("shift_jis", "replace")
    if encoding == "unicode":
        return u
    a = []
    for uc in u:
        try:
            uc.encode(encoding)
            a.append(uc)
        except UnicodeError:
            for uc2 in shift_jis_normalize_table.get(uc, uc):
                a.append(char_substs.get(uc2, uc2))

    return "".join(a)


class IconSys:
    def __init__(self, data):

        if len(data) != _icon_sys_struct.size:
            raise Corrupt("icon.sys file has invalid size.")

        d = _icon_sys_struct.unpack(data)

        if d[0] != _PS2_ICON_SYS_MAGIC:
            raise Corrupt("icon.sys has incorrect magic.")

        self._title_line_offset = d[2]
        self.background_transparency = d[4]

        self.bg_colors = (d[5:9], d[9:13], d[13:17], d[17:21])

        self.light_dirs = (d[21:25], d[25:29], d[29:33])
        self.light_colors = (d[33:37], d[37:41], d[41:45])
        self.ambient_light_color = d[45:49]

        self._title_sjis = utils.zero_terminate(d[49])
        self.icon_file_normal = utils.zero_terminate(d[50]).decode("ascii")
        self.icon_file_copy = utils.zero_terminate(d[51]).decode("ascii")
        self.icon_file_delete = utils.zero_terminate(d[52]).decode("ascii")

    def get_title(self, encoding):
        title2 = shift_jis_conv(self._title_sjis[self._title_line_offset:], encoding)
        title1 = shift_jis_conv(self._title_sjis[:self._title_line_offset], encoding)
        return title1, title2
