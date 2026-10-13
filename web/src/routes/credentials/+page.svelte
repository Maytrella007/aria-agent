<script lang="ts">
	import { api } from '$lib/api';
	import { onMount } from 'svelte';

	/* ── Types ── */
	interface Provider {
		name: string;
		model: string | null;
		state: 'active' | 'configured' | 'empty' | 'local';
		key_preview: string | null;
		auth_methods: string[];
	}

	interface ProvidersResponse {
		providers: Provider[];
		active: string | null;
	}

	interface Agent {
		name: string;
		description: string;
		binary: string;
		installed: boolean;
		authenticated: boolean;
		is_default: boolean;
		env_keys: string[];
		install_cmd: string | null;
		install_alt: string | null;
		auth_cmd: string | null;
	}

	interface AgentsResponse {
		agents: Agent[];
	}

	interface Service {
		name: string;
		label: string;
		auth_type: 'oauth' | 'api_key';
		scopes?: string[];
		oauth_provider?: string;
		env_key?: string;
		planned: boolean;
		state: 'connected' | 'unconfigured' | 'planned';
		connected: boolean;
	}

	interface ServicesResponse {
		services: Service[];
	}

	/* ── State ── */
	let providers: Provider[] = $state([]);
	let activeProvider: string | null = $state(null);
	let agents: Agent[] = $state([]);
	let services: Service[] = $state([]);

	let loading = $state(true);
	let error: string | null = $state(null);

	/* inline editing */
	let editingKey: string | null = $state(null);
	let keyInput = $state('');
	let savingKey = $state(false);
	let activatingProvider: string | null = $state(null);
	let settingDefault: string | null = $state(null);
	let oauthStarting: string | null = $state(null);
	let oauthRevoking: string | null = $state(null);
	let oauthMessage: string | null = $state(null);
	let oauthPolling: string | null = $state(null);
	let oauthAuthUrl: string | null = $state(null);

	/* ollama models */
	let ollamaModels: string[] = $state([]);
	let ollamaError: string | null = $state(null);
	let showOllamaModels = $state(false);
	let loadingOllamaModels = $state(false);

	/* agent install/uninstall info */
	let installInfo: Record<string, { install_cmd: string | null; install_alt: string | null; auth_cmd: string | null; note: string } | null> = $state({});
	let uninstallInfo: Record<string, { uninstall_cmd: string | null; note: string } | null> = $state({});
	let showInstall: string | null = $state(null);
	let showUninstall: string | null = $state(null);

	/* ── Glyphs ── */
	const providerGlyphs: Record<string, string> = {
		anthropic: '\u25C6',
		openai: '\u25CC',
		google: '\u25EF',
		deepseek: '\u25CA',
		openrouter: '\u25D0',
		ollama: '\u25C9'
	};

	const agentGlyphs: Record<string, string> = {
		claude_code: '\u25ED',
		codex: '\u25EE',
		aider: '\u25F1',
		opencode: '\u25F2'
	};

	/* ── Fetch helpers ── */
	async function fetchProviders() {
		const res = await api<ProvidersResponse>('credentials/providers');
		providers = res.providers;
		activeProvider = res.active;
	}

	async function fetchAgents() {
		const res = await api<AgentsResponse>('credentials/agents');
		agents = res.agents;
	}

	async function fetchServices() {
		const res = await api<ServicesResponse>('credentials/services');
		services = res.services;
	}

	async function loadAll() {
		loading = true;
		error = null;
		try {
			await Promise.all([fetchProviders(), fetchAgents(), fetchServices()]);
		} catch (e: any) {
			error = e.message || 'Failed to load credentials';
		} finally {
			loading = false;
		}
	}

	onMount(() => { loadAll(); });

	/* ── Actions ── */
	function startEdit(providerName: string, currentPreview: string | null) {
		editingKey = providerName;
		keyInput = '';
	}

	function cancelEdit() {
		editingKey = null;
		keyInput = '';
	}

	async function saveKey(providerName: string) {
		const trimmed = keyInput.trim();
		if (!trimmed) return;
		savingKey = true;
		try {
			await api('credentials/providers/' + providerName + '/key', {
				method: 'POST',
				body: { key: trimmed }
			});
			editingKey = null;
			keyInput = '';
			await fetchProviders();
		} catch (e: any) {
			error = e.message || 'Failed to save key';
		} finally {
			savingKey = false;
		}
	}

	async function activateProvider(providerName: string) {
		activatingProvider = providerName;
		try {
			await api('credentials/providers/' + providerName + '/activate', { method: 'POST' });
			await fetchProviders();
		} catch (e: any) {
			error = e.message || 'Failed to activate provider';
		} finally {
			activatingProvider = null;
		}
	}

	async function fetchOllamaModels() {
		loadingOllamaModels = true;
		ollamaError = null;
		try {
			const res = await api<{ models: string[]; endpoint?: string; error?: string }>('credentials/providers/ollama/models');
			ollamaModels = res.models;
			if (res.error) ollamaError = res.error;
			showOllamaModels = true;
		} catch (e: any) {
			ollamaError = e.message || 'Failed to fetch models';
			showOllamaModels = true;
		} finally {
			loadingOllamaModels = false;
		}
	}

	async function setDefaultAgent(agentName: string) {
		settingDefault = agentName;
		try {
			await api('credentials/agents/' + agentName + '/default', { method: 'POST' });
			await fetchAgents();
		} catch (e: any) {
			error = e.message || 'Failed to set default agent';
		} finally {
			settingDefault = null;
		}
	}

	async function fetchInstallInfo(agentName: string) {
		if (showInstall === agentName) { showInstall = null; return; }
		try {
			const res = await api<{ install_cmd: string | null; install_alt: string | null; auth_cmd: string | null; note: string }>('credentials/agents/' + agentName + '/install');
			installInfo = { ...installInfo, [agentName]: res };
			showInstall = agentName;
		} catch (e: any) {
			error = e.message || 'Failed to get install info';
		}
	}

	async function fetchUninstallInfo(agentName: string) {
		if (showUninstall === agentName) { showUninstall = null; return; }
		try {
			const res = await api<{ uninstall_cmd: string | null; note: string }>('credentials/agents/' + agentName + '/uninstall');
			uninstallInfo = { ...uninstallInfo, [agentName]: res };
			showUninstall = agentName;
		} catch (e: any) {
			if (e.statusCode === 404) {
				uninstallInfo = { ...uninstallInfo, [agentName]: { uninstall_cmd: null, note: 'No uninstall recipe available' } };
				showUninstall = agentName;
			} else {
				error = e.message || 'Failed to get uninstall info';
			}
		}
	}

	async function copyToClipboard(text: string) {
		try { await navigator.clipboard.writeText(text); } catch {}
	}

	async function startOAuth(provider: string) {
		oauthStarting = provider;
		oauthMessage = null;
		oauthAuthUrl = null;
		try {
			const res = await api<{ ok: boolean; provider: string; auth_url?: string }>(
				'credentials/oauth/' + provider + '/start', { method: 'POST' }
			);

			if (res.auth_url) {
				// Open the authorization page in a new tab
				window.open(res.auth_url, '_blank');
				oauthAuthUrl = res.auth_url;
				oauthMessage = 'Authorization window opened. Complete the flow there, then return here.';
				// Start polling for completion
				pollOAuthStatus(provider);
			} else {
				// Fallback: no URL returned
				oauthMessage = 'OAuth flow started. Check the server console for the authorization URL.';
			}
		} catch (e: any) {
			error = e.message || 'Failed to start OAuth flow';
		} finally {
			oauthStarting = null;
		}
	}

	async function pollOAuthStatus(provider: string) {
		oauthPolling = provider;
		const maxAttempts = 120; // 5 minutes at 2.5s intervals
		let attempts = 0;

		const poll = async () => {
			if (attempts >= maxAttempts) {
				oauthMessage = 'Authorization timed out. Click "Connect" to try again.';
				oauthPolling = null;
				oauthAuthUrl = null;
				return;
			}
			attempts++;
			try {
				const res = await api<{ status: string; detail?: string }>(
					'credentials/oauth/' + provider + '/status'
				);
				if (res.status === 'success') {
					oauthMessage = 'Connected successfully.';
					oauthPolling = null;
					oauthAuthUrl = null;
					await fetchServices();
					return;
				}
				if (res.status === 'error') {
					oauthMessage = res.detail || 'Authorization failed.';
					oauthPolling = null;
					oauthAuthUrl = null;
					return;
				}
				// Still pending — poll again
				setTimeout(poll, 2500);
			} catch {
				// Network error — retry
				setTimeout(poll, 5000);
			}
		};
		setTimeout(poll, 2500);
	}

	function confirmOAuthComplete(provider: string) {
		// User says they completed the flow — just keep polling (or re-check now)
		pollOAuthStatus(provider);
	}

	async function revokeOAuth(provider: string) {
		if (!confirm('Disconnect ' + provider + '? This will revoke the OAuth token.')) return;
		oauthRevoking = provider;
		try {
			await api('credentials/oauth/' + provider + '/revoke', { method: 'POST' });
			oauthMessage = null;
			await fetchServices();
		} catch (e: any) {
			error = e.message || 'Failed to revoke OAuth';
		} finally {
			oauthRevoking = null;
		}
	}

	function providerRowClass(p: Provider): string {
		if (p.state === 'active') return 'is-active';
		if (p.state === 'configured') return 'is-configured';
		if (p.state === 'local') return 'is-local';
		return 'is-empty';
	}
</script>

<div class="page">

	{#if loading}
		<div class="loading-state">
			<span class="diamond diamond--accent" aria-hidden="true"></span>
			<span class="loading-text mono">loading credentials...</span>
		</div>
	{:else}

	{#if error}
		<div class="error-banner" role="alert">
			<span>{error}</span>
			<button type="button" onclick={() => { error = null; }}>dismiss</button>
		</div>
	{/if}

	<!-- Header -->
	<header class="header">
		<h1>credentials</h1>
		<span class="meta">api keys, coding agents & oauth integrations</span>
	</header>

	<!-- ============================================================
	     ZONE 1 — LLM Keys
	============================================================ -->
	<section class="llm-section" aria-labelledby="llm-title">
		<header class="zone-head">
			<h2 id="llm-title">llm keys</h2>
			<span class="hint">api keys for llm providers</span>
		</header>
		<div class="zone-legend" role="note" aria-label="LLM state legend">
			<span class="lg active"><span class="dot"></span>active — currently in use</span>
			<span class="lg configured"><span class="dot"></span>configured — key saved, not selected</span>
			<span class="lg empty"><span class="dot"></span>empty — no key</span>
		</div>

		<div class="llm-list" role="list">
			{#each providers as p, i (p.name)}
				<div class="llm-row {providerRowClass(p)}" role="listitem" style="animation-delay: {120 + i * 50}ms">
					<span class="llm-glyph" aria-hidden="true">{providerGlyphs[p.name] ?? '\u25C7'}</span>

					<div class="llm-id">
						<span class="name">{p.name}</span>
						{#if p.model}
							<span class="model mono">{p.model}</span>
						{/if}
					</div>

					<div class="llm-state">
						<span class="dot"></span>
						<span class="label">
							{#if p.state === 'active'}active
							{:else if p.state === 'configured'}configured
							{:else if p.state === 'local'}local
							{:else}not configured
							{/if}
						</span>
					</div>

					<!-- Key preview or inline edit -->
					<span class="llm-key mono">
						{#if editingKey === p.name}
							<span class="inline-edit">
								<input
									type="password"
									class="key-input mono"
									placeholder="paste api key..."
									bind:value={keyInput}
									onkeydown={(e) => { if (e.key === 'Enter') saveKey(p.name); if (e.key === 'Escape') cancelEdit(); }}
									disabled={savingKey}
								/>
								<button class="key-save" type="button" onclick={() => saveKey(p.name)} disabled={savingKey || !keyInput.trim()}>
									{savingKey ? '...' : 'save'}
								</button>
								<button class="key-cancel" type="button" onclick={cancelEdit} disabled={savingKey}>
									cancel
								</button>
							</span>
						{:else if p.key_preview}
							{p.key_preview}
						{:else}
							no key
						{/if}
					</span>

					<!-- Actions -->
					<div class="llm-actions" role="group" aria-label="{p.name} actions">
						{#if p.name === 'ollama'}
							<button class="llm-action" type="button" aria-label="Manage ollama local models" onclick={fetchOllamaModels} disabled={loadingOllamaModels}>
								{loadingOllamaModels ? '...' : 'models'}
							</button>
						{:else if p.state === 'active'}
							<button class="llm-action" type="button" aria-label="Edit {p.name} API key" onclick={() => startEdit(p.name, p.key_preview)}>
								edit key
							</button>
						{:else if p.state === 'configured'}
							<button
								class="llm-action use"
								type="button"
								aria-label="Use {p.name} as active LLM"
								onclick={() => activateProvider(p.name)}
								disabled={activatingProvider === p.name}
							>
								{activatingProvider === p.name ? '...' : 'use'}
							</button>
							<button class="llm-action" type="button" aria-label="Edit {p.name} API key" onclick={() => startEdit(p.name, p.key_preview)}>
								edit key
							</button>
							{#if p.auth_methods.includes('oauth')}
								<button class="llm-action oauth" type="button" aria-label="Sign in with {p.name} account">
									sign in
								</button>
							{/if}
						{:else if p.state === 'empty'}
							<button class="llm-action primary" type="button" aria-label="Add {p.name} API key" onclick={() => startEdit(p.name, null)}>
								+ add key
							</button>
						{/if}
					</div>
				</div>
			{/each}
		</div>

		<!-- Ollama models popup -->
		{#if showOllamaModels}
			<div class="ollama-models">
				<div class="ollama-models-header">
					<span class="mono">ollama models</span>
					<button class="key-cancel" type="button" onclick={() => { showOllamaModels = false; }}>close</button>
				</div>
				{#if ollamaError}
					<p class="ollama-error mono">ollama not available: {ollamaError}</p>
				{:else if ollamaModels.length === 0}
					<p class="ollama-empty mono">no models installed</p>
				{:else}
					<div class="ollama-chips">
						{#each ollamaModels as model (model)}
							<span class="ollama-chip mono">{model}</span>
						{/each}
					</div>
				{/if}
			</div>
		{/if}
	</section>

	<!-- ============================================================
	     ZONE 2 — Coding Agents
	============================================================ -->
	<section class="agents-section" aria-labelledby="agents-title">
		<header class="zone-head">
			<h2 id="agents-title">coding agents</h2>
			<span class="hint">managed via environment · not stored</span>
		</header>

		<div class="agents-list" role="list">
			{#each agents as ag, i (ag.name)}
				<div
					class="agent {ag.is_default ? 'is-primary' : ''} {!ag.installed ? 'is-down' : ''}"
					role="listitem"
					style="animation-delay: {240 + i * 50}ms"
				>
					<span class="glyph" aria-hidden="true">{agentGlyphs[ag.name] ?? '\u25C7'}</span>

					<div class="agent-main">
						<span class="agent-name">{ag.name}</span>
						<span class="agent-role {ag.is_default ? 'primary' : ''}">
							{ag.is_default ? 'primary' : 'fallback'}
						</span>
					</div>

					<div class="agent-meta">
						<span class="check {ag.installed ? 'ok' : 'miss'}">
							<span class="diamond {ag.installed ? 'diamond--ok' : ''}" aria-hidden="true"></span>
							{ag.installed ? 'binary detected' : 'not in $PATH'}
						</span>
						<span class="sep">/</span>
						<span class="check {ag.authenticated ? 'ok' : 'miss'}">
							<span class="diamond {ag.authenticated ? 'diamond--ok' : ''}" aria-hidden="true"></span>
							{#if ag.authenticated}
								{ag.env_keys[0] ?? 'env key'} present
							{:else}
								env key missing
							{/if}
						</span>
						<span class="sep">&middot;</span>
						<span class="path">binary: {ag.binary}</span>
					</div>

					<div class="agent-side">
						{#if ag.installed}
							{#if ag.is_default}
								<span class="default-pill" aria-label="Current default coding agent">
									<span class="glyph" aria-hidden="true">{'\u25C6'}</span>default
								</span>
							{:else}
								<button
									class="mini-btn"
									type="button"
									aria-label="Set {ag.name} as default coding agent"
									onclick={() => setDefaultAgent(ag.name)}
									disabled={settingDefault === ag.name}
								>
									{settingDefault === ag.name ? '...' : 'set default'}
								</button>
							{/if}
							<button class="mini-btn" type="button" aria-label="Configure {ag.name}">
								config
							</button>
							<button
								class="mini-btn danger"
								type="button"
								aria-label="Uninstall {ag.name}"
								onclick={() => fetchUninstallInfo(ag.name)}
							>
								uninstall
							</button>
						{:else}
							<button
								class="mini-btn install"
								type="button"
								aria-label="Install {ag.name}"
								onclick={() => fetchInstallInfo(ag.name)}
							>
								+ install
							</button>
						{/if}
					</div>
				</div>

				<!-- Install info panel -->
				{#if showInstall === ag.name && installInfo[ag.name]}
					<div class="info-panel">
						<p class="info-note mono">{installInfo[ag.name]!.note}</p>
						{#if installInfo[ag.name]!.install_cmd}
							<div class="info-cmd">
								<code class="mono">{installInfo[ag.name]!.install_cmd}</code>
								<button class="copy-btn" type="button" onclick={() => copyToClipboard(installInfo[ag.name]!.install_cmd!)}>copy</button>
							</div>
						{/if}
						{#if installInfo[ag.name]!.install_alt}
							<div class="info-cmd">
								<code class="mono">{installInfo[ag.name]!.install_alt}</code>
								<button class="copy-btn" type="button" onclick={() => copyToClipboard(installInfo[ag.name]!.install_alt!)}>copy</button>
							</div>
						{/if}
						{#if installInfo[ag.name]!.auth_cmd}
							<div class="info-cmd">
								<code class="mono">{installInfo[ag.name]!.auth_cmd}</code>
								<button class="copy-btn" type="button" onclick={() => copyToClipboard(installInfo[ag.name]!.auth_cmd!)}>copy</button>
							</div>
						{/if}
						<button class="key-cancel" type="button" onclick={() => { showInstall = null; }}>close</button>
					</div>
				{/if}

				<!-- Uninstall info panel -->
				{#if showUninstall === ag.name && uninstallInfo[ag.name]}
					<div class="info-panel">
						<p class="info-note mono">{uninstallInfo[ag.name]!.note}</p>
						{#if uninstallInfo[ag.name]!.uninstall_cmd}
							<div class="info-cmd">
								<code class="mono">{uninstallInfo[ag.name]!.uninstall_cmd}</code>
								<button class="copy-btn" type="button" onclick={() => copyToClipboard(uninstallInfo[ag.name]!.uninstall_cmd!)}>copy</button>
							</div>
						{/if}
						<button class="key-cancel" type="button" onclick={() => { showUninstall = null; }}>close</button>
					</div>
				{/if}
			{/each}
		</div>
	</section>

	<!-- ============================================================
	     ZONE 3 — Services
	============================================================ -->
	<section class="services-section" aria-labelledby="services-title">
		<header class="zone-head">
			<h2 id="services-title">services</h2>
			<span class="hint">third-party integrations</span>
		</header>

		{#if oauthMessage}
			<div class="oauth-message mono" role="status">
				<div class="oauth-message-body">
					{#if oauthPolling}
						<span class="diamond diamond--accent" aria-hidden="true"></span>
					{/if}
					<span>{oauthMessage}</span>
				</div>
				<div class="oauth-message-actions">
					{#if oauthAuthUrl}
						<a
							href={oauthAuthUrl}
							target="_blank"
							rel="noopener noreferrer"
							class="oauth-link"
						>open auth page</a>
					{/if}
					{#if oauthPolling}
						<button class="key-save" type="button" onclick={() => confirmOAuthComplete(oauthPolling!)}>
							I've completed authorization
						</button>
					{/if}
					<button class="key-cancel" type="button" onclick={() => { oauthMessage = null; oauthPolling = null; oauthAuthUrl = null; }}>dismiss</button>
				</div>
			</div>
		{/if}

		<div class="services-list" role="list">
			{#each services as svc (svc.name)}
				<div class="svc {svc.planned ? 'svc--planned' : ''}" role="listitem" aria-disabled={svc.planned ? 'true' : undefined}>
					<span class="svc-glyph" aria-hidden="true">
						{#if svc.auth_type === 'oauth'}{'\u2299'}{:else}{'\u22A0'}{/if}
					</span>

					<div class="svc-line">
						{svc.label}
						<span class="type">{svc.auth_type === 'oauth' ? 'OAuth' : 'API_KEY'}</span>
					</div>

					<div class="svc-meta">
						{#if !svc.planned}
							<span class="dot" style={svc.connected ? 'background: var(--ok)' : ''} aria-hidden="true"></span>
							<span class="status">{svc.state}</span>
							<span aria-hidden="true">&middot;</span>
						{/if}
						{#if svc.scopes && svc.scopes.length > 0}
							<span>{svc.scopes.join(' \u00B7 ')}</span>
						{:else if svc.env_key}
							<span>transactional email &middot; {svc.env_key?.slice(0, 4)}&hellip;</span>
						{/if}
					</div>

					<div class="svc-action">
						{#if svc.planned}
							<span class="planned-badge" role="status">planned</span>
						{:else if svc.connected}
							<button
								type="button"
								class="svc-btn svc-btn--disconnect"
								onclick={() => revokeOAuth(svc.oauth_provider!)}
								disabled={oauthRevoking === svc.oauth_provider}
							>
								{oauthRevoking === svc.oauth_provider ? '...' : 'disconnect'}
							</button>
						{:else if svc.auth_type === 'oauth'}
							<button
								type="button"
								class="svc-btn"
								onclick={() => startOAuth(svc.oauth_provider!)}
								disabled={oauthStarting === svc.oauth_provider}
							>
								{oauthStarting === svc.oauth_provider ? '...' : '+ connect via ' + svc.oauth_provider}
							</button>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	</section>

	<!-- Footer -->
	<div class="footer">
		core/llm/llm_providers.py &middot; core/skills/coding_agent.py &middot; core/infra/auth_manager.py
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

	/* ── Loading state ── */
	.loading-state {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 12px;
		padding: 120px 0;
		animation: reveal-up 350ms var(--ease-arrive) both;
	}
	.loading-text {
		font-size: 12px;
		color: var(--text-faint);
		letter-spacing: 0.04em;
	}

	/* ── Error banner ── */
	.error-banner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 10px 16px;
		margin-bottom: 24px;
		background: var(--danger-subtle);
		border: 1px solid var(--danger);
		border-radius: 6px;
		font-size: 12px;
		color: var(--danger);
		font-family: var(--font-mono);
		animation: reveal-up 250ms var(--ease-arrive) both;
	}
	.error-banner button {
		background: none;
		border: 1px solid var(--danger);
		color: var(--danger);
		font-family: var(--font-mono);
		font-size: 10px;
		padding: 3px 8px;
		border-radius: 3px;
		cursor: pointer;
		transition: all 120ms var(--ease-micro);
	}
	.error-banner button:hover {
		background: rgba(199, 90, 90, 0.15);
	}

	/* ── Header ── */
	.header {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		margin-bottom: 36px;
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

	/* ── Zone headers ── */
	.zone-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		margin-bottom: 14px;
		padding: 0 2px;
		gap: 16px;
		flex-wrap: wrap;
	}
	.zone-head h2 {
		font-family: var(--font-body);
		font-weight: 500;
		font-size: 15px;
		letter-spacing: 0.01em;
		color: var(--text-strong);
		margin: 0;
		text-transform: lowercase;
	}
	.zone-head .hint {
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-faint);
		letter-spacing: 0.02em;
	}
	.zone-legend {
		display: flex;
		gap: 14px;
		flex-wrap: wrap;
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-muted);
		letter-spacing: 0.02em;
		margin: -4px 2px 12px;
	}
	.zone-legend .lg {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.zone-legend .lg .dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--text-muted);
	}
	.zone-legend .lg.active .dot {
		background: var(--sage);
		box-shadow: 0 0 0 3px rgba(124, 154, 142, 0.12);
	}
	.zone-legend .lg.active { color: var(--sage); }
	.zone-legend .lg.configured .dot { background: var(--accent-dim); }
	.zone-legend .lg.empty .dot { background: var(--text-faint); }

	/* ============================================================
	   ZONE 1 — LLM
	============================================================ */
	.llm-section {
		margin-top: 0;
		animation: reveal-up 350ms var(--ease-arrive) both;
		animation-delay: 60ms;
	}
	.llm-list {
		display: flex;
		flex-direction: column;
		gap: 1px;
		background: var(--border);
		border: 1px solid var(--border);
		border-radius: 8px;
		overflow: hidden;
	}
	.llm-row {
		background: var(--bg-card);
		display: grid;
		grid-template-columns: 22px 1fr auto auto auto;
		align-items: center;
		gap: 14px;
		padding: 16px 20px;
		transition: background 120ms var(--ease-micro);
		animation: reveal-up 350ms var(--ease-arrive) both;
	}
	.llm-row:hover { background: var(--bg-hover); }

	.llm-glyph {
		font-family: var(--font-mono);
		font-size: 14px;
		color: var(--text-faint);
		text-align: center;
		line-height: 1;
		user-select: none;
	}
	.llm-row.is-configured .llm-glyph { color: var(--accent-dim); }
	.llm-row.is-active .llm-glyph { color: var(--accent); }

	.llm-id {
		display: flex;
		align-items: baseline;
		gap: 10px;
		min-width: 0;
	}
	.llm-id .name {
		font-family: var(--font-body);
		font-weight: 500;
		font-size: 13.5px;
		color: var(--text-strong);
		letter-spacing: 0.01em;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.llm-id .model {
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-faint);
		letter-spacing: 0.02em;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.llm-state {
		display: flex;
		align-items: center;
		gap: 8px;
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-muted);
		letter-spacing: 0.03em;
	}
	.llm-state .dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--text-faint);
		flex-shrink: 0;
	}
	.llm-row.is-active .llm-state .dot {
		background: var(--sage);
		box-shadow: 0 0 0 3px rgba(124, 154, 142, 0.12);
	}
	.llm-row.is-configured .llm-state .dot { background: var(--accent-dim); }
	.llm-row.is-local .llm-state .dot { background: var(--sage); }
	.llm-row.is-active .llm-state .label { color: var(--sage); }
	.llm-row.is-local .llm-state .label { color: var(--sage); }

	.llm-key {
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-muted);
		letter-spacing: 0.04em;
		padding-left: 14px;
		border-left: 1px solid var(--border-strong);
		white-space: nowrap;
	}
	.llm-row.is-empty .llm-key { color: var(--text-faint); font-style: italic; }
	.llm-row.is-local .llm-key { color: var(--text-faint); }

	/* ── Inline edit ── */
	.inline-edit {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.key-input {
		background: var(--bg-elevated);
		border: 1px solid var(--border-strong);
		color: var(--text);
		font-family: var(--font-mono);
		font-size: 10.5px;
		padding: 4px 8px;
		border-radius: 3px;
		outline: none;
		width: 180px;
		transition: border-color 120ms var(--ease-micro);
	}
	.key-input:focus {
		border-color: var(--accent);
	}
	.key-save {
		background: var(--accent-subtle);
		border: 1px solid var(--accent-dim);
		color: var(--accent);
		font-family: var(--font-mono);
		font-size: 10px;
		padding: 3px 8px;
		border-radius: 3px;
		cursor: pointer;
		transition: all 120ms var(--ease-micro);
	}
	.key-save:hover:not(:disabled) {
		background: var(--accent-glow);
		border-color: var(--accent);
	}
	.key-save:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.key-cancel {
		background: none;
		border: 1px solid var(--border-strong);
		color: var(--text-muted);
		font-family: var(--font-mono);
		font-size: 10px;
		padding: 3px 8px;
		border-radius: 3px;
		cursor: pointer;
		transition: all 120ms var(--ease-micro);
	}
	.key-cancel:hover {
		border-color: var(--text-muted);
		color: var(--text);
	}

	/* ── LLM actions ── */
	.llm-actions {
		display: flex;
		align-items: center;
		gap: 6px;
		justify-content: flex-end;
	}
	.llm-action {
		background: none;
		border: 1px solid var(--border-strong);
		color: var(--text-muted);
		font-family: var(--font-mono);
		font-size: 10.5px;
		padding: 6px 11px;
		border-radius: 4px;
		min-height: 32px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		cursor: pointer;
		letter-spacing: 0.03em;
		transition: all 120ms var(--ease-micro);
	}
	.llm-action:hover {
		border-color: var(--accent);
		color: var(--accent);
		background: var(--accent-subtle);
	}
	.llm-action:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.llm-action.primary {
		color: var(--accent);
		border-color: var(--accent-dim);
	}
	.llm-action.oauth {
		color: var(--sage);
		border-color: var(--border-strong);
		text-transform: lowercase;
	}
	.llm-action.oauth:hover {
		color: var(--sage);
		border-color: var(--sage);
		background: rgba(124, 154, 142, 0.10);
	}
	.llm-action.use {
		color: var(--sage);
		border-color: var(--border-strong);
	}
	.llm-action.use:hover {
		color: var(--sage);
		border-color: var(--sage);
		background: rgba(124, 154, 142, 0.10);
	}

	/* ── Ollama models ── */
	.ollama-models {
		margin-top: 12px;
		padding: 14px 18px;
		background: var(--bg-card);
		border: 1px solid var(--border);
		border-radius: 6px;
		animation: reveal-up 250ms var(--ease-arrive) both;
	}
	.ollama-models-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 10px;
		font-size: 12px;
		color: var(--text-strong);
	}
	.ollama-error {
		font-size: 11px;
		color: var(--danger);
		margin: 0;
	}
	.ollama-empty {
		font-size: 11px;
		color: var(--text-faint);
		margin: 0;
	}
	.ollama-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.ollama-chip {
		font-size: 10.5px;
		padding: 4px 10px;
		background: var(--bg-elevated);
		border: 1px solid var(--border-strong);
		border-radius: 4px;
		color: var(--text);
		letter-spacing: 0.02em;
	}

	/* ============================================================
	   ZONE 2 — Coding Agents
	============================================================ */
	.agents-section {
		margin-top: 40px;
		animation: reveal-up 350ms var(--ease-arrive) both;
		animation-delay: 200ms;
	}
	.agents-list {
		display: flex;
		flex-direction: column;
		gap: 1px;
		background: var(--border);
		border: 1px dashed var(--border-strong);
		border-radius: 8px;
		overflow: hidden;
		box-shadow: inset 0 0 0 9999px rgba(124, 154, 142, 0.025);
	}
	.agent {
		background: var(--bg-card);
		padding: 16px 20px;
		display: grid;
		grid-template-columns: 28px 1fr auto;
		align-items: center;
		column-gap: 16px;
		row-gap: 4px;
		transition: background 120ms;
		animation: reveal-up 350ms var(--ease-arrive) both;
	}
	.agent:hover { background: var(--bg-hover); }

	.agent > .glyph {
		grid-column: 1;
		grid-row: 1 / span 2;
		font-size: 18px;
		line-height: 1;
		color: var(--text-muted);
		text-align: center;
		user-select: none;
	}
	.agent.is-primary > .glyph { color: var(--accent); }

	.agent-main {
		grid-column: 2;
		grid-row: 1;
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
	}
	.agent-name {
		font-family: var(--font-body);
		font-size: 13.5px;
		font-weight: 600;
		color: var(--text);
		letter-spacing: 0.01em;
	}
	.agent.is-down .agent-name { color: var(--text-muted); }

	.agent-role {
		font-family: var(--font-mono);
		font-size: 9.5px;
		text-transform: lowercase;
		letter-spacing: 0.06em;
		padding: 2px 7px;
		border-radius: 3px;
		background: var(--bg-hover);
		color: var(--text-faint);
	}
	.agent-role.primary {
		background: var(--accent-subtle);
		color: var(--accent);
	}

	.agent-meta {
		grid-column: 2;
		grid-row: 2;
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-faint);
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
	}
	.agent-meta .check {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.agent-meta .check.ok { color: var(--sage); }
	.agent-meta .check.miss { color: var(--text-muted); }
	.agent-meta .sep { color: var(--text-faint); opacity: 0.5; }
	.agent-meta .path { color: var(--text-muted); }

	.agent-side {
		grid-column: 3;
		grid-row: 1 / span 2;
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.default-pill {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		min-height: 32px;
		padding: 6px 10px;
		font-family: var(--font-mono);
		font-size: 10.5px;
		letter-spacing: 0.03em;
		text-transform: lowercase;
		color: var(--accent);
		border: none;
		background: transparent;
		cursor: default;
		user-select: none;
	}
	.default-pill > .glyph {
		font-size: 10px;
		line-height: 1;
	}

	.mini-btn {
		background: none;
		border: 1px solid var(--border-strong);
		color: var(--text-muted);
		font-family: var(--font-mono);
		font-size: 10.5px;
		text-transform: lowercase;
		letter-spacing: 0.03em;
		padding: 6px 11px;
		border-radius: 4px;
		min-height: 32px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		cursor: pointer;
		transition: all 120ms var(--ease-micro);
	}
	.mini-btn:hover {
		color: var(--accent);
		border-color: var(--accent);
		background: var(--accent-subtle);
	}
	.mini-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.mini-btn.danger {
		color: var(--text-muted);
		border-color: var(--border);
		opacity: 0.75;
	}
	.mini-btn.danger:hover {
		color: var(--danger);
		border-color: var(--danger);
		background: rgba(199, 90, 90, 0.08);
		opacity: 1;
	}
	.mini-btn.install {
		color: var(--accent);
		border-color: var(--accent-dim);
	}
	.mini-btn.install:hover {
		color: var(--accent);
		border-color: var(--accent);
		background: var(--accent-subtle);
	}

	/* ── Info panels (install/uninstall) ── */
	.info-panel {
		background: var(--bg-elevated);
		padding: 14px 20px;
		display: flex;
		flex-direction: column;
		gap: 8px;
		animation: reveal-up 250ms var(--ease-arrive) both;
	}
	.info-note {
		font-size: 11px;
		color: var(--text-faint);
		margin: 0;
	}
	.info-cmd {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.info-cmd code {
		flex: 1;
		font-size: 11px;
		padding: 6px 10px;
		background: var(--bg-deep, var(--bg));
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		overflow-x: auto;
		white-space: nowrap;
	}
	.copy-btn {
		background: none;
		border: 1px solid var(--border-strong);
		color: var(--text-muted);
		font-family: var(--font-mono);
		font-size: 10px;
		padding: 4px 8px;
		border-radius: 3px;
		cursor: pointer;
		transition: all 120ms var(--ease-micro);
		flex-shrink: 0;
	}
	.copy-btn:hover {
		border-color: var(--accent);
		color: var(--accent);
		background: var(--accent-subtle);
	}

	/* ============================================================
	   ZONE 3 — Services
	============================================================ */
	.services-section {
		margin-top: 40px;
		animation: reveal-up 350ms var(--ease-arrive) both;
		animation-delay: 340ms;
	}
	.services-list {
		display: flex;
		flex-direction: column;
		gap: 1px;
		background: var(--border);
		border: 1px solid var(--border);
		border-radius: 8px;
		overflow: hidden;
	}
	.svc {
		background: var(--bg-card);
		padding: 16px 20px;
		display: grid;
		grid-template-columns: 28px 1fr auto;
		align-items: center;
		gap: 4px 16px;
		transition: background 120ms;
	}
	.svc:hover { background: var(--bg-hover); }

	.svc-glyph {
		grid-column: 1;
		grid-row: 1 / span 2;
		width: 28px;
		height: 28px;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 16px;
		color: var(--text-muted);
		border: 1px solid var(--border-strong);
		border-radius: 6px;
		background: var(--bg-elevated);
	}
	.svc-line {
		grid-column: 2;
		display: flex;
		align-items: center;
		gap: 10px;
		font-size: 14px;
		color: var(--text-strong);
		font-weight: 500;
	}
	.svc-line .type {
		font-family: var(--font-mono);
		font-size: 10px;
		color: var(--text-faint);
		letter-spacing: 0.06em;
		padding: 2px 7px;
		border: 1px solid var(--border-strong);
		border-radius: 3px;
		text-transform: uppercase;
	}
	.svc-meta {
		grid-column: 2;
		display: flex;
		align-items: center;
		gap: 8px;
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-faint);
		margin-top: 4px;
	}
	.svc-meta .dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--text-faint);
		display: inline-block;
	}
	.svc-meta .status {
		color: var(--text-muted);
		text-transform: lowercase;
	}
	.svc-action {
		grid-column: 3;
		grid-row: 1 / span 2;
		display: flex;
		align-items: center;
	}
	.svc-btn {
		min-height: 32px;
		padding: 6px 11px;
		background: transparent;
		border: 1px solid var(--accent-dim);
		color: var(--accent);
		border-radius: 4px;
		font-family: var(--font-mono);
		font-size: 10.5px;
		letter-spacing: 0.03em;
		cursor: pointer;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		transition: all 120ms var(--ease-micro);
	}
	.svc-btn:hover {
		border-color: var(--accent);
		background: var(--accent-subtle);
	}
	.svc-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.svc-btn--disconnect {
		border-color: var(--border-strong);
		color: var(--text-muted);
	}
	.svc-btn--disconnect:hover {
		border-color: var(--danger);
		color: var(--danger);
		background: rgba(199, 90, 90, 0.08);
	}

	.svc--planned { opacity: 0.6; }
	.svc--planned .svc-glyph {
		border-style: dashed;
		color: var(--text-faint);
	}
	.svc--planned .svc-line { color: var(--text-muted); }

	.planned-badge {
		min-height: 32px;
		padding: 6px 11px;
		display: inline-flex;
		align-items: center;
		border: 1px dashed var(--border-strong);
		border-radius: 4px;
		font-family: var(--font-mono);
		font-size: 10.5px;
		letter-spacing: 0.06em;
		text-transform: lowercase;
		color: var(--text-muted);
		background: transparent;
		cursor: not-allowed;
	}

	/* ── OAuth message ── */
	.oauth-message {
		display: flex;
		flex-direction: column;
		gap: 10px;
		padding: 12px 16px;
		margin-bottom: 12px;
		background: var(--info-subtle);
		border: 1px solid var(--info);
		border-radius: 6px;
		font-size: 11px;
		color: var(--info);
		animation: reveal-up 250ms var(--ease-arrive) both;
	}
	.oauth-message-body {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.oauth-message-actions {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	.oauth-link {
		font-family: var(--font-mono);
		font-size: 10px;
		padding: 3px 8px;
		border: 1px solid var(--info);
		border-radius: 3px;
		color: var(--info);
		text-decoration: none;
		transition: all 120ms var(--ease-micro);
	}
	.oauth-link:hover {
		background: rgba(100, 150, 200, 0.15);
	}

	/* ── Diamond ── */
	.diamond {
		display: inline-block;
		width: 8px;
		height: 8px;
		transform: rotate(45deg);
		border-radius: 1px;
		background: var(--text-faint);
	}
	.diamond--ok { background: var(--ok); }
	.diamond--accent {
		background: var(--accent);
		animation: breathe 3s ease-in-out infinite;
	}

	/* ── Footer ── */
	.footer {
		margin-top: 56px;
		padding-top: 20px;
		text-align: center;
		border-top: 1px solid var(--border);
		font-family: var(--font-mono);
		font-size: 10px;
		color: var(--text-muted);
		letter-spacing: 0.02em;
		opacity: 0.7;
		animation: reveal-up 350ms var(--ease-arrive) both;
		animation-delay: 480ms;
	}

	/* ── Responsive ── */
	@media (max-width: 680px) {
		.page { padding: 32px 20px 64px; }
		.llm-row {
			grid-template-columns: 22px 1fr auto;
			grid-template-areas:
				"g id action"
				". state state"
				". key key";
			row-gap: 6px;
		}
		.llm-glyph { grid-area: g; }
		.llm-id { grid-area: id; }
		.llm-state { grid-area: state; }
		.llm-key { grid-area: key; padding-left: 0; border-left: none; }
		.llm-actions { grid-area: action; }
		.header { flex-direction: column; gap: 6px; }
	}
</style>
