"""B04 independent WGS84/UTM controls. No pyproj or product imports.

Snyder PP1395 printed61/63 (PDF70/72) equations8-9,8-10,8-17,8-18,
3-21,3-24,3-26. Truncated series are used only within2deg of the central
meridian and |latitude|<=60deg; prospective tolerances below are fixed.
These mathematical controls establish neither GUI parity nor geodetic datum
realization/epoch or vertical transformation.
"""
import math

PROVENANCE = {
    "projection": {
        "author": "John P. Snyder", "title": "Map Projections - A Working Manual",
        "year": 1987, "series": "USGS Professional Paper1395", "doi": "10.3133/pp1395",
        "publisher_url": "https://pubs.usgs.gov/pp/1395/report.pdf",
        "retrieval_url": "https://csde.washington.edu/wp-content/uploads/2017/04/MapProjections_AWorkingManual_USGS_1987.pdf",
        "pdf_sha256": "489b4b40aea725355c07a41f44246744815102e2c998de5bf7515081d140081e",
        "inspected_pages": [{"printed": 60, "pdf_one_based": 69}, {"printed": 61, "pdf_one_based": 70}, {"printed": 63, "pdf_one_based": 72}],
        "equations": ["8-9", "8-10", "8-12", "4-20", "8-13", "8-14", "8-15", "3-21", "8-17", "8-18", "3-24", "3-26"],
    },
    "ellipsoid": {
        "authority": "NGA WGS84 Defining Parameters",
        "url": "https://earth-info.nga.mil/index.php?action=wgs84&dir=wgs84",
        "a_m": 6378137.0, "inverse_flattening": 298.257223563,
    },
    "utm": {"zone31_central_meridian_degree": 3.0, "scale": 0.9996,
            "false_easting_m": 500000.0, "north_false_northing_m": 0.0, "south_false_northing_m": 10000000.0,
            "url": "https://proj.org/en/stable/operations/projections/utm.html"},
    "expected_values": "authored standard-library equations; never pyproj outputs or product helpers",
}
FORWARD_TOLERANCE_M = 0.005
INVERSE_TOLERANCE_DEG = 1e-7
ORIGIN_TOLERANCE_M = 1e-7
A = 6378137.0
F = 1 / 298.257223563
E2 = F * (2 - F)
EP2 = E2 / (1 - E2)
K0 = 0.9996
CONTROLS = (
    {"name": "central_equator_north", "lon": 3.0, "lat": 0.0, "zone": 31, "south": False},
    {"name": "central_equator_south", "lon": 3.0, "lat": 0.0, "zone": 31, "south": True},
    {"name": "central_60n", "lon": 3.0, "lat": 60.0, "zone": 31, "south": False},
    {"name": "east_50n", "lon": 4.0, "lat": 50.0, "zone": 31, "south": False},
    {"name": "west_30s", "lon": 2.0, "lat": -30.0, "zone": 31, "south": True},
    {"name": "east_20n", "lon": 5.0, "lat": 20.0, "zone": 31, "south": False},
    {"name": "west_20n", "lon": 1.0, "lat": 20.0, "zone": 31, "south": False},
    {"name": "korea_zone52_offset", "lon": 128.0, "lat": 36.0, "zone": 52, "south": False},
)


def meridian(phi):
    """Snyder3-21 through e^6, phi in radians, result metres."""
    return A * ((1 - E2/4 - 3*E2**2/64 - 5*E2**3/256)*phi
                - (3*E2/8 + 3*E2**2/32 + 45*E2**3/1024)*math.sin(2*phi)
                + (15*E2**2/256 + 45*E2**3/1024)*math.sin(4*phi)
                - 35*E2**3/3072*math.sin(6*phi))


def forward(lon, lat, *, zone=31, south=False):
    """Lon/lat degrees -> easting/northing metres from printed equations."""
    central = 6*zone - 183
    if not (abs(lon-central) <= 2 and abs(lat) <= 60):
        raise ValueError("Independent truncated oracle outside its declared domain")
    phi, dl = math.radians(lat), math.radians(lon-central)
    n = A / math.sqrt(1-E2*math.sin(phi)**2)
    t, c, q = math.tan(phi)**2, EP2*math.cos(phi)**2, dl*math.cos(phi)
    east = 500000 + K0*n*(q + (1-t+c)*q**3/6 + (5-18*t+t*t+72*c-58*EP2)*q**5/120)
    north = K0*(meridian(phi)+n*math.tan(phi)*(q*q/2+(5-t+9*c+4*c*c)*q**4/24+(61-58*t+t*t+600*c-330*EP2)*q**6/720))
    return [east, north + (10000000 if south else 0)]


def inverse(east, north, *, zone=31, south=False):
    """Snyder8-17/18 independent inverse, not a product roundtrip."""
    y = north - (10000000 if south else 0)
    mu = (y/K0) / (A*(1-E2/4-3*E2**2/64-5*E2**3/256))
    e1 = (1-math.sqrt(1-E2))/(1+math.sqrt(1-E2))
    phi = (mu+(3*e1/2-27*e1**3/32)*math.sin(2*mu)
           +(21*e1**2/16-55*e1**4/32)*math.sin(4*mu)
           +151*e1**3/96*math.sin(6*mu)+1097*e1**4/512*math.sin(8*mu))
    n = A/math.sqrt(1-E2*math.sin(phi)**2)
    r = A*(1-E2)/(1-E2*math.sin(phi)**2)**1.5
    t, c, d = math.tan(phi)**2, EP2*math.cos(phi)**2, (east-500000)/(n*K0)
    lat = phi-n*math.tan(phi)/r*(d*d/2-(5+3*t+10*c-4*c*c-9*EP2)*d**4/24+(61+90*t+298*c+45*t*t-252*EP2-3*c*c)*d**6/720)
    lon = math.radians(6*zone-183)+(d-(1+2*t+c)*d**3/6+(5-2*c+28*t-3*c*c+8*EP2+24*t*t)*d**5/120)/math.cos(phi)
    return [math.degrees(lon), math.degrees(lat)]


def meridian_integral(lat, steps=1024):
    """Independent numerical integration of ellipsoid meridian curvature.

    A check on series transcription/truncation at the central meridian, not
    a second invocation of PROJ. Composite Simpson rule, deterministic steps.
    """
    h = math.radians(lat)/steps
    def radius(phi):
        return A*(1-E2)/(1-E2*math.sin(phi)**2)**1.5
    return h/3*math.fsum([radius(0), radius(h*steps)] +
        [(4 if i % 2 else 2)*radius(i*h) for i in range(1, steps)])


def declared_controls():
    return [dict(row, target_crs=f"EPSG:{(32700 if row['south'] else 32600)+row['zone']}",
                 xy_m=forward(row["lon"], row["lat"], zone=row["zone"], south=row["south"])) for row in CONTROLS]
