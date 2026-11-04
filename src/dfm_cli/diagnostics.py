"""Bounded excerpts from native logs; raw files remain the authoritative evidence."""
from collections import deque
import hashlib
import re

ERROR = re.compile(r"\*\*\s*(?:ERROR|FATAL)\s*:|forrtl:\s*severe|Fortran runtime error|^\s*(?:ERROR|FATAL)\s*:", re.I)
WARNING = re.compile(r"\*\*\s*WARNING\s*:")
LIMIT, WIDTH = 32, 1024
SERIAL_MPI = re.compile(r"MPI\s*:\s*no\.")
ONE_THREAD = re.compile(r"OpenMP\s*:\s*yes\..*#threads max\s*:\s*1\b")
VERSIONS = {"fm": re.compile(r"^(?:\*\s+)([0-9]+\.[0-9]+\.[^\s]+)|D-Flow FM\s*([0-9]+\.[0-9]+\.[^\s]+)"),
            "dimr_exe": re.compile(r"DIMR_EXE Version ([^,\s]+)"), "dimr_library": re.compile(r"DIMR_LIB Version ([^,\s]+)")}


def collect_diagnostics(folder, manifest):
    dia = sorted((folder / "model").rglob("*.dia"))
    sources = [folder / "stdout.log", *dia, folder / "stderr.log"]
    markers = dict.fromkeys(("initialized", "finished", "serial_mpi", "one_thread"), False)
    versions = dict.fromkeys((*VERSIONS, "source_revision"))
    excerpts = {key: [] for key in ("stderr_lines", "warning_lines", "error_lines")}
    counts = dict.fromkeys(excerpts, 0)
    clipped = 0
    primary = None
    primary_meaningful = False
    digests = {}
    for path in sources:
        if not path.is_file():
            continue
        stdout, stderr = path == sources[0], path == sources[-1]
        before, pending = deque(maxlen=2), []
        digest = hashlib.sha256() if path.suffix.lower() == ".dia" else None
        with path.open("rb") as stream:
            for number, raw in enumerate(stream, 1):
                if digest is not None:
                    digest.update(raw)
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                excerpt = line[:WIDTH]
                clipped += len(line) > WIDTH
                if pending:
                    for item in pending:
                        item["context"].append(excerpt)
                    pending = [item for item in pending if number < item["line"]+2]
                if stdout:
                    if not markers["initialized"] and "Model initialization was successful" in line:
                        markers["initialized"] = True
                    if not markers["finished"] and "Computation finished at:" in line:
                        markers["finished"] = True
                    if not markers["serial_mpi"] and "MPI" in line and SERIAL_MPI.search(line):
                        markers["serial_mpi"] = True
                    if not markers["one_thread"] and "OpenMP" in line and ONE_THREAD.search(line):
                        markers["one_thread"] = True
                    if (line.startswith("*") and line[1:2].isspace()) or "D-Flow FM" in line or "DIMR_" in line:
                        for key, pattern in VERSIONS.items():
                            if versions[key] is None and (match := pattern.search(line)):
                                versions[key] = next(v[:WIDTH] for v in match.groups() if v)
                if stderr:
                    counts["stderr_lines"] += 1
                    if len(excerpts["stderr_lines"]) < LIMIT:
                        excerpts["stderr_lines"].append(excerpt)
                if "WARNING" in line and WARNING.search(line):
                    counts["warning_lines"] += 1
                    if len(excerpts["warning_lines"]) < LIMIT:
                        excerpts["warning_lines"].append(excerpt)
                # Every ERROR alternative contains one of these literal tokens.
                # Test the whole line, not the clipped excerpt or just its prefix.
                folded = line.lower()
                if ("error" in folded or "fatal" in folded or "forrtl:" in folded) and ERROR.search(line):
                    counts["error_lines"] += 1
                    meaningful = bool(ERROR.sub("", line).strip(" .*:\t"))
                    keep_primary = primary is None or (not primary_meaningful and meaningful)
                    if keep_primary or len(excerpts["error_lines"]) < LIMIT:
                        item = {"path": str(path), "line": number, "text": excerpt, "context": [*before, excerpt]}
                        pending.append(item)
                        if len(excerpts["error_lines"]) < LIMIT:
                            excerpts["error_lines"].append(item)
                        if keep_primary:
                            primary, primary_meaningful = item, meaningful
                before.append(excerpt)
        if digest:
            digests[path] = digest.hexdigest()
    manifest["diagnostics"] = {**excerpts, "primary_error": primary, "dia_paths": list(map(str, dia)),
                               "limits": {"entries_per_list": LIMIT, "characters_per_line": WIDTH, "context_each_side": 2},
                               "omitted": {k: v-len(excerpts[k]) for k, v in counts.items()}, "clipped_source_lines": clipped,
                               "markers": markers}
    if "ignored_cancel_request" in manifest:
        manifest["diagnostics"]["ignored_cancel_request"] = manifest["ignored_cancel_request"]
    manifest["runtime_versions"] = versions
    if manifest["validation"]["engine_initialization"] != "not_performed":
        manifest["validation"]["engine_initialization"] = ("passed_native_marker" if markers["initialized"] else
                                                           "failed_native_diagnostic" if primary else "unconfirmed")
    return digests
