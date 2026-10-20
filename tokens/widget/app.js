const SNAP_SAME = '../../data/tokens.json';
const SNAP_RAW = 'https://raw.githubusercontent.com/jehyunlee/dashboards/data/data/tokens.json';
const MB_SAME = '../../data/gjc_macbook.json';
const MB_RAW = 'https://raw.githubusercontent.com/jehyunlee/dashboards/data/data/gjc_macbook.json';
const VISIBLE = 288;
const $ = (id) => document.getElementById(id);

function ageMs(iso){ const t = Date.parse(iso || ''); return Number.isFinite(t) ? Date.now() - t : Infinity; }
function fmtAge(ms){ if(!Number.isFinite(ms)) return 'unknown'; const s=Math.max(0,Math.round(ms/1000)); if(s<90) return `${s}s ago`; const m=Math.round(s/60); if(m<90) return `${m}m ago`; const h=Math.round(m/60); return `${h}h ago`; }
function cls(status){ return ['ok','tracking'].includes(status) ? 'ok' : ['missing','rate_limited','warn','unknown'].includes(status) ? 'warn' : 'bad'; }
function escapeHtml(s){ return String(s ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])); }
function statusText(status){ return ({ok:'tracking', tracking:'tracking', missing:'missing', auth_error:'auth error', rate_limited:'rate limited', provider_error:'provider error', error:'error', warn:'warn', unknown:'unknown'})[status] || status || 'unknown'; }

function fmtCompact(n){
  const x = Number(n);
  if(!Number.isFinite(x)) return '—';
  if(x >= 1e9) return (x/1e9).toFixed(x>=1e10?0:1)+'B';
  if(x >= 1e6) return (x/1e6).toFixed(x>=1e7?0:1)+'M';
  if(x >= 1e3) return (x/1e3).toFixed(x>=1e4?0:1)+'K';
  return String(Math.round(x));
}
function fmtMoney(n){ const x=Number(n); return Number.isFinite(x) ? '$'+x.toLocaleString('en-US',{maximumFractionDigits:x>=100?0:2}) : '—'; }
function lastN(arr, n){ return (arr || []).slice(Math.max(0, (arr || []).length - n)); }

async function fetchOne(url){
  const r = await fetch(`${url}?t=${Date.now()}`, {cache:'no-store'});
  if(!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
async function newestOf(urls){
  const results = await Promise.allSettled(urls.map(fetchOne));
  const ok = results.filter(r => r.status === 'fulfilled').map(r => r.value).filter(Boolean);
  if(!ok.length) throw new Error(results.map(r => r.reason?.message || String(r.reason)).join('; '));
  ok.sort((a,b) => (Date.parse(b.updated_at || 0) || 0) - (Date.parse(a.updated_at || 0) || 0));
  return ok[0];
}

function mergeSeries(base, over){
  if(!over || !over.available) return base;
  if(!base || !base.available) return over;
  const bmap = new Map((base.points || []).map(p => [p.t, Number(p.tokens) || 0]));
  const omap = new Map((over.points || []).map(p => [p.t, Number(p.tokens) || 0]));
  const grid = (over.points && over.points.length >= (base.points || []).length) ? over.points : base.points;
  let total = 0;
  const points = (grid || []).map(p => {
    const v = Math.max(bmap.get(p.t) || 0, omap.get(p.t) || 0);
    total += v;
    return {t: p.t, tokens: v};
  });
  return {...base, ...over, available: true, points, window_tokens: total};
}
function applyMacbookOverlay(d, mb){
  if(!d || !mb || !mb.providers) return d;
  if(Date.parse(mb.updated_at || 0) > Date.parse(d.updated_at || 0)) d.updated_at = mb.updated_at;
  for(const p of (d.providers || [])){
    const mp = mb.providers[p.id];
    if(!mp) continue;
    if(mp.subscription_series) p.subscription_series = mergeSeries(p.subscription_series, mp.subscription_series);
    if(mp.usage_series) p.usage_series = mergeSeries(p.usage_series, mp.usage_series);
    if(p.id === 'gemini' && mp.billing && mp.billing.available) p.billing = mp.billing;
  }
  return d;
}
function spark(series){
  const points = lastN((series && series.available && series.points) ? series.points : [], VISIBLE);
  if(!points.length) return '<p class="note">최근 24시간 사용 표본 없음</p>';
  const vals = points.map(p => Number(p.tokens) || 0);
  const max = Math.max(1, ...vals);
  return `<div class="spark">${points.map((p, i) => {
    const v = vals[i];
    const h = v <= 0 ? 2 : Math.max(4, Math.round(v / max * 30));
    return `<span class="bar ${v <= 0 ? 'zero' : ''}" style="height:${h}px" title="${escapeHtml(p.t)} · ${fmtCompact(v)} tokens"></span>`;
  }).join('')}</div>`;
}
function seriesTotal(series){
  const points = lastN((series && series.available && series.points) ? series.points : [], VISIBLE);
  return points.reduce((sum, p) => sum + (Number(p.tokens) || 0), 0);
}

function renderProvider(p){
  const billing = p.billing || {};
  const usage = billing.usage || {};
  const api24h = seriesTotal(p.usage_series);
  const sub24h = seriesTotal(p.subscription_series);
  const hasSub = !!p.subscription_series;
  const cost = billing.month_to_date_cost;
  const status = cls(p.status);
  return `<article class="provider provider-${escapeHtml(p.id)}">
    <div class="provider-head">
      <h2>${escapeHtml(p.label || p.id)}</h2>
      <span class="badge ${status}">${escapeHtml(statusText(p.status))}</span>
    </div>
    <div class="row">
      <div class="metric"><span>30d API</span><b>${fmtCompact(usage.total_tokens)} tokens</b></div>
      <div class="metric"><span>Cost</span><b>${fmtMoney(cost)}</b></div>
    </div>
    <div class="metric"><span>API 24h</span><b>${fmtCompact(api24h)} tokens</b></div>
    ${spark(p.usage_series)}
    ${hasSub ? `<div class="metric"><span>CLI subscription 24h</span><b>${fmtCompact(sub24h)} tokens</b></div>${spark(p.subscription_series)}` : ''}
  </article>`;
}

async function refresh(){
  try{
    const [rawSnap, mb] = await Promise.all([
      newestOf([SNAP_SAME, SNAP_RAW]),
      newestOf([MB_SAME, MB_RAW]).catch(() => null),
    ]);
    const d = applyMacbookOverlay(rawSnap, mb);
    const age = ageMs(d.updated_at);
    const stale = age > 30 * 60 * 1000;
    const overall = stale ? 'warn' : (d.overall || 'unknown');
    $('widget').className = `widget status-${cls(overall)}`;
    $('title').textContent = overall === 'ok' ? 'Token usage telemetry' : overall === 'warn' ? 'Token data stale' : 'Token data unavailable';
    $('detail').textContent = `${d.summary || ''} · ${fmtAge(age)}${stale ? ' · stale' : ''}`;
    $('updatedAt').textContent = d.updated_at ? new Date(d.updated_at).toLocaleString([], {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}) : 'not updated';
    $('providers').innerHTML = (d.providers || []).map(renderProvider).join('') || '<div class="empty">No providers found.</div>';
  }catch(err){
    $('widget').className = 'widget status-bad';
    $('title').textContent = 'Token data unavailable';
    $('detail').textContent = String(err);
    $('providers').innerHTML = '';
  }
}
refresh();
setInterval(refresh, 60000);
