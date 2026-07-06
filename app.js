const DATA_URL = 'https://api.github.com/repos/jehyunlee/dashboards/contents/data/macmini.json?ref=data';
const RAW_DATA_URL = 'https://raw.githubusercontent.com/jehyunlee/dashboards/data/data/macmini.json';
let zoom = Number(localStorage.getItem('dashZoom') || '1');
const $ = (id) => document.getElementById(id);
const surface = $('zoomSurface');

function setZoom(v){
  zoom = Math.min(1.6, Math.max(.7, v));
  surface.style.transform = `scale(${zoom})`;
  surface.style.marginBottom = `${(zoom - 1) * 260}px`;
  $('zoomLabel').textContent = `${Math.round(zoom * 100)}%`;
  localStorage.setItem('dashZoom', String(zoom));
}
$('zoomIn').onclick = () => setZoom(zoom + .1);
$('zoomOut').onclick = () => setZoom(zoom - .1);
$('zoomReset').onclick = () => setZoom(1);
setZoom(zoom);

window.addEventListener('wheel', e => {
  if(!e.ctrlKey && !e.metaKey) return;
  e.preventDefault();
  setZoom(zoom + (e.deltaY < 0 ? .06 : -.06));
}, {passive:false});

function ageMs(iso){
  const t = Date.parse(iso || '');
  return Number.isFinite(t) ? Date.now() - t : Infinity;
}
function fmtAge(ms){
  if(!Number.isFinite(ms)) return 'unknown';
  const s = Math.max(0, Math.round(ms / 1000));
  if(s < 90) return `${s}s ago`;
  const m = Math.round(s / 60);
  if(m < 90) return `${m}m ago`;
  const h = Math.round(m / 60);
  return `${h}h ago`;
}
function cls(status){
  return status === 'ok' ? 'ok' : status === 'warn' ? 'warn' : status === 'bad' ? 'bad' : 'unknown';
}
function setBadge(cardId, status, detail){
  const card = $(cardId);
  if(!card) return;
  const b = card.querySelector('.badge');
  b.className = `badge ${cls(status)}`;
  b.textContent = status || 'unknown';
  const p = card.querySelector('p');
  if(p) p.textContent = detail || 'No data.';
}
function eventLine(e){
  return `${e.time || ''} — ${e.message || JSON.stringify(e)}`;
}
function decodeData(payload){
  if(!payload || !payload.content) return payload;
  const bin = atob(String(payload.content).replace(/\n/g, ''));
  const bytes = Uint8Array.from(bin, c => c.charCodeAt(0));
  return JSON.parse(new TextDecoder('utf-8').decode(bytes));
}

async function fetchData(){
  try{
    const r = await fetch(`${DATA_URL}&t=${Date.now()}`, {cache:'no-store'});
    if(!r.ok) throw new Error(`GitHub API HTTP ${r.status}`);
    return decodeData(await r.json());
  }catch(apiErr){
    const r = await fetch(`${RAW_DATA_URL}?t=${Math.floor(Date.now() / 60000)}`, {cache:'no-store'});
    if(!r.ok) throw new Error(`${apiErr.message}; raw HTTP ${r.status}`);
    return r.json();
  }
}

const TASK_LABEL = {
  ready: 'READY',
  on_progress: 'ON PROGRESS',
  done: 'DONE',
  fail: 'FAIL',
  retry: 'RETRY'
};
const TASK_CLASS = {
  ready: 'ready',
  on_progress: 'progress',
  done: 'done',
  fail: 'fail',
  retry: 'retry'
};
function taskClass(status){
  return TASK_CLASS[status] || 'ready';
}
function taskLabel(status){
  return TASK_LABEL[status] || String(status || 'READY').toUpperCase();
}
function escapeHtml(s){
  return String(s ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function renderSshTimeline(history){
  const el = $('sshTimeline');
  if(!el) return;
  const slotMs = 5 * 60 * 1000, slots = 48;
  const nowBucket = Math.floor(Date.now() / slotMs);
  const byBucket = new Map();
  (history || []).forEach(h => {
    const t = Date.parse(h.time || h.updated_at || '');
    if(Number.isFinite(t)) byBucket.set(Math.floor(t / slotMs), (h.status || '').toLowerCase());
  });
  let pass = 0, fail = 0, html = '';
  for(let b = nowBucket - slots + 1; b <= nowBucket; b++){
    const s = byBucket.get(b);
    const ok = s === 'pass' || s === 'ok';
    const state = byBucket.size ? (ok ? 'pass' : 'fail') : 'unknown';
    if(state === 'pass') pass++; else if(state === 'fail') fail++;
    const tm = new Date(b * slotMs).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
    html += `<span class="ssh-slot ${state}" title="${tm} · ${state.toUpperCase()}"></span>`;
  }
  el.innerHTML = html;
  const ssh = history && history.length ? history[history.length - 1] : null;
  if(ssh) $('sshDetail').textContent += ` · 5분 슬롯: ${pass} pass / ${fail} fail-missing`;
}

function renderWorkflow(w){
  if(!w){
    $('workflowSteps').innerHTML = '<div class="task ready current"><b>READY</b><span>No workflow data yet.</span></div>';
    return;
  }
  const target = w.target || {};
  const last = w.last_completed || {};
  const steps = w.steps || [];
  const current = steps.find(s => s.current) || steps.find(s => s.id === w.current_step) || steps[0] || {};
  const currentLabel = taskLabel(current.status);
  const currentName = current.label || 'Workflow';
  const title = w.mode === 'idle' ? 'Resting / READY' : `${currentLabel}: ${currentName}`;
  $('overallTitle').textContent = title;
  $('overallDetail').textContent = `${w.summary || ''} · last heartbeat ${fmtAge(ageMs(window.__updatedAt))}`;
  $('workflowBadge').className = `badge ${cls(w.status || 'unknown')}`;
  $('workflowBadge').textContent = w.mode || 'unknown';
  $('workflowMode').textContent = `${currentLabel} · ${currentName} · ${current.detail || ''}`;

  const next = target.lecture ? `L${target.lecture} · ${target.scheduled_at || ''} · ${target.title || ''}` : 'No remaining run';
  const lastText = last.lecture ? `최근 완료: L${last.lecture} · ${last.completed_at || ''} · ${last.title || ''}` : '최근 완료 기록 없음';
  setBadge('currentRunCard', w.status || 'unknown', `${next} / ${lastText}`);

  $('workflowSteps').innerHTML = steps.map((s, idx) => {
    const status = taskClass(s.status);
    const cur = s.current ? ' current' : '';
    return `<div class="task ${status}${cur}">
      <div class="task-top"><span class="task-index">${idx + 1}</span><b>${escapeHtml(s.label)}</b><em>${taskLabel(s.status)}</em></div>
      <p>${escapeHtml(s.detail || '')}</p>
    </div>`;
  }).join('');

  const tail = w.log && Array.isArray(w.log.tail) ? w.log.tail : [];
  $('logTail').textContent = tail.length ? tail.join('\n') : 'No active workflow log tail.';
}

async function refresh(){
  try{
    const d = await fetchData();
    window.__updatedAt = d.updated_at;
    const age = ageMs(d.updated_at);
    const stale = age > 10 * 60 * 1000;
    const offline = age > 30 * 60 * 1000;
    const workflow = d.workflow || null;
    const overall = offline ? 'bad' : stale ? 'warn' : (d.overall || workflow?.status || 'ok');

    $('hero').className = `hero status-${cls(overall)}`;
    $('updatedAt').textContent = d.updated_at ? `updated ${new Date(d.updated_at).toLocaleString()}` : '—';
    renderWorkflow(workflow);

    if(offline || stale){
      $('overallDetail').textContent += ` · heartbeat ${offline ? 'offline' : 'stale'}`;
    }

    const ssh = d.checks?.ssh || {};
    setBadge('sshCard', ssh.status || (offline ? 'bad' : 'unknown'), ssh.detail || 'No SSH check detail.');
    renderSshTimeline(d.ssh_history || []);

    const dg = d.checks?.digest || {};
    setBadge('digestCard', dg.status || 'unknown', dg.detail || 'No digest detail.');

    const wd = d.checks?.watchdog || {};
    setBadge('watchdogCard', wd.status || 'unknown', wd.detail || 'No watchdog detail.');

    const events = (d.events || []).slice(-12).reverse();
    $('events').innerHTML = events.length ? events.map(e => `<li>${escapeHtml(eventLine(e))}</li>`).join('') : '<li>No recent events.</li>';
  }catch(err){
    $('hero').className = 'hero status-bad';
    $('overallTitle').textContent = 'Dashboard data unavailable';
    $('overallDetail').textContent = String(err);
    setBadge('digestCard', 'bad', 'Cannot fetch heartbeat JSON.');
  }
}
refresh();
setInterval(refresh, 20000);
