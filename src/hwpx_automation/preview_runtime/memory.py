# SPDX-License-Identifier: Apache-2.0
"""Read the resident memory of an owned renderer child without extra packages."""
import ctypes
import subprocess
import sys


def resident_bytes(proc):
    if sys.platform == 'win32':
        class Counters(ctypes.Structure):
            _fields_ = [('cb', ctypes.c_ulong), ('faults', ctypes.c_ulong)] + [
                (name, ctypes.c_size_t) for name in [
                    'peakWorkingSet', 'workingSet', 'quotaPeakPaged', 'quotaPaged',
                    'quotaPeakNonPaged', 'quotaNonPaged', 'pageFile', 'peakPageFile']]
        fn = ctypes.WinDLL('psapi').GetProcessMemoryInfo
        fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
        fn.restype = ctypes.c_int
        value = Counters()
        value.cb = ctypes.sizeof(value)
        return value.workingSet if fn(int(proc._handle), ctypes.byref(value), value.cb) else None
    if sys.platform == 'darwin':
        return macos_resident_bytes(proc.pid)
    return None


def macos_resident_bytes(pid):
    # Apple ps(1): rss is in 1024-byte units; an empty heading suppresses it.
    # https://github.com/apple-oss-distributions/adv_cmds/blob/main/ps/ps.1
    # Query only our child's numeric PID, without a shell or PATH resolution.
    if type(pid) is not int or pid <= 0:
        raise ValueError('A positive child PID is required.')
    try:
        result = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'rss='],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=.5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    if result.returncode or not value or not value.isdigit():
        return None
    return int(value) * 1024
