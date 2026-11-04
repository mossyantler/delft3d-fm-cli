"""Independent file/quantity-aware provenance verifier; never accept Name alone.

Adapter recognizes flat source/output paths or nested source/output descriptors,
with artifact path context on parent group records. Unknown schemas fail closed.
"""
import json
from pathlib import Path

from .verify_boundary_export_fixture import require,sha,validate_output_tree


def _unique(pairs):
    result={}
    for k,v in pairs:
        require(k not in result,"Duplicate key in export provenance JSON")
        result[k]=v
    return result


def _value(node,keys):
    return next((node[k] for k in keys if isinstance(node.get(k),str)),None)


def _descriptor(node,side):
    names=("source_path","source_bc","source_pli","original_path") if side=="source" else ("output_path","output_bc","output_pli","destination_path","exported_path")
    direct=_value(node,names)
    if direct:return direct
    for key in (("source","original") if side=="source" else ("output","destination","exported")):
        value=node.get(key)
        if isinstance(value,str):return value
        if isinstance(value,dict):
            found=_value(value,("path","file","relative_path","bc_file","pli_file"))
            if found:return found
    return None


def audit(fixture,out,report,byte_audit):
    out=Path(out).resolve(strict=True);validate_output_tree(out)
    docs=[]
    manifests=list(out.rglob("*.json"))
    require(bool(manifests),"Export lacks a retained source-mapping manifest")
    for path in manifests:
        require(path.stat().st_size<=8*1024**2,"Export mapping manifest exceeds independent bound")
        docs.append(json.loads(path.read_bytes(),object_pairs_hook=_unique))
    # Retained files must carry complete provenance independently of ephemeral
    # stdout. A correct response cannot compensate for a truncated manifest.
    if "manifest_sha256" in report:
        matched_manifests=[p for p in manifests if sha(p)==report["manifest_sha256"]]
        require(len(matched_manifests)==1,"Retained manifest hash differs from public receipt")
        if "manifest" in report:
            require(json.loads(matched_manifests[0].read_bytes(),object_pairs_hook=_unique)==report["manifest"],"Retained manifest content differs from public response")
    if isinstance(report.get("files"),list):
        actual={p.relative_to(out).as_posix():{"sha256":sha(p),"bytes":p.stat().st_size} for p in out.rglob("*") if p.is_file()}
        claimed={row["path"]:{"sha256":row["sha256"],"bytes":row["bytes"]} for row in report["files"]}
        require(len(claimed)==len(report["files"]) and actual==claimed,"Output inventory/size/hash differs from public receipt")
    expected={(b["output_path"],b["name"],b["quantity"]):b for b in byte_audit["actual_blocks"]}
    matched=set();geometry=set();source_paths={b["original"]["source_path"] for b in byte_audit["actual_blocks"]}
    source_paths|={str(p) for p in fixture.pli.values()}

    def source_path(value):
        if not value:return None
        p=Path(value)
        if not p.is_absolute():p=fixture.model/p
        return str(p.resolve(strict=True))

    def output_path(value):
        if not value:return None
        p=Path(value)
        if not p.is_absolute():
            require(".." not in p.parts,"Provenance destination traversal")
            p=out/p
        p=p.resolve(strict=True)
        require(p.is_relative_to(out),"Provenance destination outside export root")
        return str(p)

    def visit(value,src=None,dst=None,label=None):
        if isinstance(value,list):
            for child in value:visit(child,src,dst,label)
            return
        if not isinstance(value,dict):return
        s,d=_descriptor(value,"source"),_descriptor(value,"output")
        if s and Path(s).suffix.casefold() in {".bc",".pli"}:src=source_path(s)
        if d and Path(d).suffix.casefold() in {".bc",".pli"}:dst=output_path(d)
        generic=_value(value,("path","file","relative_path","bc_file","pli_file"))
        if generic and Path(generic).suffix.casefold() in {".bc",".pli"}:
            # Artifact parent records commonly carry a destination relative path.
            p=Path(generic)
            candidate=(out/p).resolve() if not p.is_absolute() else p.resolve()
            if candidate.is_relative_to(out) and candidate.is_file():dst=str(candidate)
            elif str(p.resolve()) in source_paths:src=str(p.resolve())
        named=_value(value,("boundary","boundary_label","label"))
        if named in fixture.pli:label=named
        support=_value(value,("support","support_name","point","name"))
        quantity=_value(value,("quantity","boundary_quantity","physical_quantity"))
        if src and dst and Path(src).suffix.casefold()==Path(dst).suffix.casefold()==".bc" and support and quantity:
            identity=(dst,support,quantity)
            require(identity in expected,"Manifest maps a nonexistent/foreign output block")
            block=expected[identity]
            require(src==str(Path(block["original"]["source_path"]).resolve()),"BC mapping points at wrong original source")
            if label:require(label==block["original"]["boundary"],"BC mapping has wrong original PLI identity")
            original=block["original"]
            source=value.get("source",{});target=value.get("output",{})
            if isinstance(source,dict) and {"byte_start","byte_end"}<=set(source):
                a,z=source["byte_start"],source["byte_end"]
                require(type(a) is type(z) is int and (a,z)==(original["byte_start"],original["byte_end"]),"Original BC span is wrong")
                require(Path(src).read_bytes()[a:z]==original["raw"],"Original BC span does not identify the expected block")
                if "block" in source:require(source["block"]==original["ordinal"],"Wrong original block ordinal")
                if "sha256" in source:require(source["sha256"]==__import__("hashlib").sha256(original["raw"]).hexdigest(),"Wrong original block hash")
            if isinstance(target,dict) and {"byte_start","byte_end"}<=set(target):
                a,z=target["byte_start"],target["byte_end"]
                require(type(a) is type(z) is int and 0<=a<z<=Path(dst).stat().st_size,"Invalid output BC span")
                payload=Path(dst).read_bytes()[a:z]
                require(payload==original["raw"],"Output BC span is not the exact original block")
                if "sha256" in target:require(target["sha256"]==__import__("hashlib").sha256(payload).hexdigest(),"Wrong exported block hash")
            matched.add(identity)
        if src and dst and Path(src).suffix.casefold()==Path(dst).suffix.casefold()==".pli" and label:
            require(src==str(fixture.pli[label].resolve()),"PLI mapping points at wrong original")
            require(Path(src).read_bytes()==Path(dst).read_bytes(),"Mapped PLI bytes differ")
            geometry.add(label)
        for key,child in value.items():
            if isinstance(child,(list,dict)):visit(child,src,dst,label)
    for doc in docs:visit(doc)
    require(matched==set(expected),"Incomplete BC mapping: require output file + exact support + quantity + original file")
    expected_labels={b["original"]["boundary"] for b in byte_audit["actual_blocks"]}
    require(geometry==expected_labels,"Incomplete original-to-exported PLI mapping")
    return {"state":"passed_independent_source_mapping","BC_block_mappings":len(matched),"PLI_mappings":len(geometry),
            "mapping_manifest_hashes":{p.relative_to(out).as_posix():sha(p) for p in manifests}}
