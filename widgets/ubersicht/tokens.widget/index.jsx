const DATA_URL = 'https://raw.githubusercontent.com/jehyunlee/dashboards/data/data/tokens.json';
const VISIBLE = 24;
const STALE_MS = 30 * 60 * 1000;

export const refreshFrequency = 60 * 1000;
export const initialState = { data: null, error: null, fetchedAt: null };

export const command = (dispatch) => {
  fetch(`${DATA_URL}?widget=${Date.now()}`, { cache: 'no-store' })
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then((data) => dispatch({ type: 'TOKEN_DATA', data }))
    .catch((error) => dispatch({ type: 'TOKEN_ERROR', error: String(error && error.message ? error.message : error) }));
};

export const updateState = (event, previousState = initialState) => {
  if (event.type === 'TOKEN_DATA') return { data: event.data, error: null, fetchedAt: new Date().toISOString() };
  if (event.type === 'TOKEN_ERROR') return { ...previousState, error: event.error };
  return previousState;
};

export const className = `
  right: 28px;
  bottom: 34px;
  width: 420px;
  color: #111827;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Noto Sans KR", Segoe UI, sans-serif;
  pointer-events: none;

  .token-widget {
    padding: 16px;
    border: 1px solid rgba(148, 163, 184, .30);
    border-radius: 24px;
    background: rgba(255, 255, 255, .82);
    box-shadow: 0 18px 48px rgba(15, 23, 42, .18);
    backdrop-filter: blur(22px) saturate(1.25);
  }
  .token-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding-bottom: 12px; border-bottom: 1px solid rgba(148, 163, 184, .24); }
  .eyebrow { margin: 0 0 3px; color: #667085; font-size: 11px; font-weight: 900; letter-spacing: .14em; }
  h1 { margin: 0; font-size: 28px; letter-spacing: -.06em; line-height: 1.02; }
  p { margin: 0; }
  .detail { margin-top: 6px; color: #667085; font-size: 13px; line-height: 1.35; }
  .dot { flex: 0 0 auto; width: 16px; height: 16px; margin-top: 6px; border-radius: 999px; background: #64748b; box-shadow: 0 0 0 7px rgba(100, 116, 139, .12); }
  .status-ok .dot { background: #16a34a; box-shadow: 0 0 0 7px rgba(22, 163, 74, .13); }
  .status-warn .dot { background: #d97706; box-shadow: 0 0 0 7px rgba(217, 119, 6, .13); }
  .status-bad .dot { background: #dc2626; box-shadow: 0 0 0 7px rgba(220, 38, 38, .13); }
  .providers { display: grid; gap: 10px; margin-top: 12px; }
  .provider { padding: 12px; border: 1px solid rgba(148, 163, 184, .24); border-radius: 18px; background: rgba(255, 255, 255, .64); }
  .provider-head, .metric { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
  h2 { margin: 0; font-size: 16px; letter-spacing: -.035em; }
  .badge { border-radius: 999px; padding: 3px 8px; font-size: 10px; font-weight: 950; text-transform: uppercase; white-space: nowrap; }
  .badge.ok { color: #166534; background: #dcfce7; }
  .badge.warn { color: #92400e; background: #fef3c7; }
  .badge.bad { color: #991b1b; background: #fee2e2; }
  .badge.unknown { color: #475569; background: #e2e8f0; }
  .metric { margin-top: 8px; color: #475467; font-size: 12px; }
  .metric b { color: #111827; }
  .spark { display: flex; align-items: flex-end; gap: 2px; height: 30px; margin-top: 8px; }
  .bar { flex: 1 1 0; min-width: 2px; border-radius: 2px 2px 0 0; background: linear-gradient(to top, #2563eb, #60a5fa); opacity: .96; }
  .provider-anthropic .bar { background: linear-gradient(to top, #c2410c, #fb923c); }
  .provider-gemini .bar { background: linear-gradient(to top, #0f766e, #2dd4bf); }
  .bar.zero { height: 2px !important; opacity: .22; }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .row .metric { display: block; padding-top: 8px; border-top: 1px solid rgba(148, 163, 184, .24); }
  .row span { display: block; color: #94a3b8; font-size: 10px; font-weight: 900; text-transform: uppercase; letter-spacing: .08em; }
  .row b { display: block; margin-top: 2px; font-size: 13px; }
  .note { margin-top: 8px; color: #94a3b8; font-size: 12px; font-weight: 750; }
  .footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 11px; color: #94a3b8; font-size: 11px; font-weight: 750; }
  .empty { padding: 14px; color: #94a3b8; font-size: 13px; font-weight: 800; text-align: center; }
`;

function ageMs(iso) {
  const t = Date.parse(iso || '');
  return Number.isFinite(t) ? Date.now() - t : Infinity;
}
function fmtAge(ms) {
  if (!Number.isFinite(ms)) return 'unknown';
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 90) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 90) return `${m}m ago`;
  return `${Math.round(m / 60)}h ago`;
}
function cls(status) {
  return status === 'ok' ? 'ok' : ['missing', 'rate_limited', 'warn', 'unknown'].includes(status) ? 'warn' : 'bad';
}
function statusText(status) {
  return ({ ok: 'connected', missing: 'missing', auth_error: 'auth error', rate_limited: 'rate limited', provider_error: 'provider error', error: 'error', unknown: 'unknown' })[status] || status || 'unknown';
}
function fmtCompact(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return '—';
  if (x >= 1e9) return `${(x / 1e9).toFixed(x >= 1e10 ? 0 : 1)}B`;
  if (x >= 1e6) return `${(x / 1e6).toFixed(x >= 1e7 ? 0 : 1)}M`;
  if (x >= 1e3) return `${(x / 1e3).toFixed(x >= 1e4 ? 0 : 1)}K`;
  return String(Math.round(x));
}
function fmtMoney(n) {
  const x = Number(n);
  return Number.isFinite(x) ? `$${x.toLocaleString('en-US', { maximumFractionDigits: x >= 100 ? 0 : 2 })}` : '—';
}
function lastN(arr, n) {
  return (arr || []).slice(Math.max(0, (arr || []).length - n));
}
function seriesPoints(series) {
  return lastN((series && series.available && series.points) ? series.points : [], VISIBLE);
}
function seriesTotal(series) {
  return seriesPoints(series).reduce((sum, p) => sum + (Number(p.tokens) || 0), 0);
}

function Spark({ series }) {
  const points = seriesPoints(series);
  if (!points.length) return <p className="note">최근 6시간 사용 표본 없음</p>;

  const values = points.map((p) => Number(p.tokens) || 0);
  const max = Math.max(1, ...values);

  return (
    <div className="spark">
      {points.map((p, i) => {
        const v = values[i];
        const height = v <= 0 ? 2 : Math.max(4, Math.round(v / max * 30));
        return <span key={`${p.t || i}-${i}`} className={`bar ${v <= 0 ? 'zero' : ''}`} style={{ height }} />;
      })}
    </div>
  );
}

function ProviderCard({ provider: p }) {
  const billing = p.billing || {};
  const usage = billing.usage || {};
  const windowTokens = (p.token_window && p.token_window.tokens) || {};
  const hasSub = p.id !== 'gemini' && p.subscription_series;

  return (
    <article className={`provider provider-${p.id || 'unknown'}`}>
      <div className="provider-head">
        <h2>{p.label || p.id || 'Provider'}</h2>
        <span className={`badge ${cls(p.status)}`}>{statusText(p.status)}</span>
      </div>
      <div className="row">
        <div className="metric"><span>30d API</span><b>{fmtCompact(usage.total_tokens)} tokens</b></div>
        <div className="metric"><span>Cost</span><b>{fmtMoney(billing.month_to_date_cost)}</b></div>
      </div>
      <div className="metric"><span>API 6h</span><b>{fmtCompact(seriesTotal(p.usage_series))} tokens</b></div>
      <Spark series={p.usage_series} />
      {hasSub ? <div className="metric"><span>CLI subscription 6h</span><b>{fmtCompact(seriesTotal(p.subscription_series))} tokens</b></div> : null}
      {hasSub ? <Spark series={p.subscription_series} /> : null}
      {windowTokens.remaining ? <p className="note">rate window remaining {fmtCompact(windowTokens.remaining)} / {fmtCompact(windowTokens.limit)}</p> : null}
    </article>
  );
}

export const render = ({ data, error }) => {
  if (!data && error) {
    return (
      <div className="token-widget status-bad">
        <div className="token-head">
          <div>
            <p className="eyebrow">TOKEN STATUS</p>
            <h1>Unavailable</h1>
            <p className="detail">{error}</p>
          </div>
          <span className="dot" />
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="token-widget status-warn">
        <div className="token-head">
          <div>
            <p className="eyebrow">TOKEN STATUS</p>
            <h1>Checking…</h1>
            <p className="detail">Waiting for token status data.</p>
          </div>
          <span className="dot" />
        </div>
      </div>
    );
  }

  const age = ageMs(data.updated_at);
  const stale = age > STALE_MS;
  const overall = stale ? 'warn' : (data.overall || 'unknown');
  const providers = data.providers || [];
  const title = overall === 'ok' ? 'APIs connected' : overall === 'warn' ? 'Token status stale' : 'Provider check failing';
  const updatedAt = data.updated_at ? new Date(data.updated_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'not updated';

  return (
    <div className={`token-widget status-${cls(overall)}`}>
      <div className="token-head">
        <div>
          <p className="eyebrow">TOKEN STATUS</p>
          <h1>{title}</h1>
          <p className="detail">{data.summary || ''} · {fmtAge(age)}{stale ? ' · stale' : ''}{error ? ` · last fetch error: ${error}` : ''}</p>
        </div>
        <span className="dot" />
      </div>
      <section className="providers">
        {providers.length ? providers.map((p) => <ProviderCard key={p.id} provider={p} />) : <div className="empty">No providers found.</div>}
      </section>
      <div className="footer"><span>{updatedAt}</span><span>tech.jehyunlee.dev/dashboards/tokens</span></div>
    </div>
  );
};
