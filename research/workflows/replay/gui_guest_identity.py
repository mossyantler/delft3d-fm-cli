"""Read-only Windows identity probe. No VM enumeration, subprocess or settings writes.

This is an identity gate, not an attestation of VM disposability or a GUI launcher.
The operator must supply the separate declaration described in the bridge README.
"""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path, PureWindowsPath
import uuid


def smbios_identity(raw):
    """Parse the bounded RawSMBIOSData returned by GetSystemFirmwareTable(RSMB)."""
    if len(raw) < 8 or int.from_bytes(raw[4:8], "little") != len(raw) - 8:
        raise ValueError("Invalid SMBIOS length")
    offset = 8
    while offset + 4 <= len(raw):
        kind, size = raw[offset:offset + 2]
        if size < 4 or offset + size > len(raw):
            raise ValueError("Truncated SMBIOS structure")
        end = raw.find(b"\0\0", offset + size)
        if end < 0:
            raise ValueError("Unterminated SMBIOS string table")
        strings = raw[offset + size:end].split(b"\0")
        if kind == 1:
            if size < 24:
                raise ValueError("No SMBIOS system UUID")
            def string(index):
                if not 0 < index <= len(strings):
                    raise ValueError("Missing SMBIOS system string")
                return strings[index - 1].decode("ascii", errors="strict").strip()
            value = uuid.UUID(bytes_le=raw[offset + 8:offset + 24])
            if value.int in (0, (1 << 128) - 1):
                raise ValueError("Placeholder SMBIOS UUID")
            return {"firmware_uuid": str(value), "manufacturer": string(raw[offset + 4]),
                    "product": string(raw[offset + 5])}
        offset = end + 2
    raise ValueError("No SMBIOS system identity")


def probe():
    if os.name != "nt":
        raise ValueError("An actual Windows token/profile/firmware probe is required")
    import winreg
    kernel = c.WinDLL("kernel32", use_last_error=True)
    advapi = c.WinDLL("advapi32", use_last_error=True)
    userenv = c.WinDLL("userenv", use_last_error=True)
    shell = c.WinDLL("shell32", use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [c.c_void_p], c.c_void_p
    advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
    advapi.GetTokenInformation.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [c.c_void_p, c.POINTER(w.LPWSTR)]
    userenv.GetUserProfileDirectoryW.argtypes = [w.HANDLE, w.LPWSTR, c.POINTER(w.DWORD)]
    shell.SHGetFolderPathW.argtypes = [w.HWND, c.c_int, w.HANDLE, w.DWORD, w.LPWSTR]
    kernel.GetDriveTypeW.argtypes, kernel.GetDriveTypeW.restype = [w.LPCWSTR], w.UINT
    kernel.GetSystemFirmwareTable.argtypes = [w.DWORD, w.DWORD, c.c_void_p, w.DWORD]
    kernel.GetSystemFirmwareTable.restype = w.UINT
    def checked(ok):
        if not ok:
            raise c.WinError(c.get_last_error())
    token = w.HANDLE()
    checked(advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, c.byref(token)))
    try:
        size = w.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, c.byref(size))
        if not 0 < size.value < 65536:
            raise ValueError("Unbounded token identity")
        data = c.create_string_buffer(size.value)
        checked(advapi.GetTokenInformation(token, 1, data, size, c.byref(size)))
        sid_pointer = c.c_void_p.from_buffer(data).value
        sid_text = w.LPWSTR()
        checked(advapi.ConvertSidToStringSidW(sid_pointer, c.byref(sid_text)))
        try:
            sid = sid_text.value
        finally:
            kernel.LocalFree(c.cast(sid_text, c.c_void_p))
        profile_size = w.DWORD(32768)
        profile = c.create_unicode_buffer(profile_size.value)
        checked(userenv.GetUserProfileDirectoryW(token, profile, c.byref(profile_size)))
        folders = {}
        for name, identifier in (("profile", 0x28), ("local_appdata", 0x1c), ("roaming_appdata", 0x1a)):
            path = c.create_unicode_buffer(32768)
            if shell.SHGetFolderPathW(None, identifier, token, 0, path) != 0:
                raise ValueError("Windows known folder unavailable: " + name)
            folders[name] = path.value
    finally:
        kernel.CloseHandle(token)
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                        0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        machine = winreg.QueryValueEx(key, "MachineGuid")[0]
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                        "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProfileList\\" + sid,
                        0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        registered = os.path.expandvars(winreg.QueryValueEx(key, "ProfileImagePath")[0])
    signature = int.from_bytes(b"RSMB", "big")
    size = kernel.GetSystemFirmwareTable(signature, 0, None, 0)
    if not 8 < size <= 4 * 1024 * 1024:
        raise ValueError("Firmware identity unavailable or unbounded")
    raw = c.create_string_buffer(size)
    if kernel.GetSystemFirmwareTable(signature, 0, raw, size) != size:
        raise ValueError("Firmware identity changed during read")
    return {"schema": 1, "probe": "windows_token_known_folders_registry_read_and_SMBIOS",
            "machine_guid": str(uuid.UUID(machine)), **smbios_identity(raw.raw), "user_sid": sid,
            "token_profile": profile.value, "registered_profile": registered, "known_folders": folders,
            "profile_drive_type": kernel.GetDriveTypeW(PureWindowsPath(profile.value).anchor)}


def validate_profile(value):
    import re
    if value.get("schema") != 1 or value.get("probe") != "windows_token_known_folders_registry_read_and_SMBIOS":
        raise ValueError("Not the required Windows identity descriptor")
    for key in ("machine_guid", "firmware_uuid"):
        parsed = uuid.UUID(value[key])
        if parsed.int in (0, (1 << 128) - 1) or str(parsed) != value[key]:
            raise ValueError("Noncanonical/placeholder machine identity")
    if not re.fullmatch(r"S-1-5-21-\d+-\d+-\d+-\d+", value["user_sid"]):
        raise ValueError("Require a distinct ordinary Windows user SID")
    profile = PureWindowsPath(value["token_profile"])
    if not profile.is_absolute() or profile.drive.startswith("\\") or ".." in profile.parts or value["profile_drive_type"] != 3:
        raise ValueError("Profile must be on a local fixed Windows volume")
    if profile == PureWindowsPath(profile.anchor):
        raise ValueError("A drive root is not a private profile")
    if PureWindowsPath(value["registered_profile"]) != profile or PureWindowsPath(value["known_folders"]["profile"]) != profile:
        raise ValueError("Token, registered profile and OS known profile disagree")
    for key in ("local_appdata", "roaming_appdata"):
        path = PureWindowsPath(value["known_folders"][key])
        if not path.is_relative_to(profile) or path == profile or ".." in path.parts:
            raise ValueError("AppData known folder is outside the independent profile")
    return profile


def validate_distinct(host, guest):
    validate_profile(host)
    profile = validate_profile(guest)
    for name in ("machine_guid", "firmware_uuid", "user_sid"):
        if host[name] == guest[name]:
            raise ValueError("Host/guest identity must differ: " + name)
    hardware = (guest["manufacturer"].casefold(), guest["product"].casefold())
    accepted = (("microsoft corporation", "virtual machine"), ("vmware, inc.", "vmware virtual platform"),
                ("innotek gmbh", "virtualbox"), ("qemu", "standard pc"))
    if not any(hardware[0] == maker and hardware[1].startswith(product) for maker, product in accepted):
        raise ValueError("No supported disposable-guest firmware identity; refuse uncertainty")
    return profile


def validate_live_paths(value):
    """Run only after distinct identity; no host profile traversal in offline replay."""
    validate_profile(value)
    for name in ("profile", "local_appdata", "roaming_appdata"):
        path = Path(value["known_folders"][name])
        for ancestor in (path, *path.parents):
            if ancestor.is_symlink() or (ancestor.exists() and getattr(ancestor.lstat(), "st_file_attributes", 0) & 0x400):
                raise ValueError("Redirected/reparse guest profile refused")
        if not path.is_dir():
            raise ValueError("Guest known folder does not exist")
