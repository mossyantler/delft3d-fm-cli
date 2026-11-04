"""Portable G06 public CLI tests; no research fixtures or product helper imports.

Inspection/schema need only stdlib. Edit tests skip if optional geo packages are
absent. Every model is independently authored in a TemporaryDirectory; no native
engine, GUI, installation or existing project is used.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HAVE_GEO = all(importlib.util.find_spec(name) is not None for name in ("netCDF4", "numpy", "pyproj"))
X, Y = "400012.5", "2000001.5"
RAW = (b"\xef\xbb\xbf# portable independently authored stations\r\n"
       b" 4.00002375D+05\t2.000000750E+06  'Anchor west' # keep quoted identity\r\n"
       b"400014.25 2000002.5 plain_keep # retain old row\r\n"
       b"# unknown comment stays byte-identical\r\n"
       b"400012.625 2000000.25 'Gauge East' # EOF comment without newline")
NODES = [(400000,2000000),(400012,2000000),(400014,2000000),
         (400002,2000004),(400014,2000004),(400016,2000004)]
FACES = [(0,1,4,3),(1,2,5,4)]


def snapshot(root):
    return {p.relative_to(root).as_posix():p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def directories(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir())


def write_mesh(path):
    import netCDF4 as nc
    edges=sorted({tuple(sorted((a,b))) for f in FACES for a,b in zip(f,f[1:]+f[:1])})
    with nc.Dataset(path,"w",format="NETCDF3_64BIT_OFFSET") as d:
        for n,size in (("node",6),("face",2),("maxFaceNodes",4),("edge",len(edges)),("two",2)):d.createDimension(n,size)
        d.Conventions="CF-1.8 UGRID-1.0";d.vertical_datum="local fixture zero; no conversion"
        crs=d.createVariable("projected_coordinate_system","i4");crs.assignValue(0)
        crs.setncatts({"EPSG_code":"EPSG:32631","epsg":32631,"grid_mapping_name":"transverse_mercator",
            "longitude_of_central_meridian":3.,"latitude_of_projection_origin":0.,"scale_factor_at_central_meridian":.9996,
            "false_easting":500000.,"false_northing":0.,"semi_major_axis":6378137.,"inverse_flattening":298.257223563,
            "longitude_of_prime_meridian":0.})
        t=d.createVariable("mesh2d","i4");t.assignValue(0)
        t.setncatts({"cf_role":"mesh_topology","topology_dimension":2,"node_coordinates":"mesh2d_node_x mesh2d_node_y mesh2d_node_z",
            "face_node_connectivity":"mesh2d_face_nodes","face_dimension":"face","edge_node_connectivity":"mesh2d_edge_nodes","grid_mapping":crs.name})
        for axis,i in (("x",0),("y",1)):
            v=d.createVariable("mesh2d_node_"+axis,"f8",("node",));v[:]=[p[i] for p in NODES]
            v.units="m";v.standard_name="projection_"+axis+"_coordinate";v.grid_mapping=crs.name
        z=d.createVariable("mesh2d_node_z","f8",("node",));z[:]=[-1]*6;z.units="m";z.positive="up";z.grid_mapping=crs.name
        for name,data,dimensions,role in (("mesh2d_face_nodes",FACES,("face","maxFaceNodes"),"face_node_connectivity"),
              ("mesh2d_edge_nodes",edges,("edge","two"),"edge_node_connectivity")):
            v=d.createVariable(name,"i4",dimensions);v[:]=data;v.start_index=0;v.cf_role=role


class PublicCase(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix="g06-observation-public-")
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)/"dedicated model";self.root.mkdir()
        self.mdu=self.root/"model.mdu";self.xyn=self.root/"stations.xyn";self.mesh=self.root/"mesh.nc"
        self.xyn.write_bytes(RAW)
        self.mdu.write_bytes(b"# standalone portable fixture\r\n[General]\r\nFileType = modelDef\r\nFileVersion = 1.09\r\nPathsRelativeToParent = 0\r\n[Geometry]\r\nNetFile = mesh.nc\r\n[External Forcing]\r\nExtForceFileNew = forcing.ext\r\n[Output]\r\nObsFile = stations.xyn # retain comment\r\nCrsFile = sections.pli\r\nOutputDir = output\r\nHisFile = history.nc\r\n[Vendor]\r\nUnknownScalar = preserve\r\n")
        (self.root/"forcing.ext").write_bytes(b"[General]\nfileType = extForce\nfileVersion = 2.01\n[Boundary]\nquantity = waterlevelbnd\nlocationFile = boundary.pli\nforcingFile = future.bc\n")
        (self.root/"future.bc").write_bytes(b"# future BC syntax stays opaque to station editor\n[General]\nfileType = boundConds\n[UnknownSignal]\nopaque = preserve\n")
        (self.root/"boundary.pli").write_bytes(b"west\n2 2\n400000 2000000\n400002 2000004\n")
        (self.root/"sections.pli").write_bytes(b"Q_NOT_A_COORDINATE_CRS\n2 2\n400004 2000000.5\n400005 2000003.5\n")
        (self.root/"unknown.bin").write_bytes(b"\x00\xffunknown\r\n")
        (self.root/"output").mkdir()

    def call(self,*args):
        self.assertTrue(args[:2] in (("schema","inspect"),("observation","inspect"),("observation","add"),("observation","move")))
        env=os.environ.copy();env["PYTHONPATH"]=str(ROOT/"src");env["PYTHONDONTWRITEBYTECODE"]="1"
        r=subprocess.run([sys.executable,"-B","-m","dfm_cli",*map(str,args)],cwd=ROOT,env=env,capture_output=True,timeout=30)
        try:p=json.loads(r.stdout)
        except (ValueError,UnicodeError):self.fail(f"Non-JSON public response: {r.stdout!r} {r.stderr!r}")
        self.assertEqual(p.get("protocol_version"),2)
        self.assertEqual(r.returncode==0,p.get("ok") is True,p)
        self.assertNotEqual(r.returncode,70,p);self.assertEqual(r.stderr,b"",r.stderr)
        return r.returncode,p

    def edit(self,action="move",identity="Anchor west",x=X,y=Y,apply=False,digest=None):
        args=["observation",action,self.mdu,"--id",identity,"--x",x,"--y",y,"--crs","EPSG:32631","--unit","m"]
        if apply:args += ["--apply"]
        if digest is not None:args += ["--expect-sha256",digest]
        return self.call(*args)

    def refusal(self,expected=3,**options):
        before=snapshot(self.root);before_dirs=directories(self.root)
        try:code,p=self.edit(**options)
        finally:
            self.assertEqual(snapshot(self.root),before,"Refusal/failed operation changed input bytes")
            self.assertEqual(directories(self.root),before_dirs,"Refusal changed directories")
        self.assertEqual(code,expected,p);self.assertTrue(p["error"]["code"])
        return p["error"]


class ObservationInspectPublicTests(PublicCase):
    def test_schema_parameters_and_record_byte_bound(self):
        code,p=self.call("schema","inspect");self.assertEqual(code,0)
        result=p["result"];contract=result["observation_edit"]
        self.assertEqual(contract["contract"],"observation-named-xyn-v2")
        self.assertEqual(contract["bounds"]["serialized_record_required_tokens_end_byte_column"],256)
        for action in ("add","move"):
            parameters={v["name"]:v for v in result["command_parameters"]["observation "+action]}
            for name in ("mdu","id","x","y","crs","unit"):self.assertTrue(parameters[name]["required"])
            self.assertEqual(parameters["unit"]["choices"],["m"])

    def test_inspect_without_mesh_reports_raw_spans_not_inferred_CRS(self):
        before=snapshot(self.root)
        code,p=self.call("observation","inspect",self.mdu);self.assertEqual(code,0,p)
        r=p["result"];self.assertEqual(r["ObsFile"]["raw_value"],"stations.xyn")
        self.assertEqual(r["CRS"],"not_inferred_or_validated")
        stations=r["stations"]["rows"]
        self.assertEqual([s["id"] for s in stations],["Anchor west","plain_keep","Gauge East"])
        for row in stations:
            self.assertEqual(RAW[slice(*row["x_span"])].decode(),row["x"])
            self.assertEqual(RAW[slice(*row["y_span"])].decode(),row["y"])
            self.assertEqual(RAW[slice(*row["id_span"])].decode(),row["id_token"])
        self.assertEqual(snapshot(self.root),before)


@unittest.skipUnless(HAVE_GEO,"Optional geo extra required: netCDF4, numpy, pyproj")
class ObservationEditPublicTests(PublicCase):
    def setUp(self):super().setUp();write_mesh(self.mesh)

    def apply(self,action="move",identity="Anchor west",x=X,y=Y):
        before=snapshot(self.root);before_dirs=directories(self.root)
        code,p=self.edit(action,identity,x,y);self.assertEqual(code,0,p)
        self.assertEqual(snapshot(self.root),before,"Preview wrote files")
        self.assertEqual(directories(self.root),before_dirs)
        preview=p["result"]
        self.assertEqual(preview["original_input_XY"]["x"],x)
        self.assertEqual(preview["original_input_XY"]["y"],y)
        self.assertEqual(preview["target_face"]["index"],0)
        self.assertEqual(preview["target_face"]["index_base"],0)
        self.assertFalse(preview["geometry"]["native_snap_verified"])
        digest=preview["input_sha256"];self.assertRegex(digest,r"^[0-9a-f]{64}$")
        code,p=self.edit(action,identity,x,y,apply=True,digest=digest);self.assertEqual(code,0,p)
        after=snapshot(self.root)
        self.assertEqual(set(after),set(before))
        for name,raw in before.items():
            if name!="stations.xyn":self.assertEqual(after[name],raw,name)
        self.assertEqual(directories(self.root),before_dirs)
        return before["stations.xyn"],after["stations.xyn"]

    def test_move_only_two_tokens_preserves_BOM_quotes_trivia_and_non_nearest_face(self):
        before,after=self.apply()
        expected=before.replace(b"4.00002375D+05",X.encode(),1).replace(b"2.000000750E+06",Y.encode(),1)
        self.assertEqual(after,expected)
        # x=400012.5,y=2000001.5 is left of shared x=400012+0.5*(y-2000000),
        # inside face0, although face1 centre(400014,2000002) is closer than
        # face0 centre(400007,2000002). No snapped coordinates are inferred.
        self.assertLess(float(X),400012+.5*(float(Y)-2000000))

    def test_add_has_separate_EOF_framing_and_preserves_original_prefix(self):
        before,after=self.apply("add","New station")
        self.assertEqual(after,before+b"\r\n"+X.encode()+b" "+Y.encode()+b" 'New station'\r\n")

    def boundary_name(self,column,multibyte=False,leading=b"",bom=b"",x=X,y=Y):
        prefix=bom+leading+x.encode()+b" "+y.encode()+b" "
        size=column-len(prefix)-2
        identity=("a"*(size%2)+"\u00e9"*(size//2)) if multibyte else "n"*size
        self.assertLessEqual(len(identity),255)
        row=prefix+b"'"+identity.encode()+b"'"
        self.assertEqual(len(row),column)
        return identity,row

    def test_ASCII_closing_apostrophe_full_row_column256_is_accepted(self):
        identity,_=self.boundary_name(256)
        _,after=self.apply("add",identity)
        last=after.splitlines()[-1];self.assertEqual(len(last),256);self.assertTrue(last.endswith(b"'"))

    def test_ASCII_closing_apostrophe_full_row_column257_is_refused_unchanged(self):
        identity,_=self.boundary_name(257)
        error=self.refusal(action="add",identity=identity)
        self.assertEqual(error["code"],"observation_record_too_long")

    def test_multibyte_codepoint_count_fits_but_row257_is_refused_unchanged(self):
        identity,_=self.boundary_name(257,multibyte=True)
        self.assertLess(len(identity),len(identity.encode()))
        error=self.refusal(action="add",identity=identity)
        self.assertEqual(error["code"],"observation_record_too_long")

    def test_existing_overwide_row_counts_leading_bytes_and_BOM(self):
        identity,row=self.boundary_name(257,leading=b" \t",bom=b"\xef\xbb\xbf")
        self.xyn.write_bytes(row+b"\r\n")
        self.assertEqual(self.refusal(identity=identity)["code"],"observation_record_too_long")

    def test_shared_edge_refused_without_snap(self):self.refusal(x="400013",y="2000002")
    def test_shared_vertex_refused(self):self.refusal(x="400012",y="2000000")
    def test_outside_refused_without_nearest_fallback(self):self.refusal(x="400017",y="2000002")
    def test_add_existing_or_casefold_ID_refused(self):
        self.refusal(action="add",identity="anchor WEST")
    def test_aliased_observation_cross_section_input_refused(self):
        self.mdu.write_bytes(self.mdu.read_bytes().replace(b"CrsFile = sections.pli",b"CrsFile = stations.xyn"));self.refusal()
    def test_repeated_ObsFile_reference_refused(self):
        self.mdu.write_bytes(self.mdu.read_bytes().replace(b"ObsFile = stations.xyn",b"ObsFile = stations.xyn\r\nObsFile = stations.xyn"));self.refusal()
    def test_missing_apply_consent_refused(self):self.refusal(expected=2,apply=True)

    def stale(self,mutate):
        code,p=self.edit();self.assertEqual(code,0,p)
        mutate()
        self.assertEqual(self.refusal(expected=4,apply=True,digest=p["result"]["input_sha256"])["code"],"observation_stale_preview")

    def same_stat(self,path,old,new):
        info=path.stat();raw=path.read_bytes();new_raw=raw.replace(old,new,1)
        self.assertNotEqual(raw,new_raw);self.assertEqual(len(raw),len(new_raw))
        path.write_bytes(new_raw);os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns))
        self.assertEqual((path.stat().st_size,path.stat().st_mtime_ns),(info.st_size,info.st_mtime_ns))

    def test_stale_non_target_XYN_byte_change_same_size_and_mtime(self):
        self.stale(lambda:self.same_stat(self.xyn,b"retain old row",b"RETAIN old row"))
    def test_stale_connected_BC_opaque_bytes_same_size_and_mtime(self):
        self.stale(lambda:self.same_stat(self.root/"future.bc",b"opaque = preserve",b"opaque = PRESERVE"))
    def test_stale_cross_section_bytes_same_size_and_mtime(self):
        self.stale(lambda:self.same_stat(self.root/"sections.pli",b"400005",b"400006"))
    def test_stale_mesh_coordinate_bytes_same_size_and_mtime(self):
        def mutate():
            import netCDF4 as nc
            info=self.mesh.stat()
            with nc.Dataset(self.mesh,"r+") as d:d["mesh2d_node_x"][0]=400000.125
            os.utime(self.mesh,ns=(info.st_atime_ns,info.st_mtime_ns))
            self.assertEqual((self.mesh.stat().st_size,self.mesh.stat().st_mtime_ns),(info.st_size,info.st_mtime_ns))
        self.stale(mutate)


if __name__=="__main__":unittest.main()
