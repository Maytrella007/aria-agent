<script lang="ts">
	import { api, ApiError } from '$lib/api';
	import { onMount } from 'svelte';

	/* ── Types ── */
	interface DashboardData {
		messages_today?: number;
		received?: number;
		sent?: number;
		peak_time?: string;
		peak_rate?: number;
		active_chats?: Record<string, number>;
		avg_latency_ms?: number;
		retry_queue?: number;
		recent_errors?: number;
		healthy_count?: number;
		total_running?: number;
	}

	interface ChannelMetrics {
		uptime?: string;
		today?: number;
		received?: number;
		sent?: number;
		latency_ms?: number;
		chats?: number;
		retry?: number;
		errors?: number;
		[key: string]: any;
	}

	interface Channel {
		name: string;
		status: string;
		metrics: ChannelMetrics;
		kind?: string;
		description?: string;
		config?: Record<string, any>;
		guilds?: string[];
		allowed_channels?: string[];
	}

	/* ── Static channel metadata ── */
	const CHANNEL_META: Record<string, { glyph: string; kind: string; description: string }> = {
		telegram: {
			glyph: '\u25B3',
			kind: 'bot',
			description: 'Primary conversational channel. Listens to all incoming DMs; replies handled by ChannelBase.on_message(). No allow-list -- open to anyone with the bot handle.'
		},
		discord: {
			glyph: '\u2B21',
			kind: 'gateway',
			description: 'Scoped to specific guilds and channels only. Ignores DMs and any guild not in the allow-list.'
		},
		slack: {
			glyph: '\u229F',
			kind: 'socket mode',
			description: 'Socket-mode bot for workspace integration. Requires both a bot_token (xoxb-...) and an app_token (xapp-...) plus at least one allowed channel id.'
		}
	};

	/* ── State ── */
	let dashboard: DashboardData | null = $state(null);
	let channels: Channel[] = $state([]);
	let loading = $state(true);
	let error: string | null = $state(null);
	let actionLoading: Record<string, boolean> = $state({});
	let actionError: Record<string, string | null> = $state({});
	let revealedTokens: Record<string, string | null> = $state({});
	let revealTimers: Record<string, ReturnType<typeof setTimeout>> = {};
	let rotateMessage: string | null = $state(null);

	/* ── Computed helpers ── */
	function activeCount(): number {
		return channels.filter(c => c.status === 'running').length;
	}

	function unconfiguredCount(): number {
		return channels.filter(c => c.status === 'unconfigured').length;
	}

	function stoppedCount(): number {
		return channels.filter(c => c.status === 'stopped').length;
	}

	function statusLabel(status: string): string {
		if (status === 'running') return 'active';
		if (status === 'unconfigured') return 'unconfigured';
		return 'stopped';
	}

	function statusClass(status: string): string {
		if (status === 'running') return 'is-running';
		if (status === 'unconfigured') return 'is-stopped';
		return 'is-stopped';
	}

	/* ── Fetch data ── */
	async function fetchDashboard() {
		try {
			dashboard = await api<DashboardData>('channels/dashboard');
		} catch (e: any) {
			if (e?.statusCode === 503) {
				error = 'Channel system not available';
			}
		}
	}

	async function fetchChannels() {
		try {
			const res = await api<{ channels: Channel[] }>('channels');
			channels = res.channels || [];
		} catch (e: any) {
			if (e?.statusCode === 503) {
				error = 'Channel system not available';
			} else {
				error = e?.detail || e?.message || 'Failed to load channels';
			}
		}
	}

	async function loadAll() {
		loading = true;
		error = null;
		await Promise.all([fetchDashboard(), fetchChannels()]);
		loading = false;
	}

	/* ── Actions ── */
	async function startChannel(name: string) {
		actionLoading[name] = true;
		actionError[name] = null;
		try {
			await api(`channels/${name}/start`, { method: 'POST' });
			await fetchChannels();
			await fetchDashboard();
		} catch (e: any) {
			actionError[name] = e?.detail || 'Failed to start channel';
		} finally {
			actionLoading[name] = false;
		}
	}

	async function stopChannel(name: string) {
		actionLoading[name] = true;
		actionError[name] = null;
		try {
			await api(`channels/${name}/stop`, { method: 'POST' });
			await fetchChannels();
			await fetchDashboard();
		} catch (e: any) {
			actionError[name] = e?.detail || 'Failed to stop channel';
		} finally {
			actionLoading[name] = false;
		}
	}

	async function revealToken(name: string) {
		actionLoading[`reveal-${name}`] = true;
		try {
			const res = await api<{ token: string }>(`channels/${name}/token`, { method: 'POST' });
			revealedTokens[name] = res.token;
			// Clear any existing timer
			if (revealTimers[name]) clearTimeout(revealTimers[name]);
			// Auto-hide after 10 seconds
			revealTimers[name] = setTimeout(() => {
				revealedTokens[name] = null;
			}, 10000);
		} catch (e: any) {
			actionError[name] = e?.detail || 'Failed to reveal token';
		} finally {
			actionLoading[`reveal-${name}`] = false;
		}
	}

	async function rotateToken(name: string) {
		actionLoading[`rotate-${name}`] = true;
		try {
			await api(`channels/${name}/rotate-token`, { method: 'POST' });
		} catch (e: any) {
			if (e?.statusCode === 501) {
				rotateMessage = e?.detail || 'Token rotation is not automated. Please rotate the token manually via the provider dashboard.';
			} else {
				actionError[name] = e?.detail || 'Failed to rotate token';
			}
		} finally {
			actionLoading[`rotate-${name}`] = false;
		}
	}

	function dismissRotateMessage() {
		rotateMessage = null;
	}

	function getMeta(name: string) {
		return CHANNEL_META[name] || { glyph: '?', kind: 'unknown', description: '' };
	}

	onMount(() => {
		loadAll();
	});
</script>

<div class="page">

	<!-- ── Loading state ── -->
	{#if loading}
		<div class="state-msg">
			<span class="state-icon diamond diamond--accent" aria-hidden="true"></span>
			<p>loading channels...</p>
		</div>

	<!-- ── Error state ── -->
	{:else if error}
		<div class="state-msg">
			<p class="state-error">{error}</p>
			<button class="btn" onclick={() => loadAll()}>retry</button>
		</div>

	<!-- ── Empty state ── -->
	{:else if channels.length === 0}
		<div class="state-msg">
			<p>no channels found</p>
		</div>

	{:else}
		<!-- ── Header ── -->
		<header class="header">
			<h1>channels</h1>
			<span class="meta">
				{#if activeCount() > 0}
					<span class="live">{activeCount()} active</span>
				{/if}
				{#if stoppedCount() > 0}
					{#if activeCount() > 0}&nbsp;·&nbsp;{/if}
					<span>{stoppedCount()} stopped</span>
				{/if}
				{#if unconfiguredCount() > 0}
					{#if activeCount() > 0 || stoppedCount() > 0}&nbsp;·&nbsp;{/if}
					<span class="warn">{unconfiguredCount()} unconfigured</span>
				{/if}
			</span>
		</header>

		<!-- ── Dashboard ── -->
		{#if dashboard}
			<section class="dash">
				<div class="dash-cell">
					<div class="dash-label">messages · today</div>
					<div class="dash-total">
						{dashboard.messages_today ?? 0}<span class="unit">in + out</span>
					</div>
					<div class="dash-total-sub">
						{dashboard.received ?? 0} received · {dashboard.sent ?? 0} sent
						{#if dashboard.peak_time}
							<br>
							<span style="color:var(--text-faint);">peak {dashboard.peak_time} · {dashboard.peak_rate ?? 0}/min</span>
						{/if}
					</div>
				</div>

				<div class="dash-cell">
					<div class="dash-label">active chats</div>
					<div class="dash-list">
						{#if dashboard.active_chats}
							{#each Object.entries(dashboard.active_chats) as [name, count]}
								<div class="dash-row">
									<span class="name" class:hi={count > 0}>{name}</span>
									<span class="num" class:hi={count > 0}>{count > 0 ? count : '\u2014'}</span>
								</div>
							{/each}
							<div class="dash-row dash-row--total">
								<span class="name">total</span>
								<span class="num">{Object.values(dashboard.active_chats).reduce((a, b) => a + b, 0)}</span>
							</div>
						{:else}
							<div class="dash-row">
								<span class="name">no data</span>
								<span class="num">\u2014</span>
							</div>
						{/if}
					</div>
				</div>

				<div class="dash-cell">
					<div class="dash-label">health</div>
					<div class="dash-list">
						<div class="dash-row">
							<span class="name">avg latency</span>
							<span class="num">{dashboard.avg_latency_ms ?? 0}ms</span>
						</div>
						<div class="dash-row">
							<span class="name">retry queue</span>
							<span class="num">{dashboard.retry_queue ?? 0}</span>
						</div>
						<div class="dash-row">
							<span class="name" class:warn={(dashboard.recent_errors ?? 0) > 0}>recent errors</span>
							<span class="num" class:warn={(dashboard.recent_errors ?? 0) > 0}>{dashboard.recent_errors ?? 0}</span>
						</div>
						<div class="dash-row dash-row--total">
							<span class="name hi">healthy</span>
							<span class="num hi">{dashboard.healthy_count ?? activeCount()} / {dashboard.total_running ?? channels.length}</span>
						</div>
					</div>
				</div>
			</section>
		{/if}

		<!-- ── Section label ── -->
		<div class="section-label">
			<h2>configured channels</h2>
			<span class="hint">core/channels/ · {channels.length} hardcoded</span>
		</div>

		<!-- ── Channel list ── -->
		<section class="chlist">
			{#each channels as ch, i}
				{@const meta = getMeta(ch.name)}
				{@const isUnconfigured = ch.status === 'unconfigured'}
				{@const isRunning = ch.status === 'running'}
				<article
					class="ch"
					class:ch--needs={isUnconfigured}
					style="animation-delay: {180 + i * 80}ms;"
				>
					<!-- Glyph -->
					<div class="ch-glyph" aria-hidden="true">{meta.glyph}</div>

					<!-- Head -->
					<div class="ch-head">
						<span class="ch-name">{ch.name.charAt(0).toUpperCase() + ch.name.slice(1)}</span>
						<span class="ch-kind">{ch.kind || meta.kind}</span>
						<span class="ch-status {statusClass(ch.status)}">
							<span class="sdot"></span>
							<span>{statusLabel(ch.status)}</span>
						</span>
					</div>

					<!-- Description -->
					<div class="ch-desc">
						{ch.description || meta.description}
						{#if ch.name === 'discord' && (ch.guilds?.length || ch.allowed_channels?.length)}
							<br>
							<span class="list" style="margin-top:6px; display:inline-flex;">
								{#each ch.guilds ?? [] as g}
									<span class="tag">{g}</span>
								{/each}
								{#each ch.allowed_channels ?? [] as c}
									<span class="tag">#{c}</span>
								{/each}
							</span>
						{/if}
					</div>

					<!-- Metrics -->
					<div class="ch-metrics">
						{#if isUnconfigured}
							<span class="m" style="color:var(--text-faint);">no metrics until tokens are configured</span>
						{:else}
							<span class="m"><span>up</span><span class="v">{ch.metrics?.uptime ?? '\u2014'}</span></span>
							<span class="sep"></span>
							<span class="m"><span>today</span><span class="v hi">{ch.metrics?.today ?? 0}</span></span>
							<span class="sep"></span>
							<span class="m"><span>in/out</span><span class="v">{ch.metrics?.received ?? 0} / {ch.metrics?.sent ?? 0}</span></span>
							<span class="sep"></span>
							<span class="m"><span>lat</span><span class="v ok">{ch.metrics?.latency_ms ?? 0}ms</span></span>
							<span class="sep"></span>
							<span class="m"><span>chats</span><span class="v">{ch.metrics?.chats ?? 0}</span></span>
							<span class="sep"></span>
							<span class="m"><span>retry</span><span class="v">{ch.metrics?.retry ?? 0}</span></span>
							{#if (ch.metrics?.errors ?? 0) > 0}
								<span class="sep"></span>
								<span class="m"><span>err</span><span class="v warn">{ch.metrics.errors}</span></span>
							{/if}
						{/if}
					</div>

					<!-- Config block for unconfigured (Slack-style) -->
					{#if isUnconfigured && ch.config}
						<div class="config-block">
							{#each Object.entries(ch.config) as [key, val]}
								<div class="token-row">
									<span class="lbl">{key}</span>
									<span class="val" class:miss={!val || val === '' || (Array.isArray(val) && val.length === 0)}>
										{#if !val || val === ''}
											missing
										{:else if Array.isArray(val) && val.length === 0}
											[] empty
										{:else}
											{val}
										{/if}
									</span>
								</div>
							{/each}
						</div>
					{/if}

					<!-- Side actions -->
					<div class="ch-side">
						{#if isUnconfigured}
							<a class="btn btn--accent" href="/credentials" aria-label="Add {ch.name} tokens">add tokens</a>
							<button class="btn" aria-label="View {ch.name} documentation">view docs</button>
						{:else}
							<button
								class="btn btn--accent"
								onclick={() => isRunning ? stopChannel(ch.name) : startChannel(ch.name)}
								disabled={actionLoading[ch.name]}
								aria-label="{isRunning ? 'Stop' : 'Start'} {ch.name} channel"
							>
								{#if actionLoading[ch.name]}
									...
								{:else}
									{isRunning ? 'stop' : 'start'}
								{/if}
							</button>

							<!-- Token row -->
							<span class="token-row">
								<span class="lbl">token</span>
								{#if revealedTokens[ch.name]}
									<span class="val revealed">{revealedTokens[ch.name]}</span>
								{:else}
									<span class="val">{'\u2022'.repeat(8)}</span>
								{/if}
							</span>
							<div class="ghost-row">
								<button
									class="btn btn--ghost"
									onclick={() => revealToken(ch.name)}
									disabled={actionLoading[`reveal-${ch.name}`]}
									aria-label="Reveal {ch.name} bot token"
								>
									{actionLoading[`reveal-${ch.name}`] ? '...' : 'reveal'}
								</button>
								<button
									class="btn btn--ghost"
									onclick={() => rotateToken(ch.name)}
									disabled={actionLoading[`rotate-${ch.name}`]}
									aria-label="Rotate {ch.name} bot token"
								>
									{actionLoading[`rotate-${ch.name}`] ? '...' : 'rotate'}
								</button>
							</div>
						{/if}

						{#if actionError[ch.name]}
							<span class="action-error">{actionError[ch.name]}</span>
						{/if}
					</div>
				</article>
			{/each}
		</section>

		<!-- ── Footer ── -->
		<div class="footer">
			<div class="path">core/channels/ · channel_base.py · telegram_bot.py · discord_bot.py · slack_bot.py</div>
			<div class="count">{channels.length} channels hardcoded</div>
		</div>
	{/if}

	<!-- ── Rotate token info dialog ── -->
	{#if rotateMessage}
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="overlay" onclick={dismissRotateMessage}>
			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div class="dialog" onclick={(e) => e.stopPropagation()}>
				<div class="dialog-title">token rotation</div>
				<p class="dialog-body">{rotateMessage}</p>
				<div class="dialog-actions">
					<button class="btn btn--accent" onclick={dismissRotateMessage}>understood</button>
				</div>
			</div>
		</div>
	{/if}
</div>

<style>
	/* ── Page layout ── */
	.page {
		max-width: 880px;
		margin: 0 auto;
		padding: 48px 32px 96px;
		position: relative;
		z-index: 2;
	}

	/* ── States ── */
	.state-msg {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 16px;
		min-height: 300px;
		color: var(--text-faint);
		font-family: var(--font-mono);
		font-size: 13px;
	}
	.state-error {
		color: var(--danger);
	}

	/* ── Header ── */
	.header {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		margin-bottom: 32px;
		animation: reveal-up 350ms var(--ease-arrive) both;
	}
	.header h1 {
		font-size: 24px;
		font-weight: 500;
		color: var(--text-strong);
		letter-spacing: -0.02em;
		margin: 0;
	}
	.header .meta {
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--text-faint);
	}
	.header .meta .live {
		color: var(--sage);
	}
	.header .meta .live::before {
		content: '';
		display: inline-block;
		width: 5px;
		height: 5px;
		border-radius: 50%;
		background: var(--sage);
		margin-right: 6px;
		vertical-align: middle;
		animation: breathe 3s ease-in-out infinite;
	}
	.header .meta .warn {
		color: var(--danger);
	}

	/* ── Dashboard ── */
	.dash {
		display: grid;
		grid-template-columns: 1.2fr 1fr 1fr;
		gap: 1px;
		background: var(--border);
		border: 1px solid var(--border);
		border-radius: 8px;
		overflow: hidden;
		margin-bottom: 24px;
		animation: reveal-up 350ms var(--ease-arrive) both;
		animation-delay: 60ms;
	}
	.dash-cell {
		background: var(--bg-card);
		padding: 18px 20px;
	}
	.dash-label {
		font-family: var(--font-mono);
		font-size: 9.5px;
		color: var(--text-faint);
		letter-spacing: 0.1em;
		text-transform: uppercase;
		margin-bottom: 10px;
	}
	.dash-total {
		font-size: 36px;
		font-weight: 500;
		color: var(--text-strong);
		letter-spacing: -0.025em;
		line-height: 1;
		font-variant-numeric: tabular-nums;
	}
	.dash-total .unit {
		font-size: 13px;
		color: var(--text-faint);
		margin-left: 6px;
		font-weight: 400;
		letter-spacing: 0;
	}
	.dash-total-sub {
		font-size: 11px;
		color: var(--text-muted);
		margin-top: 6px;
		line-height: 1.5;
	}
	.dash-list {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.dash-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		font-size: 11.5px;
		color: var(--text-muted);
	}
	.dash-row .name {
		text-transform: lowercase;
	}
	.dash-row .num {
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-faint);
	}
	.dash-row .name.hi { color: var(--accent); }
	.dash-row .num.hi { color: var(--accent); }
	.dash-row .name.warn { color: var(--danger); }
	.dash-row .num.warn { color: var(--danger); }
	.dash-row--total {
		margin-top: 4px;
		padding-top: 6px;
		border-top: 1px solid var(--border);
	}

	/* ── Section label ── */
	.section-label {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 12px;
		animation: reveal-up 350ms var(--ease-arrive) both;
		animation-delay: 120ms;
	}
	.section-label h2 {
		margin: 0;
		font-size: 11px;
		font-family: var(--font-mono);
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: var(--text-faint);
		font-weight: 500;
	}
	.section-label .hint {
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-faint);
	}

	/* ── Channel list ── */
	.chlist {
		display: flex;
		flex-direction: column;
		gap: 1px;
		background: var(--border);
		border: 1px solid var(--border);
		border-radius: 8px;
		overflow: hidden;
	}
	.ch {
		background: var(--bg-card);
		padding: 22px 24px;
		display: grid;
		grid-template-columns: auto 1fr auto;
		gap: 6px 20px;
		align-items: start;
		transition: background 120ms;
		animation: reveal-up 350ms var(--ease-arrive) both;
	}
	.ch:hover {
		background: var(--bg-hover);
	}
	.ch.ch--needs {
		background: linear-gradient(180deg, var(--bg-card) 0%, rgba(199, 90, 90, 0.035) 100%);
	}
	.ch.ch--needs:hover {
		background: linear-gradient(180deg, var(--bg-hover) 0%, rgba(199, 90, 90, 0.06) 100%);
	}

	/* Glyph */
	.ch-glyph {
		grid-row: 1 / span 3;
		width: 44px;
		height: 44px;
		display: flex;
		align-items: center;
		justify-content: center;
		border: 1px solid var(--border-strong);
		border-radius: 8px;
		font-size: 20px;
		color: var(--accent);
		background: var(--bg-elevated);
		font-family: var(--font-mono);
		position: relative;
	}
	.ch-glyph::after {
		content: '';
		position: absolute;
		inset: 0;
		border-radius: 8px;
		box-shadow: inset 0 0 0 1px rgba(212, 160, 74, 0.08);
	}
	.ch--needs .ch-glyph {
		color: var(--text-faint);
		border-color: var(--border);
		background: var(--bg-card);
	}

	/* Head */
	.ch-head {
		grid-column: 2;
		grid-row: 1;
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
	}
	.ch-name {
		font-size: 15px;
		font-weight: 500;
		color: var(--text-strong);
		letter-spacing: -0.01em;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 100%;
	}
	.ch-kind {
		font-family: var(--font-mono);
		font-size: 9.5px;
		color: var(--text-faint);
		letter-spacing: 0.1em;
		text-transform: uppercase;
		padding: 2px 7px;
		border: 1px solid var(--border);
		border-radius: 3px;
	}
	.ch-status {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-family: var(--font-mono);
		font-size: 10px;
		color: var(--text-muted);
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}
	.ch-status .sdot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--text-faint);
		box-shadow: 0 0 0 2px var(--bg-card);
	}
	.ch-status.is-running .sdot {
		background: var(--ok);
		box-shadow: 0 0 0 2px var(--bg-card), 0 0 8px rgba(94, 184, 122, 0.45);
		animation: pulse-soft 3.2s ease-in-out infinite;
	}
	.ch-status.is-running {
		color: var(--ok);
	}
	.ch-status.is-stopped .sdot {
		background: var(--danger);
	}
	.ch-status.is-stopped {
		color: var(--danger);
	}

	/* Description */
	.ch-desc {
		grid-column: 2;
		grid-row: 2;
		font-size: 13px;
		color: var(--text-muted);
		line-height: 1.55;
		margin-top: 4px;
		max-width: 520px;
	}
	.ch-desc :global(.mono) {
		color: var(--text);
		font-size: 11.5px;
	}
	.ch-desc .list {
		display: inline-flex;
		flex-wrap: wrap;
		gap: 4px;
		vertical-align: middle;
	}
	.ch-desc .tag {
		background: var(--bg-hover);
		color: var(--text-muted);
		padding: 1px 7px;
		border-radius: 3px;
		font-size: 10px;
		font-family: var(--font-mono);
	}

	/* Metrics */
	.ch-metrics {
		grid-column: 2;
		grid-row: 3;
		display: flex;
		flex-wrap: wrap;
		gap: 14px;
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-faint);
		margin-top: 12px;
	}
	.ch-metrics .m {
		display: inline-flex;
		align-items: baseline;
		gap: 5px;
	}
	.ch-metrics .m .v {
		color: var(--text);
	}
	.ch-metrics .m .v.hi {
		color: var(--accent);
	}
	.ch-metrics .m .v.ok {
		color: var(--ok);
	}
	.ch-metrics .m .v.warn {
		color: var(--danger);
	}
	.ch-metrics .sep {
		width: 1px;
		height: 11px;
		background: var(--border);
		align-self: center;
	}

	/* Config block */
	.config-block {
		grid-column: 2;
		grid-row: 4;
		margin-top: 14px;
		padding-top: 14px;
		border-top: 1px dashed var(--border);
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	/* Side actions */
	.ch-side {
		grid-column: 3;
		grid-row: 1 / span 3;
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 10px;
		min-width: 150px;
	}

	/* Buttons */
	.btn {
		background: none;
		border: 1px solid var(--border);
		color: var(--text-muted);
		padding: 7px 14px;
		border-radius: 6px;
		font-family: var(--font-mono);
		font-size: 10.5px;
		letter-spacing: 0.04em;
		cursor: pointer;
		transition: all 140ms var(--ease-micro);
		text-transform: lowercase;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		text-decoration: none;
	}
	.btn:hover {
		color: var(--text-strong);
		border-color: var(--border-strong);
		background: var(--bg-hover);
	}
	.btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.btn--accent {
		color: var(--accent);
		border-color: rgba(212, 160, 74, 0.35);
		background: var(--accent-subtle);
	}
	.btn--accent:hover {
		border-color: var(--accent);
		background: rgba(212, 160, 74, 0.16);
	}
	.btn--ghost {
		padding: 5px 10px;
		font-size: 9.5px;
		color: var(--text-faint);
		min-height: 32px;
	}
	.btn--ghost:hover {
		color: var(--text-muted);
	}

	/* Token row */
	.token-row {
		display: flex;
		align-items: center;
		gap: 8px;
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-faint);
	}
	.token-row .lbl {
		color: var(--text-faint);
		letter-spacing: 0.04em;
	}
	.token-row .val {
		color: var(--text-muted);
		background: var(--bg-elevated);
		padding: 2px 7px;
		border-radius: 3px;
		border: 1px solid var(--border);
	}
	.token-row .val.miss {
		color: var(--danger);
		border-color: rgba(199, 90, 90, 0.3);
	}
	.token-row .val.revealed {
		color: var(--accent);
		border-color: rgba(212, 160, 74, 0.35);
	}

	.ghost-row {
		display: flex;
		gap: 6px;
	}

	.action-error {
		font-family: var(--font-mono);
		font-size: 10px;
		color: var(--danger);
		max-width: 180px;
		text-align: right;
		line-height: 1.4;
	}

	/* ── Footer ── */
	.footer {
		margin-top: 24px;
		text-align: center;
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--text-faint);
		animation: reveal-up 350ms var(--ease-arrive) both;
		animation-delay: 500ms;
	}
	.footer .count {
		margin-top: 6px;
	}
	.footer .path {
		color: var(--text-muted);
	}

	/* ── Rotate info dialog ── */
	.overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		z-index: 100;
		display: flex;
		align-items: center;
		justify-content: center;
		animation: fade-in 150ms ease-out;
	}
	.dialog {
		background: var(--bg-elevated);
		border: 1px solid var(--border-strong);
		border-radius: 10px;
		padding: 28px 32px;
		max-width: 440px;
		width: 90%;
		animation: reveal-up 250ms var(--ease-arrive);
	}
	.dialog-title {
		font-family: var(--font-mono);
		font-size: 12px;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		color: var(--text-faint);
		margin-bottom: 14px;
	}
	.dialog-body {
		font-size: 13px;
		color: var(--text);
		line-height: 1.6;
		margin: 0 0 20px;
	}
	.dialog-actions {
		display: flex;
		justify-content: flex-end;
	}

	@keyframes fade-in {
		from { opacity: 0; }
		to { opacity: 1; }
	}

	/* ── Responsive ── */
	@media (max-width: 680px) {
		.dash {
			grid-template-columns: 1fr;
		}
		.page {
			padding: 32px 20px 64px;
		}
		.ch {
			grid-template-columns: auto 1fr;
		}
		.ch-side {
			grid-column: 1 / -1;
			grid-row: auto;
			align-items: flex-start;
			flex-direction: row;
			flex-wrap: wrap;
		}
		.config-block {
			grid-column: 1 / -1;
		}
	}
</style>
