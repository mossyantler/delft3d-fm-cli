"""O02 scalar restart-interval authoring contract; never runs/verifies an engine.

Pinned Delft3D5a4649830b1e5072caf019fb4850bbdefd9ad431:
unstruc_model.f90:2210-2213,4164-4233 reads seconds, optional window and DtUser
alignment (native clamps a positive interval below DtUser; this editor refuses).
flow_externaloutput.F90:255-272 writes only for positive intervals and clamps the
last positive-schedule checkpoint to the output-window end. m_flowtimes.f90:318
starts time_rst at tstart_user. No unconditional final checkpoint is promised.
wrirst.f90:61/unstruc_files.f90:342-344/time_module.f90:1099-1122 encode filenames
to whole seconds, so this bounded editor authors whole-second cadence only.

Existing history/map/stop editing and the shared output verifier are untouched.
Existing or requested windows must not be flattened by this scalar editor.
"""
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import math
import re
import sys

from .common import DfmError

ADDRESS='output/rstinterval'
SOURCE='5a4649830b1e5072caf019fb4850bbdefd9ad431'
TOKEN=r'[+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?'
SETTING={
    'unit':'seconds','type':'nonnegative whole-second scalar decimal',
    'scope':'Existing single-value RstInterval only; existing/requested windows are refused',
    'zero':'Disables scheduled checkpoints, including initial/final; default require-final run policy is unchanged',
    'positive':'Initial checkpoint, regular cadence and output-period end; interval need not divide duration',
    'requirements':'Explicit unique absolute StartDateTime/StopDateTime, RefDate, TUnit and TZone; positive cadence requires positive DtUser and exact alignment',
    'numeric_encoding':'One ASCII decimal token, optional + and E/e; <=256 characters; finite normal binary64 or exact zero; nonzero subnormals/overflow/underflow refused',
    'precision_scope':'Whole-second cadence avoids ambiguous subsecond restart filenames; no native clamp or implicit timestep default',
    'native_alignment_limit':'Positive interval/DtUser and duration/DtUser must be integers <=2147483647 (pinned default-integer NINT)',
    'source_revision':SOURCE,
}


def scalar(token,address,*,signed=False):
    pattern=TOKEN if not signed else r'[+-]?'+TOKEN.removeprefix('[+]?')
    if not isinstance(token,str) or len(token)>256 or not re.fullmatch(pattern,token):
        raise DfmError('invalid_scalar','Expected one bounded ASCII decimal token',details={'setting':address,'value':token})
    try:
        number=Decimal(token);native=float(number)
        if not number.is_finite() or not math.isfinite(native):raise ValueError('overflow or nonfinite')
        if number!=0 and (native==0 or abs(native)<sys.float_info.min):
            raise ValueError('nonzero underflow or subnormal binary64')
    except (InvalidOperation,OverflowError,ValueError) as exc:
        raise DfmError('invalid_scalar','Value must be finite normal binary64 or exact zero',details={'setting':address,'value':token}) from exc
    return number


def restart_edit(mdu,old,value):
    """Validate one token replacement and report intended, unexecuted semantics."""
    for label,token in (('existing',old),('requested',value)):
        if (isinstance(token,str) and len(token.split())>1
                and all(re.fullmatch(TOKEN,part) for part in token.split())):
            raise DfmError('unsupported_output_schedule','Scalar restart edit refuses existing/requested windows or multiple values',
                           details={'setting':ADDRESS,'which':label,'value':token})
    scalar(old,ADDRESS);number=scalar(value,ADDRESS)
    from .model import clock,date
    schedule_clock=clock(mdu)  # Enforces both explicit absolute dates and unique keys.
    ref=mdu.get('time/refdate')
    if not re.fullmatch(r'[0-9]{8}',ref):
        raise DfmError('invalid_date','Restart edit requires explicit YYYYMMDD RefDate',details=ref)
    date(ref+'000000')
    if mdu.get('time/tunit') not in ('S','M','H','D'):
        raise DfmError('unsupported_output_schedule','Restart edit requires explicit TUnit S, M, H or D')
    scalar(mdu.get('time/tzone'),'time/tzone',signed=True)
    if number>0:
        interval=Fraction(number)
        if interval.denominator!=1:
            raise DfmError('unsupported_output_schedule','Restart interval editing is limited to whole seconds because native restart filenames encode seconds',details=value)
        dt=scalar(mdu.get('time/dtuser'),'time/dtuser')
        if dt<=0:raise DfmError('invalid_interval','Positive restart cadence requires explicit positive DtUser')
        timestep=Fraction(dt);duration=Fraction(str(schedule_clock['duration_seconds']))
        step_ticks=interval/timestep;duration_ticks=duration/timestep
        if interval<timestep or step_ticks.denominator!=1 or duration_ticks.denominator!=1:
            raise DfmError('unsupported_output_schedule','Positive restart interval must be >=DtUser and interval/output-period end must align exactly to DtUser',
                           details={'setting':ADDRESS,'interval_seconds':value,'dtuser_seconds':str(dt),'duration_seconds':str(duration)})
        # Pinned is_not_multiple uses default-integer NINT(time/DtUser).
        if step_ticks>2147483647 or duration_ticks>2147483647:
            raise DfmError('unsupported_output_schedule','Restart schedule exceeds the pinned native 32-bit NINT alignment range')
    return {'setting':ADDRESS,'unit':'seconds','mode':'disabled' if number==0 else 'periodic',
        'interval_seconds':str(number),'clock':schedule_clock,
        'window':'whole explicit simulation period; no window edited',
        'expected_checkpoints':'none' if number==0 else 'initial, regular cadence, and final period end even if off cadence',
        'default_run_policy':'requires final checkpoint; disabling checkpoints requires an explicitly supported alternative policy',
        'native_execution':'not_performed','source_revision':SOURCE}
