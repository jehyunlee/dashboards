const DATA_URL = './data/macmini.json';
let zoom = Number(localStorage.getItem('dashZoom') || '1');
const $ = (id) => document.getElementById(id);
const surface = $('zoomSurface');
function setZoom(v){ zoom=Math.min(1.6,Math.max(.7,v)); surface.style.transform=`scale(${zoom})`; surface.style.marginBottom=`${(zoom-1)*260}px`; $('zoomLabel').textContent=`${Math.round(zoom*100)}%`; localStorage.setItem('dashZoom',String(zoom)); }
$('zoomIn').onclick=()=>setZoom(zoom+.1); $('zoomOut').onclick=()=>setZoom(zoom-.1); $('zoomReset').onclick=()=>setZoom(1); setZoom(zoom);
window.addEventListener('wheel', e=>{ if(!e.ctrlKey && !e.metaKey) return; e.preventDefault(); setZoom(zoom + (e.deltaY<0 ? .06 : -.06)); }, {passive:false});
function ageMs(iso){ const t=Date.parse(iso||''); return Number.isFinite(t)? Date.now()-t : Infinity; }
function fmtAge(ms){ if(!Number.isFinite(ms)) return 'unknown'; const s=Math.max(0,Math.round(ms/1000)); if(s<90) return `${s}s ago`; const m=Math.round(s/60); if(m<90) return `${m}m ago`; const h=Math.round(m/60); return `${h}h ago`; }
function cls(status){ return status==='ok'?'ok':status==='warn'?'warn':status==='bad'?'bad':'unknown'; }
function setBadge(cardId, status, detail){ const card=$(cardId); const b=card.querySelector('.badge'); b.className=`badge ${cls(status)}`; b.textContent=status||'unknown'; const p=card.querySelector('p'); p.textContent=detail||'No data.'; }
function eventLine(e){ return `${e.time||''} — ${e.message||JSON.stringify(e)}`; }
async function refresh(){
  try{
    const r=await fetch(`${DATA_URL}?t=${Date.now()}`, {cache:'no-store'}); if(!r.ok) throw new Error(`HTTP ${r.status}`); const d=await r.json();
    const age=ageMs(d.updated_at); const stale=age>10*60*1000; const offline=age>30*60*1000;
    const overall = offline ? 'bad' : stale ? 'warn' : (d.overall || 'ok');
    $('hero').className=`hero status-${cls(overall)}`; $('overallTitle').textContent = overall==='ok' ? 'All systems operational' : overall==='warn' ? 'Degraded / stale heartbeat' : 'Offline or unreachable';
    $('overallDetail').textContent = `${d.host||'mac mini'} · last heartbeat ${fmtAge(age)} · ${d.summary||''}`;
    $('updatedAt').textContent = d.updated_at ? `updated ${new Date(d.updated_at).toLocaleString()}` : '—';
    setBadge('heartbeatCard', offline?'bad':stale?'warn':'ok', `Last heartbeat ${fmtAge(age)} from ${d.host||'unknown host'}.`);
    const ssh = d.checks?.ssh || {}; setBadge('sshCard', ssh.status || (offline?'bad':'unknown'), ssh.detail || 'No SSH check detail.');
    const dg = d.checks?.digest || {}; setBadge('digestCard', dg.status || 'unknown', dg.detail || 'No digest detail.');
    const wd = d.checks?.watchdog || {}; setBadge('watchdogCard', wd.status || 'unknown', wd.detail || 'No watchdog detail.');
    const lec=d.lecture || {}; const done=Number(lec.done||0), total=Number(lec.total||0); const pct=total?Math.round(done*100/total):0; $('lectureProgress').firstElementChild.style.width=`${pct}%`; $('lectureBadge').className=`badge ${cls(lec.status||'unknown')}`; $('lectureBadge').textContent=lec.status||'unknown'; $('lectureDetail').textContent=`${done}/${total} completed. ${lec.current ? 'Current/next: '+lec.current : ''}`;
    const events=(d.events||[]).slice(-12).reverse(); $('events').innerHTML = events.length ? events.map(e=>`<li>${eventLine(e)}</li>`).join('') : '<li>No recent events.</li>';
  }catch(err){ $('hero').className='hero status-bad'; $('overallTitle').textContent='Dashboard data unavailable'; $('overallDetail').textContent=String(err); setBadge('heartbeatCard','bad','Cannot fetch data/macmini.json.'); }
}
refresh(); setInterval(refresh, 20000);
