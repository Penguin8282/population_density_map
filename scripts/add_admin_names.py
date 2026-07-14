#!/usr/bin/env python3
"""각 1km 격자에 행정명(시도·시군구·읍면동)을 공간결합으로 부여한다.

행정동 경계(vuski/admdongkor, EPSG:4326)를 받아 서울·인천·경기만 추린 뒤,
격자의 대표점(representative_point)이 속한 행정동을 찾아 이름을 붙인다.

입력:  data/processed/seoul_incheon_gyeonggi_1km_pop.gpkg
출력:  data/processed/seoul_incheon_gyeonggi_1km_pop_admin.gpkg
"""
import os
import subprocess
from pathlib import Path
import geopandas as gpd

GPKG_IN = os.environ.get("GPKG_IN", "data/processed/seoul_incheon_gyeonggi_1km_pop.gpkg")
GPKG_OUT = os.environ.get("GPKG_OUT", "data/processed/seoul_incheon_gyeonggi_1km_pop_admin.gpkg")
BOUNDARY = os.environ.get("BOUNDARY", "data/raw/hangjeongdong.geojson")
BOUNDARY_URL = os.environ.get(
    "BOUNDARY_URL",
    "https://raw.githubusercontent.com/vuski/admdongkor/master/"
    "ver20260701/HangJeongDong_ver20260701.geojson",
)
# 수도권 시도코드: 서울=11, 인천=28, 경기=41
CAPITAL_SIDO = {"11", "28", "41"}


def ensure_boundary() -> Path:
    p = Path(BOUNDARY)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        print(f"행정동 경계 다운로드: {BOUNDARY_URL}")
        subprocess.run(["curl", "-sSL", "--max-time", "180", "-o", str(p), BOUNDARY_URL], check=True)
    return p


def eupmyeondong(adm_nm: str, sidonm: str, sggnm: str) -> str:
    """전체 행정명에서 읍면동만 추출. 예: '서울특별시 종로구 사직동' → '사직동'."""
    tail = adm_nm
    for prefix in (sidonm, sggnm):
        if isinstance(prefix, str) and prefix and tail.startswith(prefix):
            tail = tail[len(prefix):]
        else:
            # 접두어가 정확히 안 맞으면 마지막 토큰 사용
            tail = adm_nm.split()[-1]
            break
    return tail.strip() or adm_nm


def main() -> int:
    ensure_boundary()

    print("경계 로드 중...")
    bnd = gpd.read_file(BOUNDARY)
    bnd = bnd[bnd["sido"].astype(str).isin(CAPITAL_SIDO)].copy()
    print(f"  수도권 행정동: {len(bnd):,}개")

    grid = gpd.read_file(GPKG_IN)
    print(f"  격자: {len(grid):,}개 (CRS={grid.crs})")

    # 정확도를 위해 격자 native CRS(5179)로 경계를 맞추고, 대표점으로 결합
    bnd = bnd.to_crs(grid.crs)
    pts = grid[["gid", "geometry"]].copy()
    pts["geometry"] = grid.geometry.representative_point()

    joined = gpd.sjoin(
        pts, bnd[["adm_nm", "sidonm", "sggnm", "adm_cd2", "geometry"]],
        how="left", predicate="within",
    )
    # 중복(경계 겹침) 방지: gid 당 첫 매칭
    joined = joined.drop_duplicates(subset="gid", keep="first")

    joined["emd"] = joined.apply(
        lambda r: eupmyeondong(r["adm_nm"], r["sidonm"], r["sggnm"])
        if isinstance(r["adm_nm"], str) else None,
        axis=1,
    )

    admcols = joined.set_index("gid")[["sidonm", "sggnm", "emd", "adm_nm", "adm_cd2"]]
    out = grid.merge(admcols, left_on="gid", right_index=True, how="left")
    out = out.rename(columns={
        "sidonm": "sido", "sggnm": "sigungu",
        "emd": "eupmyeondong", "adm_nm": "adm_full", "adm_cd2": "adm_code",
    })

    matched = int(out["adm_full"].notna().sum())
    print(f"  행정명 매칭: {matched:,}/{len(out):,} "
          f"({100*matched/len(out):.1f}%) · 미매칭(해상/경계 밖) {len(out)-matched:,}")

    Path(GPKG_OUT).parent.mkdir(parents=True, exist_ok=True)
    out.to_file(GPKG_OUT, layer="population_1km", driver="GPKG")
    print(f"저장: {GPKG_OUT}")
    print("샘플:")
    print(out[["gid", "sido", "sigungu", "eupmyeondong", "val", "pop_density"]]
          .dropna(subset=["eupmyeondong"]).head(6).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
