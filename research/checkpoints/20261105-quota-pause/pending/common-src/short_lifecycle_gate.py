"""Canonical-manifest S07 process gate; read-only, no sidecar fallback or FFI."""
from dfm_cli.run_pump_lifecycle import natural_exit,_close_assessment

def assess(record):
    issues=[]
    if not (record.get('schema_version')==3 and record.get('state')=='completed' and
            record.get('profile_name')=='short' and record.get('route')=='direct' and
            type(record.get('returncode')) is int and record['returncode']==0):
        issues.append('actual_completed_short_direct_integer_zero_required')
    normal=natural_exit(record)
    if not normal['passed']:issues.append('original_retained_member_root_job_exit_unconfirmed')
    ownership=record.get('ownership',{})
    close=_close_assessment(ownership.get('job_close'),normal['job_instance_token'])
    if not close['passed']:issues.append('original_job_collector_close_unconfirmed')
    lifecycle=ownership.get('short_lifecycle',{})
    if not (lifecycle.get('schema_version')==2 and lifecycle.get('state')=='passed'
            and lifecycle.get('issues')==[] and lifecycle.get('exit_evidence')==normal
            and lifecycle.get('close_assessment')==close and 'close_error' not in lifecycle):
        issues.append('canonical_short_lifecycle_not_passed')
    try:
        if any(type(m['exit']['exit_code']) is not int or m['exit']['exit_code']!=0
                for m in ownership['normal_exit']['member_trace']['members']):
            issues.append('member_exit_nonzero_or_unknown')
        if any(e['raw_message']==8 for e in ownership['normal_exit']['member_trace']['collection']['events']):
            issues.append('abnormal_exit_notification_precludes_computation_success')
    except (KeyError,TypeError):issues.append('member_exit_details_missing')
    stop=record.get('termination')
    natural_race=(type(stop) is dict and stop.get('forced') is False and stop.get('tree_terminated') is True
                  and type(stop.get('termination_request')) is dict
                  and stop['termination_request'].get('attempted') is False and normal['passed'])
    if ('termination' in record and not natural_race) or (record.get('cancellation') and not natural_race) or record.get('stop_reason'):
        issues.append('stopped_or_forced_not_successful_natural_case')
    return {'passed':not issues,'issues':issues,'natural_exit':normal,'close':close,
            'raw_path':'ownership.job_close','assessment_path':'ownership.short_lifecycle',
            'sidecar_fallback':False,'kernel_queries':0,'scope':'Actual original-owner manifest receipt assessment only; no scientific validation'}
