"""Prelaunch proof API for E007's separately gated guest controller.

RSA/SHA256 signatures attest an exact resolver statement, not GUI completion.
No resolver/key is admitted in this release: unsupported statements fail closed.
Tests inject a public TEST authority through the Python API, never a CLI flag.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path, PureWindowsPath
import secrets
import sys
import types

sys.dont_write_bytecode = True
TRANSFER_SHA = "cdbd15b5685771ef4d906c7d46b8110045751d5eee4fbbc71af68642e4a20184"
IDENTITY_SHA = "8f3e0085462ac5330d50598409b15b69f470661c40f01fd060a0370798303cd3"
PAYLOAD_SHA = "16ebbde700314e0a2984974e43833f3ead417cdef08901270eec08259e6c3c58"
ADMITTED_RESOLVERS = {}  # Source review + a new controller freeze required to admit one.
PATH_KEYS = {"temp", "settings", "portable_user_config", "core_user_config_local",
             "core_user_config_roaming", "log_directory"}
SHA256_DER = bytes.fromhex("3031300d060960864801650304020105000420")


class Refusal(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def require(value, code, message):
    if not value:
        raise Refusal(code, message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def transfer_api(bundle=None):
    """Check frozen dependencies before importing any transferred Python bytes."""
    here = Path(__file__).resolve()
    scripts = Path(bundle) / "scripts" if bundle is not None else here.parent
    if bundle is None and not (scripts / "gui_guest_bridge.py").exists():
        scripts = here.parent.parent / "transfer/scripts"
    for name, expected in (("gui_guest_bridge.py", TRANSFER_SHA), ("gui_guest_identity.py", IDENTITY_SHA)):
        path = scripts / name
        for ancestor in (path, *path.parents):
            require(not ancestor.is_symlink() and not (ancestor.exists() and getattr(ancestor.lstat(), "st_file_attributes", 0) & 0x400),
                    "dependency_alias", "Frozen code path contains a link/reparse point")
        require(path.is_file() and sha(path) == expected, "dependency_changed", "Frozen transfer code differs: " + name)
    name = "_e007_controller_transfer_" + TRANSFER_SHA[:12]
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(scripts)]
        sys.modules[name] = package
    # Compile the verified bytes, not timestamp-valid unverified .pyc files.
    for short_name in ("gui_guest_identity", "gui_guest_bridge"):
        module_name = name + "." + short_name
        if module_name not in sys.modules:
            path = scripts / (short_name + ".py")
            module = types.ModuleType(module_name)
            module.__file__, module.__package__ = str(path), name
            sys.modules[module_name] = module
            exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return sys.modules[name + ".gui_guest_bridge"]


def inspect_transfer(bundle, expected_sha):
    bridge = transfer_api(bundle)
    require(bridge.sha(bridge.inside(bundle, "payload/payload-lock.json")) == PAYLOAD_SHA,
            "dependency_changed", "Frozen payload lock differs")
    return bridge, bridge.inspect_bundle(bundle, expected_sha)


def issue_challenge(binding, now, *, nonce=None, seconds=180):
    require(0 < seconds <= 300, "challenge_lifetime", "Challenge lifetime must be at most 300 seconds")
    bridge = transfer_api()
    issued = bridge.wall_time(now)
    nonce = secrets.token_hex(32) if nonce is None else nonce
    require(isinstance(nonce, str) and bridge.HEX.fullmatch(nonce), "challenge_nonce", "Require 256-bit nonce")
    return {"schema": 1, "kind": "E007_prelaunch_challenge", "nonce": nonce,
            "issued_at_utc": issued.isoformat(), "expires_at_utc": (issued + timedelta(seconds=seconds)).isoformat(),
            "binding": json.loads(canonical(binding)), "binding_sha256": fingerprint(binding)}


def validate_challenge(challenge, binding, now):
    bridge = transfer_api()
    require(challenge.get("schema") == 1 and challenge.get("kind") == "E007_prelaunch_challenge"
            and isinstance(challenge.get("nonce"), str) and bridge.HEX.fullmatch(challenge["nonce"]),
            "challenge_schema", "Invalid prelaunch challenge")
    issued, expires, current = [bridge.wall_time(value) for value in
                                (challenge["issued_at_utc"], challenge["expires_at_utc"], now)]
    require(issued <= current <= expires and 0 < (expires - issued).total_seconds() <= 300,
            "challenge_expired", "Challenge is future-dated, expired or overlong")
    require(challenge["binding"] == binding and challenge["binding_sha256"] == fingerprint(binding),
            "challenge_binding", "Machine/user, suite, root, transfer or controller signature changed")


def verify_signature(statement, signature_hex, key):
    """Strict RSASSA-PKCS1-v1_5 SHA256 verification; handles public data only."""
    try:
        modulus, exponent = int(key["n"], 16), key["e"]
        require(2048 <= modulus.bit_length() <= 8192 and type(exponent) is int
                and exponent >= 65537 and exponent % 2 == 1, "signature_key", "Invalid RSA public key")
        size = (modulus.bit_length() + 7) // 8
        require(isinstance(signature_hex, str) and len(signature_hex) == size * 2,
                "signature_invalid", "Signature width differs")
        signature = bytes.fromhex(signature_hex)
        value = int.from_bytes(signature, "big")
        require(0 < value < modulus, "signature_invalid", "Signature integer outside key")
        decoded = pow(value, exponent, modulus).to_bytes(size, "big")
        encoded_digest = SHA256_DER + hashlib.sha256(canonical(statement)).digest()
        padding = size - len(encoded_digest) - 3
        require(padding >= 8 and decoded == b"\0\1" + b"\xff" * padding + b"\0" + encoded_digest,
                "signature_invalid", "Resolver statement signature failed")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, Refusal):
            raise
        raise Refusal("signature_invalid", "Malformed signature/public key") from exc


def validate_paths(paths, binding):
    bridge = transfer_api()
    def local(value):
        try:
            return bridge.local_windows_root(value)
        except ValueError as exc:
            raise Refusal("startup_paths", str(exc)) from exc
    require(set(paths) == PATH_KEYS, "startup_paths", "Require portable, both real .NET config paths, temp and log directory")
    guest = binding["guest_identity"]
    profile = local(guest["token_profile"])
    root = local(binding["allocation_root"])
    require(root == profile, "allocation_root", "Frozen host requires an allocated whole disposable guest profile")
    parsed = {key: local(value) for key, value in paths.items()}
    for key, path in parsed.items():
        require(path != root and path.is_relative_to(root), "startup_path_escape", "Startup path outside allocation: " + key)
    require(parsed["temp"] == root / "temp", "startup_temp", "TEMP must match new private root/temp")
    local_folder = local(guest["known_folders"]["local_appdata"])
    roaming = local(guest["known_folders"]["roaming_appdata"])
    for key, parent in (("portable_user_config", local_folder), ("core_user_config_local", local_folder),
                        ("core_user_config_roaming", roaming), ("settings", local_folder), ("log_directory", local_folder)):
        require(parsed[key] != parent and parsed[key].is_relative_to(parent), "startup_known_folder",
                "Actual startup path is outside its OS known folder: " + key)
    configs = [parsed[key] for key in ("portable_user_config", "core_user_config_local", "core_user_config_roaming")]
    require(all(path.name == "user.config" for path in configs) and len(set(configs)) == 3,
            "startup_config_alias", "Portable and real .NET local/roaming configs must be separately resolved")
    # Reject broad retention scopes and collisions with the owned host protocol.
    protected = {root / name for name in ("protocol", "input", "harness", "project", "working", "temp",
                                           "settings", "logs", "snapshots", "blobs")}
    evidence = local(binding["evidence_root"])
    bundle = local(binding["bundle_root"])
    folders = {parsed["settings"], parsed["log_directory"], *(path.parent for path in configs)}
    for folder in folders:
        require(folder not in {root, local_folder, roaming}, "startup_snapshot_scope", "Broad profile/AppData snapshot refused")
        for other in protected | {evidence, bundle}:
            require(not folder.is_relative_to(other) and not other.is_relative_to(folder),
                    "startup_scope_overlap", "Startup settings/log scope overlaps controller or input evidence")
    return parsed


@dataclass(frozen=True)
class LaunchPermit:
    challenge_sha256: str
    binding_sha256: str
    proof_sha256: str
    paths: dict
    authority: str


def validate_proof(challenge, binding, proof, now, *, policies=None):
    """Pure proof API. Production calls use source-frozen ADMITTED_RESOLVERS only."""
    validate_challenge(challenge, binding, now)
    policies = ADMITTED_RESOLVERS if policies is None else policies
    require(isinstance(proof, dict) and set(proof) == {"statement", "authority", "signature"},
            "proof_schema", "Require a signed resolver statement")
    authority = proof["authority"]
    require(isinstance(authority, str) and authority in policies, "startup_resolver_not_admitted",
            "No reviewed real-entry-context startup resolver/key admitted for this installation")
    policy = policies[authority]
    statement = proof["statement"]
    require(isinstance(statement, dict), "proof_schema", "Resolver statement must be a JSON object")
    verify_signature(statement, proof["signature"], policy["public_key"])
    require(statement.get("schema") == 1 and statement.get("kind") == "E007_exact_prestartup_paths"
            and statement.get("challenge_sha256") == fingerprint(challenge), "proof_challenge",
            "Startup proof is not bound to this fresh challenge")
    context = statement["context"]
    expected_context = {"entry_executable": str(PureWindowsPath(binding["install_root"]) / "bin/DeltaShell.Gui.exe"),
                        "application_config": str(PureWindowsPath(binding["install_root"]) / "bin/DeltaShell.Gui.exe.config"),
                        "resolution": "real_entry_assembly_and_appdomain_before_target_entrypoint",
                        "resolver_sha256": policy["resolver_sha256"],
                        "framework_sha256": policy["framework_sha256"],
                        "suite_signature": binding["suite_signature"], "settings_written": False,
                        "target_entrypoint_executed": False, "clickonce": False}
    require(context == expected_context and context["settings_written"] is False
            and context["target_entrypoint_executed"] is False and context["clickonce"] is False,
            "proof_context", "Resolver used a surrogate/changed application context or caused startup side effects")
    require(policy["suite_signature"] == binding["suite_signature"], "policy_suite", "Resolver not reviewed for this suite")
    require(policy["framework_sha256"] == binding["framework_signature"], "policy_framework",
            "Actual Framework file signatures differ from the reviewed resolver")
    validate_paths(statement["paths"], binding)
    return LaunchPermit(fingerprint(challenge), fingerprint(binding), fingerprint(proof),
                        types.MappingProxyType(json.loads(canonical(statement["paths"]))), authority)
