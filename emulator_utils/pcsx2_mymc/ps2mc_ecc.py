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

"""
Routines for calculating the Hamming codes, a simple form of error
correcting codes (ECC), as used on PS2 memory cards.  
"""

import array

from .round import div_round_up

__ALL__ = ["ECC_CHECK_OK", "ECC_CHECK_CORRECTED", "ECC_CHECK_FAILED",
           "ecc_calculate", "ecc_check", "ecc_calculate_page", "ecc_check_page"]

ECC_CHECK_OK = 0
ECC_CHECK_CORRECTED = 1
ECC_CHECK_FAILED = 2


def _popcount(a):
    count = 0
    while a != 0:
        a &= a - 1
        count += 1
    return count


def _parityb(a):
    a = (a ^ (a >> 1))
    a = (a ^ (a >> 2))
    a = (a ^ (a >> 4))
    return a & 1


def _make_ecc_tables():
    parity_table = [_parityb(b) for b in range(256)]
    cpmasks = [0x55, 0x33, 0x0F, 0x00, 0xAA, 0xCC, 0xF0]

    column_parity_masks = [None] * 256
    for b in range(256):
        mask = 0
        for i in range(len(cpmasks)):
            mask |= parity_table[b & cpmasks[i]] << i
            column_parity_masks[b] = mask

    return parity_table, column_parity_masks


_parity_table, _column_parity_masks = _make_ecc_tables()


def _ecc_calculate(s):
    """Calculate the Hamming code for a 128 byte long string or byte array."""

    if not isinstance(s, array.array):
        a = array.array('B')
        a.frombytes(s)
        s = a
    column_parity = 0x77
    line_parity_0 = 0x7F
    line_parity_1 = 0x7F
    for i in range(len(s)):
        b = s[i]
        column_parity ^= _column_parity_masks[b]
        if _parity_table[b]:
            line_parity_0 ^= ~i
            line_parity_1 ^= i
    return [column_parity, line_parity_0 & 0x7F, line_parity_1]


def _ecc_check(s, ecc):
    """Detect and correct any single bit errors.
    
    The parameters "s" and "ecc", the data and expected Hamming code 
    repectively, must be modifiable sequences of integers and are
    updated with the corrected values if necessary."""

    computed = ecc_calculate(s)
    if computed == ecc:
        return ECC_CHECK_OK

    #print
    #_print_bin(0, s.tobytes())
    #print "computed %02x %02x %02x" % tuple(computed)
    #print "actual %02x %02x %02x" % tuple(ecc)

    # ECC mismatch

    cp_diff = (computed[0] ^ ecc[0]) & 0x77
    lp0_diff = (computed[1] ^ ecc[1]) & 0x7F
    lp1_diff = (computed[2] ^ ecc[2]) & 0x7F
    lp_comp = lp0_diff ^ lp1_diff
    cp_comp = (cp_diff >> 4) ^ (cp_diff & 0x07)

    #print "%02x %02x %02x %02x %02x" % (cp_diff, lp0_diff, lp1_diff,
    #                    lp_comp, cp_comp)

    if lp_comp == 0x7F and cp_comp == 0x07:
        print("corrected 1")
        # correctable 1 bit error in data
        s[lp1_diff] ^= 1 << (cp_diff >> 4)
        return ECC_CHECK_CORRECTED
    if ((cp_diff == 0 and lp0_diff == 0 and lp1_diff == 0)
            or _popcount(lp_comp) + _popcount(cp_comp) == 1):
        print("corrected 2")
        # correctable 1 bit error in ECC
        # (and/or one of the unused bits was set)
        ecc[0] = computed[0]
        ecc[1] = computed[1]
        ecc[2] = computed[2]
        return ECC_CHECK_CORRECTED

    # uncorrectable error
    return ECC_CHECK_FAILED


def ecc_calculate_page(page):
    """Return a list of the ECC codes for a PS2 memory card page."""
    return [ecc_calculate(page[i * 128 : i * 128 + 128])
            for i in range(div_round_up(len(page), 128))]


def ecc_check_page(page, spare):
    """Check and correct any single bit errors in a PS2 memory card page."""

    failed = False
    corrected = False

    #chunks = [(array.array('B', page[i * 128 : i * 128 + 128]),
    #       map(ord, spare[i * 3 : i * 3 + 3]))
    #      for i in range(div_round_up(len(page), 128))]

    chunks = []
    for i in range(div_round_up(len(page), 128)):
        a = array.array('B')
        a.frombytes(page[i * 128 : i * 128 + 128])
        chunks.append((a, list(spare[i * 3 : i * 3 + 3])))

    r = [ecc_check(s, ecc)
         for (s, ecc) in chunks]
    ret = ECC_CHECK_OK
    if ECC_CHECK_CORRECTED in r:
        # rebuild sector and spare from the corrected versions
        page = b"".join([a[0].tobytes() for a in chunks])
        spare = bytes([a[1][i]
                       for a in chunks
                       for i in range(3)])
        ret = ECC_CHECK_CORRECTED
    if ECC_CHECK_FAILED in r:
        ret = ECC_CHECK_FAILED
    return ret, page, spare


ecc_calculate = _ecc_calculate
ecc_check = _ecc_check
