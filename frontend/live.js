// 화면 ↔ 백엔드 API 연결 (행사 정보 → 품목 → 분석 → AI 추천 → 리포트)
// app.js 의 render() 가 화면을 그린 뒤 onScreen(이름) 을 부릅니다.
// 입력 상태는 이 브라우저(localStorage)에 저장되어 새로고침해도 유지됩니다.

// 백엔드가 화면도 함께 제공하면(run.sh, 8000번) 같은 주소의 /api, 프론트 개발 서버(4173)면 8000번 백엔드
const API = location.port === '4173' ? 'http://127.0.0.1:8000/api' : '/api';
const STORE_KEY = 'tanso.state.v1';
const PINE_KG_PER_YEAR = 6.6; // 30년생 소나무 1그루 연간 CO₂ 흡수량(kg) — 화면 환산용 참고값

const CATEGORIES = [
  { route: 'items-print', name: '인쇄물·홍보물', short: '인쇄', color: '#8fb3f4' },
  { route: 'items-drink', name: '음료·일회용품', short: '음료', color: '#87cf9a' },
  { route: 'items-food', name: '음식·간식', short: '음식', color: '#f28b82' },
  { route: 'items-goods', name: '굿즈', short: '굿즈', color: '#f5c451' },
];
const DELIVERY = { name: '배송', short: '배송', color: '#c9cdd2' };
const categoryOf = name => CATEGORIES.find(c => c.name === name) || (name === '배송' ? DELIVERY : { name, short: name, color: '#c9cdd2' });

const GOALS = {
  budget: { label: '예산 유지 기준', goal: { budget_increase_allowed: false, preserve_event_quality: true } },
  carbon20: { label: '탄소 감축 우선', goal: { budget_increase_allowed: true, target_reduction_percent: 20, preserve_event_quality: false } },
  quality: { label: '품질 유지 기준', goal: { budget_increase_allowed: true, preserve_event_quality: true } },
  custom: { label: '직접 입력 기준', goal: null },
};
const NOT_APPLICABLE = { FIXED_QUANTITY: '수량을 바꿀 수 없는 품목', BUDGET_INCREASE: '예산이 늘어나는 대안' };
const ERROR_TEXT = {
  EVENT_NOT_FOUND: '행사 정보를 찾을 수 없어요. 행사 정보부터 다시 입력해주세요.',
  INVALID_QUANTITY: '수량은 1 이상의 숫자로 입력해주세요.',
  AI_UNAVAILABLE: 'AI 추천을 불러오지 못했어요. 잠시 후 다시 시도해주세요.',
  STALE_DATA: '품목이 바뀌어서 추천을 다시 받아야 해요.',
};

// ---------------------------------------------------------------- 공통
const app = document.querySelector('#app');
const $ = (s, root = app) => root.querySelector(s);
const $$ = (s, root = app) => [...root.querySelectorAll(s)];
const named = (name, root = app) => $$('[data-name]', root).filter(e => e.dataset.name === name);
const fmt = (n, d = 0) => Number(n).toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d });
const kg = n => fmt(n, Math.abs(n) >= 100 ? 0 : 1);
const minus = n => '−' + fmt(Math.abs(n), 2);
const won = n => n == null ? '-' : fmt(n) + '원';
const go = name => { location.hash = '/' + name; };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function toast(message) {
  const t = document.querySelector('#toast');
  t.textContent = message; t.classList.add('show');
  clearTimeout(toast.timer); toast.timer = setTimeout(() => t.classList.remove('show'), 3200);
}

export const store = {
  get() { try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; } catch { return {}; } },
  set(patch) { const next = { ...store.get(), ...patch }; try { localStorage.setItem(STORE_KEY, JSON.stringify(next)); } catch { /* 저장 불가 환경 */ } return next; },
  reset() { try { localStorage.removeItem(STORE_KEY); } catch { /* 무시 */ } },
};

class ApiError extends Error {
  constructor(code, message, field) { super(message); this.code = code; this.field = field; }
}
async function api(method, path, body) {
  let res;
  try {
    res = await fetch(API + path, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
  } catch {
    throw new ApiError('NETWORK', '서버에 연결할 수 없어요. ./run.sh 로 서버를 켰는지 확인해주세요.');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.error || 'HTTP_' + res.status, ERROR_TEXT[data.error] || data.message || '요청을 처리하지 못했어요.', data.field);
  return data;
}

let catalogCache = null;
async function catalog() {
  if (!catalogCache) catalogCache = api('GET', '/items').then(r => r.items).catch(e => { catalogCache = null; throw e; });
  return catalogCache;
}

function setText(el, value) { if (el) el.textContent = value; }
function busy(button, on, label) {
  if (!button) return;
  if (on) { button.dataset.label = button.innerHTML; button.classList.add('lv-busy'); button.setAttribute('aria-busy', 'true'); if (label) button.querySelector('p') ? (button.querySelector('p').textContent = label) : (button.textContent = label); }
  else { if (button.dataset.label) button.innerHTML = button.dataset.label; button.classList.remove('lv-busy'); button.removeAttribute('aria-busy'); }
}
function intercept(el, handler) {
  if (!el) return;
  el.addEventListener('click', ev => { ev.preventDefault(); ev.stopImmediatePropagation(); handler(ev); }, true);
}
function requireStep(state, need) {
  if (need.includes('event') && !state.eventId) { toast('행사 정보를 먼저 입력해주세요.'); go('event'); return false; }
  if (need.includes('items') && !(state.items || []).length) { toast('품목을 먼저 추가해주세요.'); go('items-print'); return false; }
  if (need.includes('saved') && !state.itemsSaved) { toast('품목 입력 화면에서 "다음으로"를 눌러 저장해주세요.'); go('items-print'); return false; }
  return true;
}
function changeSummary(rec, unit) {
  if (rec.action_type === 'reduce_quantity') return `${rec.item_name} ${fmt(rec.current_value)}${unit || ''} → ${fmt(rec.recommended_value)}${unit || ''}`;
  return `${rec.item_name} → ${rec.alternative_item_name || rec.alternative_item_id}${rec.alternative_variant ? ' ' + rec.alternative_variant : ''}`;
}
function trees(kgValue) { return Math.max(0, kgValue / PINE_KG_PER_YEAR); }

// ---------------------------------------------------------------- 1. 행사 정보
function eventScreen() {
  const state = store.get();
  const fields = {
    event_name: $('[aria-label="행사명"]'), event_type: $('[aria-label="행사 유형"]'), participants: $('[aria-label="예상 참가인원"]'),
    budget: $('[aria-label="총 예산"]'), event_date: $('[aria-label="행사 날짜"]'), location: $('[aria-label="장소"]'), description: $('[aria-label="행사 설명"]'),
  };
  const date = fields.event_date;
  if (date) {
    const mark = () => { date.dataset.empty = String(!date.value); };
    date.addEventListener('click', () => { try { date.showPicker?.(); } catch { /* 일부 브라우저 미지원 */ } });
    date.addEventListener('input', mark); mark();
  }
  if (fields.budget) {
    fields.budget.inputMode = 'numeric';
    fields.budget.addEventListener('input', () => { const d = fields.budget.value.replace(/[^\d]/g, ''); fields.budget.value = d ? fmt(Number(d)) : ''; });
  }
  if (fields.participants) { fields.participants.min = '1'; fields.participants.step = '1'; }
  for (const el of Object.values(fields)) el?.addEventListener('input', () => el.closest('.field-shell')?.classList.remove('lv-invalid'));
  const saved = state.event || {};
  for (const [key, el] of Object.entries(fields)) {
    if (!el || saved[key] == null || saved[key] === '') continue;
    el.value = key === 'budget' ? fmt(saved[key]) : saved[key];
    el.dispatchEvent(new Event('input'));
  }
  const next = $('[data-node-id="24:731"]');
  intercept(next, async () => {
    const data = {
      event_name: fields.event_name?.value.trim(),
      event_type: fields.event_type?.selectedIndex > 0 ? fields.event_type.value : '',
      participants: Number(fields.participants?.value),
      budget: fields.budget?.value ? Number(fields.budget.value.replace(/[^\d]/g, '')) : null,
      event_date: date?.value || null,
      location: fields.location?.value.trim() || null,
      description: fields.description?.value.trim() || null,
    };
    const missing = [['event_name', '행사명'], ['event_type', '행사 유형'], ['participants', '예상 참가인원']].filter(([k]) => !data[k] || (k === 'participants' && !(data[k] >= 1)));
    for (const el of Object.values(fields)) el?.closest('.field-shell')?.classList.remove('lv-invalid');
    if (missing.length) {
      for (const [k] of missing) fields[k]?.closest('.field-shell')?.classList.add('lv-invalid');
      toast(`${missing.map(m => m[1]).join(', ')}을(를) 입력해주세요.`);
      fields[missing[0][0]]?.focus();
      return;
    }
    if (!Number.isInteger(data.participants)) { toast('참가인원은 정수로 입력해주세요.'); return; }
    busy(next, true, '저장 중…');
    try {
      const res = await api('POST', '/events', data);
      // 행사가 새로 만들어지면 이전 분석·추천은 의미가 없으므로 지움 (품목 목록은 유지)
      store.set({ event: data, eventId: res.event_id, scenarioId: res.scenario_id, itemsSaved: false, analysis: null, recs: null, applied: [] });
      go('items-print');
    } catch (e) { toast(e.message); busy(next, false); }
  });
}

// ---------------------------------------------------------------- 2. 품목 입력
function cardMeta(screens) {
  // Figma 품목 카드(4개 화면)에서 품목별 아이콘·설명을 가져옴. 이름이 다른 품목은 별칭으로 연결
  const alias = { '종이컵(뚜껑 포함)': 'paper_cup', 'PET컵(뚜껑 포함)': 'pet_cup' };
  const meta = {};
  for (const c of CATEGORIES) {
    const tpl = document.createElement('template'); tpl.innerHTML = screens[c.route] || '';
    for (const card of tpl.content.querySelectorAll('[data-name^="Card "]')) {
      const ps = card.querySelectorAll('p'); const title = ps[0]?.textContent.trim();
      meta[title] = meta[alias[title]] = { icon: card.querySelector('img')?.getAttribute('src'), desc: ps[1]?.textContent.trim() };
    }
  }
  return meta;
}

async function itemsScreen(routeName, screens) {
  const category = CATEGORIES.find(c => c.route === routeName) || CATEGORIES[0];
  // 카테고리 메뉴 선택 표시 (인쇄물 화면을 공통 틀로 사용)
  const nav = named('Nav')[0];
  if (nav) {
    const entries = [...nav.children].filter(e => CATEGORIES.some(c => e.textContent.includes(c.name)));
    const selected = entries.find(e => e.textContent.includes(CATEGORIES[0].name));
    const target = entries.find(e => e.textContent.includes(category.name));
    if (selected && target && selected !== target) { const cls = selected.className; selected.className = target.className; target.className = cls; }
    target?.setAttribute('aria-current', 'page');
  }

  // 카드 그리드 전체(줄 단위 Row 1~3 포함)를 비우고 API 품목으로 다시 채움
  const grid = named('Product 2-Column Grid')[0] || $('[data-name^="Card "]')?.parentElement;
  const template = grid?.querySelector('[data-name^="Card "]')?.cloneNode(true);
  const rowsHost = named('Item Rows List')[0];
  if (!grid || !template || !rowsHost) return;
  grid.replaceChildren(); grid.classList.add('lv-card-grid');
  rowsHost.replaceChildren();

  let items;
  try { items = await catalog(); }
  catch (e) { grid.innerHTML = `<p class="lv-empty">${esc(e.message)}</p>`; renderRows(); return; }
  const byId = Object.fromEntries(items.map(i => [i.item_id, i]));
  const meta = cardMeta(screens);
  const iconOf = id => meta[byId[id]?.item_name]?.icon || meta[id]?.icon || template.querySelector('img')?.getAttribute('src');

  // 카드: 백엔드 품목 목록으로 다시 그림
  for (const item of items.filter(i => i.category === category.name)) {
    const card = template.cloneNode(true);
    card.dataset.name = `Card: ${item.item_name}`;
    const ps = card.querySelectorAll('p');
    setText(ps[0], item.item_name);
    setText(ps[1], meta[item.item_name]?.desc || meta[item.item_id]?.desc || `${item.input_unit} 단위`);
    const img = card.querySelector('img'); if (img) img.src = iconOf(item.item_id);
    card.setAttribute('aria-label', `${item.item_name} 추가`);
    card.addEventListener('click', () => addItem(item));
    grid.append(card);
  }
  const search = $('[aria-label="품목 검색"]');
  if (search) {
    search.addEventListener('input', () => {
      const q = search.value.trim().toLowerCase();
      for (const card of grid.children) card.style.display = card.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
  }

  function state() { return store.get(); }
  function saveRows(rows) { store.set({ items: rows, itemsSaved: false, analysis: null, recs: null, applied: [] }); renderRows(); }
  function addItem(item) {
    const rows = state().items || [];
    if (rows.some(r => r.item_id === item.item_id)) { toast(`${item.item_name}은(는) 이미 추가했어요. 아래 목록에서 수량을 바꿔주세요.`); document.querySelector(`[data-row="${item.item_id}"] input`)?.focus(); return; }
    const variant = (item.variants || []).find(v => v.is_default)?.variant ?? item.variants?.[0]?.variant ?? null;
    rows.push({ item_id: item.item_id, quantity: null, variant, width_m: null, height_m: null, unit_price: null, delivery: false });
    saveRows(rows); toast(`${item.item_name}을(를) 추가했어요. 수량을 입력해주세요.`);
    setTimeout(() => document.querySelector(`[data-row="${item.item_id}"] input`)?.focus(), 30);
  }

  function renderRows() {
    const rows = (state().items || []).filter(r => byId[r.item_id]);
    const title = $$('p', named('Added Items Section (추가한 품목)')[0] || app).find(p => p.textContent.startsWith('추가한 품목'));
    setText(title, `추가한 품목 (${rows.length})`);
    const deliveryCount = rows.filter(r => r.delivery).length;
    const countText = $$('p').find(p => /^배송 이용 \d+ \/ \d+개 품목$/.test(p.textContent.trim()) || p.dataset.lvDeliveryCount);
    if (countText) { countText.dataset.lvDeliveryCount = '1'; setText(countText, `배송 이용 ${deliveryCount} / ${rows.length}개 품목`); }
    rowsHost.replaceChildren();
    if (!rows.length) rowsHost.innerHTML = '<p class="lv-empty">위에서 품목 카드를 눌러 추가해주세요. 모든 품목은 선택 사항이에요.</p>';
    for (const row of rows) rowsHost.append(rowElement(row, byId[row.item_id]));
    updateTotals(rows);
  }

  function rowElement(row, item) {
    const el = document.createElement('div');
    el.className = 'lv-row'; el.dataset.row = row.item_id;
    const unit = item.input_unit;
    const numberField = (key, label, value, step = '1', suffix = '') => `<label class="lv-field"><span>${label}${key !== 'unit_price' ? ' <b>*</b>' : ''}</span><span class="lv-input"><input type="number" inputmode="decimal" min="0" step="${step}" data-key="${key}" value="${value ?? ''}" placeholder="${key === 'unit_price' ? '선택' : ''}">${suffix ? `<em>${suffix}</em>` : ''}</span></label>`;
    let fields = '';
    if (item.input_method === 'dimension') {
      fields += numberField('quantity', '개수', row.quantity, '1', unit) + numberField('width_m', '가로', row.width_m, '0.1', 'm') + numberField('height_m', '세로', row.height_m, '0.1', 'm');
    } else {
      fields += numberField('quantity', '수량', row.quantity, '1', unit);
      if (item.variants?.length) {
        fields += `<label class="lv-field"><span>${item.input_method === 'count_variant' ? '규격·용량' : '종류'}</span><span class="lv-input"><select data-key="variant">${item.variants.map(v => `<option value="${esc(v.variant)}"${v.variant === row.variant ? ' selected' : ''}>${esc(v.label)}</option>`).join('')}</select></span></label>`;
      }
    }
    fields += numberField('unit_price', '단가', row.unit_price, '10', `원/${unit}`);
    el.innerHTML = `
      <div class="lv-row-name"><span class="lv-row-icon"><img alt="" src="${esc(iconOf(item.item_id))}"></span><span><strong>${esc(item.item_name)}</strong>${item.notes?.length ? `<small>${esc(item.notes.join(' · '))}</small>` : ''}</span></div>
      <div class="lv-row-fields">${fields}</div>
      <div class="lv-row-side">
        <button type="button" class="lv-chip" data-act="delivery" aria-pressed="${row.delivery}">${row.delivery ? '✓ ' : ''}배송 이용</button>
        <p class="lv-row-cost"></p>
        <button type="button" class="lv-delete" data-act="delete" aria-label="${esc(item.item_name)} 삭제">삭제</button>
      </div>`;
    const sync = () => {
      const rows = state().items || []; const r = rows.find(x => x.item_id === row.item_id); if (!r) return;
      for (const input of el.querySelectorAll('[data-key]')) {
        const k = input.dataset.key;
        r[k] = k === 'variant' ? input.value : input.value === '' ? null : Number(input.value);
      }
      store.set({ items: rows, itemsSaved: false, analysis: null, recs: null, applied: [] });
      updateRowCost(el, r); updateTotals(rows);
    };
    el.addEventListener('input', sync); el.addEventListener('change', sync);
    el.querySelector('[data-act="delete"]').addEventListener('click', () => {
      saveRows((state().items || []).filter(r => r.item_id !== row.item_id)); toast(`${item.item_name}을(를) 목록에서 지웠어요.`);
      const heading = $$('p').find(p => p.textContent.startsWith('추가한 품목'));
      if (heading) { heading.tabIndex = -1; heading.focus({ preventScroll: true }); }
    });
    el.querySelector('[data-act="delivery"]').addEventListener('click', ev => {
      const rows = state().items || []; const r = rows.find(x => x.item_id === row.item_id); r.delivery = !r.delivery;
      store.set({ items: rows, itemsSaved: false, analysis: null, recs: null, applied: [] });
      ev.currentTarget.setAttribute('aria-pressed', r.delivery); ev.currentTarget.textContent = (r.delivery ? '✓ ' : '') + '배송 이용';
      renderRows();
    });
    updateRowCost(el, row);
    return el;
  }
  function rowCost(r) { return r.unit_price != null && r.quantity ? Math.round(r.unit_price) * Math.round(r.quantity) : null; }
  function updateRowCost(el, r) { const c = rowCost(r); el.querySelector('.lv-row-cost').textContent = c == null ? '단가 미입력' : `합계 ${won(c)}`; }
  function updateTotals(rows) {
    const total = rows.reduce((s, r) => s + (rowCost(r) || 0), 0);
    const priced = rows.filter(r => rowCost(r) != null).length;
    const totalEl = $$('p').find(p => /^[\d,]+원$/.test(p.textContent.trim()) || p.dataset.lvTotal);
    if (totalEl) { totalEl.dataset.lvTotal = '1'; setText(totalEl, won(total)); }
    const deliveryNote = $$('p').find(p => p.textContent.startsWith('배송 이용 품목') || p.dataset.lvDeliveryNote);
    const delivered = rows.filter(r => r.delivery).length;
    if (deliveryNote) { deliveryNote.dataset.lvDeliveryNote = '1'; setText(deliveryNote, delivered ? `배송 이용 품목 ${delivered}개 (일반 배송 1회로 계산)` : `단가 입력 ${priced} / ${rows.length}개 품목`); }
  }

  // "배송 이용 전체 선택"
  const allToggle = named('배송 이용 전체 선택')[0];
  if (allToggle) {
    allToggle.classList.add('lv-clickable'); allToggle.setAttribute('role', 'button'); allToggle.tabIndex = 0;
    const toggleAll = () => {
      const rows = state().items || []; const on = !rows.every(r => r.delivery);
      rows.forEach(r => { r.delivery = on; });
      store.set({ items: rows, itemsSaved: false, analysis: null, recs: null, applied: [] }); renderRows();
    };
    allToggle.addEventListener('click', toggleAll);
    allToggle.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleAll(); } });
  }
  renderRows();

  // "다음으로": 품목 저장 → 분석 화면
  const next = named('Navigation Buttons')[0]?.querySelector('a[href="#/analysis"]');
  intercept(next, async () => {
    const s = state();
    if (!requireStep(s, ['event'])) return;
    const rows = (s.items || []).filter(r => byId[r.item_id]);
    if (!rows.length) { toast('품목을 하나 이상 추가해주세요.'); return; }
    const invalid = rows.find(r => !(r.quantity >= 1) || !Number.isInteger(r.quantity)
      || (byId[r.item_id].input_method === 'dimension' && !(r.width_m > 0 && r.height_m > 0)));
    if (invalid) {
      const it = byId[invalid.item_id];
      toast(it.input_method === 'dimension' && invalid.quantity >= 1 ? `${it.item_name}의 가로·세로를 입력해주세요.` : `${it.item_name}의 수량을 1 이상의 정수로 입력해주세요.`);
      document.querySelector(`[data-row="${invalid.item_id}"] input`)?.focus(); return;
    }
    const payload = rows.map(r => {
      const it = byId[r.item_id];
      const out = { item_id: r.item_id, quantity: r.quantity, unit_price: r.unit_price == null ? null : Math.round(r.unit_price) };
      if (it.variants?.length) out.variant = r.variant;
      if (it.input_method === 'dimension') { out.width_m = r.width_m; out.height_m = r.height_m; }
      return out;
    });
    if (rows.some(r => r.delivery) && byId.delivery) payload.push({ item_id: 'delivery' });
    busy(next, true, '저장 중…');
    try {
      await api('PUT', `/events/${s.eventId}/items`, { items: payload });
      store.set({ itemsSaved: true, analysis: null, recs: null, applied: [] });
      go('analysis');
    } catch (e) {
      busy(next, false);
      if (e.code === 'EVENT_NOT_FOUND') { store.set({ eventId: null }); toast(e.message); go('event'); return; }
      toast(e.message);
    }
  });
}

// ---------------------------------------------------------------- 3. 분석 결과
async function analysisScreen() {
  const s = store.get();
  if (!requireStep(s, ['event', 'items', 'saved'])) return;
  const content = named('Content')[0];
  content?.classList.add('lv-loading');
  let a;
  try {
    a = await api('POST', `/events/${s.eventId}/analyze`);
    store.set({ analysis: a });
  } catch (e) {
    content?.classList.remove('lv-loading'); toast(e.message);
    if (e.code === 'EVENT_NOT_FOUND') { store.set({ eventId: null }); go('event'); }
    return;
  }
  content?.classList.remove('lv-loading');
  const byItem = a.by_item || [];
  const nameOf = id => byItem.find(i => i.item_id === id)?.item_name || id;

  // 총 배출량 카드
  const total = named('Card / Total')[0];
  if (total) {
    setText($('[data-name="Value"] p', total), kg(a.total_emission));
    const t = trees(a.total_emission);
    const treeIcons = named('Tree', total);
    treeIcons.forEach((e, i) => { e.style.display = i < Math.min(6, Math.max(1, Math.round(t))) ? '' : 'none'; });
    const eq = $('[data-name="Equivalent"] p', total);
    setText(eq, `소나무 약 ${fmt(t, t < 10 ? 1 : 0)}그루가 1년 동안 흡수하는 양과 같아요. · 1인당 ${fmt(a.emission_per_person, 2)} kgCO₂e`);
  }

  // 인사이트
  const insight = named('Card / Insight')[0];
  if (insight) {
    const ps = [...($('[data-node-id="7:93"]', insight)?.querySelectorAll('p') || []), $('[data-node-id="7:94"]', insight)];
    const top = (a.top_items || []).slice(0, 3);
    setText(ps[0], `상위 ${top.length}개 품목이 전체 배출량의`);
    setText(ps[1], `${fmt(a.top_items_share ?? 0, 0)}%를 차지하고 있어요`);
    setText(ps[2], `${top.map(nameOf).join(' · ')}만 조정해도 큰 감축 효과를 기대할 수 있어요.`);
    ['Top 1', 'Top 2', 'Top 3'].forEach((n, i) => {
      const chip = named(n, insight)[0]; if (!chip) return;
      if (!top[i]) { chip.style.display = 'none'; return; }
      setText(chip.querySelectorAll('p')[1], nameOf(top[i]));
    });
  }

  // 품목별 막대 (상위 5개 + 기타)
  const bars = named('Bars')[0];
  if (bars) {
    const tpl = bars.querySelector('[data-name^="Bar / "]').cloneNode(true);
    bars.replaceChildren();
    const sorted = [...byItem].sort((x, y) => y.emission - x.emission);
    const shown = sorted.slice(0, 5);
    const rest = sorted.slice(5);
    if (rest.length) shown.push({ item_name: '기타', emission: rest.reduce((s2, i) => s2 + i.emission, 0), ratio: rest.reduce((s2, i) => s2 + (i.ratio || 0), 0), category: '기타' });
    const max = Math.max(...shown.map(i => i.emission), 0.0001);
    for (const item of shown) {
      const bar = tpl.cloneNode(true);
      bar.dataset.name = `Bar / ${item.item_name}`;
      setText(bar.querySelector('[data-name="품목 라벨 + 산정 기준"] p'), item.item_name);
      const badge = bar.querySelector('[data-name^="배지"]');
      if (badge) { if (item.variant_label) setText(badge.querySelector('p'), item.variant_label); else badge.style.display = 'none'; }
      const fill = bar.querySelector('[data-name="Track"] [data-name="Rectangle"]');
      if (fill) { fill.style.width = `${Math.max(2, item.emission / max * 100)}%`; fill.style.background = categoryOf(item.category).color; }
      const vals = bar.querySelectorAll('[data-name="Frame"] p');
      setText(vals[0], kg(item.emission)); setText(vals[1], `(${fmt(item.ratio ?? 0, 0)}%)`);
      bars.append(bar);
    }
  }

  // 카테고리 도넛
  const donutCard = named('Card / Donut')[0];
  if (donutCard) {
    const cats = a.by_category || [];
    const donut = named('Donut', donutCard)[0];
    if (donut) {
      let acc = 0; const stops = [];
      for (const c of cats) { const r = c.ratio ?? 0; stops.push(`${categoryOf(c.category).color} ${acc}% ${acc + r}%`); acc += r; }
      donut.innerHTML = `<div class="lv-donut" style="background:conic-gradient(${stops.join(',') || '#e5e7eb 0 100%'})"><div><strong>${kg(a.total_emission)}</strong><span>kgCO₂e</span></div></div>`;
    }
    const legend = named('Legend', donutCard)[0];
    if (legend) {
      legend.innerHTML = cats.map(c => `<div class="lv-legend"><i style="background:${categoryOf(c.category).color}"></i><span>${esc(c.category)}</span><b>${fmt(c.ratio ?? 0, 0)}%</b></div>`).join('');
    }
  }

  // 비용 합계
  const cost = named('비용 합계 / 단가 미입력 제외')[0];
  if (cost) {
    const info = cost.querySelectorAll('[data-name="비용 합계 정보"] p');
    setText(info[1], a.total_cost == null || !a.priced_item_count ? '입력된 단가 없음' : won(a.total_cost) + (a.budget_usage_rate != null ? ` (예산의 ${fmt(a.budget_usage_rate, 1)}%)` : ''));
    const note = cost.querySelectorAll('[data-name="비용 제외 안내"] p');
    const unpriced = byItem.filter(i => i.cost == null && i.item_id !== 'delivery').length;
    setText(note[0], unpriced ? `비용 미입력 ${unpriced}개 품목 제외` : '모든 품목 단가 입력됨');
  }
  if (a.warnings?.length) {
    const title = named('Title')[0];
    if (title && !title.querySelector('.lv-warning')) title.insertAdjacentHTML('beforeend', `<p class="lv-warning">참고: ${esc(a.warnings.join(' · '))}</p>`);
  }
}

// ---------------------------------------------------------------- 4. AI 추천
function goalKeyFrom(el) {
  const n = el?.dataset.name || '';
  return n.includes('20%') ? 'carbon20' : n.includes('품질') ? 'quality' : n.includes('직접') ? 'custom' : 'budget';
}
export function customGoal(text, keepBudget) {
  store.set({ customGoal: { text, keepBudget } });
  if (location.hash.includes('recommend')) recommendScreen({ goalKey: 'custom', force: true });
}

async function recommendScreen({ goalKey, force } = {}) {
  const s = store.get();
  if (!requireStep(s, ['event', 'items', 'saved'])) return;
  goalKey = goalKey || s.goalKey || 'budget';
  if (goalKey === 'custom' && !s.customGoal?.text) goalKey = 'budget';
  store.set({ goalKey });

  // 개선 방향 카드 선택 표시 + 클릭 시 새로 추천
  for (const card of $$('[data-name^="Goal / "]')) {
    const key = goalKeyFrom(card);
    card.classList.toggle('selected-goal', key === goalKey);
    if (!card.dataset.lvBound && key !== 'custom') {
      card.dataset.lvBound = '1';
      card.addEventListener('click', () => recommendScreen({ goalKey: key }));
    }
  }
  for (const c of $$('[data-name="Chip"] p')) if (/기준|우선/.test(c.textContent)) c.textContent = GOALS[goalKey].label;

  const list = named('Card / Recommendations')[0];
  const head = list && named('Head', list)[0];
  const tplSource = list?.querySelector('[data-name="Recommendation 2"]') || list?.querySelector('[data-name^="Recommendation "]');
  if (!list || !tplSource) return;
  const tpl = recommendScreen.tpl || (recommendScreen.tpl = tplSource.cloneNode(true));
  const more = named('More')[0]; if (more) more.style.display = 'none';
  const clear = () => { for (const r of $$('[data-name^="Recommendation "], .lv-message', list)) r.remove(); };
  const message = (html) => { clear(); head.insertAdjacentHTML('afterend', `<div class="lv-message">${html}</div>`); };

  let recs = s.recs && s.recs.goalKey === goalKey && !force ? s.recs : null;
  if (!recs) {
    message('<span class="lv-spinner"></span> AI가 행사에 맞는 저탄소 대안을 찾고 있어요…');
    const goal = goalKey === 'custom'
      ? { budget_increase_allowed: !s.customGoal.keepBudget, preserve_event_quality: true, custom_condition: s.customGoal.text.slice(0, 300) }
      : GOALS[goalKey].goal;
    try {
      const res = await api('POST', `/events/${s.eventId}/recommend`, { goal });
      recs = { goalKey, list: res.recommendations, empty: res.empty_reason };
      store.set({ recs, applied: [] });
    } catch (e) {
      message(`${esc(e.message)} <button type="button" class="lv-retry">다시 시도</button>`);
      list.querySelector('.lv-retry')?.addEventListener('click', () => recommendScreen({ goalKey, force: true }));
      return;
    }
  }
  const units = Object.fromEntries((await catalog().catch(() => [])).map(i => [i.item_id, i.input_unit]));
  clear();
  if (!recs.list.length) {
    message(recs.empty === 'ALL_FILTERED' ? '조건에 맞는 대안이 없어요. 다른 개선 방향을 선택해보세요.' : '추천할 수 있는 대안이 없어요. 품목이나 수량을 바꿔 다시 시도해보세요.');
  }
  let anchor = head;
  // 적용 가능한 대안 먼저, 감축 효과가 큰 순서로
  const ordered = [...recs.list].sort((x, y) => (y.applicable - x.applicable) || (y.emission_reduction - x.emission_reduction));
  ordered.forEach((rec, i) => {
    const row = tpl.cloneNode(true);
    row.dataset.name = `Recommendation ${i + 1}`;
    const direct = [...row.children];
    setText(direct.find(e => e.tagName === 'P'), String(i + 1));
    setText($('[data-name="Tile"] p', row), categoryOf(rec.category).short);
    const text = $('[data-name="Text"]', row);
    const tps = text ? [...text.querySelectorAll(':scope > p')] : [];
    setText(tps[0], rec.title);
    setText(tps[1], `${changeSummary(rec, units[rec.item_id])} · ${rec.reason}`);
    const chips = text ? text.querySelectorAll('[data-name="Chip"] p') : [];
    setText(chips[0], rec.cost_change == null ? '비용 변화 미입력' : `비용 ${rec.cost_change > 0 ? '+' : rec.cost_change < 0 ? '−' : ''}${fmt(Math.abs(rec.cost_change))}원`);
    setText(chips[1], `난이도 ${rec.difficulty}`);
    const red = $('[data-name="Reduction"] [data-name="Frame"] p', row);
    setText(red, minus(rec.emission_reduction));
    const oldBtn = row.querySelector('button, [data-name^="Button / "]');
    const btn = document.createElement('button');
    btn.type = 'button'; btn.className = (oldBtn?.className || '') + ' ui-control lv-apply'; btn.dataset.rec = rec.rec_id;
    if (!rec.applicable) { btn.disabled = true; btn.textContent = NOT_APPLICABLE[rec.not_applicable_reason] ? '적용 불가' : '적용 불가'; btn.title = NOT_APPLICABLE[rec.not_applicable_reason] || ''; }
    btn.addEventListener('click', () => {
      const applied = new Set(store.get().applied || []);
      applied.has(rec.rec_id) ? applied.delete(rec.rec_id) : applied.add(rec.rec_id);
      store.set({ applied: [...applied] }); paintApply(); summary();
    });
    oldBtn ? oldBtn.replaceWith(btn) : row.append(btn);
    anchor.after(row); anchor = row;
  });
  paintApply(); summary();

  function paintApply() {
    const applied = new Set(store.get().applied || []);
    for (const b of $$('.lv-apply', list)) {
      if (b.disabled) continue;
      const on = applied.has(b.dataset.rec);
      b.classList.toggle('lv-applied', on); b.setAttribute('aria-pressed', on);
      b.textContent = on ? '✓ 적용됨' : '적용하기';
    }
  }
  function summary() {
    const applied = new Set(store.get().applied || []);
    const chosen = recs.list.filter(r => applied.has(r.rec_id));
    const sum = chosen.reduce((t, r) => t + r.emission_reduction, 0);
    const cost = chosen.reduce((t, r) => t + (r.cost_change || 0), 0);
    const box = named('Summary')[0];
    if (box) {
      const ps = box.querySelectorAll('p');
      setText(ps[0], `${chosen.length}개 적용됨`);
      setText(ps[ps.length - 1], chosen.length ? `예상 감축 ${minus(sum)} kgCO₂e · 비용 변화 ${cost > 0 ? '+' : cost < 0 ? '−' : ''}${fmt(Math.abs(cost))}원` : '적용할 대안을 선택해주세요.');
    }
  }
  const compare = named('Footer')[0]?.querySelector('a[href="#/report"]');
  if (compare && !compare.dataset.lvBound) {
    compare.dataset.lvBound = '1';
    intercept(compare, () => {
      if (!(store.get().applied || []).length) { toast('적용할 개선안을 하나 이상 선택해주세요.'); return; }
      go('report');
    });
  }
}

// ---------------------------------------------------------------- 5. 리포트
async function reportScreen() {
  const s = store.get();
  if (!requireStep(s, ['event', 'items', 'saved'])) return;
  if (!(s.applied || []).length || !s.recs) { toast('AI 추천에서 적용할 개선안을 먼저 골라주세요.'); go('recommend'); return; }
  let r;
  try { r = await api('POST', `/events/${s.eventId}/compare`, { applied_rec_ids: s.applied }); }
  catch (e) {
    toast(e.message);
    if (e.code === 'STALE_DATA' || e.code === 'REC_NOT_FOUND') { store.set({ recs: null, applied: [] }); go('recommend'); }
    return;
  }
  const units = Object.fromEntries((await catalog().catch(() => [])).map(i => [i.item_id, i.input_unit]));
  const rate = r.reduction_rate ?? 0;

  const kpi1 = named('KPI / 탄소배출량')[0];
  if (kpi1) {
    const v = kpi1.querySelectorAll('[data-name="Value"] > p');
    setText(v[0], kg(r.before.total_emission)); setText(v[2], kg(r.after.total_emission));
    setText($('[data-name="Chip"] p', kpi1), `▼ ${fmt(rate, 1)}% 감소`);
  }
  const kpi2 = named('KPI / 예상 비용')[0];
  if (kpi2) {
    const v = kpi2.querySelectorAll('[data-name="Value"] > p');
    const b = r.before.total_cost, af = r.after.total_cost;
    setText(v[0], b == null ? '-' : fmt(b)); setText(v[2], af == null ? '-' : fmt(af));
    const chip = $('[data-name="Chip"] p', kpi2);
    if (b == null || af == null) setText(chip, '단가 입력 품목만 계산');
    else if (af < b) setText(chip, `▼ ${fmt((b - af) / b * 100, 1)}% 절감`);
    else if (af > b) setText(chip, `▲ ${fmt((af - b) / (b || 1) * 100, 1)}% 증가`);
    else setText(chip, '비용 변화 없음');
  }
  const kpi3 = named('KPI / 감축량')[0];
  if (kpi3) {
    setText($('[data-name="Value row"] [data-name="Frame"] p', kpi3), kg(r.reduction));
    const t = trees(r.reduction);
    setText([...kpi3.querySelectorAll(':scope > p')].pop(), `소나무 약 ${fmt(t, t < 10 ? 1 : 0)}그루가 1년 동안 흡수하는 양이에요.`);
  }

  // 품목별 비교 막대 (바뀐 품목 우선, 최대 6개)
  const chart = named('Chart')[0];
  if (chart) {
    const tpl = chart.querySelector('[data-name^="Group / "]').cloneNode(true);
    const rows = [...r.item_comparison].sort((x, y) => (y.changed - x.changed) || (y.before_emission - x.before_emission)).slice(0, 6);
    const max = Math.max(...rows.flatMap(i => [i.before_emission, i.after_emission]), 0.0001);
    chart.replaceChildren();
    for (const it of rows) {
      const g = tpl.cloneNode(true); g.dataset.name = `Group / ${it.item_name}`;
      const frames = g.querySelectorAll('[data-name="Bars"] > [data-name="Frame"]');
      [[frames[0], it.before_emission], [frames[1], it.after_emission]].forEach(([f, val]) => {
        if (!f) return; setText(f.querySelector('p'), kg(val));
        const rect = f.querySelector('[data-name="Rectangle"]'); if (rect) rect.style.height = `${Math.max(2, val / max * 150)}px`;
      });
      setText([...g.children].find(e => e.tagName === 'P'), it.after_item_name && it.after_item_name !== it.item_name ? `${it.item_name}→${it.after_item_name}` : it.item_name);
      chart.append(g);
    }
  }

  // 적용된 개선 사항
  const appliedCard = named('Card / Applied')[0];
  if (appliedCard) {
    const recs = s.recs.list.filter(x => s.applied.includes(x.rec_id));
    const tpl = appliedCard.querySelector('[data-name^="Applied / "]').cloneNode(true);
    for (const e of appliedCard.querySelectorAll('[data-name^="Applied / "]')) e.remove();
    const spacer = named('Spacer', appliedCard)[0] || named('Total', appliedCard)[0];
    for (const rec of recs) {
      const el = tpl.cloneNode(true); el.dataset.name = `Applied / ${rec.title}`;
      const frames = el.querySelectorAll(':scope > [data-name="Frame"]');
      setText(frames[0]?.querySelector('p'), categoryOf(rec.category).short);
      const tp = frames[1]?.querySelectorAll('p') || [];
      setText(tp[0], rec.title); setText(tp[1], changeSummary(rec, units[rec.item_id]));
      setText([...el.children].find(e => e.tagName === 'P'), minus(rec.emission_reduction));
      spacer ? spacer.before(el) : appliedCard.append(el);
    }
    const chip = $('[data-name="Frame"] [data-name="Chip"] p', appliedCard); setText(chip, `${recs.length}개`);
    const totalP = named('Total', appliedCard)[0]?.querySelectorAll('p');
    if (totalP?.[1]) totalP[1].innerHTML = `${minus(r.reduction)} kgCO<sub>2</sub>e`;
  }

  // 하단 배너
  const banner = named('Carbon Report')[0];
  if (banner) {
    const headline = $$('p', banner).find(p => p.textContent.includes('줄일 수 있어요'));
    if (headline) {
      const hl = headline.querySelectorAll('span')[1]?.className || '';
      headline.innerHTML = `이번 행사에서 탄소배출량을 <span class="${hl}">${fmt(rate, 1)}%</span> 줄일 수 있어요.`;
    }
    const sub = $$('p', banner).find(p => p.textContent.includes('예산은') || p.dataset.lvSub);
    if (sub) {
      sub.dataset.lvSub = '1';
      const c = r.cost_change;
      setText(sub, c == null ? '단가를 입력한 품목 기준으로 비용을 계산했어요.' : c < 0 ? `예산은 ${fmt(-c)}원 절감하면서, 더 지속가능한 행사를 만들 수 있어요.` : c === 0 ? '예산은 그대로 유지하면서, 더 지속가능한 행사를 만들 수 있어요.' : `비용이 ${fmt(c)}원 늘지만, 더 지속가능한 행사를 만들 수 있어요.`);
    }
  }
  const restart = $$('a, button', app).find(e => e.textContent.includes('처음으로'));
  restart?.addEventListener('click', () => store.reset());
}

// ---------------------------------------------------------------- 진입점
export function onScreen(name, screens) {
  if (name === 'event') eventScreen();
  else if (name.startsWith('items-')) itemsScreen(name, screens);
  else if (name === 'analysis') analysisScreen();
  else if (name === 'recommend' || name === 'recommend-more') recommendScreen();
  else if (name === 'report') reportScreen();
}
