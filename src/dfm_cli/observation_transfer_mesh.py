"""One prepared batch spatial index; shared G06 reader owns all mesh checks.

No per-station mesh reads/quality validation. Geometry preparation delegates to
observation_mesh_reader, shared with G06. Its existing CF validator adds one
fixed read per batch, independently of station count. No root changes here.
"""
from fractions import Fraction
import math

from .observation_text import number
from .observation_transfer_contract import MAX_ROWS, MAX_INDEX_REFS, MAX_EXACT_FACE_TESTS, MAX_AABB_TESTS
from .observation_transfer_io import fail


def prepare(graph, crs, unit):
    from .observation_mesh_reader import read_validated_mesh
    return Prepared(**read_validated_mesh(graph, crs, unit, fail=fail))


class Prepared:
    def __init__(self,nodes,faces,normalized,target,metrics,face_dimension,dimension_basis,crs,unit,versions):
        self.nodes,self.faces,self.normalized=nodes,faces,normalized
        self.target,self.metrics=target,metrics
        self.face_dimension,self.dimension_basis=face_dimension,dimension_basis
        self.crs,self.unit,self.versions=crs,unit,versions
        self.extent=metrics["extent"]
        self.side=max(1,min(256,math.ceil(math.sqrt(len(faces)))))
        self.boxes=[]
        self.buckets={}
        self.fractions={}
        self.cache={}
        self.work={"geometry_preparations":1,"quality_passes":1,"index_references":0,"AABB_tests":0,"exact_face_tests":0,"cache_hits":0,"positions":0}
        for index,face in enumerate(normalized):
            polygon=[nodes[n] for n in face]
            box=(min(p[0] for p in polygon),min(p[1] for p in polygon),max(p[0] for p in polygon),max(p[1] for p in polygon))
            self.boxes.append(box)
            lo,hi=self.cell(box[:2]),self.cell(box[2:])
            for i in range(lo[0],hi[0]+1):
                for j in range(lo[1],hi[1]+1):
                    self.work["index_references"]+=1
                    if self.work["index_references"]>MAX_INDEX_REFS:
                        fail("geometry_budget", "Spatial-index reference budget exceeded",self.work)
                    self.buckets.setdefault((i,j),[]).append(index)

    def cell(self,point):
        return tuple(max(0,min(self.side-1,int((point[a]-self.extent[a])/(self.extent[a+2]-self.extent[a])*self.side))) for a in (0,1))

    def locate(self,row,dataset):
        self.work["positions"]+=1
        if self.work["positions"]>MAX_ROWS:
            fail("geometry_budget", "Combined original/incoming position budget exceeded",self.work)
        xy=[number(row[a],existing=True) for a in ("x","y")]
        key=tuple(v[0] for v in xy)
        if key in self.cache:
            self.work["cache_hits"]+=1
            face=self.cache[key]
        else:
            face=self._locate(xy,{"dataset":dataset,"line":row["line"],"id":row["id"]})
            self.cache[key]=face
        return {"dataset":dataset,"id":row["id"],"line":row["line"],"input_XY":{"x":row["x"],"y":row["y"]},
                "input_face_index":face,"index_base":0,
                "node_indices":list(self.faces[face]),"node_index_base":0,
                "polygon_xy_m":[list(self.nodes[n]) for n in self.faces[face]]}

    def _locate(self,xy,identity):
        binary=tuple(v[1] for v in xy)
        points=[tuple(Fraction(v[0]) for v in xy),tuple(Fraction(v[1]) for v in xy)]
        interiors,edges=[[],[]],[[],[]]
        if all(self.extent[a]<=binary[a]<=self.extent[a+2] for a in (0,1)):
            for index in self.buckets.get(self.cell(binary),[]):
                self.work["AABB_tests"]+=1
                if self.work["AABB_tests"]>MAX_AABB_TESTS:
                    fail("geometry_budget", "AABB query budget exceeded",self.work)
                box=self.boxes[index]
                if not all(box[a]<=binary[a]<=box[a+2] for a in (0,1)):
                    continue
                self.work["exact_face_tests"]+=1
                if self.work["exact_face_tests"]>MAX_EXACT_FACE_TESTS:
                    fail("geometry_budget", "Exact face predicate budget exceeded",self.work)
                face=self.normalized[index]
                for n in face:
                    if n not in self.fractions:
                        self.fractions[n]=tuple(Fraction(v) for v in self.nodes[n])
                poly=[self.fractions[n] for n in face]
                for which,point in enumerate(points):
                    crosses=[(b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0]) for a,b in zip(poly,poly[1:]+poly[:1])]
                    if all(v>=0 for v in crosses):
                        (edges[which] if any(v==0 for v in crosses) else interiors[which]).append(index)
        for which in (0,1):
            if edges[which] or len(interiors[which])!=1:
                fail("location_not_strict_interior", "Every original and incoming position must be strictly inside exactly one face",
                     {**identity,"basis":"decimal_request" if which==0 else "binary64_written","interior_faces":interiors[which],"boundary_faces":edges[which]})
        if interiors[0][0]!=interiors[1][0]:
            fail("location_rounding", "Decimal and written binary64 positions select different faces",identity)
        return interiors[0][0]

    def report(self):
        return {"requested_crs":self.crs,"unit":self.unit,"axis_order":"file_X_Y","transformation_performed":False,
                "target_model":self.target,"geometry_validation":self.metrics,
                "face_basis":"input UGRID connectivity row; NOT runtime FM map numbering",
                "predicate_basis":"exact rational predicates on actual mesh binary64 nodes; decimal AND binary64 request; no tolerance/snap",
                "face_dimension":self.face_dimension,"face_dimension_basis":self.dimension_basis,
                "work":{**self.work,"exact_nodes_constructed":len(self.fractions),"spatial_buckets":len(self.buckets)},
                "reader_versions":self.versions,"native_snapped_coordinates":None,"native_snap_verified":False,
                "vertical_datum":"not inferred or modified; no vertical coordinate imported"}
