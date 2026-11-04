"""Portable metadata for accepted f152 trials; never verify an inspected run.

Snapshot reviewed against the immutable G#72 receipt and coordinator raw check.
No research checkout, receipt file, installation, or native process is consulted
at runtime. Native input inventory binding prevents carrying this acceptance to
a future changed recipe. Preparation metadata/output files are not native inputs.
"""
from .coupling_common import digest


GATE='RR-G-f152-exchange-01'
RECEIPT='research/experiments/RR-G-f152-exchange-01/verification.json'
RECEIPT_SHA256='55565bc073875fe5043925db6edc7d3bbd499e04749177cf7b31a872a8d40fa8'
RAW_RECEIPT='research/experiments/RR-G-f152-exchange-01/coordinator-raw.json'
RAW_SHA256='7f9594edfa338997458b8f9296b7fe1fed66b184f424fe8f95d3211f68513957'
NATIVE_INPUTS={
    'wet':'919dd30fc20365217eb06bea9d8e599e248eaa18f6c8e60eadc8737a2eb834f7',
    'dry':'5772dd5440d9f32167a964116816e9f297d53cba42bd8b23096ed46c407dd89a',
    'hydraulic':'0206466fbc60a157fe93696df63f0150cb161103c07f94dfe2e4b2b9396e2008',
}


def fixture_evidence(role,native_inputs):
    """Describe accepted trials and whether their exact recipe matches inputs.

    The caller has already byte-verified the fixed recipe. These fingerprints
    identify the60 native input paths/bytes, independently of location, metadata
    receipt IDs or run outputs. A matching recipe is not a new run verification.
    """
    inventory=sorted(({key:entry[key] for key in ('relative_path','sha256','bytes')}
                      for entry in native_inputs),key=lambda entry:entry['relative_path'])
    fingerprint=digest(inventory)
    matched=(len(inventory)==60 and len({e['relative_path'] for e in inventory})==60
             and fingerprint==NATIVE_INPUTS.get(role))
    return dict(
        state='passed_fixture' if matched else 'not_applicable_to_current_recipe',
        gate_id=GATE,verification_applies_to='accepted_fixture_runs_only',
        receipt=dict(path=RECEIPT,sha256=RECEIPT_SHA256),
        coordinator_raw=dict(path=RAW_RECEIPT,sha256=RAW_SHA256),
        native_slots=dict(independent=71,coordinator=72),
        scope='Exact pinned62-blob f152 derivatives: wet/dry/hydraulic, serial FM-RR DIMR, 0..600 seconds; bridge declaration and native rain-header repairs retained',
        recipe_binding=dict(role=role,state='matched' if matched else 'not_matched',
                            native_input_count=len(inventory),native_input_sha256=fingerprint,
                            accepted_native_input_sha256=NATIVE_INPUTS.get(role)),
        observed=dict(
            completed_cases=['wet','dry','hydraulic'],final_seconds=600,
            exchange_ids=34,transactions_per_direction_per_case=68,
            controller_offsets_seconds=[0,300],rr_completed_offsets_seconds=[300,600],
            receiver_checks='FM levels -> actual RR Boundary_Level with explicit float32 encoding; actual RR Flow -> FM prescribed/realized lateral discharge at following solved steps',
            signed_volume_closure='Actual native RR discharge and FM realized interval-average discharge agree within declared signed-volume bounds in all three cases',
            outputs='RR history, FM history/map and final restart clock600s; native RR return code0',
            successful_exit_ownership='Private Job assigned before resume; both native member handles confirmed signalled and exact Job empty for each accepted run'),
        controls=dict(
            rain_Q_max_difference_m3_s=6.379887655377388,
            rain_consumed_FM_volume_difference_m3=21054.36723623425,
            hydraulic_FM_send_level_difference_m=0.0069750415175073854,
            hydraulic_RR_received_level_difference_m=0.0069751739501953125,
            hydraulic_RR_Q_difference_measured_m3_s=0.00010342895984649658,
            interpretation='Separate measured rainfall and hydraulic receiver influence; no requirement that every exchange ID respond, and no assumed runoff feedback'),
        installation=dict(
            suite='2026.02 OpenHMWQ',engine_source_commit='unknown',
            binaries_sha256={
                'bin/dimr.exe':'5880b1e6695f89f6cdb46b00b82f740056b7d8091cb21bd8cdd39d04e7b8ab64',
                'lib/dimr.dll':'4ab97270b982513f97623b54a208a2235b4f8e21224b5ca897add7884a822dc1',
                'lib/dflowfm.dll':'ca6de0b6d900a51ece33140b4666ca97d6875d8e60cac31e91ad072800f1df99',
                'lib/rr_dll.dll':'8a4ca6ba2066d77bcbbc96193c12365807a18575ce4a48bb8f95ff547830b7ec'}),
        current_operation=dict(native_execution='not_performed',native_initialization='not_performed',
                               scientific_validation='not_performed',
                               note='Prepare/inspect checks inputs; it does not execute or verify this individual case or its outputs'),
        c11=dict(native_gate='pending',scope='Separate RR/FM graph; f152 acceptance does not apply'),
        unverified=['calibration','absolute_vertical_datum_equivalence','general_GUI_workflows',
                    'arbitrary_RR_graphs_or_new_native_input_recipes','other_installations_or_durations',
                    'RR_specific_timeout_or_cancellation_controls'],
    )
