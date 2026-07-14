#!/usr/bin/env python3
"""결과 GeoPackage 를 클릭 가능한 인터랙티브 지도(HTML)로 렌더링.

- OpenStreetMap 베이스맵 위에 1km 격자 인구밀도를 표시
- 격자 클릭 → 지역(시도)·격자ID·인구·인구밀도 팝업
- 마우스 오버 → 간단 정보 툴팁
"""
import os
import geopandas as gpd
import folium
import branca.colormap as cm

# 행정명(읍면동)이 결합된 gpkg 를 우선 사용
GPKG = os.environ.get("GPKG", "data/processed/seoul_incheon_gyeonggi_1km_pop_admin.gpkg")
OUT = os.environ.get("OUT", "interactive_map.html")

# 지역(시도) 라벨 정리: source(ZIP명) → 한글 시도명 (행정명 미매칭 시 폴백)
REGION_KR = {
    "seoul_1km_202410": "서울특별시",
    "incheon_1km_202410": "인천광역시",
    "gyeonggi_1km_202410": "경기도",
}

def region_label(source: str) -> str:
    parts = [REGION_KR.get(s, s) for s in str(source).split(",")]
    return "·".join(dict.fromkeys(parts))  # 중복 제거, 경계셀은 "서울·경기" 식

g = gpd.read_file(GPKG).to_crs(4326)
g["pop"] = g["val"]
g["density"] = g["pop_density"]

# 행정명 컬럼(시도·시군구·읍면동)이 있으면 사용, 없으면 source 기반 시도명
if {"sido", "sigungu", "eupmyeondong"}.issubset(g.columns):
    g["sido"] = g["sido"].fillna(g["source"].map(region_label))
    g["sigungu"] = g["sigungu"].fillna("")
    g["eupmyeondong"] = g["eupmyeondong"].fillna("(행정동 미상)")
else:
    g["sido"] = g["source"].map(region_label)
    g["sigungu"] = ""
    g["eupmyeondong"] = ""

# 지도 중심 = 데이터 중심
c = g.geometry.union_all().centroid
m = folium.Map(location=[c.y, c.x], zoom_start=10, tiles="CartoDB positron")

# 인구밀도 색상 (분위수 기반 단계 색상, OrRd)
vals = g["density"].dropna()
breaks = [0, 13, 41, 85, 154, 342, 4708, float(vals.max())]
colormap = cm.StepColormap(
    ["#fff5eb", "#fee6ce", "#fdd0a2", "#fdae6b", "#fd8d3c", "#f16913", "#7f2704"],
    index=breaks, vmin=0, vmax=vals.max(),
    caption="인구밀도 (명/㎢)",
)

def style_fn(feat):
    d = feat["properties"]["density"]
    return {
        "fillColor": "#d9d9d9" if d is None else colormap(d),
        "color": "#00000022", "weight": 0.3,
        "fillOpacity": 0.35 if d is None else 0.75,
    }

keep = g[["gid", "sido", "sigungu", "eupmyeondong", "pop", "density", "geometry"]].copy()
keep["pop"] = keep["pop"].round(0)
keep["density"] = keep["density"].round(0)

folium.GeoJson(
    keep,
    name="1km 인구밀도 격자",
    style_function=style_fn,
    highlight_function=lambda f: {"weight": 2, "color": "#1f78b4"},
    tooltip=folium.GeoJsonTooltip(
        fields=["sido", "sigungu", "eupmyeondong", "density"],
        aliases=["시도", "시군구", "읍면동", "인구밀도(명/㎢)"],
        localize=True,
    ),
    popup=folium.GeoJsonPopup(
        fields=["sido", "sigungu", "eupmyeondong", "gid", "pop", "density"],
        aliases=["시도", "시군구", "읍면동", "격자ID", "인구(명)", "인구밀도(명/㎢)"],
        localize=True,
    ),
).add_to(m)

colormap.add_to(m)
folium.LayerControl().add_to(m)
m.save(OUT)
print("저장:", OUT, "| 격자:", len(keep))
