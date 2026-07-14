#!/usr/bin/env python3
"""
build_population_gpkg.py — [2단계] 병합·중복제거·인구밀도·GeoPackage 저장
=========================================================================

서울·인천·경기 국토통계지도 1km 격자 인구 셰이프파일을 하나로 병합하고,
격자ID 기준으로 중복을 제거한 뒤, 인구밀도 컬럼을 추가하여
``data/processed/`` 아래 GeoPackage(.gpkg) 로 저장한다.

파이프라인
----------
1. 각 지역 ZIP 해제 (한글 파일명 cp949 복원)
2. 셰이프파일 로드 (.cpg/.cst 로 인코딩 자동판별, 없으면 cp949)
3. 공통 좌표계로 재투영(reproject) 후 병합(concat)
4. 격자ID 기준 중복 제거 (경계 중첩 격자 정리)
5. 격자 실면적(area_km2) 및 인구밀도(pop_density = 인구/㎢) 계산
6. GeoPackage 로 저장

사용 예::

    python src/build_population_gpkg.py \
        --zip data/raw/서울.zip data/raw/인천.zip data/raw/경기.zip \
        --out data/processed/seoul_incheon_gyeonggi_1km_pop.gpkg

단일 통합 ZIP(안에 3개 셰이프파일) 이라면::

    python src/build_population_gpkg.py --zip data/raw/수도권_1km.zip
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gridlib  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="수도권 1km 격자 인구 병합 → GeoPackage 생성"
    )
    p.add_argument(
        "--zip",
        nargs="+",
        required=True,
        type=Path,
        help="입력 ZIP 경로(들). 통합 ZIP 1개 또는 지역별 ZIP 여러 개 모두 가능",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("data/processed/seoul_incheon_gyeonggi_1km_pop.gpkg"),
        help="출력 GeoPackage 경로",
    )
    p.add_argument(
        "--layer-name",
        default="population_1km",
        help="GeoPackage 내 레이어 이름 (기본: population_1km)",
    )
    p.add_argument(
        "--extract-dir",
        type=Path,
        default=Path("data/raw/extracted"),
        help="ZIP 해제 위치",
    )
    p.add_argument("--encoding", default="auto",
                   help="DBF 인코딩. auto=.cpg/.cst 자동판별 후 cp949 폴백 (기본: auto)")
    p.add_argument("--grid-col", default=None, help="격자ID 컬럼 강제 지정")
    p.add_argument("--pop-col", default=None, help="인구 컬럼 강제 지정")
    p.add_argument(
        "--target-crs",
        default=None,
        help="병합·저장에 사용할 목표 CRS. 미지정 시 첫 레이어의 CRS 사용",
    )
    p.add_argument(
        "--fallback-crs",
        default=gridlib.DEFAULT_KOREA_CRS,
        help=f"CRS 가 비어 있을 때 사용할 좌표계 (기본: {gridlib.DEFAULT_KOREA_CRS})",
    )
    p.add_argument(
        "--dedup",
        choices=["sum", "first", "last"],
        default="sum",
        help=(
            "격자ID 중복 처리 방식 (기본: sum). "
            "sum=경계 셀 인구를 합산해 셀 전체 인구 복원(권장), "
            "first/last=한 행만 남기고 나머지 폐기(부분값만 유지)"
        ),
    )
    return p.parse_args(argv)


def load_layers(args: argparse.Namespace) -> list[tuple[str, gpd.GeoDataFrame]]:
    """모든 ZIP 을 해제·로드하여 (원본명, GeoDataFrame) 목록을 반환."""
    layers: list[tuple[str, gpd.GeoDataFrame]] = []
    for zip_path in args.zip:
        if not zip_path.exists():
            raise FileNotFoundError(f"ZIP 을 찾을 수 없습니다: {zip_path}")
        dest = args.extract_dir / zip_path.stem
        gridlib.extract_zip(zip_path, dest)
        shapefiles = gridlib.find_shapefiles(dest)
        if not shapefiles:
            print(f"[경고] {zip_path.name} 에서 .shp 를 찾지 못했습니다.", file=sys.stderr)
        multi = len(shapefiles) > 1
        for shp in shapefiles:
            gdf = gridlib.read_grid_shapefile(
                shp, encoding=args.encoding, fallback_crs=args.fallback_crs
            )
            # 출처 라벨: ZIP 이름 기준(내부 .shp 는 대개 vl_blk 로 동일).
            # 한 ZIP 에 셰이프파일이 여러 개면 shp 이름을 덧붙여 구분.
            source = f"{zip_path.stem}/{shp.stem}" if multi else zip_path.stem
            layers.append((source, gdf))
            print(f"  로드: {source}  ({len(gdf):,}행, CRS={gdf.crs})")
    return layers


def build(args: argparse.Namespace) -> gpd.GeoDataFrame:
    print("=== 1) ZIP 해제 및 로드 ===")
    layers = load_layers(args)
    if not layers:
        raise RuntimeError("로드된 레이어가 없습니다.")

    # 목표 CRS 결정
    target_crs = args.target_crs or layers[0][1].crs
    if target_crs is None:
        target_crs = args.fallback_crs
    print(f"\n=== 2) 공통 좌표계로 재투영: {target_crs} ===")

    # 컬럼 자동 탐지 (첫 레이어 기준, 이후 검증)
    first_cols = layers[0][1].columns
    grid_col = gridlib.detect_grid_column(first_cols, args.grid_col)
    pop_col = gridlib.detect_pop_column(first_cols, args.pop_col)
    if grid_col is None:
        raise RuntimeError(
            f"격자ID 컬럼을 탐지하지 못했습니다. --grid-col 로 지정하세요. 컬럼: {list(first_cols)}"
        )
    if pop_col is None:
        raise RuntimeError(
            f"인구 컬럼을 탐지하지 못했습니다. --pop-col 로 지정하세요. 컬럼: {list(first_cols)}"
        )
    print(f"  격자ID 컬럼: {grid_col} / 인구 컬럼: {pop_col}")

    prepared: list[gpd.GeoDataFrame] = []
    for name, gdf in layers:
        if grid_col not in gdf.columns or pop_col not in gdf.columns:
            raise RuntimeError(
                f"레이어 '{name}' 에 필요한 컬럼이 없습니다 "
                f"({grid_col}, {pop_col}). 실제 컬럼: {list(gdf.columns)}"
            )
        if gdf.crs is not None and str(gdf.crs) != str(target_crs):
            gdf = gdf.to_crs(target_crs)
        elif gdf.crs is None:
            gdf = gdf.set_crs(target_crs, allow_override=True)
        gdf = gdf.copy()
        gdf["source"] = name  # 출처 지역 추적
        prepared.append(gdf)

    print("\n=== 3) 병합(concat) ===")
    merged = gpd.GeoDataFrame(
        pd.concat(prepared, ignore_index=True), crs=target_crs
    )
    print(f"  병합 후 행 수: {len(merged):,}")

    print(f"\n=== 4) 격자ID 기준 중복 처리 (방식: {args.dedup}) ===")
    # 인구 컬럼을 수치형으로 정규화 (문자열/공백/NULL 방어)
    merged[pop_col] = pd.to_numeric(merged[pop_col], errors="coerce")
    before = len(merged)
    dup_ids = int(merged[grid_col].duplicated().sum())

    if args.dedup == "sum":
        # 경계에 걸친 셀: 지역별 부분 인구를 합산해 셀 전체 인구를 복원한다.
        # (전부 결측이면 NaN 유지 — min_count=1). source 는 기여 지역을 모두 표기.
        merged[pop_col] = merged.groupby(grid_col)[pop_col].transform(
            lambda s: s.sum(min_count=1)
        )
        merged["source"] = merged.groupby(grid_col)["source"].transform(
            lambda s: ",".join(sorted(set(s)))
        )
        merged = merged.drop_duplicates(subset=[grid_col], keep="first")
    else:
        merged = merged.drop_duplicates(subset=[grid_col], keep=args.dedup)
    merged = merged.reset_index(drop=True)

    removed = before - len(merged)
    print(
        f"  중복 격자ID {dup_ids:,}개 → {removed:,}행 정리 → {len(merged):,}행 "
        f"(고유 격자 {merged[grid_col].nunique():,})"
    )

    print("\n=== 5) 인구밀도 계산 ===")
    pop_nulls = int(merged[pop_col].isna().sum())
    if pop_nulls:
        print(f"  [주의] 인구 결측 {pop_nulls:,}행 → 밀도는 NaN 으로 남습니다.")

    # 격자 실면적(㎢). 투영좌표계(m)라면 geom.area/1e6.
    if merged.crs is not None and merged.crs.is_geographic:
        print(
            "  [경고] CRS 가 지리좌표계입니다. 면적 계산을 위해 "
            f"{gridlib.DEFAULT_KOREA_CRS} 로 임시 재투영합니다."
        )
        area_km2 = merged.to_crs(gridlib.DEFAULT_KOREA_CRS).geometry.area / 1_000_000.0
    else:
        area_km2 = merged.geometry.area / 1_000_000.0

    merged["area_km2"] = area_km2.round(6)
    # 인구밀도 = 인구 / 면적(㎢). 면적 0 방어.
    merged["pop_density"] = (
        merged[pop_col] / merged["area_km2"].where(merged["area_km2"] > 0)
    ).round(4)
    print(
        f"  area_km2 범위: {merged['area_km2'].min():.4f} ~ {merged['area_km2'].max():.4f}"
    )
    valid = merged["pop_density"].dropna()
    if len(valid):
        print(
            f"  pop_density 범위: {valid.min():.2f} ~ {valid.max():.2f} (명/㎢)"
        )

    return merged


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    merged = build(args)

    print("\n=== 6) GeoPackage 저장 ===")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    merged.to_file(args.out, layer=args.layer_name, driver="GPKG")
    print(f"  저장 완료: {args.out} (레이어: {args.layer_name}, {len(merged):,}행)")
    print(f"  최종 컬럼: {list(merged.columns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
