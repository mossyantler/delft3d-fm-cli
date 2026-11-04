"""B10 independent single-file publication/peer-ownership probes; no native."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from unittest.mock import patch

from .verify_boundary_support_fixture import Fixture,HookCLI,PublicCLI,signals,semantic,snapshot,save,sha

PEER=b"B10-V PROTECTED PEER BYTES: exporter must not delete or rewrite\r\n"
SCENARIOS=("success_reoccupation","failed_renamed_replacement","failed_same_inode_content","failed_owned_stage","precommit_request_change")


def run_case(root,scenario,*,interface="cli"):
    from dfm_cli import boundary_support_write as writer
    root=Path(root);root.mkdir(parents=True,exist_ok=False);fixture=Fixture(root/"fixture")
    factory=HookCLI if interface=="hooks" else PublicCLI
    args=fixture.function_args("timeseries") if scenario=="precommit_request_change" else fixture.support_args("disable",point="east_0003")
    preview=factory(root/"preview-command").invoke(*args);before=snapshot(fixture.model)
    real_publish=writer._publish;real_fsync=writer.os.fsync;peer=None;held=None;peer_bytes=None
    observed={"scenario":scenario,"interface":interface,"triggered":False,"native_launches":0}
    def injection(stage,target):
        nonlocal peer,held,peer_bytes
        stage=Path(stage);target=Path(target);observed.update(triggered=True,stage=str(stage),stage_identity=[stage.stat().st_dev,stage.stat().st_ino])
        if scenario=="success_reoccupation":
            real_publish(stage,target);stage.write_bytes(PEER);peer=stage;peer_bytes=PEER
        elif scenario=="failed_renamed_replacement":
            held=fixture.model/"peer-held-renamed-stage.dat";stage.rename(held);stage.write_bytes(PEER);peer=stage;peer_bytes=PEER
            raise OSError("B10 controlled failure after stage name reassignment")
        elif scenario=="failed_same_inode_content":
            peer_bytes=stage.read_bytes()+PEER;stage.write_bytes(peer_bytes);peer=stage
            observed["peer_identity"]=[stage.stat().st_dev,stage.stat().st_ino]
            raise OSError("B10 controlled failure after foreign bytes added to same owned inode")
        elif scenario=="failed_owned_stage":raise OSError("B10 controlled publication failure, no peer action")
        else:raise AssertionError("Unexpected publication callback")
    def fsync(fd):
        real_fsync(fd)
        if not observed["triggered"]:
            observed["triggered"]=True
            fixture.to_linear.write_bytes(fixture.to_linear.read_bytes()+b"\r\n# request changed during staging\r\n")
    output=io.StringIO()
    point=patch.object(writer.os,"fsync",side_effect=fsync) if scenario=="precommit_request_change" else patch.object(writer,"_publish",side_effect=injection)
    with point:
        if interface=="hooks":code,payload=HookCLI().call(*args,"--apply","--expect-sha256",preview["input_sha256"])
        else:
            from dfm_cli.cli import main
            with redirect_stdout(output):code=main([*map(str,args),"--apply","--expect-sha256",preview["input_sha256"]])
            payload=json.loads(output.getvalue())
    save(root/"apply.json",payload)
    current=snapshot(fixture.model)
    originals_equal=all(current.get(name)==raw for name,raw in before.items() if name!="shared.bc")
    observed.update(CLI_exit_code=code,public_result=payload,original_other_inputs_unchanged=originals_equal,
        target_unchanged=current.get("shared.bc")==before["shared.bc"],target_sha256=sha(fixture.bc),
        protected_peer_path=str(peer) if peer else None,
        peer_survived=peer is not None and peer.is_file() and peer.read_bytes()==peer_bytes,
        held_original_survived=held.is_file() if held else None,
        remaining_stage_names=[p.name for p in fixture.model.glob(".dfm-boundary-support-*")],
        files_after={name:__import__("hashlib").sha256(raw).hexdigest() for name,raw in current.items()})
    if scenario=="success_reoccupation":
        expected=signals(before["shared.bc"]);del expected["east_0003"];actual=signals(fixture.bc.read_bytes())
        observed["target_semantics_correct"]=set(actual)==set(expected) and all(semantic(actual[n])==semantic(expected[n]) for n in expected)
    save(root/"race-observation.json",observed)
    return observed
