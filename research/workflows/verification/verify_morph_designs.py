"""Predeclare new physical candidates; no native run or acceptance retuning."""
import argparse
import copy
import json
import math
from pathlib import Path

from .verify_morph import DECLARATION, pin_sources, release_specification, sha, write_json
from .verify_morph_diagnose import held_out_specification


def design(base,period,amplitude,hump):
    s=copy.deepcopy(base);s['grid']['hump_height_m']=hump;s['clock']['stop']='2001-01-01T00:%02d:00Z' % (3*period//60)
    duration=3*period;s['output']['restart_seconds']=duration
    # Three full antisymmetric cycles, exact quarter-period rows. Start and stop
    # remain at the common initial level; no net imposed mean surface offset.
    for boundary in s['boundaries']:
        sign=1 if boundary['side']=='west' else -1
        boundary['water_level_m']=[[i*period/4,s['initial_water_level_m']+sign*amplitude*(0,1,0,-1)[i%4]] for i in range(13)]
    g=s['grid'];h=s['initial_water_level_m']-g['bed_base_m'];hmin=h-hump;length=g['length_m'];gravity=9.81
    rho=s['grain']['particle_density']['value'];d=s['grain']['d50']['value'];n=s['roughness']['value']
    velocity=gravity*(2*amplitude)/(length*(2*math.pi/period))
    critical=h**(1/6)*math.sqrt(.047*(rho/1000-1)*d)/n
    theta=n*n*velocity*velocity/(h**(1/3)*(rho/1000-1)*d)
    mass_flux_scale=8*math.sqrt((rho/1000-1)*gravity*d**3)*max(theta-.047,0)**1.5*rho
    return s,{'forcing_period_seconds':period,'cycles':3,'forcing_rows':13,'surface_amplitude_each_m':amplitude,
              'minimum_initial_depth_m':hmin,'barotropic_crossing_seconds':length/math.sqrt(gravity*hmin),
              'barotropic_roundtrip_seconds':2*length/math.sqrt(gravity*hmin),
              'uniform_acceleration_velocity_scale_m_s':velocity,'MPM_critical_Shields':.047,
              'Manning_based_critical_velocity_scale_m_s':critical,'MPM_mass_flux_scale_kg_s_m':mass_flux_scale,
              'interpretation':'Scale estimates using linear shallow-water acceleration, Manning shear and MPM capacity; NOT an analytic coupled solution, prediction of erosion/deposition, or fitted acceptance target',
              'physical_design':'Reversing flow over a stronger smooth hump creates opposing transport gradients on stoss/lee slopes. Three cycles permit redistribution; open boundaries may still export material.',
              'budget_gate':'Local dry-mass/elevation conversion is necessary. Require native oriented interval-integrated boundary transport and widths for total material balance; never treat BCM=0 as closed.',
              'native_launch_ready_for_full_budget':False,'thresholds':DECLARATION}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True,type=Path);a=p.parse_args(argv)
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    report={'status':'new_candidates_predeclared_native_pending','native_started':False,'references':pin_sources(),'designs':{},'verifier_sha256':sha(Path(__file__))}
    for name,base,period,amplitude,hump in [('active',release_specification(),100,.2,.75),('held-out',held_out_specification(),120,.24,1.)]:
        spec,reason=design(base,period,amplitude,hump);write_json(out/(name+'.spec.json'),spec)
        report['designs'][name]={'spec_path':str(out/(name+'.spec.json')),'sha256':sha(out/(name+'.spec.json')),'reason':reason}
    report['prior_failure_not_relabelled']='Original 60-second trials stay failed; new shape/duration/forcing are different experiments, not a repaired prior receipt'
    write_json(out/'verification.json',report);print(json.dumps({'status':report['status'],'native_started':False,'verification':str(out/'verification.json')},indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
