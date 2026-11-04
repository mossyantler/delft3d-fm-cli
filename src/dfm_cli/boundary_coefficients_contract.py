"""B11 file-only contract. Registration/schema integration belongs to parent."""

CONTRACT = 'preserved-waterlevel-coefficients-v1'
LIMITS = [
    'New EXT O-operand 2D waterlevelbnd; select one exact PLI line and all its active supports',
    'Selected signals are linear two-column UTC time/waterlevelbnd series in metres; harmonic/constant/3D/multi-quantity selected signals refused',
    'Set the requested absolute Factor or Offset on every active selected support; preserve the other coefficient independently per support',
    'Factor is dimensionless; Offset requires explicit --unit m; no unit conversion',
    'Only unique Factor/Offset before the FIRST Quantity are supported; late/duplicate/unknown metadata refused',
    'Implicit coefficients are Factor=1 and Offset=0; insert only the requested header immediately before the first Quantity physical line',
    'Existing coefficient changes splice only its numeric token; data rows, times, names, whitespace, comments, BOM, line endings and other supports stay byte-identical',
    'Missing BC support, empty series block and active series are distinct; no-active inspection is valid, no-active edit refused',
    'Finite ASCII decimal tokens <=256 bytes; reject binary64 overflow/underflow of inputs and nonfinite multiply-then-add intermediates/results',
    'At most 64 selected supports, 100000 aggregate BC data rows, 16 MiB parsed BC; evidence keeps first four and last four rows plus a digest of ALL rows',
    'Preview binds exact request, implementation and complete supported connected input paths/bytes; apply requires that request-bound input_sha256',
    'One existing BC atomic publication using the shared guarded publisher; full actual graph bytes and aliases rechecked after staging/fsync, including no-op apply',
    'Publication is not a global filesystem transaction against adversarial writers; failures retain the shared publisher cleanup evidence',
    'No NetCDF decoding, engine execution, GUI export/storage parity, interpolation or scientific validation is performed',
]
SOURCE = {
    'source_commit': '5a4649830b1e5072caf019fb4850bbdefd9ad431',
    'manual': 'D-Flow FM User Manual 2026.02 revision81168 section7.4.8.4 PDF132 printed106; GUI table claim, not exporter byte evidence',
    'global_header': 'src/utils_lgpl/ec_module/packages/ec_module/src/ec_bcreader.f90:516-521; processhdr accepts Factor/Offset only while iq==0',
    'defaults': 'src/utils_lgpl/ec_module/packages/ec_module/src/ec_typedefs.f90:85-86; Offset=0, Factor=1',
    'scalar_arithmetic': 'ec_bcreader.f90:844,856-858; selected physical scalar raw*factor+offset; time conversion is separate',
    'excluded_semantics': 'ec_bccollect.f90:422-429 is not the traced FM POLY_TIM reader; harmonic branch ec_bcreader.f90:869-875 is separate',
    'source_evidence': 'B11-COEFF-I-20261105-024319-28b59c47/source-evidence.json; B11-COEFF-G-input-review-01/verification.json',
    'installed_engine_source_commit': 'unknown; never inferred from the suite version',
    'native_evidence': 'not established by this operation',
}


def contract():
    return {'contract': CONTRACT, 'command': 'boundary coefficients',
            'quantity': 'waterlevelbnd', 'factor_unit': '1', 'offset_unit': 'm',
            'coefficient_operation': 'absolute_assignment_not_composition',
            'inspection': 'omit both factor and offset; apply/expected-hash/unit then refused',
            'apply': '--apply --expect-sha256 INPUT_SHA256 from the same exact edit preview',
            'insertion': 'Factor = <literal> or Offset = <literal>, no indentation, immediately before first Quantity physical line, with that line ending',
            'sample_evidence_limit_per_point': 8, 'sample_evidence_order': 'first4_then_last4_without_duplicates',
            'error_prefix': 'boundary_coefficients_; reused graph/numeric/publication errors preserve their existing codes',
            'source_basis': dict(SOURCE), 'limitations': list(LIMITS)}
