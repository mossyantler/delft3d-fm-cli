"""Independent retained Windows identity checks, not a live guest attestation.

No producer imports, OS identity calls, process queries or host profile traversal.
JSON can establish internal consistency; it cannot prove which machine produced
it, VM disposability, settings containment, or GUI feasibility.
"""
from __future__ import annotations

import re
import uuid

from .verify_gui_guest_paths import require, windows_path

PROBE = "windows_token_known_folders_registry_read_and_SMBIOS"


def descriptor(value):
    require(isinstance(value,dict) and type(value.get("schema")) is int and value["schema"]==1 and value.get("probe")==PROBE,
            "invalid_identity","Require the complete Windows token/registry/known-folder/firmware descriptor")
    for key in ("machine_guid","firmware_uuid"):
        try:
            parsed = uuid.UUID(value[key])
        except (ValueError,TypeError,KeyError,AttributeError):
            require(False,"invalid_identity","Missing or malformed machine/firmware UUID")
        require(str(parsed)==value[key] and parsed.int not in (0,(1<<128)-1),"invalid_identity","Noncanonical/placeholder identity")
    require(isinstance(value.get("user_sid"),str) and re.fullmatch(r"S-1-5-21-[0-9]+-[0-9]+-[0-9]+-[0-9]+",value["user_sid"]) is not None,
            "invalid_identity","Ordinary Windows user SID is required")
    require(type(value.get("profile_drive_type")) is int and value["profile_drive_type"]==3,
            "invalid_identity","Independent profile must be on a fixed local volume")
    profile = windows_path(value["token_profile"])
    require(str(profile)!=profile.anchor,"invalid_identity","Drive root is not an independent user profile")
    require(windows_path(value["registered_profile"])==profile and windows_path(value["known_folders"]["profile"])==profile,
            "invalid_identity","Token/registry/known-profile paths disagree")
    for name in ("local_appdata","roaming_appdata"):
        path = windows_path(value["known_folders"][name],str(profile))
        require(path!=profile,"invalid_identity","AppData cannot equal the profile root")
    for name in ("manufacturer","product"):
        require(isinstance(value.get(name),str) and value[name].strip()==value[name] and bool(value[name]),
                "invalid_identity","Explicit firmware manufacturer/product is required")
    return profile


def distinct(host, guest):
    descriptor(host)
    profile = descriptor(guest)
    for key in ("machine_guid","firmware_uuid","user_sid"):
        require(host[key]!=guest[key],"same_host_or_user","Host and guest must differ in "+key)
    maker, product = guest["manufacturer"].casefold(),guest["product"].casefold()
    supported = {"microsoft corporation":"virtual machine","vmware, inc.":"vmware virtual platform",
                 "innotek gmbh":"virtualbox","qemu":"standard pc"}
    require(maker in supported and product.startswith(supported[maker]),"unproven_guest","Unknown/non-guest firmware declaration")
    return {"state":"structurally_consistent","guest_profile":str(profile),
            "host_identity_proven":False,"guest_identity_proven":False,"disposability_proven":False,
            "gui_feasibility":"not_tested","native_acceptance":"not_established"}
