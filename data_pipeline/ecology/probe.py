"""One-off probe: discover ArcGIS endpoints and field names for the ecology/geology fetch.

Run in GitHub Actions (the cloud sandbox cannot reach these hosts). Prints everything to the log.
"""
import json
import requests

UA = {"User-Agent": "heatbeat-hackathon-data-pipeline/0.1 (research, non-commercial)"}
LAT, LON = 39.0158, -77.4597


def get(url, **params):
    try:
        r = requests.get(url, params=params, headers=UA, timeout=60)
        print(f"\n### {r.status_code} {r.url[:300]}")
        return r
    except Exception as e:  # noqa: BLE001
        print(f"\n### FAIL {url}: {e}")
        return None


def search(q):
    r = get("https://www.arcgis.com/sharing/rest/search", q=q, f="json", num=15)
    if r is not None and r.ok:
        for it in r.json().get("results", []):
            print(" -", it.get("type"), "|", it.get("owner"), "|", it.get("title"), "|", it.get("url"))


for q in ['PAD-US 4 type:"Feature Service"', 'PADUS GAP status type:"Feature Service" owner:USGS_GAP',
          'Protected Areas Database United States type:"Feature Service"',
          'USFWS critical habitat type:"Feature Service"', 'principal aquifers United States type:"Feature Service"',
          'USGS principal aquifers type:"Map Service"', 'karst United States type:"Feature Service"',
          'National Wetlands Inventory type:"Map Service"']:
    search(q)

pt = dict(geometry=f"{LON},{LAT}", geometryType="esriGeometryPoint", inSR=4326, spatialRel="esriSpatialRelIntersects",
          distance=5000, units="esriSRUnit_Meter", returnGeometry="false", outFields="*", f="json", resultRecordCount=5)

for base in ["https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer",
             "https://services.arcgis.com/QVENGdaPbd4LUkLV/arcgis/rest/services/USFWS_Critical_Habitat/FeatureServer"]:
    r = get(base, f="json")
    if r is not None and r.ok:
        print(json.dumps(r.json().get("layers", r.json()), indent=0)[:1500])
    for lyr in (0, 1):
        r = get(f"{base}/{lyr}/query", **pt)
        if r is not None:
            print(r.text[:1500])

r = get("https://macrostrat.org/api/v2/geologic_units/map", lat=LAT, lng=LON, scale="large")
if r is not None:
    print(r.text[:2500])
r = get("https://macrostrat.org/api/v2/geologic_units/map", lat=32.09, lng=34.88)
if r is not None:
    print(r.text[:1500])
q = '[out:json][timeout:60];(nwr(around:5000,32.09,34.88)[boundary=protected_area];nwr(around:5000,32.09,34.88)[leisure=nature_reserve];nwr(around:1000,32.09,34.88)[natural=wetland];);out tags center 20;'
try:
    r = requests.post("https://overpass-api.de/api/interpreter", data={"data": q}, headers=UA, timeout=90)
    print("\n### overpass", r.status_code, r.text[:1500])
except Exception as e:  # noqa: BLE001
    print("overpass fail", e)
