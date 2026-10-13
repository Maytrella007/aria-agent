<script lang="ts">
  import { onMount } from 'svelte';
  import { api, subscribe } from '$lib/api';

  // --- Types ---
  interface MirrorStatus {
    mirror: { exists?: boolean; improve_branches?: number; error?: string };
    counters: Record<string, number>;
  }

  interface QueueItem {
    id: string;
    target_file: string;
    modification_type: string;
    reason: string;
    initiated_by: string;
    status: string;
    commit_sha?: string;
    timestamp: string;
    tier: number;
    tier_label: string;
    feedback_sent?: boolean;
    feedback?: string;
    feedback_at?: string;
    validation_result?: { syntax?: string; imports?: string; tests?: string } | null;
    diff_lines?: number[];
  }

  interface ChangeDetail {
    id: string;
    target_file: string;
    modification_type: string;
    reason: string;
    initiated_by: string;
    status: string;
    commit_sha?: string;
    timestamp: string;
    tier: number;
    tier_label: string;
    model?: string;
    trigger?: string;
    cycle?: number | string;
    confidence?: number;
    mirror_sha?: string;
    real_sha?: string;
    diff?: string;
    diff_add?: number;
    diff_del?: number;
    validation?: {
      syntax?: { status: string; detail?: string; time?: string };
      imports?: { status: string; detail?: string; time?: string };
      tests?: { status: string; detail?: string; count?: number; time?: string };
    };
  }

  interface HistoryItem {
    id: string;
    target_file: string;
    modification_type: string;
    reason: string;
    status: string;
    timestamp: string;
    tier: number;
    tier_label: string;
    initiated_by?: string;
  }

  interface AuditItem {
    id: string;
    target_file: string;
    modification_type: string;
    status: string;
    timestamp: string;
    initiated_by?: string;
    tier: number;
    tier_label: string;
  }

  // --- State ---
  let loading = $state(true);
  let error = $state('');
  let mirrorStatus: MirrorStatus | null = $state(null);
  let pendingItems: QueueItem[] = $state([]);
  let selectedId: string | null = $state(null);
  let detail: ChangeDetail | null = $state(null);
  let detailLoading = $state(false);
  let fileHistory: HistoryItem[] = $state([]);
  let auditItems: AuditItem[] = $state([]);
  let promoting = $state(false);
  let rejecting = $state(false);
  let rejectReason = $state('');
  let showRejectDialog = $state(false);

  // --- Derived ---
  let pendingCount = $derived(pendingItems.length);
  let failedCount = $derived(pendingItems.filter(i => itemStatus(i) === 'failed').length);
  let staleCount = $derived(pendingItems.filter(i => itemStatus(i) === 'stale').length);
  function getTodayCount(s: MirrorStatus | null): number {
    return s?.counters?.today ?? s?.counters?.promotions_today ?? 0;
  }
  function getSyncLabel(s: MirrorStatus | null): string {
    return s?.mirror?.error ? 'error' : s?.mirror?.exists ? 'synced' : 'offline';
  }
  let todayCount = $derived(getTodayCount(mirrorStatus));
  let syncLabel = $derived(getSyncLabel(mirrorStatus));
  function getSyncClass(label: string): string {
    return label === 'error' || label === 'offline' ? 'is-down' : '';
  }
  let syncClass = $derived(getSyncClass(syncLabel));
  let selectedItem = $derived(pendingItems.find(i => i.id === selectedId) ?? null);

  // --- Helpers ---
  function itemStatus(item: QueueItem): string {
    if (item.validation_result) {
      const vr = item.validation_result;
      if (vr.syntax === 'fail' || vr.imports === 'fail' || vr.tests === 'fail') return 'failed';
      if (vr.syntax === 'run' || vr.imports === 'run' || vr.tests === 'run') return 'validating';
    }
    if (item.status === 'pending') {
      const ts = new Date(item.timestamp).getTime();
      const age = Date.now() - ts;
      if (age > 30 * 60 * 1000) return 'stale';
      return 'ready';
    }
    return item.status;
  }

  function itemStatusClass(item: QueueItem): string {
    const s = itemStatus(item);
    if (s === 'failed') return 'is-failed';
    if (s === 'stale') return 'is-stale';
    if (s === 'validating') return 'is-validating';
    if (s === 'ready') return 'is-ready';
    return '';
  }

  function tierClass(tier: number): string {
    if (tier === 1) return 't1';
    if (tier === 3) return 't3';
    return 't2';
  }

  function tierLabel(tier: number, label: string): string {
    return label?.toUpperCase() ?? `T${tier}`;
  }

  function relativeTime(ts: string): string {
    const diff = Date.now() - new Date(ts).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  }

  function formatTime(ts: string): string {
    try {
      const d = new Date(ts);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return ts;
    }
  }

  function gateStatus(detail: ChangeDetail, gate: string): string {
    const v = detail?.validation;
    if (!v) return 'skip';
    const g = v[gate as keyof typeof v];
    if (!g) return 'skip';
    return g.status ?? 'skip';
  }

  function gateLabel(detail: ChangeDetail, gate: string): string {
    const v = detail?.validation;
    if (!v) return '';
    const g = v[gate as keyof typeof v];
    if (!g) return '';
    return g.detail ?? '';
  }

  function gateTime(detail: ChangeDetail, gate: string): string {
    const v = detail?.validation;
    if (!v) return '';
    const g = v[gate as keyof typeof v];
    if (!g) return '';
    return g.time ?? '';
  }

  function gateSub(detail: ChangeDetail, gate: string): string {
    const parts: string[] = [];
    const lbl = gateLabel(detail, gate);
    const t = gateTime(detail, gate);
    if (lbl) parts.push(lbl);
    if (t) parts.push(t);
    return parts.join(' \u00b7 ');
  }

  function gateSymbol(status: string): string {
    if (status === 'pass') return '\u2713';
    if (status === 'fail') return '\u2717';
    if (status === 'run') return '\u2026';
    return '';
  }

  interface DiffLine {
    type: 'add' | 'del' | 'hunk' | 'ctx';
    lineNum: string;
    text: string;
  }

  function parseDiff(raw: string | undefined): DiffLine[] {
    if (!raw) return [];
    const lines = raw.split('\n');
    const result: DiffLine[] = [];
    let lineCounter = 0;
    for (const line of lines) {
      if (line.startsWith('@@')) {
        const match = line.match(/@@ [^+]*\+(\d+)/);
        if (match) lineCounter = parseInt(match[1], 10);
        result.push({ type: 'hunk', lineNum: '', text: line });
      } else if (line.startsWith('+')) {
        result.push({ type: 'add', lineNum: String(lineCounter), text: line });
        lineCounter++;
      } else if (line.startsWith('-')) {
        result.push({ type: 'del', lineNum: '', text: line });
      } else {
        result.push({ type: 'ctx', lineNum: String(lineCounter), text: line });
        lineCounter++;
      }
    }
    return result;
  }

  // --- Data fetching ---
  async function loadStatus() {
    try {
      mirrorStatus = await api<MirrorStatus>('mirror/status');
    } catch {
      mirrorStatus = null;
    }
  }

  async function loadPending() {
    try {
      const data = await api<{ items: QueueItem[]; total: number }>('mirror/pending');
      pendingItems = data.items ?? [];
    } catch {
      pendingItems = [];
    }
  }

  async function loadDetail(id: string) {
    detailLoading = true;
    detail = null;
    fileHistory = [];
    try {
      detail = await api<ChangeDetail>('mirror/changes/' + id);
      if (detail?.target_file) {
        loadFileHistory(detail.target_file);
      }
    } catch {
      detail = null;
    } finally {
      detailLoading = false;
    }
  }

  async function loadFileHistory(path: string) {
    try {
      const data = await api<{ items: HistoryItem[] }>('mirror/file-history/' + path);
      fileHistory = data.items ?? [];
    } catch {
      fileHistory = [];
    }
  }

  async function loadAudit() {
    try {
      const data = await api<{ items: AuditItem[] }>('mirror/changes', { params: { status: 'all' } });
      auditItems = (data.items ?? [])
        .filter(i => i.status === 'promoted' || i.status === 'rejected')
        .slice(0, 10);
    } catch {
      auditItems = [];
    }
  }

  function selectItem(id: string) {
    selectedId = id;
    loadDetail(id);
  }

  async function handleReject() {
    if (!selectedId) return;
    rejecting = true;
    try {
      await api('mirror/reject/' + selectedId, {
        method: 'POST',
        body: { reason: rejectReason || 'User rejected mirror promotion', initiated_by: 'user' }
      });
      showRejectDialog = false;
      rejectReason = '';
      selectedId = null;
      detail = null;
      await refresh();
    } catch {
      // error handled silently
    } finally {
      rejecting = false;
    }
  }

  async function handlePromote() {
    const ids = selectedId ? [selectedId] : pendingItems.map(i => i.id);
    if (ids.length === 0) return;
    promoting = true;
    try {
      await api('mirror/promote', {
        method: 'POST',
        body: { ids, initiated_by: 'user' }
      });
      selectedId = null;
      detail = null;
      await refresh();
    } catch {
      // error handled silently
    } finally {
      promoting = false;
    }
  }

  async function refresh() {
    await Promise.all([loadStatus(), loadPending(), loadAudit()]);
  }

  onMount(() => {
    (async () => {
      try {
        await refresh();
        if (pendingItems.length > 0 && !selectedId) {
          selectItem(pendingItems[0].id);
        }
      } catch {
        error = 'Failed to load mirror data';
      } finally {
        loading = false;
      }
    })();

    const unsub = subscribe('mirror/events', (event: any) => {
      if (event.type === 'queue_changed' || event.type === 'promoted' || event.type === 'frozen') {
        refresh();
        if (selectedId && detail) {
          loadDetail(selectedId);
        }
      }
    });

    return () => {
      unsub();
    };
  });

  function getDetailDiff(d: ChangeDetail | null): string | undefined { return d?.diff; }
  function getDetailDiffAdd(d: ChangeDetail | null): number | undefined { return d?.diff_add; }
  function getDetailDiffDel(d: ChangeDetail | null): number | undefined { return d?.diff_del; }
  let diffLines = $derived(parseDiff(getDetailDiff(detail)));
  let diffAdd = $derived(getDetailDiffAdd(detail) ?? diffLines.filter(l => l.type === 'add').length);
  let diffDel = $derived(getDetailDiffDel(detail) ?? diffLines.filter(l => l.type === 'del').length);

  // --- Keyboard shortcuts ---
  function handleKeydown(e: KeyboardEvent) {
    // Ignore when typing in inputs/textareas
    const tag = (e.target as HTMLElement)?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    if ((e.target as HTMLElement)?.isContentEditable) return;

    // Only active when a change is selected and detail is loaded
    if (!selectedId || !detail) return;

    if (e.key === 'p' && !promoting) {
      e.preventDefault();
      handlePromote();
    } else if (e.key === 'r' && !rejecting) {
      e.preventDefault();
      showRejectDialog = true;
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if loading}
  <div class="mirror-loading">
    <div class="diamond diamond--accent" aria-hidden="true"></div>
    <span>Loading Mirror...</span>
  </div>
{:else if error}
  <div class="mirror-loading">
    <span class="error-text">{error}</span>
  </div>
{:else}
  <!-- HEADER -->
  <header class="mirror-header">
    <h1>Mirror</h1>
    <span class="h-sep" aria-hidden="true"></span>

    <div class="sync-state {syncClass}" role="status" aria-label="Mirror synchronization state">
      <span class="sync-bar" aria-hidden="true"><i></i></span>
      <span class="label">{syncLabel}</span>
      {#if mirrorStatus?.mirror?.improve_branches != null}
        <span class="meta">{mirrorStatus.mirror.improve_branches} branches</span>
      {/if}
    </div>

    <span class="h-sep" aria-hidden="true"></span>

    <div class="counters" aria-label="Pending change summary">
      <span class="ctr" class:is-warn={pendingCount > 0}>
        <span class="n">{pendingCount}</span> pending
      </span>
      <span class="ctr-sep">&middot;</span>
      <span class="ctr" class:is-danger={failedCount > 0}>
        <span class="n">{failedCount}</span> failed
      </span>
      <span class="ctr-sep">&middot;</span>
      <span class="ctr" class:is-warn={staleCount > 0}>
        <span class="n">{staleCount}</span> stale
      </span>
      <span class="ctr-sep">&middot;</span>
      <span class="ctr">
        <span class="n">{todayCount}</span> today
      </span>
    </div>

    <a href="#audit" class="audit-link" aria-label="Jump to audit log section">
      audit log <span aria-hidden="true">&rarr;</span>
    </a>
  </header>

  <!-- BODY -->
  <div class="mirror-body">
    <!-- QUEUE SIDEBAR -->
    <aside class="queue" aria-label="Pending changes queue">
      <div class="queue-head">
        <h2>queue &middot; prioritized</h2>
      </div>

      {#if pendingItems.length === 0}
        <div class="queue-empty">
          <div class="diamond diamond--accent" aria-hidden="true"></div>
          <span>Mirror is clean</span>
          <span class="queue-empty-sub">No pending changes</span>
        </div>
      {:else}
        <ul class="queue-list" role="listbox" aria-label="Pending changes">
          {#each pendingItems as item (item.id)}
            <li
              class="q-item {itemStatusClass(item)}"
              class:is-selected={selectedId === item.id}
              role="option"
              tabindex="0"
              aria-selected={selectedId === item.id}
              onclick={() => selectItem(item.id)}
              onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectItem(item.id); } }}
            >
              <div class="status-bar" aria-hidden="true"></div>
              <div class="q-body">
                <div class="q-row">
                  <span class="q-tier {tierClass(item.tier)}" title="Tier {item.tier} - {item.tier_label}">
                    {tierLabel(item.tier, item.tier_label)}
                  </span>
                  <span class="q-file mono">{item.target_file}</span>
                </div>
                <div class="q-row">
                  <span class="q-verb">{item.modification_type}</span>
                  <span class="q-gates" aria-label="validation gates">
                    {#each ['syntax', 'imports', 'tests'] as gate}
                      {@const gs = item.validation_result
                        ? (item.validation_result[gate as keyof typeof item.validation_result] ?? 'skip')
                        : 'skip'}
                      <span class="q-gate {gs}" title="{gate}: {gs}"></span>
                    {/each}
                  </span>
                </div>
                <div class="q-meta">
                  <span>{relativeTime(item.timestamp)}</span>
                </div>
              </div>
            </li>
          {/each}
        </ul>
      {/if}
    </aside>

    <!-- DETAIL PANEL -->
    <section class="detail" aria-label="Change detail">
      {#if !selectedId}
        <div class="detail-empty">
          <div class="diamond diamond--accent" aria-hidden="true"></div>
          <span>Select a change to inspect</span>
        </div>
      {:else if detailLoading}
        <div class="detail-empty">
          <div class="diamond diamond--accent" aria-hidden="true"></div>
          <span>Loading detail...</span>
        </div>
      {:else if detail}
        <div class="detail-inner">
          <div class="detail-stack">
            <!-- IDENTITY -->
            <header class="identity">
              <div class="row1">
                <span class="file-path">{detail.target_file}</span>
                <span class="verb">{detail.modification_type}</span>
                <span class="diff-stat">
                  <span class="add">+{diffAdd}</span>
                  <span class="del">&minus;{diffDel}</span>
                </span>
                <span class="tier-pill {tierClass(detail.tier)}" title="Tier {detail.tier} - {detail.tier_label}">
                  <span
                    class="diamond {detail.tier === 3 ? 'diamond--danger' : detail.tier === 1 ? '' : 'diamond--accent'}"
                    style="width:6px;height:6px;animation:none;"
                    aria-hidden="true"
                  ></span>
                  tier {detail.tier} &middot; {detail.tier_label}
                </span>
              </div>
              <div class="row2">
                {#if detail.mirror_sha}
                  <span><span class="lbl">mirror</span> <code>{detail.mirror_sha?.slice(0, 6)}</code></span>
                  <span class="sep">&middot;</span>
                {/if}
                {#if detail.real_sha || detail.commit_sha}
                  <span><span class="lbl">real</span> <code>{(detail.real_sha ?? detail.commit_sha)?.slice(0, 6)}</code></span>
                  <span class="sep">&middot;</span>
                {/if}
                <span><span class="lbl">originated</span> {relativeTime(detail.timestamp)}</span>
                <span class="sep">&middot;</span>
                <span><span class="lbl">by</span> <code>{detail.initiated_by}{detail.cycle ? ` \u00b7 cycle #${detail.cycle}` : ''}</code></span>
              </div>
            </header>

            <!-- INTENT -->
            <section class="dblock" aria-labelledby="intent-h">
              <div class="dblock-head">
                <h3 id="intent-h">intent</h3>
                <span class="hint">why ARIA proposed this change</span>
              </div>
              <div class="dblock-body">
                <p class="intent-text">{detail.reason}</p>
                <div class="intent-meta">
                  {#if detail.model}
                    <span class="item"><span class="lbl">model</span> <span class="v">{detail.model}</span></span>
                  {/if}
                  {#if detail.trigger}
                    <span class="item"><span class="lbl">trigger</span> <span class="v">{detail.trigger}</span></span>
                  {/if}
                  {#if detail.cycle}
                    <span class="item"><span class="lbl">cycle</span> <span class="v">{detail.cycle}</span></span>
                  {/if}
                  {#if detail.confidence != null}
                    <span class="item"><span class="lbl">conf</span> <span class="v">{detail.confidence}</span></span>
                  {/if}
                </div>
              </div>
            </section>

            <!-- VALIDATION -->
            <section class="dblock" aria-labelledby="val-h">
              <div class="dblock-head">
                <h3 id="val-h">validation</h3>
                <span class="hint">automatic gates</span>
              </div>
              <div class="dblock-body">
                <div class="vgrid">
                  {#each ['syntax', 'imports', 'tests'] as gate}
                    {@const gs = gateStatus(detail, gate)}
                    <div class="vcell {gs}">
                      <span class="vbox" aria-hidden="true">{gateSymbol(gs)}</span>
                      <span class="lbl">{gate}</span>
                      <span class="sub">{gateSub(detail, gate)}</span>
                    </div>
                  {/each}
                </div>
              </div>
            </section>

            <!-- DIFF -->
            {#if diffLines.length > 0}
              <section class="dblock" aria-labelledby="diff-h">
                <div class="dblock-head">
                  <h3 id="diff-h">diff</h3>
                  <span class="hint">{detail.target_file}</span>
                </div>
                <div class="dblock-body">
                  <div class="diff">
                    <div class="diff-head">
                      <div class="stats">
                        <span class="add">+{diffAdd}</span>
                        <span class="del">&minus;{diffDel}</span>
                        <span style="opacity:.5;margin-left:8px;">
                          {diffLines.filter(l => l.type === 'hunk').length} hunks
                        </span>
                      </div>
                      <span class="mono" style="font-size:10px;color:var(--text-faint);">unified</span>
                    </div>
                    <div class="diff-body">
                      {#each diffLines as line}
                        <div class="dline {line.type === 'ctx' ? '' : line.type}">
                          <span class="gut">{line.lineNum}</span>
                          <span class="mark"></span>
                          <span class="code">{line.text}</span>
                        </div>
                      {/each}
                    </div>
                  </div>
                </div>
              </section>
            {/if}

            <!-- FILE HISTORY -->
            {#if fileHistory.length > 0}
              <section class="dblock" aria-labelledby="hist-h">
                <div class="dblock-head">
                  <h3 id="hist-h">file history</h3>
                  <span class="hint">last changes touching this file</span>
                </div>
                <div class="dblock-body history">
                  {#if fileHistory.length >= 5}
                    <div class="history-warn" role="status">
                      <span class="icon" aria-hidden="true">!</span>
                      <span>ARIA has touched this file <strong>{fileHistory.length} times</strong> recently. Consider whether the underlying problem is being addressed.</span>
                    </div>
                  {/if}
                  <ol>
                    {#each fileHistory as hi (hi.id)}
                      {@const isCurrent = hi.id === selectedId}
                      <li class="{hi.initiated_by === 'user' || hi.initiated_by === 'human' ? 'human' : 'aria'}" class:this={isCurrent}>
                        <span class="marker" aria-hidden="true"></span>
                        <span class="when">{isCurrent ? 'now' : relativeTime(hi.timestamp)}</span>
                        <span class="who">{hi.initiated_by ?? 'aria'}</span>
                        <span class="verb">{hi.modification_type}</span>
                        <span class="out" class:approved={hi.status === 'promoted'} class:rejected={hi.status === 'rejected'} class:pending={hi.status === 'pending'}>
                          {#if hi.status === 'promoted'}approved{:else if hi.status === 'rejected'}rejected{:else if hi.status === 'pending'}{isCurrent ? '\u2190 pending \u00b7 this' : 'pending'}{:else}{hi.status}{/if}
                        </span>
                      </li>
                    {/each}
                  </ol>
                </div>
              </section>
            {/if}

            <!-- AUDIT LOG -->
            {#if auditItems.length > 0}
              <section class="audit-section" id="audit" aria-labelledby="audit-h">
                <div class="head">
                  <h3 id="audit-h">audit log</h3>
                  <span class="hint">recent promoted or rejected</span>
                </div>
                <ol class="audit-list">
                  {#each auditItems as ai (ai.id)}
                    <li class="audit-row">
                      <span class="when">{formatTime(ai.timestamp)}</span>
                      <span class="verdict" class:approved={ai.status === 'promoted'} class:rejected={ai.status === 'rejected'}>
                        {ai.status === 'promoted' ? 'approved' : ai.status}
                      </span>
                      <span class="file mono">{ai.target_file}</span>
                      <span class="by">by {ai.initiated_by ?? 'system'}</span>
                      <button class="inspect-btn" onclick={() => selectItem(ai.id)}>inspect</button>
                    </li>
                  {/each}
                </ol>
              </section>
            {/if}
          </div>
        </div>

        <!-- ACTION BAR -->
        <div class="action-bar">
          <span class="helper">
            <kbd>r</kbd> reject &middot; <kbd>p</kbd> promote
          </span>
          <span class="spread"></span>
          <div class="group">
            <button
              class="btn btn--reject"
              disabled={rejecting || !selectedId}
              onclick={() => { showRejectDialog = true; }}
            >
              reject
            </button>
            <span class="gap-divider" aria-hidden="true"></span>
            <button
              class="btn btn--approve"
              disabled={promoting || !selectedId}
              onclick={handlePromote}
            >
              {promoting ? 'promoting...' : `promote ${selectedId ? '1' : pendingCount} to live`}
            </button>
          </div>
        </div>

        <!-- REJECT DIALOG -->
        {#if showRejectDialog}
          <div class="confirm-modal">
            <h4>Reject change?</h4>
            <p>This will mark <code class="mono">{detail?.target_file}</code> as rejected.</p>
            <div class="filename-field">
              <span class="prefix">reason:</span>
              <input
                type="text"
                placeholder="optional reason..."
                bind:value={rejectReason}
                onkeydown={(e) => { if (e.key === 'Enter') handleReject(); }}
              />
            </div>
            <div class="actions">
              <button class="btn" onclick={() => { showRejectDialog = false; }}>cancel</button>
              <button class="btn btn--reject" disabled={rejecting} onclick={handleReject}>
                {rejecting ? 'rejecting...' : 'confirm reject'}
              </button>
            </div>
          </div>
        {/if}
      {:else}
        <div class="detail-empty">
          <span>Change not found</span>
        </div>
      {/if}
    </section>
  </div>
{/if}

<style>
  /* === Layout === */
  .mirror-loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 16px;
    color: var(--text-muted);
    font-size: 14px;
  }
  .mirror-loading .diamond {
    width: 12px;
    height: 12px;
  }
  .error-text {
    color: var(--danger);
  }

  /* === Header === */
  .mirror-header {
    flex-shrink: 0;
    height: 60px;
    display: flex;
    align-items: center;
    gap: 24px;
    padding: 0 28px;
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border);
    position: relative;
    z-index: 3;
  }
  .mirror-header h1 {
    font-size: 18px;
    font-weight: 500;
    color: var(--text-strong);
    letter-spacing: -0.01em;
    margin: 0;
  }
  .h-sep {
    width: 1px;
    height: 18px;
    background: var(--border);
  }

  .sync-state {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 6px 12px;
    border-radius: 6px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text-muted);
    letter-spacing: 0.02em;
  }
  .sync-state .sync-bar {
    width: 60px;
    height: 3px;
    border-radius: 2px;
    background: var(--border);
    position: relative;
    overflow: hidden;
  }
  .sync-state .sync-bar i {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 100%;
    background: linear-gradient(90deg, var(--sage), var(--accent));
    opacity: 0.75;
  }
  .sync-state.is-down .sync-bar i {
    background: var(--danger);
    width: 30%;
  }
  .sync-state.is-down {
    color: var(--danger);
    border-color: rgba(199, 90, 90, 0.30);
  }
  .sync-state .label {
    color: inherit;
    text-transform: lowercase;
  }
  .sync-state .meta {
    color: var(--text-faint);
  }

  .counters {
    display: inline-flex;
    align-items: center;
    gap: 18px;
    font-family: var(--font-mono);
    font-size: 11.5px;
    color: var(--text-muted);
  }
  .counters .ctr {
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
  }
  .counters .ctr .n {
    color: var(--text-strong);
    font-weight: 500;
    font-size: 13px;
  }
  .counters .ctr.is-warn .n {
    color: var(--accent);
  }
  .counters .ctr.is-danger .n {
    color: var(--danger);
  }
  .counters .ctr-sep {
    color: var(--text-faint);
    opacity: 0.4;
  }

  .audit-link {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-height: 32px;
    padding: 6px 12px;
    border-radius: 4px;
    background: transparent;
    border: 1px solid var(--border-strong);
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 10.5px;
    letter-spacing: 0.03em;
    cursor: pointer;
    text-decoration: none;
    transition: all 120ms var(--ease-micro);
  }
  .audit-link:hover {
    color: var(--accent);
    border-color: var(--accent);
    background: var(--accent-subtle);
  }

  /* === Body === */
  .mirror-body {
    flex: 1;
    display: flex;
    min-height: 0;
    position: relative;
  }

  /* === Queue === */
  .queue {
    width: 340px;
    flex-shrink: 0;
    background: var(--bg-surface);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    position: relative;
    z-index: 2;
  }
  .queue-head {
    flex-shrink: 0;
    padding: 16px 18px 12px;
    border-bottom: 1px solid var(--border);
  }
  .queue-head h2 {
    margin: 0;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    color: var(--text-faint);
  }

  .queue-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    flex: 1;
    gap: 12px;
    color: var(--text-muted);
    font-size: 13px;
  }
  .queue-empty .diamond {
    width: 14px;
    height: 14px;
  }
  .queue-empty-sub {
    font-size: 11px;
    color: var(--text-faint);
    font-family: var(--font-mono);
  }

  .queue-list {
    flex: 1;
    overflow-y: auto;
    padding: 8px 0;
    list-style: none;
    margin: 0;
  }

  .q-item {
    position: relative;
    display: grid;
    grid-template-columns: 3px 1fr;
    margin: 2px 10px;
    border-radius: 6px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    cursor: pointer;
    transition: all 120ms var(--ease-micro);
    animation: reveal-up 350ms var(--ease-arrive) both;
  }
  .q-item:hover {
    background: var(--bg-hover);
    border-color: var(--border-strong);
  }
  .q-item .status-bar {
    border-top-left-radius: 6px;
    border-bottom-left-radius: 6px;
    background: var(--text-faint);
  }
  .q-item.is-failed .status-bar {
    background: var(--danger);
  }
  .q-item.is-stale .status-bar {
    background: var(--accent);
  }
  .q-item.is-validating .status-bar {
    background: var(--info);
    animation: pulse-soft 1.6s ease-in-out infinite;
  }
  .q-item.is-ready .status-bar {
    background: var(--sage);
  }
  .q-item.is-selected {
    background: var(--accent-subtle);
    border-color: var(--accent-dim);
  }
  .q-item.is-selected::after {
    content: '';
    position: absolute;
    right: -1px;
    top: 8px;
    bottom: 8px;
    width: 2px;
    background: var(--accent);
    border-radius: 1px;
  }

  .q-body {
    padding: 11px 14px;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .q-row {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }

  .q-file {
    font-family: var(--font-mono);
    font-size: 11.5px;
    color: var(--text-strong);
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex: 1;
    min-width: 0;
    direction: rtl;
    text-align: left;
  }
  .q-tier {
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: 8.5px;
    font-weight: 600;
    letter-spacing: 0.08em;
    padding: 2px 5px;
    border-radius: 2px;
    text-transform: uppercase;
  }
  .q-tier.t1 {
    color: var(--text-muted);
    border: 1px solid var(--border);
  }
  .q-tier.t2 {
    color: var(--accent);
    border: 1px solid var(--accent-dim);
    background: var(--accent-subtle);
  }
  .q-tier.t3 {
    color: var(--danger);
    border: 1px solid var(--danger);
    background: var(--danger-subtle);
  }

  .q-verb {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--text-muted);
    text-transform: lowercase;
    padding: 1px 6px;
    border-radius: 3px;
    background: var(--bg-hover);
  }
  .q-gates {
    display: flex;
    gap: 3px;
    margin-left: auto;
  }
  .q-gate {
    width: 7px;
    height: 7px;
    border-radius: 1px;
    background: var(--border-strong);
  }
  .q-gate.pass {
    background: var(--ok);
  }
  .q-gate.fail {
    background: var(--danger);
  }
  .q-gate.run {
    background: var(--info);
    animation: pulse-soft 1.4s ease-in-out infinite;
  }
  .q-gate.skip {
    background: var(--text-faint);
    opacity: 0.4;
  }

  .q-meta {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--text-faint);
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 2px;
  }

  /* === Detail panel === */
  .detail {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    background: transparent;
    position: relative;
  }
  .detail-inner {
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    width: 100%;
  }
  .detail-inner > .detail-stack {
    max-width: 920px;
    margin: 0 auto;
    padding: 36px 36px 48px;
    display: flex;
    flex-direction: column;
    gap: 28px;
  }

  .detail-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    flex: 1;
    gap: 16px;
    color: var(--text-muted);
    font-size: 14px;
  }
  .detail-empty .diamond {
    width: 12px;
    height: 12px;
  }

  /* === Identity === */
  .identity {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px 22px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    animation: reveal-up 350ms var(--ease-arrive) both;
  }
  .identity .row1 {
    display: flex;
    align-items: center;
    gap: 14px;
    flex-wrap: wrap;
  }
  .identity .file-path {
    font-family: var(--font-mono);
    font-size: 14px;
    color: var(--text-strong);
    font-weight: 500;
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .identity .verb {
    font-family: var(--font-mono);
    font-size: 10.5px;
    text-transform: lowercase;
    letter-spacing: 0.04em;
    padding: 3px 9px;
    border-radius: 3px;
    background: var(--accent-subtle);
    color: var(--accent);
    border: 1px solid var(--accent-dim);
  }
  .identity .diff-stat {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text-muted);
  }
  .identity .diff-stat .add {
    color: var(--ok);
  }
  .identity .diff-stat .del {
    color: var(--accent);
  }
  .identity .row2 {
    display: flex;
    align-items: center;
    gap: 14px;
    font-family: var(--font-mono);
    font-size: 10.5px;
    color: var(--text-faint);
    flex-wrap: wrap;
  }
  .identity .row2 .lbl {
    color: var(--text-muted);
  }
  .identity .row2 code {
    color: var(--text);
    background: var(--bg-deep);
    padding: 1px 6px;
    border-radius: 3px;
    border: 1px solid var(--border);
  }
  .identity .row2 .sep {
    opacity: 0.4;
  }
  .tier-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-family: var(--font-mono);
    font-size: 9.5px;
    font-weight: 600;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 3px;
    border: 1px solid var(--accent-dim);
    background: var(--accent-subtle);
    color: var(--accent);
  }
  .tier-pill.t3 {
    border-color: var(--danger);
    background: var(--danger-subtle);
    color: var(--danger);
  }
  .tier-pill.t1 {
    border-color: var(--border-strong);
    background: transparent;
    color: var(--text-muted);
  }

  /* === Dblock === */
  .dblock {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    animation: reveal-up 350ms var(--ease-arrive) both;
  }
  .dblock-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    padding: 14px 20px 0;
  }
  .dblock-head h3 {
    margin: 0;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    color: var(--text-faint);
  }
  .dblock-head .hint {
    font-family: var(--font-mono);
    font-size: 10.5px;
    color: var(--text-faint);
    letter-spacing: 0.02em;
  }
  .dblock-body {
    padding: 12px 20px 18px;
  }

  /* === Intent === */
  .intent-text {
    font-size: 14px;
    line-height: 1.6;
    color: var(--text);
    font-style: italic;
    border-left: 2px solid var(--sage);
    padding: 2px 0 2px 14px;
    margin: 0 0 14px;
  }
  .intent-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    font-family: var(--font-mono);
    font-size: 10.5px;
    color: var(--text-faint);
  }
  .intent-meta .item {
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  .intent-meta .lbl {
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: 9.5px;
  }
  .intent-meta .v {
    color: var(--text);
  }

  /* === Validation grid === */
  .vgrid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1px;
    background: var(--border);
    border-radius: 6px;
    overflow: hidden;
    border: 1px solid var(--border);
  }
  .vcell {
    background: var(--bg-card);
    padding: 12px 14px;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .vcell .vbox {
    flex-shrink: 0;
    width: 14px;
    height: 14px;
    border: 1px solid var(--border-strong);
    border-radius: 2px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 9px;
    line-height: 1;
  }
  .vcell.pass .vbox {
    background: var(--ok);
    border-color: var(--ok);
    color: #0a1f10;
  }
  .vcell.fail .vbox {
    background: var(--danger);
    border-color: var(--danger);
    color: #fff;
  }
  .vcell.run .vbox {
    background: var(--info);
    border-color: var(--info);
    animation: pulse-soft 1.4s ease-in-out infinite;
  }
  .vcell.skip .vbox {
    opacity: 0.5;
  }
  .vcell .lbl {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text);
    text-transform: lowercase;
    letter-spacing: 0.02em;
  }
  .vcell .sub {
    margin-left: auto;
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--text-faint);
  }
  .vcell.pass .sub {
    color: var(--text-muted);
  }
  .vcell.fail .sub {
    color: var(--danger);
  }

  /* === Diff === */
  .diff {
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
    background: var(--bg-deep);
  }
  .diff-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 14px;
    background: var(--bg-card);
    border-bottom: 1px solid var(--border);
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text-muted);
  }
  .diff-head .stats .add {
    color: var(--ok);
  }
  .diff-head .stats .del {
    color: var(--accent);
  }
  .diff-body {
    max-height: 480px;
    overflow: auto;
    font-family: var(--font-mono);
    font-size: 11.5px;
  }
  .dline {
    display: flex;
    min-height: 20px;
  }
  .dline .gut {
    flex: none;
    width: 46px;
    padding: 0 10px 0 8px;
    text-align: right;
    color: var(--text-muted);
    font-size: 10.5px;
    background: var(--bg-card);
    border-right: 1px solid var(--border);
    user-select: none;
    line-height: 20px;
  }
  .dline .mark {
    flex: none;
    width: 3px;
  }
  .dline .code {
    flex: 1;
    padding: 0 14px;
    line-height: 20px;
    white-space: pre;
    color: var(--text-muted);
  }
  .dline.add .mark {
    background: var(--ok);
  }
  .dline.add .code {
    color: var(--text);
    background: rgba(94, 184, 122, 0.05);
  }
  .dline.del .mark {
    background: var(--accent);
  }
  .dline.del .code {
    color: var(--text);
    background: rgba(212, 160, 74, 0.05);
  }
  .dline.hunk .gut {
    background: var(--bg-deep);
  }
  .dline.hunk .code {
    color: var(--accent);
    font-style: italic;
    background: transparent;
  }

  /* === File history === */
  .history {
    display: flex;
    flex-direction: column;
    gap: 0;
  }
  .history-warn {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    margin-bottom: 10px;
    border-radius: 6px;
    background: var(--accent-subtle);
    border: 1px solid var(--accent-dim);
    color: var(--accent);
    font-family: var(--font-mono);
    font-size: 11px;
  }
  .history-warn .icon {
    font-size: 13px;
    font-weight: 700;
  }
  .history ol {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
  }
  .history li {
    display: grid;
    grid-template-columns: 14px 88px 80px 100px 1fr;
    align-items: center;
    gap: 12px;
    padding: 9px 4px;
    border-bottom: 1px solid var(--border);
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text-muted);
  }
  .history li:last-child {
    border-bottom: none;
  }
  .history li.this {
    color: var(--text);
  }
  .history li .marker {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--text-faint);
    justify-self: center;
  }
  .history li.aria .marker {
    background: var(--sage);
  }
  .history li.human .marker {
    background: var(--accent);
  }
  .history li.this .marker {
    background: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-subtle);
  }
  .history li .when {
    color: var(--text-faint);
  }
  .history li .who {
    color: var(--text);
  }
  .history li .verb {
    color: var(--text-muted);
  }
  .history li .out {
    color: var(--text-faint);
  }
  .history li .out.approved {
    color: var(--ok);
  }
  .history li .out.rejected {
    color: var(--danger);
  }
  .history li .out.pending {
    color: var(--accent);
    font-weight: 500;
  }

  /* === Action bar === */
  .action-bar {
    flex-shrink: 0;
    background: var(--bg-surface);
    border-top: 1px solid var(--border);
    padding: 14px 36px;
    display: flex;
    align-items: center;
    gap: 18px;
    z-index: 4;
    position: sticky;
    bottom: 0;
  }
  .action-bar .helper {
    font-family: var(--font-mono);
    font-size: 10.5px;
    color: var(--text-faint);
    letter-spacing: 0.02em;
  }
  .action-bar .helper kbd {
    display: inline-block;
    padding: 1px 6px;
    margin: 0 2px;
    border: 1px solid var(--border-strong);
    border-radius: 3px;
    background: var(--bg-card);
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 10px;
  }
  .spread {
    flex: 1;
  }
  .group {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .gap-divider {
    width: 1px;
    height: 28px;
    background: var(--border);
    margin: 0 16px;
  }

  .btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 36px;
    padding: 8px 16px;
    border-radius: 5px;
    font-family: var(--font-mono);
    font-size: 11.5px;
    letter-spacing: 0.03em;
    cursor: pointer;
    border: 1px solid var(--border-strong);
    background: transparent;
    color: var(--text-muted);
    transition: all 120ms var(--ease-micro);
    text-transform: lowercase;
  }
  .btn:hover {
    color: var(--text);
    border-color: var(--text-muted);
  }
  .btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .btn--reject {
    color: var(--danger);
    border-color: rgba(199, 90, 90, 0.40);
  }
  .btn--reject:hover {
    background: var(--danger-subtle);
    border-color: var(--danger);
    color: var(--danger);
  }
  .btn--approve {
    color: var(--accent);
    border-color: var(--accent-dim);
    background: var(--accent-subtle);
    font-weight: 500;
  }
  .btn--approve:hover {
    color: var(--bg);
    background: var(--accent);
    border-color: var(--accent);
    box-shadow: 0 2px 12px var(--accent-glow);
  }

  /* === Confirm modal === */
  .confirm-modal {
    position: absolute;
    left: 50%;
    bottom: 78px;
    transform: translateX(-50%);
    width: min(560px, calc(100% - 80px));
    background: var(--bg-elevated);
    border: 1px solid var(--accent-dim);
    border-radius: 10px;
    box-shadow: 0 12px 48px rgba(0, 0, 0, 0.6), 0 0 0 1px var(--accent-glow);
    padding: 18px 22px;
    z-index: 5;
    animation: reveal-up 250ms var(--ease-arrive) both;
  }
  .confirm-modal h4 {
    margin: 0 0 4px;
    font-size: 13px;
    font-weight: 500;
    color: var(--text-strong);
    letter-spacing: -0.005em;
  }
  .confirm-modal p {
    margin: 0 0 14px;
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.5;
  }
  .confirm-modal .filename-field {
    display: flex;
    align-items: center;
    gap: 0;
    background: var(--bg-deep);
    border: 1px solid var(--border-strong);
    border-radius: 5px;
    overflow: hidden;
    margin-bottom: 14px;
  }
  .confirm-modal .filename-field .prefix {
    padding: 9px 4px 9px 12px;
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--text-faint);
    user-select: none;
  }
  .confirm-modal .filename-field input {
    flex: 1;
    background: transparent;
    border: none;
    padding: 9px 12px 9px 4px;
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--accent);
    outline: none;
  }
  .confirm-modal .filename-field input::placeholder {
    color: var(--text-faint);
    opacity: 0.6;
  }
  .confirm-modal .actions {
    display: flex;
    gap: 10px;
    justify-content: flex-end;
  }

  /* === Audit section === */
  .audit-section {
    margin-top: 24px;
    border-top: 1px solid var(--border);
    padding-top: 24px;
  }
  .audit-section .head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 14px;
  }
  .audit-section h3 {
    margin: 0;
    font-size: 13px;
    font-weight: 500;
    color: var(--text-strong);
    letter-spacing: -0.005em;
  }
  .audit-section .head .hint {
    font-family: var(--font-mono);
    font-size: 10.5px;
    color: var(--text-faint);
  }
  .audit-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
    background: var(--border);
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
  }
  .audit-row {
    background: var(--bg-card);
    display: grid;
    grid-template-columns: 90px 110px 1fr 100px 60px;
    align-items: center;
    gap: 14px;
    padding: 12px 18px;
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text-muted);
  }
  .audit-row .when {
    color: var(--text-faint);
  }
  .audit-row .file {
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .audit-row .verdict {
    text-transform: lowercase;
    letter-spacing: 0.04em;
    font-size: 10px;
    padding: 3px 8px;
    border-radius: 3px;
    text-align: center;
  }
  .audit-row .verdict.approved {
    color: var(--ok);
    background: var(--ok-subtle);
    border: 1px solid rgba(94, 184, 122, 0.30);
  }
  .audit-row .verdict.rejected {
    color: var(--danger);
    background: var(--danger-subtle);
    border: 1px solid rgba(199, 90, 90, 0.30);
  }
  .audit-row .by {
    color: var(--text-faint);
    text-align: right;
  }
  .inspect-btn {
    background: none;
    border: none;
    color: var(--accent);
    font-family: var(--font-mono);
    font-size: 10px;
    cursor: pointer;
    text-align: right;
    padding: 0;
  }
  .inspect-btn:hover {
    text-decoration: underline;
  }

  /* === Diamond (local) === */
  .diamond {
    display: inline-block;
    width: 8px;
    height: 8px;
    transform: rotate(45deg);
    border-radius: 1px;
    background: var(--text-faint);
  }
  .diamond--accent {
    background: var(--accent);
    animation: breathe 3s ease-in-out infinite;
  }
  .diamond--danger {
    background: var(--danger);
  }

  /* === Responsive === */
  @media (max-width: 1200px) {
    .vgrid {
      grid-template-columns: 1fr;
    }
  }
  @media (max-width: 1100px) {
    .queue {
      width: 280px;
    }
    .detail-inner > .detail-stack {
      padding: 24px 24px 48px;
    }
  }
  @media (max-width: 880px) {
    .queue {
      display: none;
    }
  }
</style>
