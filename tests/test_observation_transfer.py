"""Portable public G10 tests: temporary models, no research/product helper imports.

Export is stdlib-only and archival. Import tests skip when optional geo packages
are unavailable. These tests never start an engine, GUI, VM or install operation.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
GEO=all(importlib.util.find_spec(n) is not None for n in ("netCDF4","numpy","pyproj"))
TARGET=(b"\xef\xbb\xbf# target CRLF and exact trivia\r\n"
        b" 300001.25\t4000000.75 'Base station' # preserve\r\n"
        b"300003 4000003.25 keep_plain # last target comment")
UPLOAD=(b"\xef\xbb\xbf# upload LF style\n300006.125 4000001.75 NEW # retain source\n"
        b" 300005.5\t4000003.125 'Fresh station' # source EOF")
NODES=[(300000,4000000),(300004,4000000),(300008,4000000),
       (300000,4000004),(300004,4000004),(300008,4000004)]
FACES=[(0,1,4,3),(1,2,5,4)]


def files(root):return {p.relative_to(root).as_posix():p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()}
def dirs(root):return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir() and not p.is_symlink())


def mesh(path):
    import netCDF4 as nc
    edges=sorted({tuple(sorted((a,b))) for face in FACES for a,b in zip(face,face[1:]+face[:1])})
    with nc.Dataset(path,"w",format="NETCDF3_64BIT_OFFSET") as d:
        for name,size in (("node",6),("face",2),("maxFaceNodes",4),("edge",7),("two",2)):d.createDimension(name,size)
        d.Conventions="CF-1.8 UGRID-1.0";d.vertical_datum="local fixture zero"
        c=d.createVariable("projected_coordinate_system","i4");c.assignValue(0)
        c.setncatts({"EPSG_code":"EPSG:32631","epsg":32631,"grid_mapping_name":"transverse_mercator","longitude_of_central_meridian":3.,
            "latitude_of_projection_origin":0.,"scale_factor_at_central_meridian":.9996,"false_easting":500000.,"false_northing":0.,
            "semi_major_axis":6378137.,"inverse_flattening":298.257223563,"longitude_of_prime_meridian":0.})
        t=d.createVariable("mesh2d","i4");t.assignValue(0)
        t.setncatts({"cf_role":"mesh_topology","topology_dimension":2,"node_coordinates":"mesh2d_node_x mesh2d_node_y mesh2d_node_z",
            "face_node_connectivity":"mesh2d_face_nodes","face_dimension":"face","edge_node_connectivity":"mesh2d_edge_nodes","grid_mapping":c.name})
        for axis,i in (("x",0),("y",1)):
            v=d.createVariable("mesh2d_node_"+axis,"f8",("node",));v[:]=[p[i] for p in NODES]
            v.units="m";v.standard_name="projection_"+axis+"_coordinate";v.grid_mapping=c.name
        z=d.createVariable("mesh2d_node_z","f8",("node",));z[:]=[-1]*6;z.units="m";z.grid_mapping=c.name
        for name,data,dimensions in (("mesh2d_face_nodes",FACES,("face","maxFaceNodes")),("mesh2d_edge_nodes",edges,("edge","two"))):
            v=d.createVariable(name,"i4",dimensions);v[:]=data;v.start_index=0


class TransferCase(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="g10-transfer-public-");self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.model=self.root/"model with spaces";self.model.mkdir()
        self.mdu=self.model/"model.mdu";self.target=self.model/"stations.xyn"
        self.source=self.root/"upload.xyn";self.dest=self.root/"standalone.xyn"
        self.target.write_bytes(TARGET);self.source.write_bytes(UPLOAD)
        self.mdu.write_bytes(b"# portable standalone test, not engine-ready\r\n[General]\r\nFileType = modelDef\r\nFileVersion = 1.09\r\nPathsRelativeToParent = 0\r\n[Geometry]\r\nNetFile = mesh.nc\r\n[Output]\r\nObsFile = stations.xyn # preserve direct ref\r\nCrsFile = missing.pli\r\nOutputDir = output\r\n")
        (self.model/"unknown.bin").write_bytes(b"\x00\xffunknown bytes\r\n");(self.model/"output").mkdir()
    def call(self,action,*options):
        self.assertIn(action,("export","import"))
        env=os.environ.copy();env["PYTHONPATH"]=str(ROOT/"src");env["PYTHONDONTWRITEBYTECODE"]="1"
        r=subprocess.run([sys.executable,"-B","-m","dfm_cli","observation",action,str(self.mdu),*map(str,options)],cwd=ROOT,env=env,capture_output=True,timeout=45)
        try:p=json.loads(r.stdout)
        except (UnicodeError,ValueError):self.fail(f"Non-JSON CLI: {r.stdout!r} {r.stderr!r}")
        self.assertEqual(p.get("protocol_version"),2);self.assertEqual(r.returncode==0,p.get("ok") is True,p)
        self.assertNotEqual(r.returncode,70,p);self.assertEqual(r.stderr,b"",r.stderr)
        return r.returncode,p
    def export(self,apply=False,digest=None):
        args=["--out",self.dest]
        if apply:args += ["--apply"]
        if digest is not None:args += ["--expect-sha256",digest]
        return self.call("export",*args)
    def importing(self,mode="append",apply=False,digest=None):
        args=["--source",self.source,"--crs","EPSG:32631","--unit","m"]
        if mode is not None:args += ["--mode",mode]
        if apply:args += ["--apply"]
        if digest is not None:args += ["--expect-sha256",digest]
        return self.call("import",*args)
    def refused(self,operation,exit_code=None):
        before=files(self.root);before_dirs=dirs(self.root)
        try:code,p=operation()
        finally:self.assertEqual(files(self.root),before,"Refusal changed complete source/target bytes");self.assertEqual(dirs(self.root),before_dirs)
        self.assertNotEqual(code,0,p)
        if exit_code is not None:self.assertEqual(code,exit_code,p)
        return p["error"]
    def export_ok(self):
        before=files(self.model);before_dirs=dirs(self.model);expected=self.target.read_bytes()
        code,p=self.export();self.assertEqual(code,0,p);self.assertFalse(self.dest.exists());self.assertEqual(files(self.model),before)
        code,p=self.export(True,p["result"]["input_sha256"]);self.assertEqual(code,0,p)
        self.assertEqual(self.dest.read_bytes(),expected);self.assertEqual(files(self.model),before);self.assertEqual(dirs(self.model),before_dirs)
        self.assertTrue(p["result"]["exact_bytes"]);return p["result"]
    def mutate(self,path,old,new):
        info=path.stat();before=path.read_bytes();after=before.replace(old,new,1)
        self.assertNotEqual(before,after);self.assertEqual(len(before),len(after));path.write_bytes(after)
        os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns));self.assertEqual((path.stat().st_size,path.stat().st_mtime_ns),(info.st_size,info.st_mtime_ns))


class ObservationTransferExportTests(TransferCase):
    def test_export_exact_without_mesh_or_unrelated_references(self):self.export_ok()
    def test_empty_comment_BOM_only_exports_are_zero_station_artifacts(self):
        for i,data in enumerate((b"",b"# comments only\r\n",b"\xef\xbb\xbf")):
            with self.subTest(i=i):
                self.target.write_bytes(data);self.dest=self.root/f"empty-{i}.xyn"
                self.assertEqual(self.export_ok()["station_count"],0)
    def test_duplicate_casefold_export_preserves_bytes_reports_diagnostic(self):
        self.target.write_bytes(TARGET+b"\r\n300002 4000001 'BASE STATION'\r\n")
        self.assertTrue(self.export_ok()["duplicate_or_casefold_aliases"])
    def test_overwide_257_export_is_archival_not_sanitized(self):
        prefix=b"300002 4000001 ";self.target.write_bytes(prefix+b"'"+b"n"*(257-len(prefix)-2)+b"'\n")
        self.assertTrue(self.export_ok()["record_buffer_check"]["violations"])
    def test_existing_destination_not_overwritten(self):
        self.dest.write_bytes(b"foreign");self.refused(self.export)
    def test_destination_inside_model_refused(self):
        self.dest=self.model/"fresh.xyn";self.refused(self.export)
    def test_export_not_XYZ(self):
        self.dest=self.root/"fresh.xyz";self.refused(self.export)
    def test_destination_arrival_after_preview_preserved(self):
        code,p=self.export();self.assertEqual(code,0,p);self.dest.write_bytes(b"foreign arrival")
        self.refused(lambda:self.export(True,p["result"]["input_sha256"]))
    def test_export_stale_source_same_size_mtime(self):
        code,p=self.export();self.assertEqual(code,0,p);self.mutate(self.target,b"preserve",b"PRESERVE")
        self.refused(lambda:self.export(True,p["result"]["input_sha256"]),4)
    def test_export_stale_MDU_same_size_mtime(self):
        code,p=self.export();self.assertEqual(code,0,p);self.mutate(self.mdu,b"portable",b"PORTABLE")
        self.refused(lambda:self.export(True,p["result"]["input_sha256"]),4)


@unittest.skipUnless(GEO,"Optional geo extra required: netCDF4, numpy, pyproj")
class ObservationTransferImportTests(TransferCase):
    def setUp(self):
        super().setUp();mesh(self.model/"mesh.nc")
        (self.model/"missing.pli").write_bytes(b"Q\n2 2\n300002 4000000.5\n300002 4000003.5\n")
        self.mdu.write_bytes(self.mdu.read_bytes()+b"[External Forcing]\r\nExtForceFileNew = forcing.ext\r\n")
        (self.model/"forcing.ext").write_bytes(b"[General]\nfileType = extForce\n[Boundary]\nquantity = waterlevelbnd\nlocationFile = edge.pli\nforcingFile = opaque.bc\n")
        (self.model/"edge.pli").write_bytes(b"west\n2 2\n300000 4000000\n300000 4000004\n")
        (self.model/"opaque.bc").write_bytes(b"# future signal grammar, station edit only hashes it\n[General]\nfileType = boundConds\n[Future]\nvalue=keep\n")
    def import_ok(self,mode="append"):
        before=files(self.model);before_dirs=dirs(self.model);target=self.target.read_bytes();source=self.source.read_bytes()
        code,p=self.importing(mode);self.assertEqual(code,0,p);self.assertEqual(files(self.model),before)
        code,p=self.importing(mode,True,p["result"]["input_sha256"]);self.assertEqual(code,0,p)
        expected=source if mode=="replace-all" else target+(b"" if not target or target.endswith(b"\n") else b"\r\n")+source.removeprefix(b"\xef\xbb\xbf")
        self.assertEqual(self.target.read_bytes(),expected);self.assertEqual(self.source.read_bytes(),source)
        for name,raw in before.items():
            if name!="stations.xyn":self.assertEqual(files(self.model)[name],raw,name)
        self.assertEqual(dirs(self.model),before_dirs);return p["result"]
    def test_append_exact_old_prefix_uploaded_trivia_and_disclosed_BOM_framing(self):self.import_ok()
    def test_replace_all_exact_upload_and_disclosed_removed_IDs(self):
        result=self.import_ok("replace-all")
        self.assertEqual(set(result["identity_disclosure"]["removed_ids"]),{"Base station","keep_plain"})
        self.assertEqual(set(result["identity_disclosure"]["added_ids"]),{"NEW","Fresh station"})
    def test_empty_target_append_allowed(self):self.target.write_bytes(b"");self.import_ok()
    def test_no_default_mode(self):self.refused(lambda:self.importing(None),2)
    def test_one_case_collision_refuses_entire_batch(self):
        self.source.write_bytes(UPLOAD.replace(b"NEW",b"'BASE STATION'"));self.refused(self.importing,3)
    def test_NFC_duplicate_source_refuses_entire_batch(self):
        self.source.write_bytes("300006 4000001 'é_id'\n300005 4000002 'e\u0301_id'\n".encode());self.refused(self.importing,3)
    def test_zero_incoming_refused_even_explicit_replace_all(self):
        self.source.write_bytes(b"# zero stations\n");self.refused(lambda:self.importing("replace-all"),3)
    def test_late_shared_edge_station_refuses_entire_batch(self):
        self.source.write_bytes(UPLOAD+b"\n300004 4000002 'last edge'\n");self.refused(self.importing,3)
    def test_outside_not_snapped(self):self.source.write_bytes(b"300009 4000002 outside\n");self.refused(self.importing,3)
    def test_multibyte_required_record_end257_refused(self):
        prefix=b"300006 4000001 ";count=257-len(prefix)-2;name="x"*(count%2)+"é"*(count//2)
        self.source.write_bytes(prefix+b"'"+name.encode()+b"'\n");self.refused(self.importing,3)
    def test_upload_text_limit_not_hidden_by_short_station_rows(self):
        prefix=b"300006 4000001 NEW\n#";self.source.write_bytes(prefix+b"x"*(8*1024*1024+1-len(prefix)))
        self.refused(self.importing,3)
    def stale(self,mutate):
        code,p=self.importing();self.assertEqual(code,0,p);mutate()
        self.refused(lambda:self.importing("append",True,p["result"]["input_sha256"]),4)
    def test_stale_upload_ID_same_size_mtime(self):self.stale(lambda:self.mutate(self.source,b"NEW",b"ALT"))
    def test_stale_target_same_size_mtime(self):self.stale(lambda:self.mutate(self.target,b"preserve",b"PRESERVE"))
    def test_stale_connected_opaque_BC_same_size_mtime(self):self.stale(lambda:self.mutate(self.model/"opaque.bc",b"value=keep",b"value=KEEP"))
    def test_stale_mesh_same_size_mtime(self):
        def mutate():
            import netCDF4 as nc
            path=self.model/"mesh.nc";info=path.stat()
            with nc.Dataset(path,"r+") as d:d["mesh2d_node_x"][0]=300000.125
            os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns));self.assertEqual((path.stat().st_size,path.stat().st_mtime_ns),(info.st_size,info.st_mtime_ns))
        self.stale(mutate)
    def test_mode_switch_cannot_reuse_preview(self):
        code,p=self.importing();self.assertEqual(code,0,p)
        self.refused(lambda:self.importing("replace-all",True,p["result"]["input_sha256"]),4)


if __name__=="__main__":unittest.main()
