const SNAP_SAME = '../../data/tokens.json';
const SNAP_RAW = 'https://raw.githubusercontent.com/jehyunlee/dashboards/data/data/tokens.json';
const VISIBLE = 36;
const $ = (id) => document.getElementById(id);

function ageMs(iso){ const t = Date.parse(iso || ''); return Number.isFinite(t) ? Date.now() - t : Infinity; }
function fmtAge(ms){ if(!Number.isFinite(ms)) return 'unknown'; const s=Math.max(0,Math.round(ms/1000)); if(s<90) return `${s}s ago`; const m=Math.round(s/60); if(m<90) return `${m}m ago`; const h=Math.round(m/60); return `${h}h ago`; }
function cls(status){ return status === 'ok' ? 'ok' : ['missing','rate_limited','warn','unknown'].includes(status) ? 'warn' : 'bad'; }
function escapeHtml(s){ return String(s ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])); }
function statusText(status){ return ({ok:'connected', missing:'missing', auth_error:'auth error', rate_limited:'rate limited', provider_error:'provider error', error:'error', unknown:'unknown'})[status] || status || 'unknown'; }

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

function spark(series){
  const points = lastN((series && series.available && series.points) ? series.points : [], VISIBLE);
  if(!points.length) return '<p class="note">최근 6시간 사용 표본 없음</p>';
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
  const windowTokens = p.token_window?.tokens || {};
  const api6h = seriesTotal(p.usage_series);
  const sub6h = seriesTotal(p.subscription_series);
  const hasSub = p.id !== 'gemini' && p.subscription_series;
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
    <div class="metric"><span>API 6h</span><b>${fmtCompact(api6h)} tokens</b></div>
    ${spark(p.usage_series)}
    ${hasSub ? `<div class="metric"><span>CLI subscription 6h</span><b>${fmtCompact(sub6h)} tokens</b></div>${spark(p.subscription_series)}` : ''}
    ${windowTokens.remaining ? `<p class="note">rate window remaining ${fmtCompact(windowTokens.remaining)} / ${fmtCompact(windowTokens.limit)}</p>` : ''}
  </article>`;
}

async function refresh(){
  try{
    const d = await newestOf([SNAP_SAME, SNAP_RAW]);
    const age = ageMs(d.updated_at);
    const stale = age > 30 * 60 * 1000;
    const overall = stale ? 'warn' : (d.overall || 'unknown');
    $('widget').className = `widget status-${cls(overall)}`;
    $('title').textContent = overall === 'ok' ? 'APIs connected' : overall === 'warn' ? 'Token status stale' : 'Provider check failing';
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
