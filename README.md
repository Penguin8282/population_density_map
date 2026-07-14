# 수도권 1km 격자 인구 데이터 파이프라인

서울·인천·경기 **국토통계지도 1km 격자 인구** 셰이프파일을 병합하여
인구밀도가 포함된 GeoPackage 를 생성하는 파이프라인.

## GitHub에서 바로 실행하기 (PC 설치 없이)

데모용 원본 ZIP 3개가 `data/raw/` 에 포함되어 있어, 아래 두 방법으로 웹에서 바로 돌릴 수 있습니다.

### ① GitHub Actions — 버튼 클릭 → 결과물 다운로드
1. 저장소 상단 **Actions** 탭 → 왼쪽 **build-population-gpkg** 선택
2. 오른쪽 **Run workflow ▾ → Run workflow** 클릭
3. 실행이 끝나면 해당 실행 페이지 하단 **Artifacts** 에서 `population-density-outputs`
   (GeoPackage + 인구밀도 지도 PNG) 다운로드
   - `main` 에 코드/데이터가 바뀌면 자동으로도 실행됩니다.

### ② Codespaces — 브라우저 터미널에서 직접 실행
1. 저장소 상단 **Code ▾ → Codespaces → Create codespace on main**
2. 환경이 자동 구성되면(`.devcontainer` 로 의존성 설치) 터미널에서:
   ```bash
   python src/build_population_gpkg.py \
     --zip data/raw/seoul_1km_202410.zip data/raw/incheon_1km_202410.zip data/raw/gyeonggi_1km_202410.zip \
     --out data/processed/out.gpkg
   python scripts/plot_density.py   # density_map.png 생성
   ```

## 구성

```
.
├── data/
│   ├── raw/          # 입력 ZIP / 해제된 셰이프파일 (git 제외)
│   └── processed/    # 결과 GeoPackage (git 제외)
├── src/
│   ├── gridlib.py               # 공용 모듈 (ZIP 해제, cp949, 컬럼 자동탐지)
│   ├── inspect_grids.py         # [1단계] 스키마·CRS·행수·결측 점검
│   └── build_population_gpkg.py # [2단계] 병합·중복제거·밀도·GPKG 저장
└── requirements.txt
```

## 설치

```bash
pip install -r requirements.txt
```

> `geopandas` 는 GDAL 기반이라 시스템에 따라 설치가 무거울 수 있습니다.
> 문제가 있으면 conda(`conda install -c conda-forge geopandas`) 사용을 권장합니다.

## 사용법

원본 ZIP 파일을 `data/raw/` 에 넣습니다. 지역별 ZIP 3개든, 3개 셰이프파일이
들어 있는 통합 ZIP 1개든 모두 지원합니다.

### 1단계 — 점검 (스키마/좌표계/행수/인구 결측)

```bash
python src/inspect_grids.py --zip data/raw/서울.zip data/raw/인천.zip data/raw/경기.zip
```

각 셰이프파일의 **컬럼 스키마, 좌표계(CRS), 행 수, 인구 컬럼 결측 여부**를
출력합니다.

### 2단계 — 병합 → GeoPackage 생성

```bash
python src/build_population_gpkg.py \
    --zip data/raw/서울.zip data/raw/인천.zip data/raw/경기.zip \
    --out data/processed/seoul_incheon_gyeonggi_1km_pop.gpkg
```

처리 내용:

1. ZIP 해제 (한글 파일명 cp949 복원)
2. 셰이프파일 **cp949** 로드
3. 공통 좌표계로 재투영 후 병합
4. **격자ID 기준 중복 처리** (경계 중첩 격자 정리, 기본 `sum`)
5. 격자 실면적(`area_km2`)·**인구밀도(`pop_density`, 명/㎢)** 계산
6. GeoPackage(`.gpkg`) 저장

## 주요 옵션

| 옵션 | 설명 |
|------|------|
| `--grid-col`     | 격자ID 컬럼 강제 지정 (자동탐지 실패 시) |
| `--pop-col`      | 인구 컬럼 강제 지정 |
| `--target-crs`   | 병합/저장 목표 좌표계 (기본: 첫 레이어 CRS) |
| `--fallback-crs` | `.prj` 누락 시 사용할 좌표계 (기본: `EPSG:5179`) |
| `--dedup`        | 중복 격자 처리 `sum`/`first`/`last` (기본: `sum`) |
| `--encoding`     | DBF 인코딩. `auto`=`.cpg`/`.cst` 자동판별 후 cp949 폴백 (기본: `auto`) |

## 한글 인코딩 주의 (cp949 / UTF-8 자동판별)

통계청 국토통계지도 배포본은 파일에 따라 DBF 인코딩이 **cp949(euc-kr)**
또는 **UTF-8** 입니다(셰이프파일과 같은 이름의 `.cpg`/`.cst` 사이드카에
코드페이지가 적혀 있음). 본 파이프라인은:

- ZIP 내 한글 파일명이 cp949 로 저장된 경우 복원해 해제하고,
- `.cpg`/`.cst` 를 읽어 DBF 인코딩을 **자동 판별**하며(없으면 cp949 가정,
  읽기 실패 시 utf-8 ↔ cp949 폴백),
- 결과 GeoPackage 는 UTF-8 로 저장되어 한글이 그대로 보존됩니다.

> 실제 검증한 인천 파일(`B100…1KM…202410.zip`)의 셰이프파일(`vl_blk`)은
> `.cst = UTF-8`, EPSG:5179, 1,705행, 컬럼 `gid`(격자ID)·`lbl`·`val`(인구)
> 이며 `val` 결측(=통계없음)이 598행(35.1%) 였습니다.

## 컬럼/좌표계 자동 탐지

- **격자ID 컬럼 후보**: `gid`, `grid_id`, `grid_1k_cd`, `격자코드` 등
- **인구 컬럼 후보**: `val`, `value`, `총인구`, `인구`, `tot_ppltn` 등
- 자동 탐지에 실패하면 `--grid-col` / `--pop-col` 로 직접 지정하세요.
- 국토통계지도 계열 기본 좌표계는 **EPSG:5179 (UTM-K)** 로 가정합니다.

## 출력 스키마

원본 컬럼에 다음이 추가됩니다.

| 컬럼 | 설명 |
|------|------|
| `source`      | 출처 지역(원본 셰이프파일명) |
| `area_km2`    | 격자 실면적(㎢, 지오메트리 기준) |
| `pop_density` | 인구밀도 = 인구 / `area_km2` (명/㎢) |

> 온전한 1km 격자는 `area_km2 == 1.0` 이라 `pop_density` 가 인구값과 같지만,
> 행정경계에서 잘린 격자는 실면적으로 보정된 밀도가 계산됩니다.
> 인구가 결측인 격자의 `pop_density` 는 `NaN` 으로 유지됩니다.

## 경계 격자 중복 처리 (`--dedup`)

국토통계지도는 행정경계에 걸친 1km 셀의 인구를 **각 지역에 속한 부분만**
집계합니다. 따라서 같은 `gid` 가 서울·경기 등 여러 지역 파일에 나타나며,
그 부분 인구값이 서로 다를 수 있습니다.

- **`sum` (기본, 권장)**: 같은 격자의 지역별 부분 인구를 **합산**해 셀 전체
  인구를 복원합니다. `source` 에는 기여한 모든 지역이 기록됩니다.
  (모든 지역에서 통계없음이면 `NaN` 유지)
- **`first` / `last`**: 한 행만 남기고 나머지를 폐기 — 부분값만 유지되어
  경계 셀 인구가 과소집계될 수 있습니다.

> 실제 서울+인천+경기 병합 시 경계 중복 격자는 **282개**(그중 109개는
> 지역별 인구값 상이)였고, `sum` 으로 합산해 최종 **13,052개** 고유 격자가
> 생성되었습니다.
