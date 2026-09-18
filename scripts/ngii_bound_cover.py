"""018 §2-2 보조 — 26개소 조각의 최근접 도로중심선이 도로경계(면) 폴리곤 안에 들어 있는가."""
import json,os,urllib.parse,urllib.request,time
from pathlib import Path
from pyproj import Transformer
from shapely.geometry import shape, Point
from shapely.ops import transform as TR
import shapely
KEY=os.environ["VWORLD_APIKEY"].strip()
# 2026-09-18: 개발키는 발급 시 등록한 도메인이 같이 가야 한다(없으면 ServiceExceptionReport). 앞뒤 공백도 걷어낸다.
DOMAIN = os.environ.get("VWORLD_DOMAIN", "localhost")
t=Transformer.from_crs(4326,3857,always_xy=True); t2=Transformer.from_crs(3857,5186,always_xy=True)
ROOT=Path(__file__).resolve().parents[1]; DER=ROOT/"data/vworld/national/derived"
def get(tn,x,y,half=150):
    q={"SERVICE":"WFS","REQUEST":"GetFeature","VERSION":"1.1.0","TYPENAME":tn,"OUTPUT":"application/json","MAXFEATURES":"1000","SRSNAME":"EPSG:900913","BBOX":f"{x-half},{y-half},{x+half},{y+half},EPSG:900913","key":KEY}
    for a in range(3):
        try:
            return json.loads(urllib.request.urlopen("https://api.vworld.kr/req/wfs?"+urllib.parse.urlencode(q),timeout=60).read().decode("utf-8","replace"))["features"]
        except Exception as e:
            err=type(e).__name__; time.sleep(1.2*(a+1))
    return None
cc=json.loads((DER/"missing_alley_crosscheck.json").read_text(encoding="utf-8"))
out=[]
for s in cc["sites"]:
    for pc in s["pieces"]:
        if pc["type"]!="road": continue
        lon,lat=pc["point"]; x,y=t.transform(lon,lat); p=Point(*t2.transform(x,y))
        cf=get("lt_l_n3a0020000",x,y); bf=get("lt_c_n3a0010000",x,y)
        if cf is None or bf is None:
            out.append({"piece":pc["piece"],"error":"미조회"}); continue
        lines=[(TR(lambda a,b:t2.transform(a,b),shape(f["geometry"])),f["properties"]) for f in cf]
        lines.sort(key=lambda z:z[0].distance(p))
        g,pr=lines[0]
        polys=shapely.union_all([TR(lambda a,b:t2.transform(a,b),shape(f["geometry"])) for f in bf])
        L=g.length
        pts=[g.interpolate(L*i/20) for i in range(21)]
        inside=sum(1 for q_ in pts if polys.covers(q_))
        out.append({"piece":pc["piece"],"rvwd":pr.get("rvwd"),"rddv":pr.get("rddv"),"len_m":round(L,1),
                    "inside_frac":round(inside/21,2),"line_d_to_point_m":round(g.distance(p),1),
                    "poly_area_covering":round(polys.area,0)})
        print(json.dumps(out[-1],ensure_ascii=False),flush=True)
json.dump(out,open(DER/"ngii_bound_cover.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
n=[r for r in out if "inside_frac" in r]
print("pieces",len(out),"covered>=0.8",sum(1 for r in n if r["inside_frac"]>=0.8),"0",sum(1 for r in n if r["inside_frac"]==0))
