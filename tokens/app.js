const DATA_URL = 'https://api.github.com/repos/jehyunlee/dashboards/contents/data/tokens.json?ref=data';
const RAW_DATA_URL = 'https://raw.githubusercontent.com/jehyunlee/dashboards/data/data/tokens.json';
const $ = (id) => document.getElementById(id);

function ageMs(iso){ const t = Date.parse(iso || ''); return Number.isFinite(t) ? Date.now() - t : Infinity; }
function fmtAge(ms){ if(!Number.isFinite(ms)) return 'unknown'; const s=Math.max(0,Math.round(ms/1000)); if(s<90) return `${s}s ago`; const m=Math.round(s/60); if(m<90) return `${m}m ago`; const h=Math.round(m/60); return `${h}h ago`; }
function cls(status){ return status === 'ok' ? 'ok' : ['missing','rate_limited','unknown'].includes(status) ? 'warn' : status === 'warn' ? 'warn' : 'bad'; }
function escapeHtml(s){ return String(s ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])); }
function decodeData(payload){ if(!payload || !payload.content) return payload; const bin=atob(String(payload.content).replace(/\n/g,'')); const bytes=Uint8Array.from(bin, c=>c.charCodeAt(0)); return JSON.parse(new TextDecoder('utf-8').decode(bytes)); }
async function fetchData(){
  try{
    const r = await fetch(`${DATA_URL}&t=${Date.now()}`, {cache:'no-store'});
    if(!r.ok) throw new Error(`GitHub API HTTP ${r.status}`);
    return decodeData(await r.json());
  }catch(apiErr){
    const r = await fetch(`${RAW_DATA_URL}?t=${Math.floor(Date.now()/60000)}`, {cache:'no-store'});
    if(!r.ok) throw new Error(`${apiErr.message}; raw HTTP ${r.status}`);
    return r.json();
  }
}
function statusText(status){
  return ({ok:'connected', missing:'missing', auth_error:'auth error', rate_limited:'rate limited', provider_error:'provider error', error:'error', unknown:'unknown'})[status] || status || 'unknown';
}
function value(v){ return v === null || v === undefined || v === '' ? '—' : escapeHtml(v); }
function metric(label, val){ return `<div class="metric"><span>${escapeHtml(label)}</span><b>${value(val)}</b></div>`; }
function renderProvider(p){
  const tw = p.token_window || {};
  const tokens = tw.tokens || {};
  const requests = tw.requests || {};
  const conn = p.connection || {};
  const probe = p.model_probe || {};
  const billing = p.billing || {};
  const notes = [...(p.notes || [])];
  if(!tw.available) notes.unshift(`Token remaining/reset unavailable: ${tw.source || 'provider did not expose rate-limit headers'}.`);
  if(billing.available && billing.month_to_date_cost !== undefined){
    notes.push(`Month-to-date cost: ${billing.month_to_date_cost} ${billing.currency || ''}`.trim());
  }else if(billing.detail){
    notes.push(billing.detail);
  }
  const usage = probe.usage || {};
  const usageText = Object.keys(usage).length ? Object.entries(usage).map(([k,v]) => `${k}: ${v}`).join(', ') : '—';
  return `<article class="card provider provider-${escapeHtml(p.id)}">
    <div class="card-head"><h3>${escapeHtml(p.label || p.id)}</h3><span class="badge ${cls(p.status)}">${escapeHtml(statusText(p.status))}</span></div>
    <p>${escapeHtml(conn.detail || 'No connection detail.')}</p>
    <div class="metric-grid">
      ${metric('token limit', tokens.limit)}
      ${metric('remaining', tokens.remaining)}
      ${metric('reset', tokens.reset)}
    </div>
    <div class="section">
      <dl class="kv">
        <dt>Model probe</dt><dd>${escapeHtml(probe.model || '—')}</dd>
        <dt>Status code</dt><dd>${value(probe.status_code)}</dd>
        <dt>Latency</dt><dd>${probe.latency_ms === undefined ? '—' : `${escapeHtml(probe.latency_ms)} ms`}</dd>
        <dt>Request limit</dt><dd>${value(requests.limit)}</dd>
        <dt>Requests left</dt><dd>${value(requests.remaining)}</dd>
        <dt>Request reset</dt><dd>${value(requests.reset)}</dd>
        <dt>Probe usage</dt><dd>${escapeHtml(usageText)}</dd>
      </dl>
    </div>
    ${notes.length ? `<div class="note">${notes.map(escapeHtml).join('<br>')}</div>` : ''}
  </article>`;
}
function eventLine(e){ return `${e.time || ''} — ${e.message || JSON.stringify(e)}`; }
async function refresh(){
  try{
    const d = await fetchData();
    const age = ageMs(d.updated_at);
    const stale = age > 30 * 60 * 1000;
    const overall = stale ? 'warn' : (d.overall || 'unknown');
    $('hero').className = `hero status-${cls(overall)}`;
    $('overallTitle').textContent = overall === 'ok' ? 'All configured APIs connected' : overall === 'warn' ? 'Partial token status' : 'Provider check failing';
    $('overallDetail').textContent = `${d.summary || ''} · last update ${fmtAge(age)}${stale ? ' · stale' : ''}`;
    $('updatedAt').textContent = d.updated_at ? `updated ${new Date(d.updated_at).toLocaleString()}` : '—';
    $('providers').innerHTML = (d.providers || []).map(renderProvider).join('') || '<article class="card"><p>No providers found.</p></article>';
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
