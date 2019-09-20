"""
Stress tests for probing block size.

To verify that this does not trigger https://bugzilla.redhat.com/1751722
run this script on multiple hosts accessing the same Gluster mount.

    $ python probe_block_size_stress.py /mount/path
    512
    512
    ...

"""

import sys
import atexit

from ioprocess import IOProcess

dir_path = sys.argv[1]

iop = IOProcess(timeout=10)
atexit.register(iop.close)

try:
    while True:
        print(iop.probe_block_size(dir_path))
except KeyboardInterrupt:
    pass
