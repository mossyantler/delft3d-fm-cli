"""Read-only Win32 process witnesses for coupled cancellation verification.

No process is launched, suspended, terminated or adopted here. Handles retain
actual process objects across PID reuse. Only WAIT_OBJECT_0 proves exit; failed
OpenProcess/query/snapshot calls are unknown evidence, never proof of exit.
"""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path

from .verify_coupling_sources import fingerprint, require


class ProcessEntry(c.Structure):
    _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD), ("heap", c.c_size_t),
                ("module", w.DWORD), ("threads", w.DWORD), ("parent", w.DWORD), ("priority", w.LONG),
                ("flags", w.DWORD), ("name", w.WCHAR * 260)]


def descendants(rows, root):
    """Snapshot ancestry is only a candidate list; handles/creation times bind it."""
    require(len(rows) <= 65536 and len({r["pid"] for r in rows}) == len(rows), "Invalid/bounded process snapshot")
    found, frontier, seen = [], [root], {root}
    for _ in range(32):
        next_level = []
        for row in rows:
            if row["parent"] in frontier and row["pid"] not in seen:
                seen.add(row["pid"])
                found.append(row)
                next_level.append(row["pid"])
        if not next_level: return found
        frontier = next_level
    raise ValueError("Native descendant ancestry exceeded32 levels")


class API:
    def __init__(self):
        require(os.name == "nt", "OS-handle native witness requires Windows")
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        specs = {
            "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "GetCurrentProcess": ([], w.HANDLE),
            "DuplicateHandle": ([w.HANDLE, w.HANDLE, w.HANDLE, c.POINTER(w.HANDLE), w.DWORD, w.BOOL, w.DWORD], w.BOOL),
            "GetProcessId": ([w.HANDLE], w.DWORD),
            "GetProcessTimes": ([w.HANDLE] + [c.POINTER(w.FILETIME)] * 4, w.BOOL),
            "QueryFullProcessImageNameW": ([w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)], w.BOOL),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
            "CreateToolhelp32Snapshot": ([w.DWORD, w.DWORD], w.HANDLE),
            "Process32FirstW": ([w.HANDLE, c.POINTER(ProcessEntry)], w.BOOL),
            "Process32NextW": ([w.HANDLE, c.POINTER(ProcessEntry)], w.BOOL),
        }
        for name, (arguments, result) in specs.items():
            fn = getattr(self.kernel, name)
            fn.argtypes, fn.restype = arguments, result
        self.hashes = {}

    def checked(self, value):
        if not value: raise c.WinError(c.get_last_error())
        return value

    def snapshot(self):
        handle = self.kernel.CreateToolhelp32Snapshot(2, 0)
        if handle == c.c_void_p(-1).value: raise c.WinError(c.get_last_error())
        try:
            entry = ProcessEntry(); entry.size = c.sizeof(entry)
            rows = []
            more = self.kernel.Process32FirstW(handle, c.byref(entry))
            while more:
                rows.append({"pid": int(entry.pid), "parent": int(entry.parent), "name": entry.name})
                require(len(rows) <= 65536, "Process snapshot exceeds budget")
                more = self.kernel.Process32NextW(handle, c.byref(entry))
            if c.get_last_error() != 18: raise c.WinError(c.get_last_error())  # ERROR_NO_MORE_FILES
            return rows
        finally:
            self.kernel.CloseHandle(handle)

    def from_popen(self, process):
        duplicate = w.HANDLE()
        current = self.kernel.GetCurrentProcess()
        self.checked(self.kernel.DuplicateHandle(current, int(process._handle), current, c.byref(duplicate), 0, False, 2))
        return Witness(self, duplicate.value)

    def open(self, identity):
        handle = self.checked(self.kernel.OpenProcess(0x1000 | 0x100000, False, identity["pid"]))
        return Witness(self, handle, expected=identity)


class Witness:
    def __init__(self, api, handle, expected=None):
        self.api, self.handle = api, handle
        try:
            kernel = api.kernel
            times = [w.FILETIME() for _ in range(4)]
            api.checked(kernel.GetProcessTimes(handle, *map(c.byref, times)))
            self.identity = {"pid": int(api.checked(kernel.GetProcessId(handle))),
                             "creation_time_100ns": str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)}
            require(expected is None or self.identity == expected, "PID creation identity changed; witness rejected")
            buffer, length = c.create_unicode_buffer(32768), w.DWORD(32768)
            api.checked(kernel.QueryFullProcessImageNameW(handle, 0, buffer, c.byref(length)))
            self.image = Path(buffer.value).resolve(strict=True)
            if str(self.image) not in api.hashes: api.hashes[str(self.image)] = fingerprint(self.image)
            self.sha256 = api.hashes[str(self.image)]
            self.state()  # query failures must surface before accepting evidence
        except BaseException:
            self.close()
            raise

    def state(self):
        result = self.api.kernel.WaitForSingleObject(self.handle, 0)
        if result == 0: return "exited_signalled_handle"
        if result == 258: return "live_unsignalled_handle"
        raise OSError("Retained process handle wait failed; exit is unknown")

    def record(self):
        return {"identity": self.identity, "image": str(self.image), "image_sha256": self.sha256, "state": self.state()}

    def close(self):
        if self.handle:
            self.api.kernel.CloseHandle(self.handle)
            self.handle = None


class Tree:
    def __init__(self, api, root_identity, expected_image, expected_sha256):
        self.api = api
        self.root = api.open(root_identity)
        try:
            require(self.root.image == Path(expected_image).resolve(strict=True) and self.root.sha256 == expected_sha256,
                    "Actual root image/hash differs from selected DIMR binary")
        except BaseException:
            self.root.close()
            raise
        self.members = {(self.root.identity["pid"], self.root.identity["creation_time_100ns"]): self.root}
        self.links, self.unknown = {}, []

    def poll(self):
        if self.root.state() != "live_unsignalled_handle": return
        candidates = descendants(self.api.snapshot(), self.root.identity["pid"])
        live = {obj.identity["pid"]: obj for obj in self.members.values() if obj.state() == "live_unsignalled_handle"}
        for row in candidates:
            parent = live.get(row["parent"])
            if parent is None: continue
            try:
                # Creation time is queried independently; a snapshot PID is not identity.
                handle = self.api.checked(self.api.kernel.OpenProcess(0x1000 | 0x100000, False, row["pid"]))
                obj = Witness(self.api, handle)
                if int(obj.identity["creation_time_100ns"]) < int(parent.identity["creation_time_100ns"]):
                    obj.close()
                    raise ValueError("Snapshot parent PID was reused")
                key = (obj.identity["pid"], obj.identity["creation_time_100ns"])
                if key in self.members:
                    obj.close(); obj = self.members[key]
                else:
                    self.members[key] = obj
                    self.links[str(key)] = {"parent_identity": parent.identity, "child_identity": obj.identity}
                if obj.state() == "live_unsignalled_handle": live[obj.identity["pid"]] = obj
            except (OSError, ValueError) as error:
                if len(self.unknown) < 64: self.unknown.append({"pid": row["pid"], "reason": str(error), "exit_proven": False})

    def live_swan(self, binaries):
        expected = {(str(Path(v["path"]).resolve()), v["sha256"]) for key, v in binaries.items()
                    if Path(key).name.lower().startswith("swan") and key.lower().endswith(".exe")}
        return [obj for obj in self.members.values() if (str(obj.image), obj.sha256) in expected and obj.state() == "live_unsignalled_handle"]

    def record(self):
        return {"root": self.root.record(), "observed_processes": [obj.record() for obj in self.members.values()],
                "ancestry_creation_time_links": self.links, "unavailable_evidence": self.unknown,
                "scope": "Observed descendants plus retained handles; native private-job receipt establishes whole-job cleanup"}

    def all_exited(self):
        return all(obj.state() == "exited_signalled_handle" for obj in self.members.values())

    def close(self):
        for obj in self.members.values(): obj.close()
