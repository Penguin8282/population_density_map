/* =========================================================================
 * 수도권 1km 격자 인구밀도 인터랙티브 지도
 * -------------------------------------------------------------------------
 * 데이터:  data/grid.geojson  (gid, sido, sigungu, eupmyeondong, pop, density)
 * 라이브러리: Leaflet 만 사용 (그 외 전부 바닐라 JS)
 *
 * [작업 0] 정적 Leaflet 앱 기반 구축 — CARTO 베이스맵, 7단계 분위수 색상,
 *          hover 툴팁, 세로 범례. (렌더러는 SVG; 작업 2에서 캔버스로 전환)
 * =======================================================================*/

// ---- 설정 ----------------------------------------------------------------
const DATA_URL = "data/grid.geojson";
const K = 7; // 색상 단계 수
// 노랑 → 진빨강 (7단계가 눈으로 명확히 구분되는 고대비 팔레트 YlOrRd)
const COLORS = ["#ffffb2", "#fed976", "#feb24c", "#fd8d3c", "#fc4e2a", "#e31a1c", "#b10026"];
const NODATA_COLOR = "#d9d9d9";

// ---- 전역 상태 -----------------------------------------------------------
const state = {
  breaks: [],      // 분위수 경계 (길이 K+1)
  gridLayer: null, // 격자 GeoJSON 레이어
};

// ---- 지도 초기화 ---------------------------------------------------------
const map = L.map("map", { preferCanvas: false }); // 작업 0: SVG 렌더러

// CARTO Positron 베이스맵
L.tileLayer(
  "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
  {
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
      '&copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: "abcd",
    maxZoom: 19,
  }
).addTo(map);

// ---- 분류: 7단계 분위수 경계 계산 ---------------------------------------
function quantileBreaks(values, k) {
  const s = values.slice().sort((a, b) => a - b);
  const breaks = [s[0]];
  for (let i = 1; i < k; i++) {
    breaks.push(s[Math.floor((i / k) * s.length)]);
  }
  breaks.push(s[s.length - 1]);
  return breaks; // 길이 k+1
}

// 밀도 → 클래스 인덱스(0..K-1). 결측(null/undefined)은 -1.
function classOf(density) {
  if (density === null || density === undefined || Number.isNaN(density)) return -1;
  const b = state.breaks;
  for (let i = 0; i < K; i++) {
    // 마지막 구간은 상한 포함
    if (density <= b[i + 1] || i === K - 1) return i;
  }
  return K - 1;
}

function colorOf(density) {
  const c = classOf(density);
  return c < 0 ? NODATA_COLOR : COLORS[c];
}

// ---- 격자 스타일 ---------------------------------------------------------
function baseStyle(feature) {
  const d = feature.properties.density;
  const nodata = classOf(d) < 0;
  return {
    fillColor: colorOf(d),
    color: "#00000022",
    weight: 0.3,
    fillOpacity: nodata ? 0.35 : 0.75,
  };
}

// ---- 툴팁 (hover) --------------------------------------------------------
function tooltipHtml(p) {
  const dong = [p.sido, p.sigungu, p.eupmyeondong].filter(Boolean).join(" ");
  const dens = p.density == null ? "통계없음" : Math.round(p.density).toLocaleString();
  const pop = p.pop == null ? "-" : Math.round(p.pop).toLocaleString();
  return (
    `<div class="grid-tooltip"><b>${dong || "(행정동 미상)"}</b><br>` +
    `인구밀도: ${dens} 명/㎢<br>인구: ${pop} 명</div>`
  );
}

// ---- 범례 (세로 나열) ----------------------------------------------------
function fmt(n) {
  return Math.round(n).toLocaleString();
}
function buildLegend() {
  const box = document.getElementById("legend-items");
  box.innerHTML = "";
  for (let i = K - 1; i >= 0; i--) {
    // 위에서부터 높은 밀도 → 낮은 밀도
    const row = document.createElement("div");
    row.className = "legend-row";
    row.innerHTML =
      `<span class="legend-swatch" style="background:${COLORS[i]}"></span>` +
      `<span class="legend-label">${fmt(state.breaks[i])} – ${fmt(state.breaks[i + 1])}</span>`;
    box.appendChild(row);
  }
  // 결측 항목
  const row = document.createElement("div");
  row.className = "legend-row";
  row.innerHTML =
    `<span class="legend-swatch" style="background:${NODATA_COLOR}"></span>` +
    `<span class="legend-label">통계없음</span>`;
  box.appendChild(row);
}

// ---- 데이터 로드 & 렌더 --------------------------------------------------
fetch(DATA_URL)
  .then((r) => r.json())
  .then((geojson) => {
    const densities = geojson.features
      .map((f) => f.properties.density)
      .filter((d) => d !== null && d !== undefined && !Number.isNaN(d));
    state.breaks = quantileBreaks(densities, K);
    console.log("7단계 분위수 경계:", state.breaks.map((b) => Math.round(b)));

    state.gridLayer = L.geoJSON(geojson, {
      style: baseStyle,
      onEachFeature: (feature, layer) => {
        layer.bindTooltip(tooltipHtml(feature.properties), { sticky: true });
      },
    }).addTo(map);

    map.fitBounds(state.gridLayer.getBounds());
    buildLegend();
  })
  .catch((err) => {
    console.error("데이터 로드 실패:", err);
    alert("격자 데이터를 불러오지 못했습니다: " + err);
  });
