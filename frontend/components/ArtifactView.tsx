'use client';
import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ExternalLink } from 'lucide-react';
import type { Artifact } from '../lib/types';

function safeLink(url: string) { return /^https?:\/\//i.test(url) ? url : undefined; }

export function Markdown({ text }: { text: string }) {
  return <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ href, children }) => <a href={href && safeLink(href)} target="_blank" rel="noopener noreferrer">{children}</a>, img: ({ alt }) => <span>[Image: {alt}]</span> }}>{text}</ReactMarkdown></div>;
}

function Diagram({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setError(false);
    import('mermaid').then(async ({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'neutral', suppressErrorRendering: true });
      const { svg } = await mermaid.render('diagram-' + crypto.randomUUID(), code);
      if (!cancelled && ref.current) ref.current.innerHTML = svg;
    }).catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [code]);
  return <div className="diagram">{error ? <p>The diagram could not be rendered. Review the Mermaid source below.</p> : <div ref={ref} />}<details><summary>Mermaid source</summary><pre>{code}</pre></details></div>;
}

export default function ArtifactView({ artifact, tab }: { artifact: Artifact; tab: string }) {
  const c = artifact.content;
  if (tab === 'sources') return <div className="sources-view"><h2>Research sources</h2><p className="muted">{artifact.metadata.searched_at ? `Searched: ${new Date(artifact.metadata.searched_at).toLocaleString('zh-CN')}` : 'This version has no live search record.'}</p>{artifact.metadata.sources.length === 0 ? <div className="empty-inline">{artifact.metadata.mode === 'demo' ? 'Demo mode does not run Web Search and is not research evidence.' : 'This stage did not run Web Search. Review the Research stage.'}</div> : artifact.metadata.sources.map((s, i) => <a className="source-card" key={s.url} href={safeLink(s.url)} target="_blank" rel="noopener noreferrer"><span className="source-number">{String(i + 1).padStart(2, '0')}</span><div><strong>{s.title}</strong><small>{s.url}</small></div><ExternalLink size={16} /></a>)}{!!artifact.metadata.queries?.length && <><h3>Search queries used</h3><ul>{artifact.metadata.queries.map(q => <li key={q}>{q}</li>)}</ul></>}{artifact.metadata.search_text && <details><summary>Raw search report (citation positions are recorded in the export)</summary><pre className="wrap">{artifact.metadata.search_text}</pre></details>}</div>;
  if (tab === 'data') return <pre className="json-view">{JSON.stringify(c, null, 2)}</pre>;
  if (tab === 'preview' && c.html) {
    // An opaque-origin iframe can run prototype JS, but cannot access the app or network.
    const policy = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'">`;
    return <div className="preview-wrap"><div className="preview-bar"><span className="dots">● ● ●</span><span>Interactive prototype · isolated sandbox</span><span>See the prototype notes for mocked behavior</span></div><iframe title="Project prototype" sandbox="allow-scripts allow-forms" referrerPolicy="no-referrer" srcDoc={policy + c.html} /></div>;
  }
  return <div className="document-content">
    {c.recommendation && <div className="recommendation"><span className="eyebrow">AGENT RECOMMENDATION</span><strong>{c.recommendation}</strong><p>{c.rationale}</p></div>}
    <Markdown text={c.markdown} />
    {!!c.comparisons?.length && <div className="comparison-grid">{c.comparisons.map((r, i) => <section className="comparison" key={i}><span className="tag">{r.evidence}</span><h3>{r.name}</h3><p><b>Overlap: </b>{r.overlap}</p><p><b>Difference: </b>{r.difference}</p>{r.source_urls.map((u, n) => <a key={u} href={safeLink(u)} target="_blank" rel="noopener noreferrer">Source {n + 1} ↗ </a>)}</section>)}</div>}
    {c.functions && <><div className="estimate-summary">{(['low_days', 'likely_days', 'high_days'] as const).map((k, i) => <div key={k}><span>{['Low estimate', 'Likely estimate', 'High estimate'][i]}</span><strong>{Number(c.functions!.reduce((n, f) => n + f[k], 0).toFixed(2))}<small> person-days</small></strong><span>{c.currency} {(c.functions!.reduce((n, f) => n + f[k], 0) * (c.daily_rate ?? 0)).toLocaleString(undefined, { maximumFractionDigits: 2 })}</span></div>)}</div><p className="muted">All functions · daily rate assumption: {c.currency} {c.daily_rate} / person-day · operating costs excluded</p><div className="table-scroll"><table><thead><tr><th>Function / source</th><th>Scope</th><th>Dependencies</th><th>Person-days low / likely / high</th></tr></thead><tbody>{c.functions.map(f => <tr key={f.id}><td><span className="mono">{f.id} · {f.requirement}</span><strong>{f.name}</strong><small>{f.value}</small><small>Risk: {f.risk}</small></td><td><span className={'tag ' + (f.tier === 'MVP' ? 'green' : '')}>{f.tier}</span></td><td>{f.dependencies.join(', ') || '—'}</td><td className="nowrap">{f.low_days} / {f.likely_days} / {f.high_days}</td></tr>)}</tbody></table></div></>}
    {c.mermaid && <Diagram code={c.mermaid} />}
    {c.components && <div className="component-grid">{c.components.map((item, i) => <section className="comparison" key={i}><h3>{item.name}</h3><p>{item.responsibility}</p><span className="mono">{item.function_ids.join(' · ')}</span></section>)}</div>}
    {c.mappings && <div className="mapping-list">{c.mappings.map(m => <div key={m.function_id}><code>{m.function_id}</code><span>{m.implementation}</span><span className="tag">{m.behavior}</span></div>)}</div>}
    {[['Assumptions to confirm', c.assumptions], ['Uncertainty', c.uncertainty], ['Tradeoffs', c.tradeoffs], ['Suggested search terms', c.search_terms]].map(([title, items]) => Array.isArray(items) && items.length > 0 ? <section className="notes" key={title as string}><h3>{title}</h3><ul>{items.map((item, i) => <li key={i}>{item}</li>)}</ul></section> : null)}
  </div>;
}
