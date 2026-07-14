#!/usr/bin/env python3
"""
inspect_grids.py — [1단계] ZIP 해제 및 셰이프파일 스키마 점검
==============================================================

서울·인천·경기 국토통계지도 1km 격자 인구 ZIP 을 해제하고, 내부의 각
셰이프파일에 대해 다음을 보고한다:

  * 포함된 파일 목록
  * 컬럼 스키마(이름/자료형)
  * 좌표계(CRS)
  * 행 수
  * 인구 컬럼의 결측(Null) 여부

사용 예::

    python src/inspect_grids.py --zip data/raw/서울인천경기_1km.zip
    python src/inspect_grids.py --zip a.zip --extract-dir data/raw/extracted

여러 ZIP 을 한꺼번에 넘길 수도 있다::

    python src/inspect_grids.py --zip 서울.zip 인천.zip 경기.zip
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# src 를 모듈 경로에 추가 (직접 실행 대응)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gridlib  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="국토통계지도 1km 격자 인구 ZIP 점검")
    p.add_argument(
        "--zip",
        nargs="+",
        required=True,
        type=Path,
        help="점검할 ZIP 파일 경로(들)",
    )
    p.add_argument(
        "--extract-dir",
        type=Path,
        default=Path("data/raw/extracted"),
        help="ZIP 해제 위치 (기본: data/raw/extracted)",
    )
    p.add_argument("--encoding", default="auto",
                   help="DBF 인코딩. auto=.cpg/.cst 자동판별 후 cp949 폴백 (기본: auto)")
    p.add_argument("--grid-col", default=None, help="격자ID 컬럼 강제 지정")
    p.add_argument("--pop-col", default=None, help="인구 컬럼 강제 지정")
    p.add_argument(
        "--fallback-crs",
        default=None,
        help="CRS 가 비어 있을 때 사용할 좌표계 (예: EPSG:5179)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    all_shapefiles: list[Path] = []
    for zip_path in args.zip:
        if not zip_path.exists():
            print(f"[오류] ZIP 을 찾을 수 없습니다: {zip_path}", file=sys.stderr)
            return 2
        dest = args.extract_dir / zip_path.stem
        written = gridlib.extract_zip(zip_path, dest)
        print(f"\n=== ZIP 해제: {zip_path.name} → {dest} ===")
        print(f"  포함 파일 {len(written)}개:")
        for f in sorted(written):
            print(f"    · {f.relative_to(dest)}")
        all_shapefiles.extend(gridlib.find_shapefiles(dest))

    if not all_shapefiles:
        print("\n[경고] 해제된 내용에서 .shp 파일을 찾지 못했습니다.", file=sys.stderr)
        return 1

    print("\n" + "=" * 70)
    print("셰이프파일 스키마 리포트")
    print("=" * 70)
    for shp in all_shapefiles:
        info = gridlib.summarize_layer(
            shp,
            encoding=args.encoding,
            grid_col=args.grid_col,
            pop_col=args.pop_col,
            fallback_crs=args.fallback_crs,
        )
        print()
        print(gridlib.format_layer_report(info))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
