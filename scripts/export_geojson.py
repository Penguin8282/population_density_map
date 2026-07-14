#!/usr/bin/env python3
"""행정명 결합 GeoPackage → 프론트엔드용 정적 GeoJSON(web/data/grid.geojson).

프론트엔드(Leaflet)가 fetch 로 읽는 유일한 데이터 파일. 좌표는 EPSG:4326,
소수 5자리(≈1m)로 반올림하여 용량을 줄인다. 이 파일은 생성 후 수정하지 않는다.
"""
import os
import geopandas as gpd

GPKG = os.environ.get("GPKG", "data/processed/seoul_incheon_gyeonggi_1km_pop_admin.gpkg")
OUT = os.environ.get("OUT", "web/data/grid.geojson")

REGION_KR = {
    "seoul_1km_202410": "서울특별시",
    "incheon_1km_202410": "인천광역시",
    "gyeonggi_1km_202410": "경기도",
}

def region_label(source: str) -> str:
    parts = [REGION_KR.get(s, s) for s in str(source).split(",")]
    return "·".join(dict.fromkeys(parts))

g = gpd.read_file(GPKG).to_crs(4326)
g["pop"] = g["val"].round(0)
g["density"] = g["pop_density"].round(0)

if {"sido", "sigungu", "eupmyeondong"}.issubset(g.columns):
    g["sido"] = g["sido"].fillna(g["source"].map(region_label))
    g["sigungu"] = g["sigungu"].fillna("")
    g["eupmyeondong"] = g["eupmyeondong"].fillna("(행정동 미상)")
else:
    g["sido"] = g["source"].map(region_label)
    g["sigungu"] = ""
    g["eupmyeondong"] = ""

keep = g[["gid", "sido", "sigungu", "eupmyeondong", "pop", "density", "geometry"]].copy()

os.makedirs(os.path.dirname(OUT), exist_ok=True)
# OGR GeoJSON 드라이버: 좌표 정밀도 5자리로 축소 → 용량 절감
keep.to_file(OUT, driver="GeoJSON", COORDINATE_PRECISION=5)

size_mb = os.path.getsize(OUT) / 1e6
print(f"저장: {OUT} | 격자 {len(keep):,}개 | {size_mb:.1f} MB")
print(f"밀도 범위: {keep['density'].min()} ~ {keep['density'].max()} | 결측 {int(keep['density'].isna().sum())}")
