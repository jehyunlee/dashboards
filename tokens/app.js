const SNAP_SAME = '../data/tokens.json';
const SNAP_RAW = 'https://raw.githubusercontent.com/jehyunlee/dashboards/data/data/tokens.json';
const HIST_SAME = '../data/tokens_history.json';
const HIST_RAW = 'https://raw.githubusercontent.com/jehyunlee/dashboards/data/data/tokens_history.json';
const VISIBLE = 72; // 72 ticks x 5 min = last 6 hours
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
function fmtFull(n){ const x=Number(n); return Number.isFinite(x) ? x.toLocaleString('en-US') : '—'; }

async function fetchOne(url){
  const r = await fetch(`${url}?t=${Date.now()}`, {cache:'no-store'});
  if(!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
async function newestOf(urls, keyer){
  const results = await Promise.allSettled(urls.map(fetchOne));
  const ok = results.filter(r => r.status === 'fulfilled').map(r => r.value).filter(Boolean);
  if(!ok.length) throw new Error(results.map(r => r.reason?.message || String(r.reason)).join('; '));
  ok.sort((a,b) => keyer(b) - keyer(a));
  return ok[0];
}
const fetchSnapshot = () => newestOf([SNAP_SAME, SNAP_RAW], d => Date.parse(d.updated_at || 0) || 0);
const fetchHistory = async () => {
  try { return await newestOf([HIST_SAME, HIST_RAW], d => (d.samples || []).length); }
  catch { return {samples: []}; }
};

function lastN(arr, n){ return arr.slice(Math.max(0, arr.length - n)); }

function usageBars(samples, pid, field, mode){
  let values;
  if(mode === 'delta'){
    const full = samples.map(s => (s[pid] || {})[field]);
    const deltas = full.map((v, i) => {
      if(i === 0) return null;
      const pv = full[i-1], cv = v;
      if(pv === null || pv === undefined || cv === null || cv === undefined) return null;
      const a = Number(pv), b = Number(cv);
      if(!Number.isFinite(a) || !Number.isFinite(b)) return null;
      return Math.max(0, b - a);
    });
    values = lastN(deltas, VISIBLE);
  } else {
    values = lastN(samples, VISIBLE).map(s => {
      const v = (s[pid] || {})[field];
      return (v === null || v === undefined) ? null : Number(v);
    });
  }
  const visSamples = lastN(samples, VISIBLE);
  const nums = values.filter(v => Number.isFinite(v));
  if(!nums.length) return null;
  const max = Math.max(1, ...nums);
  const total = nums.reduce((a, b) => a + b, 0);
  const bars = values.map((v, i) => {
    if(!Number.isFinite(v)) return '<span class="bar na" title="no sample"></span>';
    const h = v <= 0 ? 0 : Math.max(3, Math.round(v / max * 100));
    const when = visSamples[i]?.t || '';
    return `<span class="bar" style="height:${h}%" title="${escapeHtml(when)}: ${fmtFull(v)} tokens"></span>`;
  }).join('');
  return {max, total, html:`
    <div class="chart">
      <div class="yaxis"><span>${fmtCompact(max)}</span><span>${fmtCompact(max/2)}</span><span>0</span></div>
      <div class="plot">${bars}</div>
    </div>`};
}

function seriesBars(series){
  const points = (series && series.points) || [];
  if(!points.length) return null;
  const vals = points.map(p => Number(p.tokens) || 0);
  const max = Math.max(1, ...vals);
  const total = vals.reduce((a, b) => a + b, 0);
  const bars = points.map(p => {
    const v = Number(p.tokens) || 0;
    const h = v <= 0 ? 0 : Math.max(3, Math.round(v / max * 100));
    return `<span class="bar" style="height:${h}%" title="${escapeHtml(p.t)}: ${fmtFull(v)} tokens"></span>`;
  }).join('');
  return {max, total, html:`
    <div class="chart">
      <div class="yaxis"><span>${fmtCompact(max)}</span><span>${fmtCompact(max/2)}</span><span>0</span></div>
      <div class="plot">${bars}</div>
    </div>`};
}

function renderProvider(p, samples){
  const subS = (p.subscription_series && p.subscription_series.available) ? p.subscription_series : null;
  const sub = seriesBars(subS);
  const subConfigured = !!(p.subscription_series);
  const geminiEol = p.id === 'gemini';
  const subMeta = sub
    ? `최근 6h ${fmtCompact(sub.total)} tokens${subS.window_cost ? ' · $'+subS.window_cost : ''}`
    : (geminiEol ? '개인 CLI 티어 종료' : (subConfigured ? '최근 6h 사용 없음' : '텔레메트리 미설정'));
  const subChart = sub
    ? sub.html
    : `<p class="nodata">${geminiEol
        ? 'Gemini 개인 CLI 구독 종료 (Google → Antigravity 이전) · 구독 사용량 소스 없음'
        : (subConfigured ? '최근 6시간 구독 사용 없음 (Claude Code/Codex OTel 대기 중)' : '구독 텔레메트리 미설정 — 이 provider는 CLI 구독 사용량이 없음')}</p>`;

  const apiS = (p.usage_series && p.usage_series.available) ? p.usage_series : null;
  const api = seriesBars(apiS);
  const billing = p.billing || {};
  const u = billing.usage || {};
  const apiMeta = u.available
    ? `30일 ${fmtCompact(u.total_tokens)}${billing.month_to_date_cost !== undefined ? ' · $'+billing.month_to_date_cost : ''}${api ? ' · 최근 6h '+fmtCompact(api.total) : ''}`
    : (api ? `최근 6h ${fmtCompact(api.total)} tokens (파이프라인 계측)` : 'API usage 미연결');
  const apiChart = api
    ? api.html
    : `<p class="nodata">${apiS ? '최근 6시간 API(종량제) 사용 없음' : 'API usage admin API 미연결'}</p>`;

  // Gemini has no usable subscription CLI (Google discontinued the individual
  // gemini CLI tier), so its panel shows only connection + metered API usage.
  const showSub = p.id !== 'gemini';
  const subLabel = p.id === 'openai' ? 'Codex 구독 토큰 사용량' : p.id === 'anthropic' ? 'Claude Code 구독 토큰 사용량' : '구독 토큰 사용량';
  const subBlock = showSub ? `
    <div class="series">
      <div class="series-head"><span>${subLabel} · 5분</span><em>${escapeHtml(subMeta)}</em></div>
      ${subChart}
    </div>` : '';
  return `<article class="card provider provider-${escapeHtml(p.id)}">
    <div class="card-head"><h3>${escapeHtml(p.label || p.id)}</h3><span class="badge ${cls(p.status)}">${escapeHtml(statusText(p.status))}</span></div>${subBlock}
    <div class="series">
      <div class="series-head"><span>API 토큰 사용량 (종량제) · 5분</span><em>${escapeHtml(apiMeta)}</em></div>
      ${apiChart}
    </div>
  </article>`;
}

function eventLine(e){ return `${e.time || ''} — ${e.message || JSON.stringify(e)}`; }

async function refresh(){
  try{
    const [d, hist] = await Promise.all([fetchSnapshot(), fetchHistory()]);
    const samples = hist.samples || [];
    const age = ageMs(d.updated_at);
    const stale = age > 30 * 60 * 1000;
    const overall = stale ? 'warn' : (d.overall || 'unknown');
    $('hero').className = `hero status-${cls(overall)}`;
    $('overallTitle').textContent = overall === 'ok' ? 'Token usage telemetry' : overall === 'warn' ? 'Token data stale' : 'Token data unavailable';
    $('overallDetail').textContent = `${d.summary || ''} · ${samples.length} samples · last update ${fmtAge(age)}${stale ? ' · stale' : ''}`;
    $('updatedAt').textContent = d.updated_at ? `updated ${new Date(d.updated_at).toLocaleString()}` : '—';
    $('providers').innerHTML = (d.providers || []).map(p => renderProvider(p, samples)).join('') || '<article class="card"><p>No providers found.</p></article>';
    const events = (d.events || []).slice(-12).reverse();
    $('events').innerHTML = events.length ? events.map(e => `<li>${escapeHtml(eventLine(e))}</li>`).join('') : '<li>No recent events.</li>';
  }catch(err){
    $('hero').className = 'hero status-bad';
    $('overallTitle').textContent = 'Token status unavailable';
    $('overallDetail').textContent = String(err);
  }
}
refresh();
setInterval(refresh, 60000);
