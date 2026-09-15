'use client';
import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, ArrowUpRight, BookOpen, Check, ChevronRight, CircleHelp, Download, FileText, FolderOpen, History, Layers3, LoaderCircle, Plus, Search, Settings2, Sparkles, Sprout, X } from 'lucide-react';
import ArtifactView from '../components/ArtifactView';
import { api, Artifact, AuthStatus, Health, Project, ProjectSummary, Stage, stages, stageDescriptions, stageLabels } from '../lib/types';

const sample = { title: 'Paper Reading Assistant for Students', idea: 'I want to build an app that helps university students manage academic reading. Users can save papers, organize reading notes, and filter them by research topic. I want the project to demonstrate end-to-end product design and development skills.', constraints: 'Solo developer; 4 weeks; comfortable with Python and React; web first; $20 monthly budget.' };
type Mode = 'demo' | 'live';

function AuthGate({ status, onAuthenticated }: { status: AuthStatus; onAuthenticated: (status: AuthStatus) => void }) {
  const [register, setRegister] = useState(false), [email, setEmail] = useState(''), [password, setPassword] = useState(''), [invite, setInvite] = useState('');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await api(register ? '/auth/register' : '/auth/login', register ? { email, password, invite_code: invite } : { email, password });
      onAuthenticated(await api<AuthStatus>('/auth/status'));
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }
  return <main className="auth-page"><section className="auth-card"><span className="brand-mark"><Sprout size={28} /></span><span className="eyebrow">IDEA ATELIER / V2</span><h1>{register ? 'Create your workspace' : 'Welcome back'}</h1><p>{register ? 'Use the invite code from the workspace owner.' : 'Sign in to continue your project planning.'}</p><form onSubmit={submit}><label htmlFor="auth-email">Email</label><input id="auth-email" type="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} /><label htmlFor="auth-password">Password</label><input id="auth-password" type="password" autoComplete={register ? 'new-password' : 'current-password'} minLength={register ? 12 : 1} required value={password} onChange={event => setPassword(event.target.value)} />{register && <><label htmlFor="auth-invite">Invite code</label><input id="auth-invite" type="password" required value={invite} onChange={event => setInvite(event.target.value)} /></>}{error && <div className="form-error" role="alert">{error}</div>}<button className="primary full" disabled={busy}>{busy && <LoaderCircle className="spin" size={17} />}{register ? 'Create account' : 'Sign in'}<ArrowRight size={17} /></button></form>{status.registration_enabled && <button className="auth-switch" onClick={() => { setRegister(!register); setError(''); }}>{register ? 'Already have an account? Sign in' : 'Have an invite? Create an account'}</button>}</section></main>;
}

export default function Home() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [stage, setStage] = useState<Stage>('organize');
  const [tab, setTab] = useState('document');
  const [modal, setModal] = useState(false);
  const [settings, setSettings] = useState(false);
  const [history, setHistory] = useState(false);
  const [version, setVersion] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [idea, setIdea] = useState('');
  const [constraints, setConstraints] = useState('');
  const [mode, setMode] = useState<Mode>('demo');
  const [filter, setFilter] = useState('');
  const [feedback, setFeedback] = useState('');
  const [pivot, setPivot] = useState(false);
  const [revised, setRevised] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const selectedRef = useRef<string | null>(null);
  const formTitle = useRef<HTMLInputElement>(null);

  const loadList = useCallback(async () => setProjects(await api<ProjectSummary[]>('/projects')), []);
  useEffect(() => {
    Promise.all([api<Health>('/health').then(setHealth), api<AuthStatus>('/auth/status').then(async status => { setAuth(status); if (status.authenticated) await loadList(); })])
      .catch(() => setError('The backend did not finish waking up. Retry the connection, or check the Render service logs.'))
      .finally(() => setLoading(false));
    const saved = localStorage.getItem('brainstorm-project');
    if (saved) { selectedRef.current = saved; setSelected(saved); }
  }, [loadList]);

  useEffect(() => {
    if (!selected) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const data = await api<Project>(`/projects/${selected}`);
        if (!disposed) { setProject(data); if (data.runs.some(r => r.status === 'running')) timer = setTimeout(poll, 1200); }
      } catch (e) { if (!disposed) setError((e as Error).message); }
    }
    void poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [selected, busy]);

  useEffect(() => {
    if (modal) formTitle.current?.focus();
    const close = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) { setModal(false); setSettings(false); } };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [modal, busy]);

  function choose(p: ProjectSummary | Project) {
    selectedRef.current = p.id; setSelected(p.id); setProject('artifacts' in p ? p : null);
    localStorage.setItem('brainstorm-project', p.id);
    setStage('organize'); setTab('document'); setVersion(null); setHistory(false); setFeedback(''); setError(''); setNotice(''); setPivot(false);
  }
  function chooseStage(s: Stage) { setStage(s); setVersion(null); setTab(s === 'prototype' ? 'preview' : 'document'); setFeedback(''); setHistory(false); setPivot(false); }
  async function create(e: FormEvent) {
    e.preventDefault();
    const words = idea.trim() ? idea.trim().split(/\s+/).length : 0;
    if (!title.trim() || words < 10) {
      setError(!title.trim() ? 'Add a project name to continue.' : `Describe your idea with at least 10 words. Add ${10 - words} more.`);
      return;
    }
    setBusy(true); setError('');
    try { const p = await api<Project>('/projects', { title, idea, constraints, mode }); choose(p); setModal(false); setTitle(''); setIdea(''); setConstraints(''); await loadList(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const active = (s: Stage) => project?.artifacts.find(a => a.stage === s && a.valid);
  const current = active(stage);
  const artifact = version ? project?.artifacts.find(a => a.id === version) : current;
  const index = stages.indexOf(stage);
  const running = project?.runs.find(r => r.status === 'running');
  const latestRun = project?.runs.find(r => r.stage === stage);
  const approvedCount = stages.filter(s => active(s)?.approved_at).length;
  const stopped = project?.decision === 'STOP';
  const unlocked = !stopped && stages.slice(0, index).every(s => active(s)?.approved_at) && (index < 2 || project?.decision === 'GO');

  async function generate() {
    if (!project) return;
    const id = project.id;
    setBusy(true); setError(''); setNotice(''); setVersion(null);
    try {
      await api(`/projects/${id}/stages/${stage}/generate`, { feedback });
      const p = await api<Project>(`/projects/${id}`);
      if (selectedRef.current === id) { setProject(p); setFeedback(''); }
      await loadList();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function accept(decision?: string) {
    if (!project || !current) return;
    const id = project.id;
    setBusy(true); setError('');
    try {
      const p = await api<Project>(`/projects/${id}/stages/${stage}/accept`, { artifact_id: current.id, decision: decision || null, revised_idea: revised });
      if (selectedRef.current === id) {
        setProject(p); setPivot(false); setRevised('');
        if (decision === 'PIVOT') { chooseStage('organize'); setNotice('The new direction is saved. Regenerate the idea brief, then research the revised direction.'); }
        else if (decision === 'STOP') setNotice('The project has been stopped. All artifacts and decisions are preserved.');
        else if (index < 4) { chooseStage(stages[index + 1]); setNotice('The previous stage is accepted. You can start the next step.'); }
        else setNotice('All five stages are accepted. Your project design pack is ready to export.');
      }
      await loadList();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function reconnect() {
    setError(''); setLoading(true);
    try {
      const [nextHealth, nextAuth] = await Promise.all([api<Health>('/health'), api<AuthStatus>('/auth/status')]);
      setHealth(nextHealth); setAuth(nextAuth);
      if (nextAuth.required && !nextAuth.authenticated) {
        setProjects([]); setSelected(null); setProject(null);
        return;
      }
      await loadList();
    } catch { setError('The backend is still unavailable. Check the startup logs.'); }
    finally { setLoading(false); }
  }
  async function logout() {
    await api('/auth/logout', {}); localStorage.removeItem('brainstorm-project'); setSelected(null); setProject(null); setProjects([]);
    setAuth(await api<AuthStatus>('/auth/status'));
  }
  const stageIcons = [FileText, Search, Layers3, Sparkles, FolderOpen];
  const StageIcon = stageIcons[index];
  const ideaWordCount = idea.trim() ? idea.trim().split(/\s+/).length : 0;
  const missingIdeaWords = Math.max(0, 10 - ideaWordCount);

  if (auth?.required && !auth.authenticated) return <AuthGate status={auth} onAuthenticated={async status => { setAuth(status); await loadList(); }} />;

  return <div className="app-shell">
    <aside className="sidebar">
      <button className="brand" onClick={() => { selectedRef.current = null; setSelected(null); setProject(null); localStorage.removeItem('brainstorm-project'); }} aria-label="Return to workspace home"><span className="brand-mark"><Sprout size={25} strokeWidth={1.7} /></span><span>Idea Atelier<small>Project Planning Workspace</small></span></button>
      <button className="new-button" onClick={() => setModal(true)}><Plus size={18} />New project<span>＋</span></button>
      <label className="project-search"><Search size={15} /><input aria-label="Search projects" value={filter} onChange={e => setFilter(e.target.value)} placeholder="Search projects…" /></label>
      <div className="section-label">MY PROJECTS <span>{projects.length.toString().padStart(2, '0')}</span></div>
      <nav className="project-list" aria-label="Project list">{projects.filter(p => p.title.toLowerCase().includes(filter.toLowerCase())).map(p => <button key={p.id} className={'project-link ' + (selected === p.id ? 'selected' : '')} onClick={() => choose(p)}><FolderOpen size={17} /><div><strong>{p.title}</strong><small>{p.mode === 'demo' ? 'Demo' : 'Live'} · {p.decision === 'STOP' ? 'Stopped' : `${p.accepted_count}/5  stages accepted`}</small></div>{selected === p.id && <span className="selected-dot" />}</button>)}{!loading && projects.length === 0 && <p className="sidebar-empty">Every good project<br />starts with a small idea.</p>}{projects.length > 0 && !projects.some(p => p.title.toLowerCase().includes(filter.toLowerCase())) && <p className="sidebar-empty">No matching projects.</p>}</nav>
      <div className="sidebar-bottom"><div className="workspace-note"><span className="status-dot" /><span>{auth?.required ? 'Private workspace' : 'Local workspace'}<small>Projects are saved automatically</small></span><span className="version-chip">V2</span></div><button className="settings-button" onClick={() => setSettings(true)}><Settings2 size={16} />Connection & settings<ArrowUpRight size={14} /></button></div>
    </aside>

    <main className="main">
      <header className="topbar"><div><span className="muted">Workspace</span><ChevronRight size={14} /><span>{project?.title || 'Overview'}</span></div><div><span className={'connection ' + (health ? 'online' : '')}><span />{health ? 'Service connected' : 'Waiting for backend'}</span>{auth?.required && <><span>{auth.user?.email}</span><button className="topbar-link" onClick={logout}>Sign out</button></>}<button className="icon-button" aria-label="Help & setup" onClick={() => setSettings(true)}><CircleHelp size={18} /></button></div></header>
      {error && <div className="alert error" role="alert">{error}{!health && <button onClick={reconnect}>Retry connection</button>}<button aria-label="Dismiss error" onClick={() => setError('')}><X size={16} /></button></div>}
      {notice && <div className="alert success" role="status">{notice}<button aria-label="Dismiss notice" onClick={() => setNotice('')}><X size={16} /></button></div>}
      {!selected ? <div className="overview">
        <div className="intro"><div><span className="eyebrow">FROM A SPARK TO A PLAN</span><h1>Give a good idea<br />a clear beginning<span>.</span></h1><p>Find evidence, then define the scope.<br />Turn a spark into a project you can build.</p><button className="primary" onClick={() => setModal(true)}><Plus size={17} />Start a new project<ArrowRight size={17} /></button></div><div className="idea-illustration" aria-hidden="true"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="orbit-dot" /><div className="paper paper-back"><span>RESEARCH</span><i /><i /><i /></div><div className="paper paper-front"><span>YOUR NEXT IDEA</span><Sprout size={57} strokeWidth={1.3} /><div className="paper-rule" /><small>Start with a real question</small></div><span className="illustration-note">a little curiosity goes a long way ↗</span><span className="spark">✳</span></div></div>
        <div className="journey-title"><h2>Five steps from idea to plan</h2><span>You choose the direction. The agent develops it.</span></div>
        <div className="journey">{stages.map((s, i) => { const Icon = stageIcons[i]; return <div className="journey-step" key={s}><span className="journey-number">0{i + 1}</span><Icon size={21} strokeWidth={1.5} /><h3>{stageLabels[i]}</h3><p>{stageDescriptions[i]}</p></div>; })}</div>
        <section className="recent-section"><div className="journey-title"><h2>Recent explorations <span className="count">{projects.length}</span></h2><span>Every decision stays traceable</span></div>{loading ? <div className="empty-inline"><LoaderCircle className="spin" size={22} />Connecting to your workspace…</div> : projects.length ? <div className="recent-grid">{projects.slice(0, 6).map(p => <button className="recent-card" key={p.id} onClick={() => choose(p)}><div><span className="folder-icon"><FolderOpen size={20} /></span><span className="tag">{p.mode === 'demo' ? 'Demo project' : 'Live project'}</span></div><h3>{p.title}</h3><p>{p.idea}</p><div className="progress-track"><span style={{ width: `${p.accepted_count * 20}%` }} /></div><footer><span>{p.decision === 'STOP' ? 'Stopped' : `${p.accepted_count} / 5 stages accepted`}</span><ArrowUpRight size={16} /></footer></button>)}</div> : <button className="empty-projects" onClick={() => { setTitle(sample.title); setIdea(sample.idea); setConstraints(sample.constraints); setMode('demo'); setModal(true); }}><span className="empty-icon"><BookOpen size={24} /></span><div><strong>No project yet? Start with an example.</strong><p>Try the Paper Reading Assistant workflow without an API key.</p></div><span className="text-link">Try the example <ArrowRight size={16} /></span></button>}</section>
        <footer className="overview-footer"><span>Evidence before assumptions. Clarity before code.</span><span>IDEA ATELIER / V2</span></footer>
      </div> : !project ? <div className="loading-page"><LoaderCircle className="spin" />Loading project…</div> : <div className="workspace">
        <section className="project-header"><div><div className="eyebrow">PROJECT WORKSPACE <span className="tag">{project.mode === 'demo' ? 'Demo mode' : 'Live'}</span>{stopped && <span className="tag">Stopped</span>}</div><h1>{project.title}</h1><p>{project.constraints || 'No constraints specified. Generation will state its assumptions.'}</p></div><a className="secondary" href={`/api/projects/${project.id}/export`} download><Download size={16} />Export design pack</a></section>
        {project.mode === 'demo' && <div className="demo-notice"><Sparkles size={15} /><span>This is a fixed demo. It does not call a model or perform live web search. Choose Live mode when creating a project.</span></div>}
        <nav className="stage-nav" aria-label="Five-stage workflow">{stages.map((s, i) => <button key={s} onClick={() => chooseStage(s)} className={(s === stage ? 'active ' : '') + (active(s)?.approved_at ? 'done' : '')}><span>{active(s)?.approved_at ? <Check size={16} /> : `0${i + 1}`}</span><div><strong>{stageLabels[i]}</strong><small>{active(s)?.approved_at ? 'Accepted' : running?.stage === s ? 'Generating' : active(s) ? 'Review' : 'Not started'}</small></div>{i < 4 && <ChevronRight className="stage-chevron" size={15} />}</button>)}</nav>
        <div className="work-grid"><section className="artifact-panel"><div className="artifact-title"><div><StageIcon size={19} /><h2>{stageLabels[index]}</h2>{artifact && <span className="tag">v{artifact.version} · {artifact.approved_at ? 'Accepted' : 'Draft'}{!artifact.valid ? ' · History' : ''}</span>}</div><button className={'icon-button ' + (history ? 'chosen' : '')} aria-label="Version history" onClick={() => setHistory(!history)}><History size={18} /></button></div>
          {history && <div className="history-list"><strong>Version history</strong>{project.artifacts.filter(a => a.stage === stage).length ? project.artifacts.filter(a => a.stage === stage).map(a => <button className={a.id === artifact?.id ? 'chosen' : ''} key={a.id} onClick={() => { setVersion(a.valid ? null : a.id); setTab('document'); }}><span>v{a.version} · {a.valid ? 'Current version' : 'Previous version'} · {a.decision || (a.approved_at ? 'Accepted' : 'Draft')}</span><small>{new Date(a.created_at).toLocaleString('en-US')}</small></button>) : <p>Every generated version will appear here.</p>}</div>}
          {artifact && <div className="tabs">{[...(stage === 'prototype' ? [['preview', 'Interactive preview']] : []), ['document', 'Artifact'], ['sources', `Sources ${artifact.metadata.sources.length}`], ['data', 'Structured data']].map(([key, label]) => <button key={key} onClick={() => setTab(key)} className={tab === key ? 'active' : ''}>{label}</button>)}</div>}
          {running?.stage === stage && <div className="generating" role="status"><LoaderCircle className="spin" size={18} /><div><strong>Generating {stageLabels[index]}…</strong><small>You can switch projects or refresh. The result will be saved locally.</small></div></div>}
          {latestRun?.status === 'failed' && <div className="alert error" role="alert">{latestRun.error} Retry from the panel on the right. Existing artifacts are preserved.</div>}
          {artifact ? <ArtifactView key={artifact.id} artifact={artifact} tab={tab} /> : !running && <div className="stage-empty"><div className="stage-empty-icon"><StageIcon size={32} strokeWidth={1.3} /></div><span className="eyebrow">STEP 0{index + 1}</span><h2>{stageDescriptions[index]}</h2><p>{stopped ? 'This project is stopped. You can review history or export its artifacts.' : unlocked ? 'Use the panel on the right to generate this stage. Then review, revise, and accept the result.' : 'Complete and accept the earlier stages to unlock this step.'}</p>{unlocked && <button className="primary" disabled={busy || !!running} onClick={generate}><Sparkles size={16} />Generate {stageLabels[index]}</button>}</div>}
        </section><aside className="action-rail"><section className="rail-card"><span className="eyebrow">NEXT STEP</span><h3>{stopped ? 'Exploration paused' : current?.approved_at ? 'Current artifact accepted' : current ? 'Shape the artifact around your idea' : 'Ready for the next step'}</h3><p>{current?.approved_at ? 'Continue to the next stage, or generate a revision with feedback.' : 'You accept each stage before moving forward.'}</p>
          {unlocked && <><label className="field-label" htmlFor="feedback">{current ? 'Revision notes (optional)' : 'Additional context (optional)'}</label><textarea id="feedback" maxLength={4000} rows={4} value={feedback} onChange={e => setFeedback(e.target.value)} placeholder="For example: reduce the scope and prioritize features that fit within four weeks…" /><button className="secondary full" onClick={generate} disabled={busy || !!running}><Sparkles size={16} />{current ? 'Generate revision' : `Generate ${stageLabels[index]}`}</button>{current && <small className="revision-note">A successful revision reopens this stage and all downstream stages. Earlier versions remain in history.</small>}</>}
          {current && !current.approved_at && !version && !stopped && (stage === 'research' ? <div className="decision-gate"><span className="field-label">Your final decision</span><button className="primary full" disabled={busy || !!running} onClick={() => accept('GO')}>GO · Continue planning<ArrowRight size={16} /></button><div className="decision-options"><button className="secondary" disabled={busy || !!running} onClick={() => setPivot(!pivot)}>PIVOT · Revise direction</button><button className="secondary" disabled={busy || !!running} onClick={() => accept('STOP')}>STOP · End project</button></div>{pivot && <div className="pivot-form"><label htmlFor="pivot">Complete revised idea</label><textarea id="pivot" rows={5} minLength={10} maxLength={12000} value={revised} onChange={e => setRevised(e.target.value)} placeholder="Describe the revised target user, problem, and scope (at least 10 characters)." /><small>Saving returns the workflow to stage one for a new brief and research pass.</small><button className="primary full" disabled={busy || !!running || revised.trim().length < 10} onClick={() => accept('PIVOT')}>Save revised direction</button></div>}</div> : <button className="primary full accept-button" disabled={busy || !!running} onClick={() => accept()}><Check size={16} />{index === 4 ? 'Accept and complete project' : 'Accept and continue'}</button>)}
          {current?.approved_at && index < 4 && !stopped && <button className="primary full accept-button" onClick={() => chooseStage(stages[index + 1])}>Go to {stageLabels[index + 1]}<ArrowRight size={16} /></button>}
        </section><section className="rail-card progress-card"><div><strong>Project progress</strong><span>{approvedCount} / 5</span></div><div className="progress-track"><span style={{ width: `${approvedCount * 20}%` }} /></div><p>{approvedCount === 5 ? 'The design pack is complete and ready to export.' : 'Move from evidence to implementation, one step at a time.'}</p></section><details className="rail-card idea-details"><summary>Original idea</summary><p>{project.idea}</p></details><div className="rail-footnote"><Sprout size={19} /><p>A good project can be small,<br />as long as every choice is clear.</p></div></aside></div>
      </div>}
    </main>

    {modal && <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget && !busy) setModal(false); }}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="create-title"><button className="modal-close icon-button" aria-label="Close new project dialog" onClick={() => setModal(false)} disabled={busy}><X size={20} /></button><span className="eyebrow">A NEW EXPLORATION</span><h2 id="create-title">What will you build next?</h2><p className="muted">It does not need to be complete. A short description is a good place to start.</p><form onSubmit={create}><label htmlFor="title">Project name</label><input id="title" ref={formTitle} required maxLength={120} value={title} onChange={e => setTitle(e.target.value)} placeholder="Give your idea a working title" /><label htmlFor="idea">Describe your idea</label><textarea id="idea" required maxLength={12000} rows={5} value={idea} onChange={e => setIdea(e.target.value)} placeholder="Who will it help, what problem will it solve, and what do you want to build? Write at least 10 words." /><small className={'input-hint ' + (missingIdeaWords ? 'invalid' : 'valid')}>{missingIdeaWords ? `At least 10 words · ${missingIdeaWords} more needed` : `At least 10 words · ${ideaWordCount} entered`}</small><label htmlFor="constraints">Time, skills, and budget <span className="muted">optional</span></label><textarea id="constraints" rows={2} maxLength={4000} value={constraints} onChange={e => setConstraints(e.target.value)} placeholder="For example: solo developer, 4 weeks, Python, $20/month" /><fieldset><legend>Generation mode</legend><label className={'mode-option ' + (mode === 'demo' ? 'selected' : '')}><input type="radio" name="mode" checked={mode === 'demo'} onChange={() => setMode('demo')} /><div><strong>Demo experience</strong><small>Fixed example · no API calls</small></div></label><label className={'mode-option ' + (mode === 'live' ? 'selected' : '')}><input type="radio" name="mode" checked={mode === 'live'} disabled={!health?.live_available} onChange={() => setMode('live')} /><div><strong>Live generation</strong><small>{health?.live_available ? 'Model generation + live search · uses API credits' : 'Configure the backend API key first'}</small></div></label></fieldset>{error && <div className="form-error" role="alert">{error}</div>}<button className="primary full" disabled={busy || !health || !title.trim() || missingIdeaWords > 0}>{busy ? <LoaderCircle className="spin" size={18} /> : <Plus size={18} />}{!health ? 'Waiting for backend…' : !title.trim() ? 'Create project · add a project name' : missingIdeaWords ? `Create project · add ${missingIdeaWords} more words` : 'Create project'}{health && title.trim() && !missingIdeaWords && <ArrowRight size={18} />}</button></form></section></div>}
    {settings && <div className="modal-backdrop"><section className="modal settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title"><button className="modal-close icon-button" aria-label="Close settings" onClick={() => setSettings(false)}><X size={20} /></button><span className="eyebrow">YOUR WORKSPACE</span><h2 id="settings-title">Connection & usage</h2><div className="settings-status"><span className="status-dot" />Backend: {health ? 'Connected' : 'Not connected'}<br />Access: {auth?.required ? `Private · ${auth.user?.email}` : 'Local development'}<br />Live generation: {health?.live_available ? 'API key configured' : 'API key not configured'}<br />Model: {health?.model || 'Loading'}</div><h3>How it works</h3><p>Generate and accept each stage in order. After research, you choose GO, PIVOT, or STOP. Version history preserves earlier artifacts, and exports include Markdown, JSON, a function CSV, prototype HTML, and Mermaid architecture.</p><p className="muted">Demo projects use fixed content. Live projects use the server-side OpenAI API key and count toward the deployment quota.</p><button className="secondary full" onClick={reconnect}>Refresh connection status</button></section></div>}
  </div>;
}
