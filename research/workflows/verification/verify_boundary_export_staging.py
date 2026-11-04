"""Independent peer-ownership races at the B04 directory publication boundary.

Only freshly allocated synthetic files are moved/reoccupied. No native/GUI/VM.
All probes return raw outcomes first, so failures can be frozen without cleanup
of protected peer artifacts by this verifier.
"""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch

from .verify_boundary_export_fixture import Fixture,PublicCLI,save,sha,snapshot

SCENARIOS=("success_reoccupation","failed_renamed_replacement","failed_foreign_extra_file")
PEER=b"B04-V PEER-OWNED PROTECTED DATA; exporter must not delete or rewrite\r\n"


def run_case(root,scenario,*,nested=False):
    from dfm_cli import boundary_export as target
    from dfm_cli.cli import main
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    fixture=Fixture(root/"fixture");destination=fixture.root/"exported";inputs=snapshot(fixture.model)
    preview=PublicCLI(root/"preview-command").invoke(*fixture.arguments(destination))
    real_publish=target._publish;observed={"scenario":scenario,"nested_extra":nested,"triggered":False,"native_GUI_guest_launches":0}
    peer=None;held=None
    def inject(stage,out):
        nonlocal peer,held
        stage=Path(stage);out=Path(out);observed["triggered"]=True
        observed["original_stage"]=str(stage)
        observed["original_stage_identity"]=[stage.stat().st_dev,stage.stat().st_ino]
        if scenario=="success_reoccupation":
            real_publish(stage,out);observed["published_before_reoccupation"]=True
            stage.mkdir()
        elif scenario=="failed_renamed_replacement":
            held=fixture.root/"peer-held-renamed-original-stage"
            stage.rename(held);stage.mkdir()
            observed["held_original_stage"]=str(held)
        elif scenario!="failed_foreign_extra_file":raise AssertionError("Unknown independent race scenario")
        peer=stage/("positions/peer-extra/protected.txt" if nested else "peer-protected.txt")
        peer.parent.mkdir(parents=True,exist_ok=True);peer.write_bytes(PEER)
        observed["peer_path"]=str(peer)
        observed["stage_identity_after_peer_action"]=[stage.stat().st_dev,stage.stat().st_ino]
        if scenario!="success_reoccupation":raise OSError("B04 independent controlled publication failure after peer action")
    stdout=io.StringIO()
    with patch.object(target,"_publish",side_effect=inject),redirect_stdout(stdout):
        code=main([*map(str,fixture.arguments(destination)),"--apply","--expect-sha256",preview["input_sha256"]])
    (root/"apply.stdout.json").write_text(stdout.getvalue(),encoding="utf-8")
    try:payload=json.loads(stdout.getvalue())
    except ValueError:payload={"unparsed":stdout.getvalue()}
    observed.update(CLI_exit_code=code,public_result=payload,destination_exists=destination.exists(),
        peer_survived=peer is not None and peer.is_file() and peer.read_bytes()==PEER,
        peer_expected_sha256=hashlib.sha256(PEER).hexdigest(),peer_actual_sha256=sha(peer) if peer is not None and peer.is_file() else None,
        original_inputs_unchanged=snapshot(fixture.model)==inputs,
        held_original_stage_survived=held.is_dir() if held else None)
    if destination.is_dir():
        audit=fixture.audit(destination)
        observed["published_complete"]=audit["forcing_blocks"]==8 and audit["PLI_files"]==2
    else:observed["published_complete"]=False
    observed["fixture_files_after"]={name:hashlib.sha256(raw).hexdigest() for name,raw in snapshot(fixture.root).items()}
    save(root/"race-observation.json",observed)
    return observed
