"""Independent E012 tests: generated meshes, ghost masks, confinement refusals.

No test launches an MPI launcher or native engine. Numerical oracles use raw
netCDF4, fixed predeclared tolerances, topology identity and face orientation.
"""
from __future__ import annotations

import copy
import ctypes
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

try:
    import netCDF4 as nc
    import numpy as np
except ImportError:
    nc = np = None

from research.workflows.verification.verify_parallel import (
    COORDINATE_ATOL, TOLERANCES, compare_arrays, compare_histories, compare_maps,
    compare_partition_values, entity_mapping, partition_oracle, ring, topology,
    partition_input_oracle, assembled_identity_and_masks, dataset_inventory,
    checkpoint_oracle, exact_state,
)


NODES = [(0., 0.), (1., 0.), (2., 0.), (0., 1.), (1., 1.), (2., 1.)]
FACES = [(0, 1, 4, 3), (1, 2, 5, 4)]
EDGES = [(0, 1), (1, 4), (4, 3), (3, 0), (1, 2), (2, 5), (5, 4)]
ADJACENT = [(0, None), (0, 1), (0, None), (0, None), (1, None), (1, None), (1, None)]


def write_map(path, *, node_order=(0, 1, 2, 3, 4, 5), face_order=(0, 1), edge_order=(0, 1, 2, 3, 4, 5, 6),
              reverse_neighbours=(), reverse_endpoints=(), rank=None, poison_ghosts=False, start_index=1):
    node_local = {global_id: local for local, global_id in enumerate(node_order)}
    face_local = {global_id: local for local, global_id in enumerate(face_order)}
    with nc.Dataset(path, "w") as ds:
        for key, count in (("mesh2d_nNodes", 6), ("mesh2d_nFaces", 2), ("mesh2d_nEdges", 7),
                           ("max_nodes", 4), ("two", 2), ("time", 3)):
            ds.createDimension(key, count)
        mesh = ds.createVariable("mesh2d", "i4")
        mesh.cf_role, mesh.topology_dimension = "mesh_topology", 2
        mesh.node_coordinates = "mesh2d_node_x mesh2d_node_y"
        mesh.node_dimension, mesh.face_dimension, mesh.edge_dimension = "mesh2d_nNodes", "mesh2d_nFaces", "mesh2d_nEdges"
        mesh.face_node_connectivity, mesh.edge_node_connectivity = "mesh2d_face_nodes", "mesh2d_edge_nodes"
        mesh.edge_face_connectivity = "mesh2d_edge_faces"
        mesh.face_coordinates, mesh.edge_coordinates = "mesh2d_face_x mesh2d_face_y", "mesh2d_edge_x mesh2d_edge_y"
        crs = ds.createVariable("crs", "i4")
        crs.grid_mapping_name, crs.EPSG_code = "transverse_mercator", "EPSG:32631"
        for axis, component in (("x", 0), ("y", 1)):
            var = ds.createVariable("mesh2d_node_" + axis, "f8", ("mesh2d_nNodes",))
            var.units, var.standard_name = "m", "projection_" + axis + "_coordinate"
            var[:] = [NODES[i][component] for i in node_order]
        for entity, order, identities in (("face", face_order, FACES), ("edge", edge_order, EDGES)):
            for component, axis in enumerate(("x", "y")):
                var = ds.createVariable(f"mesh2d_{entity}_{axis}", "f8", (f"mesh2d_n{entity.title()}s",))
                var.units, var.standard_name = "m", "projection_" + axis + "_coordinate"
                var[:] = [sum(NODES[j][component] for j in identities[i]) / len(identities[i]) for i in order]
        face_nodes = ds.createVariable("mesh2d_face_nodes", "i4", ("mesh2d_nFaces", "max_nodes"), fill_value=-999)
        face_nodes.start_index = start_index
        face_nodes[:] = [[node_local[i] + start_index for i in FACES[face]] for face in face_order]
        edge_nodes = ds.createVariable("mesh2d_edge_nodes", "i4", ("mesh2d_nEdges", "two"), fill_value=-999)
        edge_nodes.start_index = start_index
        edge_nodes[:] = [[node_local[i] + start_index for i in (EDGES[edge][::-1] if edge in reverse_endpoints else EDGES[edge])]
                         for edge in edge_order]
        adjacent = ds.createVariable("mesh2d_edge_faces", "i4", ("mesh2d_nEdges", "two"), fill_value=-999)
        adjacent.start_index = start_index
        adjacent[:] = [[-999 if face is None else face_local[face] + start_index
                        for face in (ADJACENT[edge][::-1] if edge in reverse_neighbours else ADJACENT[edge])]
                       for edge in edge_order]
        time = ds.createVariable("time", "f8", ("time",))
        time.standard_name, time.units = "time", "seconds since 2001-01-01 00:00:00"
        time[:] = [0, 60, 120]
        for entry in TOLERANCES["map"]:
            name = entry["variable"]
            location = "edge" if name in ("mesh2d_u1", "mesh2d_q1") else "face"
            order = edge_order if location == "edge" else face_order
            values = np.ma.array(np.arange(3 * len(order), dtype=float).reshape(3, len(order)) / 10, mask=False)
            if location == "face":
                values.mask[1, 0] = True
                if rank is not None and poison_ghosts:
                    values[:, 1 - rank] = 12345  # Ghost faces must never enter the owner assembly.
            else:
                values.mask[:, 0] = True
                for edge in reverse_neighbours:
                    values[:, edge] *= -1
            var = ds.createVariable(name, "f8", ("time", "mesh2d_nEdges" if location == "edge" else "mesh2d_nFaces"), fill_value=-999.)
            var.mesh, var.location, var.grid_mapping = "mesh2d", location, "crs"
            var.coordinates = f"mesh2d_{location}_x mesh2d_{location}_y"
            var.units = "m3 s-1" if name == "mesh2d_q1" else "m s-1" if name != "mesh2d_s1" else "m"
            var[:] = values[:, order]
        if rank is not None:
            for name, data in (("mesh2d_flowelem_domain", [face for face in face_order]),
                               ("mesh2d_flowelem_globalnr", [face + 1 for face in face_order])):
                var = ds.createVariable(name, "i4", ("mesh2d_nFaces",))
                var[:] = data


def write_history(path, *, reversed_stations=False, offset=0):
    with nc.Dataset(path, "w") as ds:
        ds.createDimension("time", 3)
        ds.createDimension("station", 2)
        ds.createDimension("name_len", 16)
        order = [1, 0] if reversed_stations else [0, 1]
        t = ds.createVariable("time", "f8", ("time",))
        t.standard_name, t.units = "time", "seconds since 2001-01-01"
        t[:] = [0, 60, 120]
        for key, labels in (("station_id", ["west", "east"]), ("station_name", ["display", "display"])):
            var = ds.createVariable(key, "S1", ("station", "name_len"))
            var.cf_role = "timeseries_id"
            var[:] = nc.stringtochar(np.array([labels[i] for i in order], dtype="S16"))
            var._Encoding = "utf-8"
        for key, data in (("station_x_coordinate", [.5, 1.5]), ("station_y_coordinate", [.5, .5])):
            var = ds.createVariable(key, "f8", ("station",))
            var.units = "m"
            var[:] = [data[i] for i in order]
        for entry in TOLERANCES["history"]:
            var = ds.createVariable(entry["variable"], "f8", ("time", "station"), fill_value=-999.)
            var.units = "m" if entry["variable"] == "waterlevel" else "m3 s-1" if entry["variable"] == "discharge_magnitude" else "m s-1"
            values = np.ma.array([[.1, .2], [.3, .4], [.5, .6]], mask=False) + offset
            values.mask[1, 0] = True
            var[:] = values[:, order]


def write_checkpoint(path, *, assembled=False, reversed_internal=False):
    """Portable legacy checkpoint with real/boundary link direction changes."""
    with nc.Dataset(path, "w") as ds:
        ds.vertical_datum = "synthetic zero"
        for name, count in (("time", 1), ("nNetNode", 6), ("nFlowElem", 2), ("nNetElem", 2),
                            ("nNetElemMaxNode", 4), ("nNetLink", 7), ("nNetLinkPts", 2),
                            ("nFlowLink", 3), ("nFlowLinkPts", 2), ("nFlowElemBnd", 2)):
            ds.createDimension(name, count)
        for name, dims, values, dtype in (
                ("time", ("time",), [120.], "f8"), ("timestep", ("time",), [1.], "f8"),
                ("FlowElemGlobalNr", ("nFlowElem",), [1, 2], "i4"),
                ("FlowElemDomain", ("nFlowElem",), [0, 1], "i4"),
                ("NetElemNode", ("nNetElem", "nNetElemMaxNode"), np.asarray(FACES) + 1, "i4"),
                ("NetLink", ("nNetLink", "nNetLinkPts"), np.asarray(EDGES) + 1, "i4"),
                ("FlowLink_xu", ("nFlowLink",), [1., 0., 2.], "f8"),
                ("FlowLink_yu", ("nFlowLink",), [.5, .5, .5], "f8"),
                ("FlowElem_xbnd", ("nFlowElemBnd",), [-.25, 2.25], "f8"),
                ("FlowElem_ybnd", ("nFlowElemBnd",), [.5, .5], "f8")):
            var = ds.createVariable(name, dtype, dims)
            var[:] = values
            if name in ("NetElemNode", "NetLink"):
                var.start_index = 1
            if name == "time":
                var.units = "seconds since 2001-01-01"
        links = [[1, 2], [1, 3], [2, 4]] if assembled else [[1, 2], [3, 1], [4, 2]]
        if reversed_internal:
            links[0] = links[0][::-1]
        var = ds.createVariable("FlowLink", "i4", ("nFlowLink", "nFlowLinkPts"))
        var[:] = links
        for name, dims, values in (("s1", ("time", "nFlowElem"), [[.2, .4]]),
                                   ("unorm", ("time", "nFlowLink"), [[1., -2., -3.]] if assembled else [[-1. if reversed_internal else 1., 2., 3.]]),
                                   ("s1_bnd", ("time", "nFlowElemBnd"), [[.1, .3]])):
            var = ds.createVariable(name, "f8", dims, fill_value=-999.)
            values = np.ma.array(values, mask=False)
            if name == "unorm":
                values.mask[0, 1] = True
            var[:] = values
        if assembled:
            for axis, values in (("x", [point[0] for point in NODES]), ("y", [point[1] for point in NODES]), ("z", [-3.] * 6)):
                var = ds.createVariable("NetNode_" + axis, "f8", ("nNetNode",))
                var[:] = values
            ds.createVariable("projected_coordinate_system", "i4")


@unittest.skipIf(nc is None, "netCDF4 optional run extra is required")
class CheckpointOracleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-e012-checkpoint-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.mesh = self.root / "input_net.nc"
        write_map(self.mesh)
        with nc.Dataset(self.mesh, "r+") as ds:
            ds.vertical_datum = "synthetic zero"
            z = ds.createVariable("mesh2d_node_z", "f8", ("mesh2d_nNodes",))
            z[:] = [-3.] * 6
        self.output = self.root / "assembled_rst.nc"
        write_checkpoint(self.output, assembled=True)
        self.sources = []
        for rank in range(2):
            map_path, restart = self.root / f"rank-{rank}_map.nc", self.root / f"rank-{rank}_rst.nc"
            write_map(map_path, rank=rank)
            write_checkpoint(restart, reversed_internal=rank == 1)
            self.sources.append({"rank": rank, "map": map_path, "restart": restart, "net": self.mesh})

    def test_owned_values_ghost_geometry_boundary_states_and_signed_links_are_exact(self):
        result = checkpoint_oracle(self.output, self.mesh, self.sources)
        self.assertEqual(result["state"], "passed")
        self.assertTrue(result["zero_tolerance"])
        self.assertEqual(result["flow_links"], 3)
        self.assertEqual(result["boundary_states"], 2)
        self.assertTrue(result["all_sources_unchanged"])

    def test_valid_time_alone_cannot_hide_missing_state_or_wrong_signed_link(self):
        with nc.Dataset(self.output, "r+") as ds:
            ds.variables["unorm"][0, 2] *= -1
        with self.assertRaisesRegex(AssertionError, "state values changed"):
            checkpoint_oracle(self.output, self.mesh, self.sources)

    def test_mask_and_global_identity_corruption_are_rejected(self):
        with nc.Dataset(self.output, "r+") as ds:
            ds.variables["unorm"][0, 1] = 0
        with self.assertRaisesRegex(AssertionError, "mask changed"):
            checkpoint_oracle(self.output, self.mesh, self.sources)
        write_checkpoint(self.output, assembled=True)
        with nc.Dataset(self.output, "r+") as ds:
            ds.variables["FlowElemGlobalNr"][:] = [1, 1]
        with self.assertRaisesRegex(AssertionError, "global face identity"):
            checkpoint_oracle(self.output, self.mesh, self.sources)


@unittest.skipIf(nc is None, "netCDF4 optional run extra is required")
class ParallelOracleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-e012-oracle-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.serial, self.assembled = self.root / "serial.nc", self.root / "assembled.nc"
        self.ranks = [self.root / f"rank-{rank}.nc" for rank in range(2)]
        write_map(self.serial)
        write_map(self.assembled, node_order=(5, 4, 3, 2, 1, 0), face_order=(1, 0), edge_order=(6, 5, 4, 3, 2, 1, 0),
                  reverse_neighbours=(1,), start_index=0)
        for rank, path in enumerate(self.ranks):
            write_map(path, rank=rank, poison_ghosts=True)

    def test_fixed_tolerances_include_face_and_signed_edge_fields_before_any_run(self):
        self.assertEqual(COORDINATE_ATOL, 1e-8)
        self.assertEqual(TOLERANCES["history"][0], {"variable": "waterlevel", "atol": 1e-6, "rtol": 1e-6})
        self.assertIn("mesh2d_q1", [v["variable"] for v in TOLERANCES["map"]])

    def test_assembled_map_matches_reordered_nodes_faces_edges_and_signed_adjacency(self):
        result = compare_maps(self.serial, self.assembled)
        self.assertEqual(result["counts"], {"node": 6, "face": 2, "edge": 7})
        self.assertTrue(all(value["max_abs_difference"] == 0 for value in result["variables"].values()))

    def test_reversed_edge_endpoints_do_not_change_face_based_normal_direction(self):
        write_map(self.assembled, reverse_endpoints=(1,))
        self.assertEqual(compare_maps(self.serial, self.assembled)["state"], "passed")

    def test_ghost_faces_are_validated_by_global_id_but_excluded_from_owned_values(self):
        result = compare_partition_values(self.serial, self.ranks)
        self.assertEqual(result["identity"]["ghost_face_occurrences"], 2)
        self.assertEqual(result["identity"]["owned_faces"], 2)
        self.assertTrue(all(value["max_abs_difference"] == 0 for value in result["variables"].values()))

    def test_duplicate_owning_faces_and_missing_owner_are_rejected(self):
        with nc.Dataset(self.ranks[1], "r+") as ds:
            ds.variables["mesh2d_flowelem_domain"][:] = [1, 1]
        with self.assertRaisesRegex(AssertionError, "multiple owning"):
            partition_oracle(self.serial, self.ranks)
        write_map(self.ranks[1], rank=1)
        with nc.Dataset(self.ranks[0], "r+") as ds:
            ds.variables["mesh2d_flowelem_domain"][:] = [1, 1]
        with self.assertRaisesRegex(AssertionError, "incomplete"):
            partition_oracle(self.serial, self.ranks)

    def test_ghost_global_ids_cannot_alias_other_geometry(self):
        with nc.Dataset(self.ranks[1], "r+") as ds:
            ds.variables["mesh2d_flowelem_globalnr"][:] = [2, 1]
        with self.assertRaisesRegex(AssertionError, "Global ID aliases"):
            partition_oracle(self.serial, self.ranks)

    def test_shared_edge_values_and_masks_must_agree_with_predeclared_tolerances(self):
        with nc.Dataset(self.ranks[1], "r+") as ds:
            ds.variables["mesh2d_q1"][2, 1] += .01
        with self.assertRaisesRegex(AssertionError, "shared edge"):
            compare_partition_values(self.serial, self.ranks)

    def test_wrong_signed_edge_orientation_is_not_hidden_by_coordinate_matching(self):
        with nc.Dataset(self.assembled, "r+") as ds:
            ds.variables["mesh2d_q1"][:, 5] *= -1
        with self.assertRaisesRegex(AssertionError, "tolerance exceeded"):
            compare_maps(self.serial, self.assembled)

    def test_equal_length_wrong_edge_connectivity_is_rejected(self):
        with nc.Dataset(self.assembled, "r+") as ds:
            ds.variables["mesh2d_edge_nodes"][0] = [0, 5]
        with self.assertRaises(AssertionError):
            compare_maps(self.serial, self.assembled)

    def test_masks_units_and_coordinate_units_must_match(self):
        for mutation in ("mask", "units", "coordinates"):
            with self.subTest(mutation=mutation):
                write_map(self.assembled)
                with nc.Dataset(self.assembled, "r+") as ds:
                    if mutation == "mask":
                        ds.variables["mesh2d_s1"][1, 0] = 0
                    elif mutation == "units":
                        ds.variables["mesh2d_s1"].units = "cm"
                    else:
                        ds.variables["mesh2d_node_x"].units = "km"
                with self.assertRaises(AssertionError):
                    compare_maps(self.serial, self.assembled)

    def test_ring_cycle_catches_crossing_faces_with_identical_node_sets(self):
        self.assertNotEqual(ring((0, 1, 4, 3)), ring((0, 4, 1, 3)))
        self.assertEqual(ring((0, 1, 4, 3)), ring((4, 3, 0, 1)))

    def test_history_uses_authoritative_ids_all_times_and_exact_masks(self):
        left, right = self.root / "serial_his.nc", self.root / "rank0_his.nc"
        write_history(left)
        write_history(right, reversed_stations=True)
        self.assertEqual(compare_histories(left, right)["station_ids"], ["west", "east"])
        with nc.Dataset(right, "r+") as ds:
            ds.variables["waterlevel"][1, 1] = 0
        with self.assertRaisesRegex(AssertionError, "masks differ"):
            compare_histories(left, right)

    def test_tolerance_does_not_hide_nonfinite_values_or_unpaired_masks(self):
        with self.assertRaisesRegex(AssertionError, "masks differ"):
            compare_arrays(np.array([np.nan]), np.array([0]), atol=1e6, rtol=1e6)
        with self.assertRaisesRegex(AssertionError, "tolerance exceeded"):
            compare_arrays(np.array([1.]), np.array([1.1]), atol=1e-6, rtol=1e-6)

    def test_partition_input_global_ids_owner_union_and_ghost_geometry_are_checked_before_run(self):
        for path in self.ranks:
            with nc.Dataset(path, "r+") as ds:
                for source, name in (("mesh2d_flowelem_domain", "idomain"), ("mesh2d_flowelem_globalnr", "iglobal_s")):
                    var = ds.createVariable(name, "i4", ("mesh2d_nFaces",))
                    var[:] = ds.variables[source][:]
        result = partition_input_oracle(self.serial, self.ranks)
        self.assertEqual(result["unique_owned_faces"], 2)
        self.assertEqual([(part["owned"], part["ghost"]) for part in result["ranks"]], [(1, 1), (1, 1)])
        with nc.Dataset(self.ranks[1], "r+") as ds:
            ds.variables["iglobal_s"][:] = [2, 1]
        with self.assertRaisesRegex(AssertionError, "ghost ID/owner|aliases"):
            partition_input_oracle(self.serial, self.ranks)

    def test_full_time_axes_must_match_even_when_final_sample_is_equal(self):
        with nc.Dataset(self.assembled, "r+") as ds:
            ds.variables["time"][1] = 59
        with self.assertRaisesRegex(AssertionError, "time axes"):
            compare_maps(self.serial, self.assembled)

    def test_assembled_global_indices_follow_owned_geometry_after_reordering(self):
        with nc.Dataset(self.assembled, "r+") as ds:
            for key, values in (("mesh2d_flowelem_globalnr", [2, 1]), ("mesh2d_flowelem_domain", [1, 0])):
                var = ds.createVariable(key, "i4", ("mesh2d_nFaces",))
                var[:] = values
        result = assembled_identity_and_masks(self.serial, self.ranks, self.assembled)
        self.assertEqual(result["ghost_duplicates_remaining"], 0)
        self.assertEqual(result["global_face_identity"][0]["serial_index"], 1)
        self.assertTrue(all(item["mask_equal"] for item in result["field_masks"]))
        with nc.Dataset(self.assembled, "r+") as ds:
            ds.variables["mesh2d_flowelem_globalnr"][:] = [1, 1]
        with self.assertRaisesRegex(AssertionError, "global face ID/owner"):
            assembled_identity_and_masks(self.serial, self.ranks, self.assembled)

    def test_empty_native_restart_product_is_invalid_even_when_netcdf_opens(self):
        restart = self.root / "empty_merged_rst.nc"
        with nc.Dataset(restart, "w") as ds:
            ds.createDimension("time", None)
            time = ds.createVariable("time", "f8", ("time",))
            time.standard_name, time.units = "time", "seconds since 2001-01-01"
        observed = dataset_inventory(restart)
        self.assertFalse(observed["valid_time_axis"])
        self.assertEqual(observed["dimensions"]["time"], 0)
        self.assertEqual(observed["numeric_variables"][0]["size"], 0)

    def test_stored_face_coordinates_must_follow_face_topology_identity(self):
        with nc.Dataset(self.assembled, "r+") as ds:
            ds.variables["mesh2d_face_x"][:] = [900, 901]
        with self.assertRaisesRegex(AssertionError, "Stored entity coordinate"):
            compare_maps(self.serial, self.assembled)


MDU = """[General]
FileVersion = 1.09
Program = D-Flow FM
PathsRelativeToParent = 0
[geometry]
NetFile = mesh_net.nc
Kmx = 0
[time]
RefDate = 20010101
TZone = 0
TUnit = S
StartDateTime = 20010101000000
StopDateTime = 20010101000200
DtUser = 1
[restart]
RestartFile =
[waves]
WaveModelNr = 0
[trachytopes]
TrtRou = N
[external forcing]
ExtForceFile =
ExtForceFileNew = boundaries.ext
[output]
OutputDir = output
HisFile =
MapFile =
HisInterval = 60
MapInterval = 60
"""


class ParallelPlanningTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-e012-plan-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.model = self.root / "inputs with spaces"
        self.model.mkdir()
        self.mdu = self.model / "model.mdu"
        self.mdu.write_text(MDU)
        (self.model / "mesh_net.nc").write_bytes(b"opaque dry fixture; never an engine input")
        (self.model / "boundaries.ext").write_text("[General]\nfileVersion=2.02\nfileType=extForce\n[Boundary]\nquantity=waterlevelbnd\nlocationFile=sea.pli\nforcingFile=sea.bc\n")
        (self.model / "sea.pli").write_text("sea\n2 2\n0 0\n0 1\n")
        (self.model / "sea.bc").write_text("[Forcing]\nname=sea_0001\nfunction=harmonic\n")
        self.kernels = self.root / "fake suite" / "plugins/DeltaShell.Dimr/kernels/x64"
        tool = self.kernels / "bin/mpiexec.exe"
        tool.parent.mkdir(parents=True)
        tool.write_bytes(b"not executable; dry inspection only")
        from research.workflows.verification.verify_parallel import sha
        self.inspected = {"installation": {"root": str(self.root / "fake suite"), "kernels": str(self.kernels), "proj_data": None},
                          "tools": [{"relative_path": "bin/mpiexec.exe", "path": str(tool), "exists": True, "sha256": sha(tool)}],
                          "localonly_script_claim": True}

    def plan(self, out=None, ranks=2, timeout=45):
        from dfm_cli import parallel_contract
        with patch.object(parallel_contract, "inspect_install", return_value=self.inspected), \
                patch("subprocess.Popen", side_effect=AssertionError("No launch in dry planning")):
            return parallel_contract.plan(self.mdu, out or self.root / "new partition", "fake suite", ranks, timeout)

    def test_dry_plan_localonly_shared_memory_and_rank_count_do_not_claim_native_support(self):
        result = self.plan()
        self.assertEqual(result["rank_list"], [0, 1])
        self.assertEqual(result["native_execution"], "not_performed")
        self.assertIn("--partition:ndomains=2:icgsolver=6", result["partition_argv"])
        self.assertIn("-localonly", result["mpi_argv"])
        self.assertNotIn("-noprompt", result["mpi_argv"])
        self.assertIn("dfm_cli.parallel_worker", result["mpi_argv"])
        self.assertNotIn("-hosts", result["mpi_argv"])
        self.assertFalse((self.root / "new partition").exists())

    def test_dry_hash_binds_output_rank_count_timeout_and_input_bytes(self):
        baseline = self.plan()["input_sha256"]
        changed = [self.plan(ranks=3)["input_sha256"], self.plan(timeout=44)["input_sha256"],
                   self.plan(out=self.root / "different output")["input_sha256"]]
        (self.model / "sea.bc").write_bytes(b"changed opaque forcing")
        changed.append(self.plan()["input_sha256"])
        self.assertTrue(all(value != baseline for value in changed))

    def test_ranks_and_timeout_are_bounded_without_invoking_any_executable(self):
        from dfm_cli.common import DfmError
        for value in (True, 1, 5, 2.0, "2"):
            with self.subTest(ranks=value), self.assertRaises(DfmError):
                self.plan(ranks=value)
        for value in (True, 0, -1, float("nan"), float("inf"), 3601):
            with self.subTest(timeout=value), self.assertRaises(DfmError):
                self.plan(timeout=value)

    def test_general_parent_relative_mode_is_explicitly_refused(self):
        from dfm_cli.common import DfmError
        self.mdu.write_text(MDU.replace("PathsRelativeToParent = 0", "PathsRelativeToParent = 1"))
        with self.assertRaises(DfmError) as error:
            self.plan()
        self.assertEqual(error.exception.code, "mpi_path_profile")

    def test_output_location_and_custom_rank_file_names_are_refused(self):
        from dfm_cli.common import DfmError
        with self.assertRaises(DfmError):
            self.plan(out=self.model / "nested")
        with self.assertRaises(DfmError):
            self.plan(out=self.root)
        self.mdu.write_text(MDU.replace("HisFile =", "HisFile = custom.nc"))
        with self.assertRaises(DfmError) as error:
            self.plan()
        self.assertEqual(error.exception.code, "mpi_output_profile")

    def test_ambient_remote_mpi_environment_is_removed_only_from_child(self):
        from dfm_cli.parallel_contract import environment
        injected = {"I_MPI_HYDRA_BOOTSTRAP": "ssh", "HYDRA_HOST_FILE": "foreign-hosts", "PMI_PORT": "bad", "FI_PROVIDER": "tcp"}
        with patch.dict(os.environ, injected):
            env, overrides, removed = environment(self.inspected["installation"])
            for key, value in injected.items():
                self.assertNotIn(key, env)
                self.assertEqual(os.environ[key], value)
                self.assertIn(key, removed)
        self.assertEqual(overrides["I_MPI_FABRICS"], "shm")
        self.assertEqual(overrides["OMP_NUM_THREADS"], "1")

    def test_dimr_config_exactly_two_ranks_and_same_model(self):
        from dfm_cli.parallel_contract import write_config
        path = self.root / "dimr_config.xml"
        write_config(path, "model.mdu", 2)
        root = ET.parse(path).getroot()
        ns = {"d": "http://schemas.deltares.nl/dimr"}
        self.assertEqual(root.findtext("d:component/d:process", namespaces=ns), "0 1")
        self.assertEqual(root.findtext("d:component/d:mpiCommunicator", namespaces=ns), "DFM_COMM_DFMWORLD")
        self.assertEqual(root.findtext("d:component/d:inputFile", namespaces=ns), "model.mdu")

    def test_apply_without_current_preview_hash_never_launches(self):
        from dfm_cli import parallel
        from dfm_cli.common import DfmError
        with patch.object(parallel, "plan", side_effect=lambda *a, **k: self.plan()), \
                patch.object(parallel, "_native", side_effect=AssertionError("Native must not be reached")) as launch:
            for expected in (None, "0" * 64):
                with self.subTest(hash=expected), self.assertRaises(DfmError):
                    parallel.partition(self.mdu, self.root / "new partition", "fake suite", apply=True, expect_sha256=expected)
            launch.assert_not_called()
        self.assertFalse((self.root / "new partition").exists())


class ParallelConfinementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-e012-guard-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "ranks").mkdir()
        self.owner = {"pid": 101, "creation_time_100ns": "1"}
        self.config = {"contract_version": 1, "folder": str(self.root), "run_id": "a" * 32,
                       "ranks": 2, "owner": self.owner, "job_handle": "123", "startup_timeout_seconds": .1}

    def test_unconfined_rank_dry_refusal_happens_before_claim_or_dimr_launch(self):
        from dfm_cli import parallel_worker
        from dfm_cli.common import DfmError
        path = self.root / "guard.json"
        path.write_text(json.dumps(self.config))
        failure = DfmError("mpi_ownership_unverified", "Rank escaped exact controller Job", 5)
        with patch.object(parallel_worker, "attest", side_effect=failure), \
                patch.object(parallel_worker, "process_identity", return_value={"pid": 202, "creation_time_100ns": "2"}), \
                patch.dict(os.environ, {"PMI_RANK": "0"}), \
                patch.object(parallel_worker.subprocess, "Popen", side_effect=AssertionError("Unconfined DIMR must never start")) as launch:
            self.assertEqual(parallel_worker.worker(path), 24)
            launch.assert_not_called()
        self.assertFalse(list((self.root / "ranks").glob("*.claim")))
        rejected = list((self.root / "ranks").glob("rejected-*.json"))
        self.assertEqual(len(rejected), 1)
        self.assertEqual(json.loads(rejected[0].read_text())["code"], "mpi_ownership_unverified")

    def test_pmi_rank_must_be_exact_ascii_declared_integer(self):
        from dfm_cli.parallel_worker import rank_id
        from dfm_cli.common import DfmError
        for value in ("", "-1", "2", "0 1", "０", "1.0"):
            with self.subTest(rank=value), self.assertRaises(DfmError):
                rank_id({"PMI_RANK": value}, 2)
        self.assertEqual(rank_id({"PMI_RANK": "1"}, 2), 1)

    def test_exact_job_attestation_rejects_escape_or_breakaway_and_closes_borrowed_handles(self):
        from dfm_cli import parallel_worker
        from dfm_cli.common import DfmError
        from dfm_cli.windows_job import ExtendedLimits
        for belongs, flags in ((False, 0x2000), (True, 0), (True, 0x2000 | 0x0800), (True, 0x2000 | 0x1000)):
            with self.subTest(belongs=belongs, flags=flags):
                kernel = Mock()
                kernel.OpenProcess.return_value = 111
                kernel.GetCurrentProcess.return_value = 999
                kernel.WaitForSingleObject.return_value = 258
                def duplicate(*args):
                    ctypes.cast(args[3], ctypes.POINTER(ctypes.c_void_p))[0] = 222
                    return 1
                def limits(*args):
                    ctypes.cast(args[2], ctypes.POINTER(ExtendedLimits)).contents.basic.flags = flags
                    return 1
                def membership(*args):
                    ctypes.cast(args[2], ctypes.POINTER(ctypes.c_long))[0] = int(belongs)
                    return 1
                kernel.DuplicateHandle.side_effect = duplicate
                kernel.QueryInformationJobObject.side_effect = limits
                kernel.IsProcessInJob.side_effect = membership
                with patch.object(parallel_worker, "api", return_value=kernel), \
                        patch.object(parallel_worker, "_handle_identity", return_value=self.owner):
                    with self.assertRaises(DfmError) as error:
                        parallel_worker.attest(self.config)
                self.assertEqual(error.exception.code, "mpi_ownership_unverified")
                self.assertEqual(kernel.CloseHandle.call_count, 2)

    def test_owned_launcher_always_closes_stdin_and_suspends_before_job_assignment(self):
        from dfm_cli import windows_job
        job = windows_job.OwnedJob.__new__(windows_job.OwnedJob)
        job.kernel, job.handle = Mock(), 123
        process = Mock(pid=202)
        process._handle = 444
        job.kernel.AssignProcessToJobObject.side_effect = RuntimeError("dry stop before resume")
        with patch.object(windows_job.subprocess, "Popen", return_value=process) as launch, \
                patch.object(windows_job.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True):
            with self.assertRaisesRegex(RuntimeError, "dry stop"):
                job.launch(["never-executed-mpiexec", "-localonly"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertEqual(launch.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertTrue(launch.call_args.kwargs["close_fds"])
        self.assertTrue(launch.call_args.kwargs["creationflags"] & 4)
        job.kernel.ResumeThread.assert_not_called()

    def test_total_operation_timeout_refuses_before_creating_or_launching_a_job(self):
        from dfm_cli import parallel
        from dfm_cli.common import DfmError
        obj = SimpleNamespace(record={"parallel": {"plan": {"fingerprints": []}}}, _mpi_deadline=time.monotonic() - 1)
        with patch.object(parallel, "OwnedJob", side_effect=AssertionError("Expired operation must not create Job")) as job:
            with self.assertRaises(DfmError) as error:
                parallel._native(obj, ["unexecuted-mpiexec"], self.root, {})
        self.assertEqual(error.exception.code, "run_timeout")
        job.assert_not_called()

    def test_pmi_transport_whitelists_one_existing_handle_without_mutating_ownership_or_endpoints(self):
        from ctypes import wintypes
        from dfm_cli import parallel_worker
        kernel = Mock()
        def information(handle, flags):
            self.assertEqual(handle, 320)
            ctypes.cast(flags, ctypes.POINTER(wintypes.DWORD))[0] = 1
            return 1
        kernel.GetHandleInformation.side_effect = information
        kernel.GetFileType.return_value = 3
        kernel.GetStdHandle.side_effect = [400, 404, 408]
        env = {"PMI_RANK": "0", "PMI_SIZE": "2", "PMI_FD": "320"}
        before = dict(env)
        with patch.object(parallel_worker, "api", return_value=kernel), \
                patch.object(parallel_worker.subprocess, "STARTUPINFO", side_effect=lambda **kwargs: SimpleNamespace(**kwargs), create=True):
            startup, evidence = parallel_worker.pmi_startup(env, 2)
        self.assertEqual(startup.lpAttributeList["handle_list"], [320])
        self.assertTrue(evidence["close_fds"])
        self.assertFalse(evidence["unrelated_handle_inheritance"])
        self.assertFalse(evidence["inheritance_flags_changed"])
        self.assertEqual(env, before)
        for method in ("SetHandleInformation", "ReadFile", "WriteFile", "DuplicateHandle", "CloseHandle"):
            getattr(kernel, method).assert_not_called()

    def test_missing_malformed_or_wrong_size_pmi_transport_is_refused_before_kernel_io(self):
        from dfm_cli import parallel_worker
        from dfm_cli.common import DfmError
        for value in ("", "0", "00320", "-1", "320x", "３２０", str(2 ** 64 - 1)):
            with self.subTest(handle=value), patch.object(parallel_worker, "api") as api:
                with self.assertRaises(DfmError) as error:
                    parallel_worker.pmi_startup({"PMI_RANK": "0", "PMI_FD": value}, 2)
                self.assertEqual(error.exception.code, "mpi_pmi_transport")
                api.assert_not_called()

    def test_noninheritable_file_or_standard_handle_is_not_promoted_into_pmi_transport(self):
        from ctypes import wintypes
        from dfm_cli import parallel_worker
        from dfm_cli.common import DfmError
        for flags, file_type, standard in ((0, 3, 400), (1, 1, 400), (1, 3, 320)):
            with self.subTest(flags=flags, file_type=file_type, standard=standard):
                kernel = Mock()
                def information(handle, pointer):
                    ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))[0] = flags
                    return 1
                kernel.GetHandleInformation.side_effect = information
                kernel.GetFileType.return_value = file_type
                kernel.GetStdHandle.return_value = standard
                with patch.object(parallel_worker, "api", return_value=kernel):
                    with self.assertRaises(DfmError) as error:
                        parallel_worker.pmi_startup({"PMI_RANK": "0", "PMI_FD": "320"}, 2)
                self.assertEqual(error.exception.code, "mpi_pmi_transport")
                kernel.SetHandleInformation.assert_not_called()
                kernel.ReadFile.assert_not_called()
                kernel.WriteFile.assert_not_called()


if __name__ == "__main__":
    unittest.main()
