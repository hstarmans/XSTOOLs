#!/usr/bin/python
# -*- coding: utf-8 -*-

# /***********************************************************************************
# *   This program is free software; you can redistribute it and/or
# *   modify it under the terms of the GNU General Public License
# *   as published by the Free Software Foundation; either version 2
# *   of the License, or (at your option) any later version.
# *
# *   This program is distributed in the hope that it will be useful,
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# *   GNU General Public License for more details.
# *
# *   You should have received a copy of the GNU General Public License
# *   along with this program; if not, write to the Free Software
# *   Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA
# *   02111-1307, USA.
# *
# *   (c)2012 - X Engineering Software Systems Corp. (www.xess.com)
# ***********************************************************************************/

"""
Object for reading and writing memory or registers.
"""

import logging
import itertools
from xshostio import *


class XsMemIo(XsHostIo):

    """Object for reading and writing memory or registers."""

    # Memory opcodes.
    _NOP_OPCODE = XsBitarray('00'[::-1])
    _READ_OPCODE = XsBitarray('11'[::-1])  # Read from memory.
    _WRITE_OPCODE = XsBitarray('10'[::-1])  # Write to memory.
    _SIZE_OPCODE = XsBitarray('01'[::-1])  # Get the address and data widths of memory.
    _SIZE_RESULT_LENGTH = 16  # Length of _SIZE_OPCODE result.

    def __init__(
        self,
        xsusb_id=DEFAULT_XSUSB_ID,
        module_id=DEFAULT_MODULE_ID,
        xsjtag_port=None,
        ):
        """Setup a DUT I/O object.
        
        xsusb_id = The ID for the USB port.
        module_id = The ID for the DUT I/O module in the FPGA.
        xsjtag_port = The Xsjtag USB port object. (Use this if not using xsusb_id.)
        """

        # Setup the super-class object.
        XsHostIo.__init__(self, xsjtag_port=xsjtag_port,
                          xsusb_id=xsusb_id, module_id=module_id)
        # Get the number of inputs and outputs of the DUT.
        (self.address_width, self.data_width) = self._get_mem_widths()
        assert self.address_width != 0
        assert self.data_width != 0
        logging.debug('address width = ' + str(self.address_width))
        logging.debug('data width = ' + str(self.data_width))

    def _get_mem_widths(self):
        """Return the (address_width, data_width) of the memory."""

        SKIP_CYCLES = 1  # Skip cycles between issuing command and reading back result.
        # Send the opcode and then read back the bits with the memory's address and data width.
        params = self.send_rcv(payload=self._SIZE_OPCODE,
                               num_result_bits=self._SIZE_RESULT_LENGTH
                               + SKIP_CYCLES)
        params = params[SKIP_CYCLES:]  # Remove the skipped cycles.
        # The address width is in the first half of the bit array.
        address_width = params[:self._SIZE_RESULT_LENGTH / 2].to_int()
        # The data width is in the last half of the bit array.
        data_width = params[self._SIZE_RESULT_LENGTH / 2:].to_int()
        return (address_width, data_width)

    def read(self, begin_address, num_of_reads=1):
        """Return a list of bit arrays read from memory.
        
        begin_address = memory address of first read.
        num_of_reads = number of memory reads to perform.
        """

        # Start the payload with the READ_OPCODE.
        payload = XsBitarray(self._READ_OPCODE)
        # Append the memory address to the payload.
        payload.extend(XsBitarray.from_int(begin_address,
                       self.address_width))
        # Send the opcode and beginning address and then read back the memory data.
        # The number of values read back is one more than requested because the first value
        # returned is crap since the memory isn't ready to respond.
        result = self.send_rcv(payload=payload,
                               num_result_bits=self.data_width
                               * (num_of_reads + 1))
        result = result[self.data_width:]  # Remove the first data value which is crap.
        if num_of_reads == 1:
            # Return the result bit array if there's only a single read.
            return result
        else:
            # Otherwise, return a list of bit arrays with data_width bits by partitioning the result bit array.
            return [d for d in itertools.izip(*[iter(result)]
                    * self.data_width)]

    def write(self, begin_address, data):
        """Write a list of bit arrays to the memory.
        
        begin_address = memory address of first write.
        data = list of bit arrays or integers.
        """

        # Start the payload with the WRITE_OPCODE.
        payload = XsBitarray(self._WRITE_OPCODE)
        # Append the memory address to the payload.
        payload.extend(XsBitarray.from_int(begin_address,
                       self.address_width))
        # Concatenate the data to the payload.
        for d in data:
            if type(d) == type(1):
                # Convert integers to bit arrays.
                payload.extend(XsBitarray.from_int(d, self.data_width))
            else:
                # Assume it's a bit array so just concatenate it.
                payload.extend(d)
        assert payload.length() > self._WRITE_OPCODE.length()
        # Send the payload to write the data to memory.
        self.send_rcv(payload=payload, num_result_bits=0)


XsMem = XsMemIo  # Associate the old XsMem class with the new XsMemIo class.
