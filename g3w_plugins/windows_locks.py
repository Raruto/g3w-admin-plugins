import contextlib
import ctypes
from ctypes import wintypes
import errno
import hashlib
import os
import subprocess
import time


kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.CreateSemaphoreW.argtypes = [ctypes.c_void_p, wintypes.LONG, wintypes.LONG, wintypes.LPCWSTR]
kernel.CreateSemaphoreW.restype = wintypes.HANDLE
kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel.CreateMutexW.restype = wintypes.HANDLE
kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel.WaitForSingleObject.restype = wintypes.DWORD
kernel.ReleaseSemaphore.argtypes = [wintypes.HANDLE, wintypes.LONG, ctypes.c_void_p]
kernel.ReleaseSemaphore.restype = wintypes.BOOL
kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
kernel.ReleaseMutex.restype = wintypes.BOOL
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.CloseHandle.restype = wintypes.BOOL


def close(handle, release=False):
    try:
        if release and not kernel.ReleaseSemaphore(handle, 1, None):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if not kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


@contextlib.contextmanager
def probe_gate(name):
    handle = kernel.CreateMutexW(None, False, name + "-gate")
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        result = kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
        if result not in (0, 0x80):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            if not kernel.ReleaseMutex(handle):
                raise ctypes.WinError(ctypes.get_last_error())
    finally:
        close(handle)


class Lock:
    def __init__(self, root, name, blocking):
        # ponytail: host-wide lock; distributed Windows deployments need a shared lock service.
        identity = os.path.normcase(str(root)).encode("utf-8")
        key = hashlib.sha256(identity).hexdigest()
        name = f"Global\\g3w-plugins-{name}-{key}"
        while True:
            # Serialize probes so the last abandoned semaphore handle can close.
            with probe_gate(name):
                self.handle = kernel.CreateSemaphoreW(None, 1, 1, name)
                if not self.handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                result = kernel.WaitForSingleObject(self.handle, 0)
                if result == 0:
                    break
                error = ctypes.get_last_error()
                close(self.handle)
            if result != 258:
                raise ctypes.WinError(error)
            if not blocking:
                raise BlockingIOError(errno.EAGAIN, "Plugin operation is already running")
            # Closing the handle lets an abandoned semaphore disappear after its last child exits.
            time.sleep(0.1)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.handle is not None:
            close(self.handle, release=True)

    def detach(self):
        close(self.handle)
        self.handle = None


@contextlib.contextmanager
def inherited(handles):
    old = [(handle, os.get_handle_inheritable(handle)) for handle in handles]
    try:
        for handle, _ in old:
            os.set_handle_inheritable(handle, True)
        info = subprocess.STARTUPINFO()
        info.lpAttributeList = {"handle_list": handles}
        yield {"startupinfo": info, "close_fds": True}
    finally:
        for handle, inheritable in old:
            os.set_handle_inheritable(handle, inheritable)
