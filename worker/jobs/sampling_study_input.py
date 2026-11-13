"""Linux child-only immutable input for the existing file-based recognizer.

The sealed anonymous file is readable via this process's procfs fd path. No
mutable filename or caller-controlled symlink is accepted. Failure/cancellation
can leave native decoding running after its awaiter returns: retain that fd until
OS process exit rather than closing/reusing it early. The supervised parent is
still the only authority that establishes process drain and releases capacity.
"""
import os
from pathlib import Path
import stat
import sys

from worker.jobs.sampling_study_manifest import validate_audio
from worker.jobs.sampling_study_store import StudyFence

# Keep objects alive, but never register an atexit close that could race native
# work. OS process teardown closes these fds. The child stops after first failure.
_RETAINED_INPUTS = []

# Linux UAPI linux/fcntl.h constants. Some supported Python builds omit their
# symbolic exports; the syscall ABI is unchanged. Never use this on other OSes.
_ADD_SEALS, _GET_SEALS, _IMMUTABLE_SEALS = 1033, 1034, 0x000F


class SealedStudyInput:
    def __init__(self, data, expected_hash):
        if sys.platform != 'linux' or not hasattr(os, 'memfd_create'):
            raise StudyFence('study_sealed_input_unsupported')
        if _RETAINED_INPUTS:
            raise StudyFence('study_input_uncertain_process')
        validate_audio(data, expected_hash)
        self.fd = None
        self.expected_hash = expected_hash
        self.size = len(data)
        self.retained = False
        try:
            import fcntl
            seals = _IMMUTABLE_SEALS
            fd = os.memfd_create('sampling-study.wav', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
            self.fd = fd
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise StudyFence('study_input_write_incomplete')
                view = view[written:]
            os.lseek(fd, 0, os.SEEK_SET)
            fcntl.fcntl(fd, _ADD_SEALS, seals)
            self.seals = seals
            self.identity = (os.fstat(fd).st_dev, os.fstat(fd).st_ino)
            self.path = Path('/proc/self/fd') / str(fd)
            self.verify()
        except BaseException:
            # Not exposed to a recognizer yet, so closing is safe here.
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            raise

    def verify(self):
        """Recheck the exact sealed inode/hash immediately before reservation."""
        import fcntl
        if self.fd is None:
            raise StudyFence('study_input_closed')
        own = os.fstat(self.fd)
        exposed = self.path.stat()
        if (not stat.S_ISREG(own.st_mode) or own.st_size != self.size or
                (own.st_dev, own.st_ino) != self.identity or
                (exposed.st_dev, exposed.st_ino) != self.identity or
                fcntl.fcntl(self.fd, _GET_SEALS) & self.seals != self.seals):
            raise StudyFence('study_input_file_changed')
        data = os.pread(self.fd, 1000001, 0)
        validate_audio(data, self.expected_hash)
        return self.path

    def close_after_success(self):
        # A successful provider response occurs only after awaited fingerprint
        # creation and HTTP settlement. It is not a timeout/native-drain shortcut.
        if self.retained:
            raise StudyFence('study_input_retained_until_exit')
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def retain_until_exit(self):
        if self.fd is not None and not self.retained:
            self.retained = True
            _RETAINED_INPUTS.append(self)
