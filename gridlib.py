"""
gridlib — 국토통계지도 1km 격자 인구 데이터 처리 공용 모듈
================================================================

서울·인천·경기 국토통계지도(1km 격자) 인구 셰이프파일을 다루기 위한
공용 유틸리티. ZIP 해제, 셰이프파일 탐색, cp949(euc-kr) 인코딩 처리,
격자ID/인구 컬럼 자동 탐지, 스키마 요약 기능을 제공한다.

핵심 주의사항
-------------
* 통계청 국토통계지도 셰이프파일의 DBF 속성은 대부분 **cp949**로 인코딩됨.
  fiona/pyogrio 가 UTF-8 로 잘못 읽으면 한글 컬럼/값이 깨지므로
  ``encoding="cp949"`` 를 명시적으로 지정한다.
* 좌표계는 보통 **EPSG:5179 (Korea 2000 / Unified CS, UTM-K, m 단위)** 또는
  EPSG:5181(중부원점 GRS80). .prj 가 없거나 모호하면 기본값을 지정할 수 있다.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import geopandas as gpd
import pandas as pd


# ---------------------------------------------------------------------------
# 컬럼 자동 탐지 후보 (대소문자 무시). 국토통계지도/SGIS 배포본에서 흔한 이름들.
# ---------------------------------------------------------------------------
GRID_ID_CANDIDATES: tuple[str, ...] = (
    "gid",
    "grid_id",
    "gridid",
    "grd_id",
    "grid_1k_cd",
    "grid1k_cd",
    "grid_cd",
    "grdidx",
    "격자id",
    "격자코드",
)

POP_CANDIDATES: tuple[str, ...] = (
    "val",
    "value",
    "pop",
    "population",
    "tot_ppltn",
    "totppltn",
    "인구",
    "총인구",
    "총인구수",
    "인구수",
    "to_in",  # 국토통계지도 축약형(총인구)에서 종종 등장
)

# 국토통계지도 계열의 기본 좌표계 후보 (미터 단위 투영좌표계)
DEFAULT_KOREA_CRS = "EPSG:5179"  # Korea 2000 / Unified CS (UTM-K)


@dataclass
class LayerInfo:
    """단일 셰이프파일(지역 레이어)에 대한 요약 정보."""

    name: str
    path: Path
    crs: Optional[str]
    row_count: int
    columns: dict[str, str]  # 컬럼명 -> dtype 문자열
    grid_col: Optional[str]
    pop_col: Optional[str]
    pop_nulls: Optional[int]
    pop_null_pct: Optional[float]
    encoding: str
    notes: list[str] = field(default_factory=list)


def extract_zip(zip_path: Path, dest_dir: Path) -> list[Path]:
    """ZIP 을 dest_dir 에 해제하고, 내부에 포함된 파일 경로 목록을 반환한다.

    한글 파일명이 cp949 로 저장된 경우 zipfile 이 UTF-8/CP437 로 잘못 디코딩해
    깨진 이름으로 풀릴 수 있으므로, 그런 항목은 cp949 로 복원해 저장한다.
    """
    zip_path = Path(zip_path)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            raw_name = info.filename
            # zipfile 은 UTF-8 플래그가 없으면 CP437 로 디코딩한다.
            # 한글이면 원래 cp949 바이트로 되돌린 뒤 cp949 로 재디코딩.
            if not (info.flag_bits & 0x800):
                try:
                    raw_name = raw_name.encode("cp437").decode("cp949")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    raw_name = info.filename

            if info.is_dir():
                (dest_dir / raw_name).mkdir(parents=True, exist_ok=True)
                continue

            target = dest_dir / raw_name
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            written.append(target)
    return written


def find_shapefiles(root: Path) -> list[Path]:
    """root 하위(재귀)에서 .shp 파일을 모두 찾아 정렬된 목록으로 반환."""
    return sorted(Path(root).rglob("*.shp"))


def _match_column(columns: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    """후보 목록과 (대소문자 무시) 일치하는 첫 컬럼명을 실제 표기로 반환."""
    lower_map = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return None


def detect_grid_column(columns: Iterable[str], override: Optional[str] = None) -> Optional[str]:
    cols = list(columns)
    if override:
        if override in cols:
            return override
        raise ValueError(f"지정한 격자ID 컬럼 '{override}' 을(를) 찾을 수 없습니다. 사용 가능: {cols}")
    return _match_column(cols, GRID_ID_CANDIDATES)


def detect_pop_column(columns: Iterable[str], override: Optional[str] = None) -> Optional[str]:
    cols = list(columns)
    if override:
        if override in cols:
            return override
        raise ValueError(f"지정한 인구 컬럼 '{override}' 을(를) 찾을 수 없습니다. 사용 가능: {cols}")
    return _match_column(cols, POP_CANDIDATES)


# 인코딩 자동 판별을 뜻하는 센티널. --encoding auto 로 지정 가능.
AUTO_ENCODING = "auto"

# .cpg/.cst 에 적힌 코드페이지 문자열 → 파이썬 코덱 정규화
_CODEPAGE_ALIASES = {
    "utf8": "utf-8",
    "utf-8": "utf-8",
    "euckr": "cp949",
    "euc-kr": "cp949",
    "ksc5601": "cp949",
    "ms949": "cp949",
    "cp949": "cp949",
    "949": "cp949",
    "system": "cp949",  # 한국 윈도우 기본 코드페이지
}


def detect_encoding(shp_path: Path) -> Optional[str]:
    """.cpg 또는 .cst 사이드카에서 DBF 인코딩을 판별한다.

    셰이프파일과 같은 이름의 .cpg(표준) 또는 .cst(구 ArcGIS) 파일에 적힌
    코드페이지 문자열을 파이썬 코덱명으로 정규화해 반환. 없으면 None.
    국토통계지도 배포본은 파일에 따라 UTF-8(.cst) 또는 cp949 를 사용한다.
    """
    shp_path = Path(shp_path)
    for ext in (".cpg", ".CPG", ".cst", ".CST"):
        side = shp_path.with_suffix(ext)
        if side.exists():
            raw = side.read_bytes().decode("ascii", "ignore").strip().lower()
            key = raw.replace(" ", "")
            if key in _CODEPAGE_ALIASES:
                return _CODEPAGE_ALIASES[key]
            # "windows-949", "codepage 949" 같은 변형 처리
            if "949" in key:
                return "cp949"
            if "utf" in key:
                return "utf-8"
    return None


def resolve_encoding(shp_path: Path, encoding: str = AUTO_ENCODING) -> str:
    """사용할 DBF 인코딩을 결정한다.

    * ``encoding`` 이 'auto' 가 아니면 그대로 사용.
    * 'auto' 이면 .cpg/.cst 사이드카를 우선, 없으면 cp949 로 가정한다.
    """
    if encoding and encoding.lower() != AUTO_ENCODING:
        return encoding
    return detect_encoding(shp_path) or "cp949"


def read_grid_shapefile(
    shp_path: Path,
    encoding: str = AUTO_ENCODING,
    fallback_crs: Optional[str] = None,
) -> gpd.GeoDataFrame:
    """셰이프파일을 올바른 한글 인코딩으로 읽어 GeoDataFrame 반환.

    * ``encoding='auto'`` (기본): .cpg/.cst 사이드카를 보고 인코딩 결정,
      없으면 cp949. 지정 시 해당 인코딩을 강제.
    * 선택한 인코딩으로 실패하면 utf-8 ↔ cp949 로 폴백.
    * .prj 가 없어 CRS 가 비어 있으면 ``fallback_crs`` 를 지정(assign)한다.
    """
    shp_path = Path(shp_path)
    enc = resolve_encoding(shp_path, encoding)
    tried = [enc] + [e for e in ("utf-8", "cp949") if e != enc]
    last_err: Optional[Exception] = None
    gdf = None
    for e in tried:
        try:
            gdf = gpd.read_file(shp_path, encoding=e)
            break
        except (UnicodeDecodeError, UnicodeError) as err:
            last_err = err
    if gdf is None:
        raise last_err if last_err else RuntimeError(f"셰이프파일 읽기 실패: {shp_path}")

    if gdf.crs is None and fallback_crs:
        gdf = gdf.set_crs(fallback_crs, allow_override=True)
    return gdf


def summarize_layer(
    shp_path: Path,
    encoding: str = AUTO_ENCODING,
    grid_col: Optional[str] = None,
    pop_col: Optional[str] = None,
    fallback_crs: Optional[str] = None,
) -> LayerInfo:
    """셰이프파일 하나에 대한 스키마/CRS/행수/인구 결측 요약을 생성한다."""
    used_encoding = resolve_encoding(shp_path, encoding)
    gdf = read_grid_shapefile(shp_path, encoding=encoding, fallback_crs=fallback_crs)

    columns = {c: str(gdf[c].dtype) for c in gdf.columns}
    detected_grid = detect_grid_column(gdf.columns, grid_col)
    detected_pop = detect_pop_column(gdf.columns, pop_col)

    notes: list[str] = []
    pop_nulls: Optional[int] = None
    pop_null_pct: Optional[float] = None
    if detected_pop is not None:
        pop_nulls = int(gdf[detected_pop].isna().sum())
        pop_null_pct = round(100.0 * pop_nulls / len(gdf), 4) if len(gdf) else 0.0
    else:
        notes.append("인구 컬럼을 자동 탐지하지 못했습니다. --pop-col 로 지정하세요.")

    if detected_grid is None:
        notes.append("격자ID 컬럼을 자동 탐지하지 못했습니다. --grid-col 로 지정하세요.")
    if gdf.crs is None:
        notes.append("CRS 가 비어 있습니다(.prj 누락 가능). --fallback-crs 로 지정하세요.")

    return LayerInfo(
        name=shp_path.stem,
        path=shp_path,
        crs=str(gdf.crs) if gdf.crs is not None else None,
        row_count=len(gdf),
        columns=columns,
        grid_col=detected_grid,
        pop_col=detected_pop,
        pop_nulls=pop_nulls,
        pop_null_pct=pop_null_pct,
        encoding=used_encoding,
        notes=notes,
    )


def format_layer_report(info: LayerInfo) -> str:
    """LayerInfo 를 사람이 읽기 좋은 텍스트 리포트로 변환."""
    lines: list[str] = []
    lines.append(f"■ 레이어: {info.name}")
    lines.append(f"  - 경로     : {info.path}")
    lines.append(f"  - 인코딩   : {info.encoding}")
    lines.append(f"  - 좌표계   : {info.crs or '(없음)'}")
    lines.append(f"  - 행 수    : {info.row_count:,}")
    lines.append(f"  - 격자ID컬럼: {info.grid_col or '(미탐지)'}")
    if info.pop_col is not None:
        lines.append(
            f"  - 인구컬럼 : {info.pop_col} "
            f"(결측 {info.pop_nulls:,}행 / {info.pop_null_pct}%)"
        )
    else:
        lines.append("  - 인구컬럼 : (미탐지)")
    lines.append("  - 컬럼 스키마:")
    for col, dtype in info.columns.items():
        lines.append(f"      · {col}: {dtype}")
    for note in info.notes:
        lines.append(f"  ! 주의: {note}")
    return "\n".join(lines)
