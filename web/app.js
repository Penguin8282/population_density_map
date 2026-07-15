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
  breaks: [],       // 분위수 경계 (길이 K+1)
  gridLayer: null,  // 격자 GeoJSON 레이어
  activeClass: null, // 범례 클릭 필터: null=전체, 0..K-1=해당 구간, -1=통계없음
  selectedDong: null, // 검색으로 선택된 읍면동 키
  dongBounds: {},   // 읍면동 키 → L.latLngBounds (검색 flyTo 용)
  densityRange: null, // [lo, hi] 밀도 범위 필터 (null=전체)
  method: "equal", // 색상 분류 방식: quantile | equal(선형·기본) | log
  densities: [],      // 결측 제외 밀도 값 배열
};

// "시도 시군구 읍면동" 형태의 검색/식별 키 (동명 중복을 시군구로 구분)
function dongKey(p) {
  return [p.sido, p.sigungu, p.eupmyeondong].filter(Boolean).join(" ");
}

// ---- 지도 초기화 ---------------------------------------------------------
// [작업 2] 렌더러: SVG → Canvas 로 전환하여 대량 폴리곤 성능 개선
//  · 변경 전(SVG, Leaflet 기본): 폴리곤 1개당 <path> DOM 노드가 생성됨.
//    격자 13,052개 → DOM 노드 13k+ 개. 줌/팬 시 브라우저 리플로우 부담이 커
//    프레임 드랍이 발생.
//  · 변경 후(Canvas): 모든 폴리곤을 단일 <canvas> 에 픽셀로 그림. DOM 노드가
//    사실상 1개로 줄어 줌/팬 재렌더가 훨씬 가벼움.
//  · hover 툴팁·범례 하이라이트(setStyle)는 Canvas 렌더러에서도 그대로 동작.
const canvasRenderer = L.canvas({ padding: 0.5 });
const map = L.map("map", { renderer: canvasRenderer });
window.__map = map; // 디버그/자동화 편의용 핸들

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

// ---- 분류: 3가지 방식으로 K단계 경계 계산 (작업 5) -----------------------
function quantileBreaks(values, k) {
  const s = values.slice().sort((a, b) => a - b);
  const breaks = [s[0]];
  for (let i = 1; i < k; i++) {
    breaks.push(s[Math.floor((i / k) * s.length)]);
  }
  breaks.push(s[s.length - 1]);
  return breaks; // 길이 k+1
}

// 분류 방식별 경계값 배열(길이 K+1) 계산
function computeBreaks(method, values, k) {
  const dmin = Math.min(...values);
  const dmax = Math.max(...values);
  if (method === "equal") {
    // 등간격: [min,max]를 균등 폭으로 분할
    const b = [];
    for (let i = 0; i <= k; i++) b.push(dmin + ((dmax - dmin) * i) / k);
    return b;
  }
  if (method === "log") {
    // 로그: 최소 양수~최대를 로그 스케일로 분할 (0 은 첫 구간에 포함)
    const lo = Math.max(values.filter((x) => x > 0).reduce((a, b) => Math.min(a, b), Infinity), 1);
    const b = [dmin];
    for (let i = 1; i <= k; i++) {
      b.push(Math.exp(Math.log(lo) + ((Math.log(dmax) - Math.log(lo)) * (i - 1)) / (k - 1)));
    }
    return b;
  }
  // 기본: 분위수
  return quantileBreaks(values, k);
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

// ---- 격자 스타일 (범례 클릭 필터 반영) ----------------------------------
function gridStyle(feature) {
  const cls = classOf(feature.properties.density);
  const s = { fillColor: colorOf(feature.properties.density), color: "#00000022", weight: 0.3 };
  if (state.activeClass === null) {
    // 필터 없음: 기본 표시
    s.fillOpacity = cls < 0 ? 0.35 : 0.75;
  } else if (cls === state.activeClass) {
    // 선택 구간: 강조 (진하게 + 테두리)
    s.fillOpacity = 0.9;
    s.color = "#333333";
    s.weight = 0.6;
  } else {
    // 그 외: 흐리게
    s.fillOpacity = 0.06;
  }
  // [작업 4] 밀도 범위 슬라이더: 선택 범위 밖 격자는 반투명
  if (cls >= 0 && state.densityRange) {
    const d = feature.properties.density;
    if (d < state.densityRange[0] || d > state.densityRange[1]) {
      s.fillOpacity = Math.min(s.fillOpacity, 0.08);
    }
  }
  // [작업 3] 검색으로 선택된 읍면동: 테두리 강조
  if (state.selectedDong && dongKey(feature.properties) === state.selectedDong) {
    s.color = "#0050b3";
    s.weight = 2;
    s.fillOpacity = Math.max(s.fillOpacity, 0.85);
  }
  return s;
}

// 범례 클릭 → 해당 구간만 강조 (같은 구간 다시 클릭 시 해제)
function setActiveClass(cls) {
  state.activeClass = state.activeClass === cls ? null : cls;
  if (state.gridLayer) state.gridLayer.setStyle(gridStyle);
  markActiveLegend();
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
function addLegendRow(box, cls, color, label) {
  const row = document.createElement("div");
  row.className = "legend-row";
  row.dataset.cls = String(cls);
  row.title = "클릭 시 이 구간만 강조 (다시 클릭하면 해제)";
  row.innerHTML =
    `<span class="legend-swatch" style="background:${color}"></span>` +
    `<span class="legend-label">${label}</span>`;
  row.addEventListener("click", () => setActiveClass(cls));
  box.appendChild(row);
}

function buildLegend() {
  const box = document.getElementById("legend-items");
  box.innerHTML = "";
  // 위에서부터 높은 밀도 → 낮은 밀도
  for (let i = K - 1; i >= 0; i--) {
    addLegendRow(box, i, COLORS[i], `${fmt(state.breaks[i])} – ${fmt(state.breaks[i + 1])}`);
  }
  addLegendRow(box, -1, NODATA_COLOR, "통계없음");
  markActiveLegend();
}

// 활성 구간 행에 표시(active 클래스) 부여
function markActiveLegend() {
  document.querySelectorAll("#legend-items .legend-row").forEach((row) => {
    const isActive = state.activeClass !== null && Number(row.dataset.cls) === state.activeClass;
    row.classList.toggle("active", isActive);
    row.classList.toggle("dimmed", state.activeClass !== null && !isActive);
  });
}

// ---- 읍면동 검색 (작업 3) ------------------------------------------------
function buildSearch() {
  const keys = Object.keys(state.dongBounds).sort();
  const dl = document.getElementById("dong-list");
  dl.innerHTML = keys.map((k) => `<option value="${k}"></option>`).join("");

  const input = document.getElementById("search-input");
  const clear = document.getElementById("search-clear");

  function selectDong(val) {
    // 정확 일치 우선, 없으면 부분 일치(첫 후보)
    let key = state.dongBounds[val] ? val : null;
    if (!key) {
      const q = val.trim();
      key = keys.find((k) => k.includes(q)) || null;
    }
    if (!key) return; // 후보 없음: 무시
    state.selectedDong = key;
    state.gridLayer.setStyle(gridStyle);
    map.flyToBounds(state.dongBounds[key], { maxZoom: 14, padding: [40, 40] });
  }

  input.addEventListener("change", () => selectDong(input.value));
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") selectDong(input.value); });
  clear.addEventListener("click", () => {
    input.value = "";
    state.selectedDong = null;
    state.gridLayer.setStyle(gridStyle);
  });
}

// ---- 레이어 오버레이 구조 (작업 6) ---------------------------------------
// 향후 500m 격자 적합성 분류(하드배제/리뷰/적격) 레이어를 얹기 위한 준비.
// 카테고리형 색상 매핑 함수 + 더미 데이터로 레이어 컨트롤 동작 검증.
const CATEGORY_COLORS = {
  "하드배제": "#d73027", // 빨강 — 개발 불가
  "리뷰": "#fee08b",     // 노랑 — 검토 필요
  "적격": "#1a9850",     // 초록 — 적합
};
function categoryColor(category) {
  return CATEGORY_COLORS[category] || "#999999";
}

// 실데이터 연결 전 구조 검증용 더미 500m 격자 (서울 도심 부근 3×3)
function makeDummySuitability() {
  const cx = 127.0, cy = 37.555, d = 0.0055; // ≈ 500m
  const cats = Object.keys(CATEGORY_COLORS);
  const features = [];
  for (let i = 0; i < 3; i++) {
    for (let j = 0; j < 3; j++) {
      const x = cx + i * d, y = cy + j * d;
      features.push({
        type: "Feature",
        properties: { category: cats[(i * 3 + j) % cats.length], note: "더미" },
        geometry: { type: "Polygon", coordinates: [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]] },
      });
    }
  }
  return { type: "FeatureCollection", features };
}

// 카테고리형 GeoJSON 레이어 생성 (실데이터도 동일 함수로 스타일링 가능)
function makeCategoryLayer(geojson) {
  return L.geoJSON(geojson, {
    style: (f) => ({
      fillColor: categoryColor(f.properties.category),
      color: "#333",
      weight: 0.6,
      fillOpacity: 0.55,
    }),
    onEachFeature: (f, l) =>
      l.bindTooltip(`적합성: <b>${f.properties.category}</b> (더미)`, { sticky: true }),
  });
}

function setupLayerControl() {
  const suitabilityLayer = makeCategoryLayer(makeDummySuitability());
  // 기본은 인구밀도만 표시, 적합성 레이어는 체크박스로 on/off
  L.control.layers(
    null,
    {
      "인구밀도 1km 격자": state.gridLayer,
      "적합성 분류 500m (더미)": suitabilityLayer,
    },
    { position: "bottomleft", collapsed: false }
  ).addTo(map);
}

// ---- 색상 분류 방식 토글 (작업 5) ----------------------------------------
function buildClassToggle() {
  const buttons = document.querySelectorAll("#class-toggle button[data-method]");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const method = btn.dataset.method;
      if (method === state.method) return;
      state.method = method;
      state.breaks = computeBreaks(method, state.densities, K);
      state.activeClass = null; // 경계가 바뀌므로 범례 필터 해제
      buttons.forEach((b) => b.classList.toggle("active", b === btn));
      buildLegend();                        // 범례 갱신
      state.gridLayer.setStyle(gridStyle);  // 격자 색상 갱신
      console.log(`분류=${method} 경계:`, state.breaks.map((b) => Math.round(b)));
    });
  });
}

// ---- 밀도 범위 필터 (작업 4 · 네이티브 이중 슬라이더) --------------------
function buildRangeFilter() {
  const dmin = Math.floor(state.breaks[0]);
  const dmax = Math.ceil(state.breaks[K]);
  const step = Math.max(1, Math.round((dmax - dmin) / 1000));
  const rmin = document.getElementById("range-min");
  const rmax = document.getElementById("range-max");
  [rmin, rmax].forEach((r) => { r.min = dmin; r.max = dmax; r.step = step; });
  rmin.value = dmin;
  rmax.value = dmax;

  function paintFill(lo, hi) {
    const l = ((lo - dmin) / (dmax - dmin)) * 100;
    const r = ((hi - dmin) / (dmax - dmin)) * 100;
    const fill = document.getElementById("range-fill");
    fill.style.left = l + "%";
    fill.style.width = (r - l) + "%";
  }

  function update() {
    let lo = +rmin.value;
    let hi = +rmax.value;
    if (lo > hi) {
      // 두 핸들 교차 방지: 방금 움직인 핸들을 상대에 맞춤
      if (document.activeElement === rmin) { lo = hi; rmin.value = lo; }
      else { hi = lo; rmax.value = hi; }
    }
    // 전체 범위면 필터 해제(null)
    state.densityRange = (lo <= dmin && hi >= dmax) ? null : [lo, hi];
    document.getElementById("range-readout").textContent = `${fmt(lo)} – ${fmt(hi)}`;
    paintFill(lo, hi);
    state.gridLayer.setStyle(gridStyle);
  }

  rmin.addEventListener("input", update);
  rmax.addEventListener("input", update);
  document.getElementById("range-readout").textContent = `${fmt(dmin)} – ${fmt(dmax)}`;
  paintFill(dmin, dmax);
}

// ---- 데이터 로드 & 렌더 --------------------------------------------------
fetch(DATA_URL)
  .then((r) => r.json())
  .then((geojson) => {
    state.densities = geojson.features
      .map((f) => f.properties.density)
      .filter((d) => d !== null && d !== undefined && !Number.isNaN(d));
    state.breaks = computeBreaks(state.method, state.densities, K);
    console.log(`초기 경계(${state.method}):`, state.breaks.map((b) => Math.round(b)));

    state.gridLayer = L.geoJSON(geojson, {
      style: gridStyle,
      onEachFeature: (feature, layer) => {
        // 데스크톱: hover 툴팁
        layer.bindTooltip(tooltipHtml(feature.properties), { sticky: true });
        // [작업 7] 모바일: 터치엔 hover 가 없으므로 tap → 팝업으로 대체
        layer.bindPopup(tooltipHtml(feature.properties));
        // [작업 3] 읍면동별 경계(bounds) 인덱스 구축 (검색 flyTo 용)
        const p = feature.properties;
        if (p.eupmyeondong && p.eupmyeondong !== "(행정동 미상)") {
          const key = dongKey(p);
          const lb = layer.getBounds();
          if (!state.dongBounds[key]) state.dongBounds[key] = L.latLngBounds(lb.getSouthWest(), lb.getNorthEast());
          else state.dongBounds[key].extend(lb);
        }
      },
    }).addTo(map);

    map.fitBounds(state.gridLayer.getBounds());
    buildLegend();
    buildSearch();
    buildRangeFilter();
    buildClassToggle();
    setupLayerControl();
  })
  .catch((err) => {
    console.error("데이터 로드 실패:", err);
    alert("격자 데이터를 불러오지 못했습니다: " + err);
  });
