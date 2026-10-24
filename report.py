"""Static HTML report: hypothesis verdicts, average CAR path, drift by event type, test tables.

Pure rendering (no network). Charts are plain SVG drawn by a small inline script, so the file opens
offline. Colors follow the dataviz reference palette (light and dark steps).
"""
import html
import json

import pandas as pd
from scipy import stats

import config

_CSS = """:root {
  color-scheme: light;
  --page: #f9f9f7; --surface-1: #fcfcfb; --text-primary: #0b0b0b; --text-secondary: #52514e;
  --muted: #898781; --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6; --series-2: #eb6834; --series-0: #898781;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --page: #0d0d0d; --surface-1: #1a1a19; --text-primary: #f0efec; --text-secondary: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --series-1: #3987e5; --series-2: #d95926; --series-0: #898781;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface-1: #1a1a19; --text-primary: #f0efec; --text-secondary: #c3c2b7;
  --muted: #898781; --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --series-1: #3987e5; --series-2: #d95926; --series-0: #898781;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--text-primary);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1120px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 19px; margin: 40px 0 8px; }
h3 { font-size: 16px; margin: 24px 0 6px; }
.lede, .note { color: var(--text-secondary); margin: 0 0 12px; }
.note { font-size: 13px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; margin-top: 20px; }
.tile, .card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
.tile-label { color: var(--text-secondary); font-size: 13px; }
.tile-value { font-size: 28px; font-weight: 600; margin: 4px 0; }
.tile-sub { color: var(--muted); font-size: 12px; }
.chip { display: inline-flex; gap: 6px; align-items: center; margin-top: 10px; font-size: 13px;
  font-weight: 600; color: var(--text-primary); }
.chip-icon { display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 50%;
  border: 1px solid var(--axis); font-size: 11px; }
.card { margin-top: 12px; }
.legend { display: flex; flex-wrap: wrap; gap: 16px; font-size: 13px; color: var(--text-secondary); margin-bottom: 8px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.key { display: inline-block; width: 16px; height: 2px; border-radius: 1px; }
svg { display: block; width: 100%; height: auto; overflow: visible; }
svg text { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
svg .lbl { fill: var(--text-secondary); font-size: 12px; }
.tip { position: fixed; pointer-events: none; background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 8px; padding: 8px 10px; font-size: 12px; box-shadow: 0 4px 16px rgba(0,0,0,.12);
  display: none; z-index: 10; min-width: 150px; }
.tip .row { display: flex; align-items: center; gap: 8px; }
.tip strong { font-variant-numeric: tabular-nums; }
.tip .muted { color: var(--text-secondary); }
.table-wrap { overflow-x: auto; margin-top: 8px; border: 1px solid var(--border); border-radius: 10px;
  background: var(--surface-1); }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { padding: 6px 10px; text-align: left; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th { color: var(--text-secondary); font-weight: 600; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
details { margin-top: 10px; font-size: 13px; }
summary { cursor: pointer; color: var(--text-secondary); }
ul.caveats { color: var(--text-secondary); padding-left: 20px; }
"""

_PATH_KS = list(range(config.CAR_PATH_WINDOW[0], config.CAR_PATH_WINDOW[1] + 1))


def _pct(x, nd=2) -> str:
    return "" if pd.isna(x) else f"{x * 100:+.{nd}f}%"


def _num(x, nd=2) -> str:
    return "" if pd.isna(x) else f"{x:+.{nd}f}"


def _p(x) -> str:
    return "" if pd.isna(x) else f"{x:.3f}"


def car_path(df: pd.DataFrame) -> list[float | None]:
    """Mean signed cumulative AR from t-10 (in %), each event signed by its news direction."""
    cols = [f"ar_{k:+d}" for k in _PATH_KS]
    if df.empty or not set(cols) <= set(df.columns):
        return [None] * len(_PATH_KS)
    signed = df[cols].mul(df["direction"], axis=0)
    cum = signed.cumsum(axis=1, skipna=False)
    return [None if pd.isna(v) else round(v * 100, 3) for v in cum.mean()]


def by_event_type(clean: pd.DataFrame) -> list[dict]:
    """Signed pre-CAR per primary event type (first merged label), non-overlapping events."""
    rows = []
    primary = clean["event_type"].str.split(" + ", regex=False).str[0]
    for label, g in clean.groupby(primary):
        x = g["signed_pre_car"].dropna()
        if len(x) < 5:
            continue
        rows.append({"label": label, "value": round(x.mean() * 100, 3), "n": len(x),
                     "p": round(float(stats.ttest_1samp(x, 0).pvalue), 3),
                     "scheduled": bool(g["scheduled"].iloc[0])})
    return sorted(rows, key=lambda r: r["value"], reverse=True)


def _verdict(p_values: list[float]) -> tuple[str, str]:
    """Conservative: the weakest of the supplied p-values decides."""
    ps = [p for p in p_values if not pd.isna(p)]
    if not ps:
        return "-", "Not enough data"
    worst = max(ps)
    if worst < 0.05:
        return "✓", "Evidence (p < 0.05)"
    if worst < 0.10:
        return "~", "Weak (p < 0.10)"
    return "✕", "No evidence"


def _tiles(tests: pd.DataFrame) -> str:
    def row(name):
        return tests.loc[name] if name in tests.index else None

    # Verdicts use unscheduled news only: before scheduled results the market knows the date and positions
    # for it openly (option OI and volume rise), which is not leakage.
    u = row("Unscheduled (non-ovl)")
    specs = []
    if u is not None:
        specs.append(("Price drift", _pct(u["signed_pre_car"]),
                      f"t-test p {_p(u['signed_p'])} · placebo p {_p(u['placebo_p'])}",
                      [u["signed_p"], u["placebo_p"]]))
        specs.append(("Share volume, t-5..t-1", _num(u["vol_z"]) + " z", f"p {_p(u['vol_p'])} vs 0", [u["vol_p"]]))
        for col, title, fmt in [("opt_vol_z", "Option volume, t-5..t-1", _num),
                                ("news_side_otm_vol_z", "Short-dated OTM options on the news side", _num),
                                ("opt_oi_chg_pre", "Option OI build-up, t-6..t-1", _pct),
                                ("fut_oi_chg_pre", "Futures OI build-up, t-6..t-1", _pct),
                                ("signed_intra_ar_z", "Price move in the hour before in-session filings", _num),
                                ("intra_vol_z", "Volume in the hour before in-session filings", _num)]:
            if col in u and not pd.isna(u[col]):
                unit = "" if fmt is _pct else " z"
                specs.append((title, fmt(u[col]) + unit, f"p {_p(u[col + '_p'])} vs placebo days",
                              [u[col + "_p"]]))
    out = []
    for title, value, sub, ps in specs:
        icon, label = _verdict(ps)
        out.append(f'<div class="tile"><div class="tile-label">{html.escape(title)}</div>'
                   f'<div class="tile-value">{html.escape(value)}</div>'
                   f'<div class="tile-sub">{html.escape(sub)}</div>'
                   f'<div class="chip"><span class="chip-icon" aria-hidden="true">{icon}</span>'
                   f'{html.escape(label)}</div></div>')
    return "\n".join(out)


def _table(df: pd.DataFrame, numeric: set[str] = frozenset()) -> str:
    head = "".join(f'<th class="{"num" if c in numeric else ""}">{html.escape(str(c))}</th>' for c in df.columns)
    body = "".join(
        "<tr>" + "".join(f'<td class="{"num" if c in numeric else ""}">{html.escape(str(v))}</td>'
                         for c, v in zip(df.columns, r)) + "</tr>"
        for r in df.itertuples(index=False))
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _tests_tables(t: pd.DataFrame) -> str:
    main = pd.DataFrame({
        "Group": t.index, "N": t["n"].astype(int), "Signed pre CAR": t["signed_pre_car"].map(_pct),
        "t-test p": t["signed_p"].map(_p), "BMP p": t["bmp_p"].map(_p),
        "Right way": t["share_right_way"].map(lambda x: "" if pd.isna(x) else f"{x:.0%}"),
        "Sign p": t["sign_p"].map(_p), "Placebo p": t["placebo_p"].map(_p),
        "Vol z": t["vol_z"].map(_num), "Vol p": t["vol_p"].map(_p), "|D0 AR|": t["day0_abs_ar"].map(_pct),
    })
    out = _table(main, set(main.columns) - {"Group"})
    extra = [c for c in config.EXTRA_SIGNAL_COLUMNS if c in t]
    if extra:
        cols = {"Group": t.index, "N": t["n"].astype(int)}
        for c in extra:
            fmt = _pct if c.endswith("_chg_pre") or c == "signed_oi_tilt" else (lambda x: "" if pd.isna(x) else f"{x:.0%}") \
                if c == "deal_any" else _num
            cols[config.EXTRA_SIGNAL_COLUMNS[c]] = t[c].map(fmt)
            cols[config.EXTRA_SIGNAL_COLUMNS[c] + " p"] = t[c + "_p"].map(_p)
        pos = pd.DataFrame(cols)
        out += ("<h3>Positioning signals</h3><p class=\"note\">Mean per event; p is a Welch test against "
                "the placebo days (the placebo row is tested against zero).</p>"
                + _table(pos, set(pos.columns) - {"Group"}))
    return out


def _top_events(clean: pd.DataFrame, n: int = 15) -> str:
    u = clean[~clean["scheduled"]].sort_values("signed_pre_car_z", ascending=False).head(n)
    if u.empty:
        return "<p>No unscheduled events.</p>"
    df = pd.DataFrame({
        "Stock": u["symbol"], "Day 0": u["day0"].dt.strftime("%Y-%m-%d"),
        "Filed (IST)": u["timestamp"].dt.strftime("%Y-%m-%d %H:%M"), "Type": u["event_type"],
        "Headline": u["headline"].str.slice(0, 70),
        "Signed pre CAR": u["signed_pre_car"].map(_pct), "CAR z": u["signed_pre_car_z"].map(_num),
        "Vol z": u["vol_z"].map(_num),
        "Option vol z": u["opt_vol_z"].map(_num) if "opt_vol_z" in u else "",
        "Intraday z": u["signed_intra_ar_z"].map(_num) if "signed_intra_ar_z" in u else "",
    })
    return _table(df, {"Signed pre CAR", "CAR z", "Vol z", "Option vol z", "Intraday z"})


def _otm_leads(ranked: pd.DataFrame, n: int = 20) -> str:
    if ranked.empty:
        return "<p>No unscheduled event had significant news-side OTM flow above the wrong side.</p>"
    r = ranked.head(n)
    side = r["direction"].map({1.0: "calls", -1.0: "puts"})
    df = pd.DataFrame({
        "Stock": r["symbol"], "Day 0": r["day0"].dt.strftime("%Y-%m-%d"),
        "Filed (IST)": r["timestamp"].dt.strftime("%Y-%m-%d %H:%M"), "Type": r["event_type"],
        "Headline": r["headline"].str.slice(0, 60), "News side": side,
        "News-side z": r["news_side_otm_vol_z"].map(_num), "Wrong-side z": r["wrong_side_otm_vol_z"].map(_num),
        "Gap": r["otm_side_gap"].map(_num), "Signed pre CAR": r["signed_pre_car"].map(_pct),
        "Day-0 AR": r["day0_ar"].map(_pct), "Post CAR": r["post_car"].map(_pct),
    })
    return _table(df, {"News-side z", "Wrong-side z", "Gap", "Signed pre CAR", "Day-0 AR", "Post CAR"})


def build(results: pd.DataFrame, placebo: pd.DataFrame, tests: pd.DataFrame, meta: dict,
          otm_ranked: pd.DataFrame | None = None) -> str:
    clean = results[~results["overlap"]]
    path = {
        "x": _PATH_KS,
        "series": [
            {"name": "Unscheduled news", "slot": 1, "n": int((~clean["scheduled"]).sum()),
             "y": car_path(clean[~clean["scheduled"]])},
            {"name": "Scheduled news", "slot": 2, "n": int(clean["scheduled"].sum()),
             "y": car_path(clean[clean["scheduled"]])},
            {"name": "Placebo days", "slot": 0, "n": len(placebo), "y": car_path(placebo)},
        ],
    }
    types = by_event_type(clean)
    data = json.dumps({"path": path, "types": types}).replace("</", "<\\/")
    n_stocks = results["symbol"].nunique()

    caveats = [
        "Direction is defined by the reaction (Day 0 + 5 days), so every line rises after Day 0 by "
        "construction. Only the part before Day 0 tests the hypothesis.",
        f"The universe is today's Nifty 50 ({n_stocks} stocks with data), so the sample has survivorship bias.",
        "Events come from a keyword classifier over BSE filings. Overlapping events are excluded from "
        "the headline tests.",
        "Several signals and groups are tested, so expect about 1 in 20 p-values under 0.05 by chance.",
        "SEBI insider-trade (PIT) disclosures are not included: NSE's feed is incomplete (no rows for "
        "HDFCBANK or TCS all year).",
        "Block deals in Nifty 50 stocks are mostly institutional crossings, not insider trades.",
    ]
    if "media_prior" in results:
        caveats.append("Media timing is experimental: Google News gives only dates, and its results "
                       "vary between runs.")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Leakage Study Report</title>
<style>
{_CSS}</style>
</head>
<body>
<main>
<h1>Pre-event drift &amp; information leakage</h1>
<p class="lede">{html.escape(meta['label'])} &middot; filings {html.escape(meta['period'])} &middot;
{len(results)} events ({len(clean)} non-overlapping) &middot; {len(placebo)} placebo days &middot;
signals: {html.escape(meta['signals'])}</p>
<p class="note">Hypothesis: prices, volume and positioning move in the direction of material news before it is
public. Each event's pre-window [t-5, t-1] is compared against its own 30-session baseline and against random
non-event days for the same stocks (placebo).</p>

<h2>Verdicts: unscheduled news, non-overlapping events</h2>
<p class="note">Scheduled news (results, dividends, board outcomes) is excluded here: its date is public, so
positioning before it is expected. Its numbers are in the tables below.</p>
<section class="tiles">
{_tiles(tests)}
</section>

<h2>Average signed cumulative abnormal return around the news</h2>
<p class="note">Non-overlapping events. Each event's Nifty-adjusted return is signed by the direction of the
news, so a line rising before Day 0 means prices moved the news' way before it was public.</p>
<div class="card">
  <div class="legend" id="path-legend"></div>
  <div id="path-chart"></div>
  <details><summary>Table view</summary><div id="path-table"></div></details>
</div>

<h2>Pre-event drift by event type</h2>
<p class="note">Mean signed pre-CAR [t-5, t-1], non-overlapping events, types with at least 5 events.</p>
<div class="card">
  <div id="type-chart"></div>
  <details><summary>Table view</summary><div id="type-table"></div></details>
</div>

<h2>Hypothesis tests</h2>
{_tests_tables(tests)}

<h2>Strongest pre-event moves, unscheduled news</h2>
<p class="note">Ranked by signed pre-CAR z. A high value on its own is not proof of insider trading; check the
filing and the press coverage.</p>
{_top_events(clean)}

<h2>Directional option flow: leads to investigate</h2>
<p class="note">Unscheduled news where front-month out-of-the-money volume on the side that profits from the news
(calls before good news, puts before bad) was significant (z &ge; {config.SIGNIFICANCE_Z}) and above the wrong
side, ranked by the gap. These are statistical leads, not findings of wrongdoing: check the filing, earlier press
coverage and SEBI orders for each.</p>
{_otm_leads(otm_ranked if otm_ranked is not None else pd.DataFrame())}

<h2>Caveats</h2>
<ul class="caveats">{''.join(f'<li>{html.escape(c)}</li>' for c in caveats)}</ul>
</main>
<div class="tip" id="tip" role="tooltip"></div>
<script type="application/json" id="data">{data}</script>
<script>
(() => {{
  const D = JSON.parse(document.getElementById('data').textContent);
  const NS = 'http://www.w3.org/2000/svg';
  const tip = document.getElementById('tip');
  const color = slot => `var(--series-${{slot}})`;
  const fmt = v => v == null ? '–' : (v > 0 ? '+' : '') + v.toFixed(2) + '%';
  const el = (tag, attrs = {{}}, parent) => {{
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  }};
  const niceTicks = (lo, hi, n = 5) => {{
    const step0 = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= step0);
    const out = [], end = Math.ceil(hi / step - 1e-9) * step;  // round outward so no mark exceeds the axis
    for (let v = Math.floor(lo / step + 1e-9) * step; v <= end + 1e-9; v += step) out.push(+v.toFixed(6));
    return out;
  }};
  const showTip = (ev, rows, title) => {{
    tip.replaceChildren();
    const h = document.createElement('div'); h.className = 'muted'; h.textContent = title; tip.appendChild(h);
    for (const r of rows) {{
      const row = document.createElement('div'); row.className = 'row';
      if (r.slot != null) {{ const k = document.createElement('span'); k.className = 'key';
        k.style.background = color(r.slot); row.appendChild(k); }}
      const s = document.createElement('strong'); s.textContent = r.value; row.appendChild(s);
      const l = document.createElement('span'); l.className = 'muted'; l.textContent = r.label; row.appendChild(l);
      tip.appendChild(row);
    }}
    tip.style.display = 'block';
    const x = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
    tip.style.left = x + 'px'; tip.style.top = (ev.clientY + 14) + 'px';
  }};
  const hideTip = () => {{ tip.style.display = 'none'; }};
  const table = (host, head, rows) => {{
    const wrap = document.createElement('div'); wrap.className = 'table-wrap';
    const t = document.createElement('table'); wrap.appendChild(t);
    const tr = t.createTHead().insertRow();
    head.forEach((h, i) => {{ const th = document.createElement('th'); th.textContent = h;
      if (i) th.className = 'num'; tr.appendChild(th); }});
    const tb = t.createTBody();
    rows.forEach(r => {{ const row = tb.insertRow(); r.forEach((v, i) => {{ const td = row.insertCell();
      td.textContent = v; if (i) td.className = 'num'; }}); }});
    host.appendChild(wrap);
  }};

  // ---- line chart: signed CAR path
  function pathChart() {{
    const P = D.path, host = document.getElementById('path-chart');
    const W = 1040, H = 340, m = {{t: 16, r: 150, b: 36, l: 52}};
    const svg = el('svg', {{viewBox: `0 0 ${{W}} ${{H}}`, role: 'img',
      'aria-label': 'Average signed cumulative abnormal return from t-10 to t+5'}}, host);
    const all = P.series.flatMap(s => s.y).filter(v => v != null).concat([0]);
    let lo = Math.min(...all), hi = Math.max(...all); const pad = (hi - lo) * 0.08 || 0.5;
    const ticks = niceTicks(lo - pad, hi + pad); lo = ticks[0]; hi = ticks[ticks.length - 1];
    const x = k => m.l + (k - P.x[0]) / (P.x[P.x.length - 1] - P.x[0]) * (W - m.l - m.r);
    const y = v => m.t + (hi - v) / (hi - lo) * (H - m.t - m.b);
    ticks.forEach(t => {{
      el('line', {{x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), stroke: t === 0 ? 'var(--axis)' : 'var(--grid)',
        'stroke-width': 1}}, svg);
      el('text', {{x: m.l - 8, y: y(t) + 4, 'text-anchor': 'end'}}, svg).textContent = t + '%';
    }});
    P.x.forEach(k => {{ el('text', {{x: x(k), y: H - m.b + 18, 'text-anchor': 'middle'}}, svg).textContent =
      k === 0 ? 'Day 0' : (k > 0 ? '+' + k : k); }});
    el('line', {{x1: x(0), x2: x(0), y1: m.t, y2: H - m.b, stroke: 'var(--axis)', 'stroke-width': 1}}, svg);
    el('text', {{x: x(-3), y: m.t + 10, 'text-anchor': 'middle', class: 'lbl'}}, svg).textContent = 'pre-window';
    const ends = [];
    P.series.forEach(s => {{
      const pts = P.x.map((k, i) => [k, s.y[i]]).filter(p => p[1] != null);
      if (!pts.length) return;
      el('path', {{d: pts.map((p, i) => (i ? 'L' : 'M') + x(p[0]) + ',' + y(p[1])).join(''), fill: 'none',
        stroke: color(s.slot), 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'}}, svg);
      const last = pts[pts.length - 1];
      el('circle', {{cx: x(last[0]), cy: y(last[1]), r: 4, fill: color(s.slot), stroke: 'var(--surface-1)',
        'stroke-width': 2}}, svg);
      ends.push({{s, yy: y(last[1]), v: last[1]}});
    }});
    // Direct end labels only when they don't collide; the legend always carries identity.
    ends.sort((a, b) => a.yy - b.yy);
    const clear = ends.every((e, i) => !i || e.yy - ends[i - 1].yy >= 16);
    if (clear) ends.forEach(e => {{ el('text', {{x: W - m.r + 10, y: e.yy + 4, class: 'lbl'}}, svg).textContent =
      `${{e.s.name}} ${{fmt(e.v)}}`; }});
    const legend = document.getElementById('path-legend');
    P.series.forEach(s => {{ const sp = document.createElement('span'); const k = document.createElement('i');
      k.className = 'key'; k.style.background = color(s.slot); sp.appendChild(k);
      sp.appendChild(document.createTextNode(`${{s.name}} (n=${{s.n}})`)); legend.appendChild(sp); }});
    const cross = el('line', {{y1: m.t, y2: H - m.b, stroke: 'var(--axis)', 'stroke-width': 1,
      visibility: 'hidden'}}, svg);
    const hit = el('rect', {{x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent',
      tabindex: 0}}, svg);
    const at = idx => {{ const k = P.x[idx]; cross.setAttribute('x1', x(k)); cross.setAttribute('x2', x(k));
      cross.setAttribute('visibility', 'visible');
      return [k, P.series.map(s => ({{slot: s.slot, value: fmt(s.y[idx]), label: s.name}}))]; }};
    hit.addEventListener('pointermove', ev => {{
      const r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) * W / r.width;
      const idx = Math.max(0, Math.min(P.x.length - 1, Math.round((px - m.l) / (W - m.l - m.r) * (P.x.length - 1))));
      const [k, rows] = at(idx); showTip(ev, rows, k === 0 ? 'Day 0' : `t${{k > 0 ? '+' : ''}}${{k}}`);
    }});
    hit.addEventListener('pointerleave', () => {{ hideTip(); cross.setAttribute('visibility', 'hidden'); }});
    table(document.getElementById('path-table'), ['Day', ...P.series.map(s => s.name)],
      P.x.map((k, i) => [k === 0 ? 'Day 0' : 't' + (k > 0 ? '+' : '') + k, ...P.series.map(s => fmt(s.y[i]))]));
  }}

  // ---- bar chart: signed pre-CAR by event type (horizontal, from a zero baseline)
  function typeChart() {{
    const T = D.types, host = document.getElementById('type-chart');
    if (!T.length) {{ host.textContent = 'Not enough events per type.'; return; }}
    const rowH = 34, W = 1040, m = {{t: 8, r: 80, b: 28, l: 190}}, H = m.t + m.b + rowH * T.length;
    const svg = el('svg', {{viewBox: `0 0 ${{W}} ${{H}}`, role: 'img', 'aria-label': 'Signed pre-CAR by event type'}}, host);
    const vals = T.map(t => t.value).concat([0]);
    const ticks = niceTicks(Math.min(...vals), Math.max(...vals), 6);
    const lo = ticks[0], hi = ticks[ticks.length - 1];
    const x = v => m.l + (v - lo) / (hi - lo) * (W - m.l - m.r);
    ticks.forEach(t => {{
      el('line', {{x1: x(t), x2: x(t), y1: m.t, y2: H - m.b, stroke: t === 0 ? 'var(--axis)' : 'var(--grid)', 'stroke-width': 1}}, svg);
      el('text', {{x: x(t), y: H - m.b + 18, 'text-anchor': 'middle'}}, svg).textContent = t + '%';
    }});
    T.forEach((t, i) => {{
      const cy = m.t + i * rowH + rowH / 2, bh = Math.min(20, rowH - 8);
      el('text', {{x: m.l - 10, y: cy + 4, 'text-anchor': 'end', class: 'lbl'}}, svg).textContent =
        `${{t.label}}${{t.scheduled ? ' (sched.)' : ''}}`;
      const x0 = x(0), x1 = x(t.value), left = Math.min(x0, x1), w = Math.max(Math.abs(x1 - x0), 1);
      // 4px rounded data end, square at the zero baseline
      const r = Math.min(4, w), pos = t.value >= 0;
      const d = pos
        ? `M${{left}},${{cy - bh / 2}}h${{w - r}}a${{r}},${{r}} 0 0 1 ${{r}},${{r}}v${{bh - 2 * r}}a${{r}},${{r}} 0 0 1 -${{r}},${{r}}h-${{w - r}}z`
        : `M${{left + w}},${{cy - bh / 2}}h-${{w - r}}a${{r}},${{r}} 0 0 0 -${{r}},${{r}}v${{bh - 2 * r}}a${{r}},${{r}} 0 0 0 ${{r}},${{r}}h${{w - r}}z`;
      const bar = el('path', {{d, fill: color(1), tabindex: 0}}, svg);
      el('text', {{x: pos ? left + w + 6 : left - 6, y: cy + 4, 'text-anchor': pos ? 'start' : 'end', class: 'lbl'}}, svg)
        .textContent = fmt(t.value);
      const hitr = el('rect', {{x: m.l, y: cy - rowH / 2, width: W - m.l - m.r, height: rowH, fill: 'transparent'}}, svg);
      const on = ev => {{ bar.setAttribute('opacity', 0.8);
        showTip(ev, [{{slot: 1, value: fmt(t.value), label: 'signed pre-CAR'}},
                     {{value: String(t.n), label: 'events'}}, {{value: t.p.toFixed(3), label: 't-test p'}}], t.label); }};
      const off = () => {{ bar.setAttribute('opacity', 1); hideTip(); }};
      hitr.addEventListener('pointermove', on); hitr.addEventListener('pointerleave', off);
    }});
    table(document.getElementById('type-table'), ['Event type', 'Signed pre-CAR', 'Events', 't-test p'],
      T.map(t => [t.label, fmt(t.value), t.n, t.p.toFixed(3)]));
  }}

  pathChart(); typeChart();
}})();
</script>
</body>
</html>
"""


def _int(x) -> str:
    return "" if pd.isna(x) else f"{x:,.0f}"


def _lead_section(lead: dict) -> str:
    ev, side = lead["event"], "calls" if lead["event"]["direction"] > 0 else "puts"
    news = "good" if lead["event"]["direction"] > 0 else "bad"
    facts = pd.DataFrame({
        "Filed (IST)": [ev["timestamp"].strftime("%Y-%m-%d %H:%M:%S")], "Session": [ev["session"]],
        "Type": [ev["event_type"]], "News": [f"{news} (news side = {side})"],
        "News-side OTM z": [_num(ev["news_side_otm_vol_z"])], "Wrong-side OTM z": [_num(ev["wrong_side_otm_vol_z"])],
        "Signed pre CAR": [_pct(ev["signed_pre_car"])], "Day-0 AR": [_pct(ev["day0_ar"])],
        "Post CAR": [_pct(ev["post_car"])],
    })
    flags = [label for col, label in [("macro_shock", "big market day in pre-window"),
                                      ("sector_shock", "big sector day in pre-window"),
                                      ("broker_prior", "broker rating/target change before filing"),
                                      ("media_prior", "matching press before filing day")]
             if col in ev and str(ev[col]) == "True"]  # CSV round-trips store booleans as text
    if "Media Clarification" in str(ev["event_type"]):
        flags.append("exchange query about a media report")
    parts = [f'<h2 id="{html.escape(lead["anchor"])}">{html.escape(ev["symbol"])} &middot; '
             f'Day 0 {ev["day0"]:%Y-%m-%d}</h2>',
             f'<p class="lede">{html.escape(str(ev["headline"]))}</p>',
             _table(facts, set(facts.columns[4:])),
             f'<p class="note">Public catalysts detected: {html.escape(", ".join(flags)) if flags else "none"}</p>']

    days = lead["days"]
    if len(days):
        window = days["k"].map(lambda k: "pre" if config.PRE_WINDOW[0] <= k <= config.PRE_WINDOW[1]
                               else "Day 0" if k == 0 else "")
        d = pd.DataFrame({
            "Day": days["k"].map(lambda k: "Day 0" if k == 0 else f"t{k:+d}"), "Date": days["date"].dt.strftime("%Y-%m-%d"),
            "Window": window, "Stock AR": days["ar"].map(_pct), "Volume x": days["vol_x"].map(lambda v: f"{v:.2f}x"),
            f"OTM {side} vol (news side)": days["news_otm_vol"].map(_int),
            "OTM vol (wrong side)": days["wrong_otm_vol"].map(_int),
            "Call OI": days["call_oi"].map(_int), "Put OI": days["put_oi"].map(_int),
        })
        parts += ["<h3>Day by day</h3><p class=\"note\">Front-month options at least "
                  f"{config.OTM_MIN_MONEYNESS:.0%} out of the money, volume in contracts. Volume x is the stock's "
                  "volume against its [t-35, t-6] average.</p>", _table(d, set(d.columns[3:]))]

    c = lead["contracts"]
    parts.append(f"<h3>News-side contracts traded before the news ({side})</h3>")
    if len(c):
        t = pd.DataFrame({
            "Expiry": c["expiry"].dt.strftime("%Y-%m-%d"), "Strike": c["strike"].map(lambda v: f"{v:,.2f}".rstrip("0").rstrip(".")),
            "OTM at t-1": c["moneyness_t1"].map(lambda v: f"{abs(v):.1%}"), "Pre-window vol": c["pre_vol"].map(_int),
            "Baseline daily vol": c["base_daily_vol"].map(lambda v: f"{v:,.1f}"),
            "x baseline": c["pre_vs_base"].map(lambda v: "new" if v == float("inf") else f"{v:.1f}x"),
            "OI t-6": c["oi_t6"].map(_int), "OI t-1": c["oi_t1"].map(_int),
            "Premium t-1": c["premium_t1"].map(lambda v: "" if pd.isna(v) else f"{v:.2f}"),
            "Premium Day 0": c["premium_day0"].map(lambda v: "" if pd.isna(v) else f"{v:.2f}"),
            "Premium chg": c["premium_chg"].map(_pct),
        })
        parts += ["<p class=\"note\">Ranked by pre-window [t-5, t-1] volume. \"x baseline\" compares the "
                  "pre-window daily average with the contract's own [t-35, t-6] average (\"new\" = no baseline "
                  "trades). Premiums are exchange closing prices; thinly traded contracts may close at stale "
                  "prices.</p>", _table(t, set(t.columns[1:]))]
    else:
        parts.append("<p>No news-side OTM contract traded in the pre-window.</p>")

    mins = lead.get("minutes") or []
    if mins:
        parts.append("<h3>When were they bought? (1-minute data)</h3><p class=\"note\">Upstox 1-minute bars from "
                     "t-5 up to the public time. A large share in the first 15 minutes of a session points to a "
                     "reaction to overnight public news; a large share in the last hour before the filing points "
                     "to positioning just ahead of it.</p>")
        for m in mins:
            sess = ", ".join(f"{d:%m-%d}: {v:,.0f}" for d, v in m["by_session"].items())
            top = pd.DataFrame({"Minute (IST)": m["top_minutes"].index.strftime("%Y-%m-%d %H:%M"),
                                "Contracts": m["top_minutes"]["contracts"].map(_int),
                                "Premium": m["top_minutes"]["close"].map(lambda v: f"{v:.2f}")})
            parts += [f"<p><strong>{html.escape(m['label'])}</strong> &middot; {m['total_contracts']:,.0f} contracts "
                      f"before the news &middot; first 15 min of sessions: {m['opening_share']:.0%} &middot; "
                      f"last 60 trading min before the news: {m['last_hour_share']:.0%}<br>"
                      f"<span class=\"note\">By session: {html.escape(sess)}</span></p>", _table(top, {"Contracts", "Premium"})]

    ins = lead.get("insider")
    parts.append(f"<h3>Reported insider trades, {-config.INSIDER_WINDOW[0]} sessions before Day 0</h3>")
    if lead.get("insider_error"):
        parts.append(f"<p class=\"note\">Insider data failed: {html.escape(lead['insider_error'])}</p>")
    elif ins is not None and len(ins):
        it = pd.DataFrame({"Category": ins["category"], "Side": ins["kind"], "Trades": ins["trades"].map(_int),
                           "Value (Rs cr)": (ins["value"] / 1e7).map(lambda v: f"{v:,.2f}")})
        parts += ["<p class=\"note\">SEBI PIT disclosures via BSE, by trade date. Names are not shown.</p>",
                  _table(it, {"Trades", "Value (Rs cr)"})]
    else:
        parts.append("<p>No reported insider trades in the window.</p>")

    so = lead.get("sebi")
    parts.append("<h3>SEBI enforcement orders mentioning the company</h3>")
    if lead.get("sebi_error"):
        parts.append(f"<p class=\"note\">SEBI search failed: {html.escape(lead['sebi_error'])}</p>")
    elif so is not None and len(so):
        rel = so[so["relevant"]]
        rows = "".join(f'<li>{d:%Y-%m-%d} &middot; <a href="{html.escape(u)}">{html.escape(t[:150])}</a></li>'
                       for d, t, u in zip(rel["date"], rel["title"], rel["url"]))
        parts.append(f"<p class=\"note\">{len(so)} orders match the company name; {len(rel)} concern insider "
                     "trading or leaked price-sensitive information. Orders usually come one to three years after "
                     "the trades, so none may exist yet for this event.</p>" + (f"<ul>{rows}</ul>" if rows else ""))
    else:
        parts.append("<p>No orders found.</p>")

    f = lead["filings"]
    parts.append("<h3>Exchange filings around the event</h3>")
    if len(f):
        ft = pd.DataFrame({"Time (IST)": f["timestamp"].dt.strftime("%Y-%m-%d %H:%M"),
                           "Classified as": f["event_type"].fillna("routine"),
                           "Subject": (f["subject"] + " | " + f["headline"]).str.slice(0, 120)})
        parts.append(_table(ft))
    else:
        parts.append("<p>No BSE filings in the window.</p>")

    pr = lead["press"]
    parts.append("<h3>Press coverage before the filing</h3>")
    if lead.get("press_error"):
        parts.append(f"<p class=\"note\">Press search failed: {html.escape(lead['press_error'])}</p>")
    elif len(pr):
        pt = pd.DataFrame({"Date": pr["date"].dt.strftime("%Y-%m-%d"),
                           "Matches story": pr["match"].map({True: "yes", False: ""}),
                           "Before filing day": pr["before"].map({True: "yes", False: ""}),
                           "Source": pr["source"].str.slice(0, 30), "Title": pr["title"].str.slice(0, 120)})
        parts += ["<p class=\"note\">Google News search for the company; dates only (no times), and results "
                  "vary between runs, so absence of coverage is not proof the story was private.</p>",
                  _table(pt)]
    else:
        parts.append("<p>No articles returned.</p>")
    return "\n".join(parts)


def build_drilldown(leads: list[dict], meta: dict) -> str:
    """One page with a section per lead: event facts, day-by-day flow, contracts, filings, press."""
    toc = "".join(f'<li><a href="#{html.escape(l["anchor"])}">{html.escape(l["event"]["symbol"])} '
                  f'{l["event"]["day0"]:%Y-%m-%d}</a> &middot; {html.escape(str(l["event"]["event_type"]))}</li>'
                  for l in leads)
    body = "\n".join(_lead_section(l) for l in leads)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Option Flow Drill-down</title>
<style>
{_CSS}
a {{ color: var(--series-1); }}
</style>
</head>
<body>
<main>
<h1>Directional option flow: event drill-down</h1>
<p class="lede">{html.escape(meta['source'])} &middot; {len(leads)} events</p>
<p class="note">Each event had significant short-dated out-of-the-money option volume on the side that profits from
the news, above the wrong side. These are statistical leads, not findings of wrongdoing. Look for: press
coverage before the filing (the news was already public), the contracts' timing and size, and the premium jump
on Day 0.</p>
<ul>{toc}</ul>
{body}
</main>
</body>
</html>
"""
