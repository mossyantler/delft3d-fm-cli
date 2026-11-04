"""Windows coordinator replay: inject one stale PID lookup during Job cleanup.

Only the lookup is substituted. The parent, child, unrelated peer, Job, handle
waits and termination call are real. This does not claim actual OS PID reuse.
Run with the coordinator's exclusive JOB-FORCE-G lease in a fresh output folder.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from dfm_cli import windows_job as native


def check(ok, message):
    if not ok:
        raise ValueError(message)


def replay(out, slot):
    ledger = Path(__file__).resolve().parents[3] / "research/experiments/roadmap-coordinator-20261104/dispatch.json"
    lease = json.loads(ledger.read_bytes())["native_slot"]
    check(lease["owner"] == "JOB-FORCE-G" and lease["sequence"] == slot, "Wrong native lease")
    out.mkdir(parents=True, exist_ok=False)
    module = Path(native.__file__)
    before = hashlib.sha256(module.read_bytes()).hexdigest()
    python = str(Path(sys._base_executable).resolve(strict=True))
    # A venv's Windows shim can introduce a third process. Use the same base
    # interpreter for all three actors, each with a private control channel.
    child_code = "import time; time.sleep(40)"
    root_code = ("import subprocess,sys,pathlib; p=subprocess.Popen([sys.executable,'-I','-c',sys.argv[1]]); "
                 "pathlib.Path(sys.argv[2]).write_text(str(p.pid)); sys.exit(p.wait())")
    peer = subprocess.Popen([python, "-I", "-c", "import sys; sys.exit(0 if sys.stdin.readline()=='release\\n' else 3)"],
                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, close_fds=True)
    job = root = witness = None
    kernel = native.api()
    receipt = {"slot": slot, "python": python, "source_sha256": before,
               "injection": "same-executable nonmember substituted for one child OpenProcess lookup",
               "actual_pid_reuse": False, "substitutions": 0}

    class Race:
        def __getattr__(self, name):
            return getattr(kernel, name)

        def OpenProcess(self, access, inherit, pid):
            if pid == receipt["child_pid"]:
                receipt["substitutions"] += 1
                return kernel.OpenProcess(access, inherit, peer.pid)
            return kernel.OpenProcess(access, inherit, pid)

    def member(handle):
        yes = wintypes.BOOL()
        native.checked(kernel.IsProcessInJob(handle, job.handle, ctypes.byref(yes)))
        return bool(yes.value)

    try:
        job = native.OwnedJob()
        mark = out / "child.pid"
        root = job.launch([python, "-I", "-c", root_code, child_code, str(mark)])
        end = time.monotonic() + 8
        while time.monotonic() < end:
            if mark.exists() and mark.read_bytes().isdigit():
                break
            time.sleep(.02)
        child = int(mark.read_bytes())
        receipt.update(root_pid=root.pid, child_pid=child, peer_pid=peer.pid)
        witness = native.checked(kernel.OpenProcess(0x101000, False, child))
        check(set(job.members()) == {child, root.pid} and member(witness) and member(int(root._handle))
              and not member(int(peer._handle)) and kernel.WaitForSingleObject(witness, 0) == 258,
              "Bad independent ownership control")
        job.kernel = Race()
        result = job.terminate(root)
        receipt.update(producer=result, original_child_wait=kernel.WaitForSingleObject(witness, 5000),
                       root_exit=root.wait(timeout=5), job_pids_after=job.members(),
                       peer_alive_before_close=peer.poll() is None)
    finally:
        if job is not None:
            job.kernel = kernel
            job.close()
        if root is not None:
            root.wait(timeout=6)
        if witness is not None:
            native.checked(kernel.CloseHandle(witness))
        receipt["peer_alive_after_close"] = peer.poll() is None
        if receipt["peer_alive_after_close"]:
            peer.stdin.write("release\n")
            peer.stdin.flush()
        peer.stdin.close()
        receipt["peer_natural_exit"] = peer.wait(timeout=5)
        receipt["source_unchanged"] = hashlib.sha256(module.read_bytes()).hexdigest() == before
        (out / "observation.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf8")

    check(receipt["substitutions"] == 1 and receipt["original_child_wait"] == 0 and receipt["root_exit"] == 1
          and receipt["job_pids_after"] == [] and receipt["peer_alive_before_close"] and receipt["peer_alive_after_close"]
          and receipt["peer_natural_exit"] == 0 and receipt["source_unchanged"], "Invalid trial; inspect observation.json")
    confirmed = receipt["producer"]["member_exit_confirmations"].get(str(child))
    safe = confirmed is False and receipt["producer"]["tree_terminated"] is False
    print(json.dumps({"safe_refusal": safe, "confirmed": confirmed, "source_sha256": before, "out": str(out)}))
    return 0 if safe else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--native-slot", type=int, required=True)
    args = parser.parse_args()
    raise SystemExit(replay(args.out.resolve(), args.native_slot))
