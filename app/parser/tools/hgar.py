#!/usr/bin/env python3

# HGAR packer/unpacker
# Mass-extract on Windows: forfiles /P C:\path_to\PSP_GAME\USRDIR\ /M *.har /S /C "C:\Python27\python.exe -c C:\path_to\hgar.py --extract @path"
# Mass-extract on Unix: find /path_to/PSP_GAME/USRDIR/ -name '*.har' -exec /path_to/hgar.py --extract {} \;

import os
import common as common

class HGArchiveFile(object):
    def __init__(self, long_name, short_name, size, 
                            encoded_identifier=None,
                            unknown_first=None,
                            unknown_last=None,
                            content=b''):
        self.long_name = long_name
        self.short_name = short_name
        self.size = size

        self.encoded_identifier = encoded_identifier
        self.identifier = 0

        self.unknown_first = unknown_first
        self.unknown_last = unknown_last

        self.content :bytes = content

    def get_viable_name(self):

        # Returns a file name for use when exporting content outside the container

        # V3 of the HGAR file format has a long name and a short name
        # While V1 only has a short name
        # Both have a weird identifier next to the short name

        # In the file names used by this script, we include all three in the form:
        # long_name#short_name#idNUMBER.short_file_format#long_file_format

        # But to simplify reading things visually, 
        # if long_name == short_name, and (if a file format exists) short_file_format == long_file_format then only:
        #     long_name#idNUMBER.long_file_format is used

        # Windows seems to have an issue where files have a period but then no extension format afterwards
        # This affects '7__1#id83.' in 'PSP_GAME/USRDIR/map/mapdata2.har' for example
        # Thus for this case we append "NOEXT"

        long_name = self.long_name
        short_name = self.short_name

        # Prepare long name
        long_name_file_format = ''
        if long_name:
            long_name = long_name.decode('ascii').rstrip(' \t\r\n\0')

            if '.' in long_name:
                (long_name, long_name_file_format) = long_name.rsplit('.', 1)
        else:
            long_name = ''
            long_name_file_format = ''

        # Prepare short name
        short_name_file_format = ''
        if short_name:
            short_name = short_name.decode('ascii').rstrip(' \t\r\n\0')

            if '.' in short_name:
                (short_name, short_name_file_format) = short_name.rsplit('.', 1)
        else:
            short_name = ''
            short_name_file_format = ''

        # Simplify the file format and file name if possible
        # This is done by this script to reduce visual clutter
        # in the naming of the extracted files
        file_name = ''
        file_format = ''
        
        if not long_name or long_name == short_name:
            file_name = short_name
        else:
            file_name = '%s#%s' % (long_name, short_name)

        if not long_name_file_format or long_name_file_format == short_name_file_format:
            file_format = short_name_file_format
        else:
            file_format = '%s#%s' % (short_name_file_format, long_name_file_format)

        # Append 'NOEXT' if file_format is blank due to Windows having an issue
        # with files that have a '.' but no extension
        if file_format == '':
            file_format = 'NOEXT'

        return '%s#id%s.%s' % (file_name, self.identifier, file_format)

    def encode_identifier(self, limit):
        compression_mask = 0
        if self.is_compressed:
            compression_mask = 0x80000000

        for guess_encode in range(0x7FFFFFFF, 0, -1):
            xor_mask = guess_encode & 0x7FFFFFFF
            mult_result = 0

            rounds = 6
            while rounds > 0:
                mult_result = ((mult_result ^ xor_mask) * 0x3D09) & 0xFFFFFFFF
                xor_mask >>= 5
                rounds -= 1

            mult_result &= (limit - 1)
            if mult_result == self.identifier:
                self.encoded_identifier = guess_encode | compression_mask
                return

    def decode_identifier(self, limit):
        self.is_compressed = ((self.encoded_identifier >> 31) == 1)

        xor_mask = self.encoded_identifier & 0x7FFFFFFF
        mult_result = 0

        rounds = 6
        while rounds > 0:
            mult_result = ((mult_result ^ xor_mask) * 0x3D09) & 0xFFFFFFFF
            xor_mask >>= 5
            rounds -= 1

        mult_result &= (limit - 1)
        self.identifier = mult_result


class HGArchive(object):
    # def __init__(self):
    #     self.version = None
    #     self.files: list[HGArchiveFile] = []
    #     self.calculate_identifier_limit()
    
    def __init__(self, version=None, files=[]):
        self.version = version
        self.files: list[HGArchiveFile] = files
        # Calculate the identifier limit based on the number of files
        self.calculate_identifier_limit()

    def add_file(self, long_name, short_name, size):
        new_file = HGArchiveFile(long_name, short_name, size)
        self.files.append(new_file)
        self.calculate_identifier_limit()
        return new_file

    def get_total_files(self):
        return len(self.files)

    def calculate_identifier_limit(self):
        # This limit seems to be a used as a mask
        # Find a power of 2 that is the next power up from the number of files
        number_of_files = len(self.files)
        current_limit = 16

        while (number_of_files > current_limit):
            current_limit *= 2
            if (current_limit > 32768):
                current_limit = 32768
                break

        self.identifier_limit = 2 * current_limit

    def decode_identifiers(self):
        # This must be done once finalizing a HGAR for saving (or after open is complete)
        # since the IDs depend on the # of files in the HGAR
        number = 0
        for file in self.files:
            file.decode_identifier(self.identifier_limit)
            # FIXME: When to USE???
            # file.number = number
            number += 1

    def build_v3_name_hash_table(self):
        if self.version != 3:
            return []

        slot_count = 2 * self.get_total_files()
        slots = [(0, 0xFFFF)] * slot_count
        long_name_offset = 0

        for file in self.files:
            long_name = file.long_name
            if isinstance(long_name, str):
                long_name = long_name.encode('ascii')
            if not long_name:
                raise ValueError('HGAR v3 files require a long name')

            name = long_name.rstrip(b'\0')
            name_hash = (sum(name) + 101 * len(name)) & 0xFFFF
            slot_index = name_hash % slot_count

            for _ in range(slot_count):
                if slots[slot_index][1] == 0xFFFF:
                    slots[slot_index] = (name_hash, long_name_offset)
                    break
                slot_index = (slot_index + 1) % slot_count
            else:
                raise ValueError('HGAR v3 name hash table is full')

            long_name_offset += 4 + len(long_name)
            if long_name_offset > 0xFFFF:
                raise ValueError('HGAR v3 long-name table exceeds 65535 bytes')

        return slots

    def info(self):
        print('Version: %s' % self.version)
        print('Number of Files: %s' % len(self.files))
        print('Number of Files (Hex): 0x%s' % format(len(self.files), '08X'))
        print('Identifier limit:      0x%s' % format(self.identifier_limit, '08X'))

        print('Files:')
        for file in self.files:
            print('\tViable Name: %s' % file.get_viable_name())
            print('\tLong Name: %s' % file.long_name)
            print('\tShort Name: %s' % file.short_name)
            print('\tCompressed: %s' % file.is_compressed)
            print('\tSize: %s' % file.size)
            # print('\tContent: %s' % file.content)
            if file.unknown_first:
                print('\tUnknown first: 0x%s' % format(file.unknown_first, '08X'))
            if file.unknown_last:
                print('\tUnknown last:  0x%s' % format(file.unknown_last, '08X'))
            print('\tEncoded Identifier: 0x%s' % format(file.encoded_identifier, '08X'))
            print('\tDecoded Identifier: 0x%s' % format(file.identifier, '08X'))
            print('')
            
    def generate_info(self, path):
        ''' Returns the information on each file.
        {
            filename: ".har"
            version: 1/3,
            contents:
                [
                    {
                        long_name: // Can be None
                        short_name:
                        encoded_identifier:
                        unknown1: // Can be None
                        unknown2: // Can be None
                        content: // exported_path, decompressed version.
                    }
                ]
        }
        '''
        
        
    def read_info(self):
        ''' Read the info file and constructs HGAR.
        '''
        
    def replace(self, file_to_replace, file_content, is_compressed=False):
        for file in self.files:
            if file.get_viable_name() == file_to_replace:
                file.content = file_content
                file.size = len(file_content)

                if is_compressed is False:
                    # Toggle off the compression flag
                    file.encoded_identifier &= 0x7FFFFFFF

                return

        raise Exception('Could not replace "%s", not found in archive!' % file_to_replace)

    def open(self, file_path):
        with open(file_path, 'rb') as f:
            # Store the filename.
            self.filename = os.path.basename(file_path)
            
            magic_number = f.read(4).decode('ascii', 'ignore')
            if magic_number != 'HGAR':
                raise Exception('Not an HGAR file!')

            self.version = common.read_uint16(f)
            if self.version not in (1, 3):
                raise Exception('Unknown HGAR version: %s' % self.version)
            
            number_of_files = common.read_uint16(f)

            file_header_offsets = [0] * number_of_files
            for i in range(0, number_of_files): 
                file_header_offsets[i] = common.read_uint32(f)

            file_unknowns = [(None, None)] * number_of_files
            file_long_names = [None] * number_of_files

            if self.version == 3:
                for i in range(0, number_of_files):
                    file_unknowns[i] = (common.read_uint32(f), common.read_uint32(f))

                for i in range(0, number_of_files):
                    # Read file number
                    file_number = common.read_uint32(f)

                    # Read name until null-terminator (but aligned to 32-bit boundaries)
                    long_name = b''
                    while True:
                        long_name += f.read(4)

                        if long_name[-1] == 0:
                            break

                    file_long_names[i] = long_name

                    if file_number != i:
                        print('\tWarning: File "%s" is stored as file number %s, but should be %s' % (long_name, file_number, i))

            for i in range(0, number_of_files):
                f.seek(file_header_offsets[i])

                short_name = f.read(0xC)
                reformatted_short_name = short_name[0:-4].rstrip() + short_name[-4:].rstrip()

                encoded_identifier = common.read_uint32(f)
                file_size = common.read_uint32(f)

                new_file = self.add_file(file_long_names[i], reformatted_short_name, file_size)
                new_file.encoded_identifier = encoded_identifier

                new_file.unknown_first = file_unknowns[i][0]
                new_file.unknown_last = file_unknowns[i][1]
                
                new_file.content = f.read(file_size)

                # The new file object will generate the short name and long name
                # upon creation, BUT overwrite these since we're opening
                # and know the exact values (instead of creating from scratch)
                new_file.short_name = reformatted_short_name
                new_file.long_name = file_long_names[i]

            # This must be done after the exact file count is known
            self.decode_identifiers()

    def save(self, file_path):
        with open(file_path, 'wb') as f:
            f.write(b'HGAR')

            common.write_uint16(f, self.version)

            number_of_files = self.get_total_files()

            common.write_uint16(f, number_of_files)

            # Calculate the header size to be able to calculate the file start offsets
            #                Magic + Version + nFiles + FileOffsets   
            size_of_header = 4 +     2 +       2 +      4 * number_of_files
            if self.version == 3:
                #                 Unknowns
                size_of_header += 8 * number_of_files

                # Add long names
                for file in self.files:
                    size_of_header += 4 + len(file.long_name)

            # Write file start offsets
            file_offset = size_of_header
            for file in self.files:
                common.write_uint32(f, file_offset)

                #              ShortName + Identifier + Size
                file_offset += 0xC       + 4 +   4

                # Actual file content
                file_offset += common.calculate_word_aligned_length(file.size)

            if self.version == 3:
                # This area is a global 2*N-slot name hash table, not two
                # independent metadata fields attached to each file.
                name_hash_slots = self.build_v3_name_hash_table()
                for slot_index in range(0, len(name_hash_slots), 2):
                    for name_hash, long_name_offset in name_hash_slots[
                        slot_index:slot_index + 2
                    ]:
                        common.write_uint16(f, name_hash)
                        common.write_uint16(f, long_name_offset)

                # Write long names
                for number, file in enumerate(self.files):
                    common.write_uint32(f, number)
                    long_name = file.long_name
                    if isinstance(long_name, str):
                        long_name = long_name.encode('ascii')
                    f.write(long_name)

            for file in self.files:
                # Write short name
                # FIXME: Need Binary
                short_name_name, short_name_extension = (file.short_name.encode('ascii') + b'.   ').split(b'.', 1)
                formatted_short_name = (short_name_name + b' ' * 8)[0:8] + b'.' + (short_name_extension + b' ' * 3)[0:3] 
                f.write(formatted_short_name)

                # Write encoded identifier
                # Do not generate a new identifier unless it's None
                # Why Would it be None ????
                if file.encoded_identifier is None:
                    file.encode_identifier(self.identifier_limit)
                common.write_uint32(f, file.encoded_identifier)

                # Write file size
                common.write_uint32(f, file.size)

                # Write content
                f.write(file.content)

                # Write padding
                padding_length = 4 - (file.size & 3)
                if padding_length != 4:
                    f.write(b'\0' * padding_length)

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 3:
        print('hgar.py <action> <archive.har>')
        print('')
        print('hgar.py --info <archive.har>')
        print('hgar.py --extract <archive.har>')
        print('hgar.py --decompress <archive.har>')
        print('hgar.py --replace <archive.har> <file_to_replace> <file_to_inject>')
        print('hgar.py --replace-raw <archive.har> <file_to_replace> <file_to_inject>')
        sys.exit(0)

    action = sys.argv[1]
    input_path = sys.argv[2]
    output_path = ''

    if len(input_path) == 0:
        print('Error: Empty input path provided')
        sys.exit(-1)

    if action in ('-i', '--info'):
        try:
            print('Opening %s:' % input_path)
            hgar = HGArchive()
            hgar.open(input_path)
            hgar.info()

        except Exception as e:
            print('Error: %s' % e)
            sys.exit(-1)

    elif action in ('-r', '--replace'):

        if len(sys.argv) < 5:
            print('hgar.py --replace <archive.har> <file_to_replace> <file_to_inject>')
            sys.exit(0)

        file_to_replace = sys.argv[3]
        file_to_inject = sys.argv[4]

        from zipped import ZipWrapper

        try:
            print('Opening %s:' % input_path)

            hgar = HGArchive()
            hgar.open(input_path)

            print('\tLoading %s' % file_to_inject)
            zip_wrapper = ZipWrapper()
            zip_wrapper.compress_from(file_to_inject)
            zip_wrapper.save(file_to_inject + '.COMPRESSED')

            file_content = ''
            with open(file_to_inject + '.COMPRESSED', 'rb') as f:
                file_content = f.read()
            
            print('\tReplacing %s' % file_to_replace)
            hgar.replace(file_to_replace, file_content, is_compressed=True)

            hgar.save(input_path + '_REPLACE')

        except Exception as e:
            print('Error: %s' % e)
            sys.exit(-1)

    elif action in ('-rr', '--replace-raw'):

        if len(sys.argv) < 5:
            print('hgar.py --replace-raw <archive.har> <file_to_replace> <file_to_inject>')
            sys.exit(0)

        file_to_replace = sys.argv[3]
        file_to_inject = sys.argv[4]

        try:
            print('Opening %s:' % input_path)

            hgar = HGArchive()
            hgar.open(input_path)

            print('\tLoading %s' % file_to_inject)
            file_content = ''
            with open(file_to_inject, 'rb') as f:
                file_content = f.read()
            
            print('\tReplacing %s' % file_to_replace)
            hgar.replace(file_to_replace, file_content, is_compressed=False)

            hgar.save(input_path + '_REPLACE')

        except Exception as e:
            print('Error: %s' % e)
            sys.exit(-1)

    elif action in ('-e', '--extract'):
        try:
            print('Opening %s:' % input_path)

            hgar = HGArchive()
            hgar.open(input_path)
            
            output_path = input_path + '.HGARPACK' + os.sep

            if not os.path.exists(output_path):
                os.makedirs(output_path)

            for file in hgar.files:
                print('\tExtracting: ' + file.get_viable_name())

                with open(output_path + file.get_viable_name(), 'wb') as w:
                    w.write(file.content)

        except Exception as e:
            print('Error: %s' % e)
            sys.exit(-1)

    elif action in ('-d', '--decompress'):
        # Import the zipped module only if decompressing
        # to save on load time for other use cases
        from zipped import ZipWrapper
        
        try:
            print('Opening %s:' % input_path)
            hgar = HGArchive()
            hgar.open(input_path)
            
            output_path = input_path + '.HGARPACK' + os.sep

            if not os.path.exists(output_path):
                os.makedirs(output_path)

            for file in hgar.files:
                print('\tExtracting: ' + file.get_viable_name())

                with open(output_path + file.get_viable_name(), 'wb') as w:
                    w.write(file.content)

                # Decompress as well?
                if file.is_compressed:
                    zip_wrapper = ZipWrapper()
                    zip_wrapper.open(output_path + file.get_viable_name())
                    zip_wrapper.decompress_as(output_path + file.get_viable_name() + '.DECOMPRESSED')

        except Exception as e:
            print('Error: %s' % e)
            sys.exit(-1)

    else:
        print('Error: Unknown action: %s' % action)
        sys.exit(-1)

    sys.exit(0)
