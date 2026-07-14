#!/usr/bin/env python3
"""결과 GeoPackage 를 인구밀도 코로플레스 지도(PNG)로 렌더링."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import geopandas as gpd
import numpy as np

import os
GPKG = os.environ.get("GPKG", "data/processed/seoul_incheon_gyeonggi_1km_pop.gpkg")
OUT = os.environ.get("OUT", "density_map.png")

# 한글 폰트(있으면) 적용
for cand in ["NanumGothic", "Noto Sans CJK KR", "Malgun Gothic", "UnDotum"]:
    try:
        font_manager.findfont(cand, fallback_to_default=False)
        plt.rcParams["font.family"] = cand
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

g = gpd.read_file(GPKG)
print("격자:", len(g), "| 밀도 유효:", int(g.pop_density.notna().sum()))

fig, ax = plt.subplots(figsize=(11, 11), dpi=130)

# 결측(통계없음) 격자: 연회색
g[g.pop_density.isna()].plot(ax=ax, color="#f2f2f2", edgecolor="none")

# 유효 격자: 국토통계지도와 유사한 OrRd 색상, 분위수(Quantiles) 분류
valid = g[g.pop_density.notna()]
valid.plot(
    ax=ax,
    column="pop_density",
    cmap="OrRd",
    scheme="quantiles",
    k=7,
    legend=True,
    linewidth=0,
    legend_kwds={
        "title": "인구밀도 (명/㎢)",
        "loc": "lower left",
        "fontsize": 8,
        "title_fontsize": 9,
        "fmt": "{:,.0f}",
    },
)

ax.set_title(
    "수도권(서울·인천·경기) 1km 격자 인구밀도\n"
    f"국토통계지도 2024.10 · EPSG:5179 · {len(g):,}개 격자",
    fontsize=13, pad=12,
)
ax.set_axis_off()
ax.set_aspect("equal")
fig.tight_layout()
fig.savefig(OUT, bbox_inches="tight", facecolor="white")
print("저장:", OUT)
