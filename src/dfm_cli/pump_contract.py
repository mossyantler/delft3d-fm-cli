"""Read-only G13 input inventory; native #175 does not qualify hydraulic reverse."""
CONTRACT="pump-inspect-v1"
NATIVE_LIMIT={"gate":"hydraulic_reversal_failed_slot175","scope":"Retained G13 bounded fixture only; not an outcome prediction for selected inputs",
    "observation":"Baseline and reversed-line runs both had +4 m3/s fixed west-to-east flow; relative reporting changed +4 to -4 m3/s",
    "conclusion":"Reversing the line alone did not reverse geographic transfer. Inspection is read-only; pump set is a separate scalar editor.",
    "reference":"research/catalog/pump-orientation-gates.json",
    "reference_sha256":"c022b4cd72d608c9bc284fa49b4e51c7301f3cfb9cb3712bc3f0b911b384f98d",
    "reference_handling":"Portable static reference and pinned SHA; no runtime evidence-file lookup"}
SOURCE={"repository":"Deltares/Delft3D","commit":"5a4649830b1e5072caf019fb4850bbdefd9ad431",
        "manual":"D-Flow FM User Manual 2026.02","sections":["7.4.2.8 PDF106-107","C.12 PDF476-477","C.12.5 PDF480","C.12.11 PDF486"],
        "modern_location":"Readstructures.f90:150-155,260-274 (path flag and locationFile)",
        "first_PLI_block":"polygon_module.f90:284-340","installed_source_revision":"not established"}
LIMITS=["Read-only input description; hydraulic direction, native initialization, numerical/scientific validity and GUI behavior are unqualified",
        "Modern StructureFile 3.01 with locationFile only; legacy polylineFile is unsupported; PLI labels are separate from pump IDs",
        "Scalar capacity; 2–10,000 XY rows; no stages or reduction; orientation and zero stage/reduction counts must be explicit",
        "Raw capacity/polarity are reported verbatim; no sign conversion, row reordering, transformation or snapping",
        "All declared supported graph files are byte-hashed/rechecked; links/aliases/unknown semantics outside supported profile refuse",
        "BOM and comment-only #, ; or * lines are raw inspection trivia; installed native acceptance, including comments between coordinate records, is not established",
        "Inspection never writes, exports or launches a process; see pump_edit for scalar preview/apply"]


def contract():
    return {"contract":CONTRACT,"commands":{"inspect":"pump inspect MDU [--id ID]"},"read_only":True,"write_commands":[],
        "identity":"exact unique structure ID; case/NFC aliases refused; location PLI label is separate",
        "scope":"Modern scalar-capacity pump input description; 2–10,000 XY rows per line; 10,000 total returned rows",
        "paths":{"StructureFile":"MDU parent; documented semicolon list allowed","mode0":"child references from MDU parent","mode1":"child references from StructureFile parent","containment":"all beneath MDU parent; ordinary . segments allowed; parent traversal and empty segments refused; reference spelling retained"},
        "result_fields":["pumps","selected","input_sha256","input_files","references","read_only","hydraulic_effect","hydraulic_use","native_validation","native_gate","gui_parity"],
        "hydraulic_effect":"not_predicted_or_verified","hydraulic_use":"unqualified","native_validation":"not_performed","native_gate":NATIVE_LIMIT["gate"],
        "gui_parity":"not_verified","native_limit":NATIVE_LIMIT,"dependencies":"standard library only","source_basis":SOURCE,"limits":LIMITS}
