"""B04 standalone position/signal collection, not a runnable model rewrite.

Parent hooks: register(boundaries), execute(args).
dfm boundary export MDU --out NEW --group-by {all,boundary,process,quantity}
[--boundary EXACT_PLI_LABEL] [--process-map JSON]
[--apply --expect-sha256 HASH]

The manual defines the four groupings, but the EXT format does not declare GUI
process membership. Process grouping therefore REQUIRES a typed operator map.
Other groupings can omit it and report processes as explicitly undeclared.
An operator declaration defines collection membership, not verified GUI labels::

 {"version":1,"quantities":{
   "waterlevelbnd":{"process":"hydrodynamics","basis":"operator collection declaration"},
   "salinitybnd":{"process":"transport","basis":"operator collection declaration"},
   "temperaturebnd":{"process":"transport","basis":"operator collection declaration"}}}

All active Forcing blocks remain exact byte slices. A newly authored General
header and explicit separators are collection framing, never silently normalized
source blocks. The manifest records source/output spans and every quantity,
support, process declaration, original boundary and unchanged PLI.
"""

CONTRACT = "standalone-boundary-collection-v1"
GROUPS = ("all", "boundary", "process", "quantity")
LIMITS = [
    "New EXT Boundary blocks with one 2D PLI locationFile and BC forcingFile; no legacy EXT or nodeId/QH location conversion",
    "Exact active Forcing bytes, comments, units and relative block order preserved; no interpolation or numeric rewriting",
    "Duplicate support names across independent quantities allowed; duplicate names within a quantity refused",
    "Multi-physical-quantity Forcing blocks refused: splitting them would violate exact block preservation",
    "All grouping uses one BC; boundary/process/quantity grouping uses actual declared membership, not filename guesses",
    "Process grouping requires a complete typed operator map; no map means explicitly undeclared process in other modes",
    "Positions copied byte-for-byte, including labels/order/CRS context; no GIS conversion or PLI replacement",
    "Fresh absent destination only, including refusal of preexisting empty directories; atomic no-replace publication",
    "Private stage identities verified before publication; cleanup touches only captured owned artifacts and preserves unknown/reassigned peer paths",
    "Preview writes nothing; hashes bind request, source paths/bytes and optional process map; final precommit content recheck",
    "Boundary graph inputs bound completely; other MDU/EXT file references hashed where explicit, nested ancillary dependencies not interpreted",
    "Unknown metadata and unreferenced/empty BC blocks explicitly inventoried; unknown sections/functions refused",
    "At most 128 boundaries, 64 BC files, 4096 blocks, 64 MiB retained graph bytes and 128 output signal groups",
    "No EXT rewrite, runnable-model claim, GUI/console parity, native initialization or scientific validation",
]
SOURCE = {
    "manual": "FM User Manual 2026.02 revision 81168 section 7.4.8.3 PDF130-132; four forcing groupings on131",
    "source_commit": "5a4649830b1e5072caf019fb4850bbdefd9ad431",
    "process_mapping": "Manual lists modes but does not define membership; optional typed operator declaration, never inferred from support/file names",
    "quantity_link": "EXT Quantity matched to ordered BC Quantity/Unit declarations; repeated t3D quantities retain vertical indices",
    "runtime": "No GUI/Console/native invocation is established by export",
}
