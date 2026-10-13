<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { api, subscribe, ApiError } from '$lib/api';

	// ── Types ──────────────────────────────────────────────
	interface ChatMessage {
		role: 'user' | 'assistant' | 'system' | 'tool' | 'recall';
		content: string;
		ts: string;
		meta?: Record<string, any>;
	}

	interface Conversation {
		id: string;
		started_at: string;
		message_count: number;
		first_message_preview: string;
	}

	// ── State ──────────────────────────────────────────────
	let messages = $state<ChatMessage[]>([]);
	let inputText = $state('');
	let isStreaming = $state(false);
	let isLoading = $state(true);
	let currentRunId = $state<string | null>(null);
	let errorMsg = $state<string | null>(null);

	// Status bar
	let connected = $state(false);
	let latencyMs = $state<number | null>(null);
	let clockTime = $state(formatTime(new Date()));

	// Session meta
	let sessionId = $state<string | null>(null);
	let blockCount = $state(0);
	let memoriesSurfaced = $state(0);

	// History panel
	let showHistory = $state(false);
	let conversations = $state<Conversation[]>([]);
	let loadingHistory = $state(false);

	// Attach button
	let attachedFile = $state<File | null>(null);
	let fileInputEl: HTMLInputElement | undefined = $state();

	// Goal mode
	let goalMode = $state(false);
	let goalText = $state('');
	let activeGoal = $state('');

	// Model info (from status endpoint)
	let modelName = $state('unknown');
	let maxTokens = $state(4096);

	// DOM refs
	let transcriptEl: HTMLDivElement | undefined = $state();
	let textareaEl: HTMLTextAreaElement | undefined = $state();
	let abortStream: (() => void) | null = null;

	// ── Helpers ────────────────────────────────────────────
	function formatTime(d: Date): string {
		return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
	}

	function formatDate(iso: string): string {
		const d = new Date(iso);
		const now = new Date();
		const isToday = d.toDateString() === now.toDateString();
		if (isToday) return 'today · ' + formatTime(d);
		return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' · ' + formatTime(d);
	}

	function shortId(id: string): string {
		return id.slice(0, 8);
	}

	async function scrollToBottom() {
		await tick();
		if (transcriptEl) {
			transcriptEl.scrollTo({ top: transcriptEl.scrollHeight, behavior: 'smooth' });
		}
	}

	function autoResize() {
		if (!textareaEl) return;
		textareaEl.style.height = 'auto';
		textareaEl.style.height = Math.min(textareaEl.scrollHeight, 200) + 'px';
	}

	// ── Connectivity check ────────────────────────────────
	async function checkStatus() {
		try {
			const start = performance.now();
			const res = await api<{
				status: string;
				model?: string;
				provider?: string;
				max_tokens?: number;
			}>('status');
			latencyMs = Math.round(performance.now() - start);
			connected = true;
			if (res.model) modelName = res.model;
			if (res.max_tokens) maxTokens = res.max_tokens;
		} catch {
			connected = false;
			latencyMs = null;
		}
	}

	// ── Attach handler ───────────────────────────────
	function openFilePicker() {
		fileInputEl?.click();
	}

	function handleFileSelected(e: Event) {
		const input = e.target as HTMLInputElement;
		if (input.files && input.files.length > 0) {
			attachedFile = input.files[0];
		}
		// Reset so the same file can be re-selected
		input.value = '';
	}

	function removeAttachment() {
		attachedFile = null;
	}

	// ── Goal handler ─────────────────────────────────
	function toggleGoalMode() {
		goalMode = !goalMode;
		if (!goalMode && goalText.trim()) {
			activeGoal = goalText.trim();
		}
	}

	function setGoal() {
		activeGoal = goalText.trim();
		goalMode = false;
	}

	function clearGoal() {
		activeGoal = '';
		goalText = '';
		goalMode = false;
	}

	// ── Send message ──────────────────────────────────
	async function sendMessage() {
		const text = inputText.trim();
		if (!text || isStreaming) return;

		inputText = '';
		if (textareaEl) {
			textareaEl.style.height = 'auto';
		}
		errorMsg = null;

		// Build the final message with goal/attachment prefixes
		let finalText = '';
		if (activeGoal) finalText += `[Goal: ${activeGoal}] `;
		if (attachedFile) finalText += `[Attached: ${attachedFile.name}] `;
		finalText += text;

		// Clear attachment after capturing filename
		attachedFile = null;

		// Add user message
		const userMsg: ChatMessage = {
			role: 'user',
			content: text,
			ts: new Date().toISOString()
		};
		messages.push(userMsg);
		blockCount++;
		await scrollToBottom();

		// Prepare assistant placeholder
		const assistantMsg: ChatMessage = {
			role: 'assistant',
			content: '',
			ts: new Date().toISOString()
		};
		messages.push(assistantMsg);
		isStreaming = true;

		try {
			const res = await api<{ run_id: string }>('chat', {
				method: 'POST',
				body: { message: finalText, user: 'william' }
			});

			if (res.run_id.startsWith('error:')) {
				isStreaming = false;
				assistantMsg.content = 'Error: ' + res.run_id.replace('error:', '');
				await scrollToBottom();
				return;
			}

			currentRunId = res.run_id;
			if (!sessionId) sessionId = res.run_id;

			// Subscribe to SSE stream
			abortStream = subscribe(
				'stream/' + res.run_id,
				(evt) => {
					if (evt.stream === 'tokens' && evt.event === 'token' && evt.data?.text) {
						assistantMsg.content += evt.data.text;
						scrollToBottom();
					} else if (evt.stream === 'tool') {
						// Insert tool marker before the assistant message
						const toolMsg: ChatMessage = {
							role: 'tool',
							content: evt.data?.tool || evt.event || 'tool',
							ts: new Date().toISOString(),
							meta: evt.data
						};
						// Insert before the last (assistant) message
						const idx = messages.length - 1;
						messages.splice(idx, 0, toolMsg);
					} else if (evt.stream === 'lifecycle' && evt.event === 'end') {
						isStreaming = false;
						currentRunId = null;
						blockCount++;
						if (abortStream) {
							abortStream();
							abortStream = null;
						}
					} else if (evt.stream === 'error') {
						errorMsg = evt.data?.message || 'An error occurred during processing.';
						isStreaming = false;
						if (abortStream) {
							abortStream();
							abortStream = null;
						}
					}
				},
				(err) => {
					if (isStreaming) {
						errorMsg = 'Stream connection lost.';
						isStreaming = false;
					}
				}
			);

			await scrollToBottom();
		} catch (err) {
			isStreaming = false;
			if (err instanceof ApiError) {
				errorMsg = err.detail || err.code;
			} else {
				errorMsg = 'Failed to send message.';
			}
			// Remove empty assistant placeholder on error
			if (assistantMsg.content === '') {
				messages.pop();
			}
		}
	}

	// ── Keyboard shortcuts ────────────────────────────────
	function handleKeydown(e: KeyboardEvent) {
		if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
			e.preventDefault();
			sendMessage();
		}
	}

	// ── History panel ─────────────────────────────────────
	async function loadConversations() {
		loadingHistory = true;
		try {
			const res = await api<{ items: Conversation[]; total: number }>('conversations', {
				params: { limit: 30 }
			});
			conversations = res.items || [];
		} catch {
			conversations = [];
		} finally {
			loadingHistory = false;
		}
	}

	async function loadConversation(id: string) {
		showHistory = false;
		isLoading = true;
		try {
			const res = await api<{
				id: string;
				started_at: string;
				message_count: number;
				messages: Array<{ role: string; content: string; ts: string }>;
			}>('conversations/' + id);

			sessionId = res.id;
			blockCount = res.message_count;
			messages = res.messages.map((m) => ({
				role: m.role as 'user' | 'assistant',
				content: m.content,
				ts: m.ts
			}));
			await scrollToBottom();
		} catch (err) {
			if (err instanceof ApiError && err.statusCode === 404) {
				errorMsg = 'Conversation not found.';
			} else {
				errorMsg = 'Failed to load conversation.';
			}
		} finally {
			isLoading = false;
		}
	}

	function toggleHistory() {
		showHistory = !showHistory;
		if (showHistory) loadConversations();
	}

	function startNewChat() {
		messages = [];
		sessionId = null;
		blockCount = 0;
		memoriesSurfaced = 0;
		errorMsg = null;
		showHistory = false;
		attachedFile = null;
		activeGoal = '';
		goalText = '';
		goalMode = false;
	}

	// ── Lifecycle ─────────────────────────────────────────
	onMount(() => {
		isLoading = false;

		// Check status immediately and periodically
		checkStatus();
		const statusInterval = setInterval(checkStatus, 15000);

		// Update clock
		const clockInterval = setInterval(() => {
			clockTime = formatTime(new Date());
		}, 10000);

		return () => {
			clearInterval(statusInterval);
			clearInterval(clockInterval);
			if (abortStream) abortStream();
		};
	});
</script>

<svelte:head>
	<title>ARIA — Workstream</title>
</svelte:head>

<div class="workstream">
	<!-- Status bar -->
	<div class="status-bar">
		<div class="status-left">
			<span
				class="diamond-sm"
				class:diamond-ok={connected}
				class:diamond-off={!connected}
				aria-hidden="true"
			></span>
			<span class="status-label" class:status-connected={connected}>
				{modelName} · {connected ? 'connected' : 'disconnected'}
			</span>
			{#if latencyMs !== null}
				<span class="status-latency">· {latencyMs}ms</span>
			{/if}
		</div>
		<span class="status-clock">{clockTime}</span>
	</div>

	<!-- Session meta -->
	{#if sessionId || messages.length > 0}
		<div class="session-meta">
			<span class="diamond-processing" aria-hidden="true"></span>
			<span class="meta-id">
				session {sessionId ? shortId(sessionId) : 'new'}
			</span>
			<span class="meta-sep">·</span>
			<span class="meta-stats">
				{blockCount} blocks · {memoriesSurfaced} memories surfaced
			</span>
		</div>
	{/if}

	<!-- Transcript -->
	<div class="transcript" bind:this={transcriptEl}>
		<div class="transcript-inner">
			{#if isLoading}
				<div class="empty-state">
					<span class="diamond-lg" aria-hidden="true"></span>
					<p>Loading...</p>
				</div>
			{:else if messages.length === 0}
				<div class="empty-state">
					<span class="diamond-lg" aria-hidden="true"></span>
					<p class="empty-title">ARIA Workstream</p>
					<p class="empty-sub">Start a conversation. ARIA is listening.</p>
				</div>
			{:else}
				<div class="message-list">
					{#each messages as msg, i (i)}
						{#if msg.role === 'user'}
							<!-- System time marker before user messages -->
							<div class="system-note">
								<span>{formatDate(msg.ts)}</span>
								<span class="hr-line"></span>
							</div>
							<div class="user-line">
								<div class="marker marker--user">You</div>
								<div class="body">{msg.content}</div>
							</div>
						{:else if msg.role === 'assistant'}
							<div class="aria-line">
								<div class="marker marker--aria">ARIA</div>
								<div class="body">
									{#each msg.content.split('\n\n') as para}
										{#if para.trim()}
											<p>{para}</p>
										{/if}
									{/each}
									{#if isStreaming && i === messages.length - 1}
										<span class="caret"></span>
									{/if}
								</div>
							</div>
						{:else if msg.role === 'tool'}
							<div class="tool-line">
								<div class="marker marker--tool">tool · {msg.content}</div>
								<div class="tool-row">
									<div class="tool-info">
										<span class="tool-name">
											{msg.meta?.description || 'executing'}
										</span>
										{#if msg.meta?.sources}
											<span class="tool-sources">{msg.meta.sources}</span>
										{/if}
									</div>
									<div class="tool-status">
										<span class="diamond-sm diamond-sage" aria-hidden="true"></span>
										<span class="tool-timing">
											{msg.meta?.duration || 'running'}
										</span>
									</div>
								</div>
								<div class="tool-trace"></div>
							</div>
						{:else if msg.role === 'recall'}
							<div class="recall-line">
								<div class="marker marker--recall">
									recalled · {msg.meta?.age || 'memory'}
								</div>
								<div class="body">{msg.content}</div>
								{#if msg.meta?.strength}
									<div class="recall-meta">
										<span>strength</span>
										<div class="strength-bar">
											<div style="width: {msg.meta.strength * 100}%"></div>
										</div>
										<span>{msg.meta.strength.toFixed(2)}</span>
									</div>
								{/if}
							</div>
						{:else if msg.role === 'system'}
							<div class="system-note">
								<span>{msg.content}</span>
								<span class="hr-line"></span>
							</div>
						{/if}
					{/each}
				</div>
			{/if}

			<!-- Activity indicator -->
			{#if isStreaming}
				<div class="activity-row" role="status" aria-live="polite">
					<div class="activity-thread"></div>
					<span>ARIA is reflecting<span class="caret"></span></span>
				</div>
			{/if}
		</div>
	</div>

	<!-- Error banner -->
	{#if errorMsg}
		<div class="error-banner" role="alert">
			<span>{errorMsg}</span>
			<button class="error-dismiss" onclick={() => (errorMsg = null)}>dismiss</button>
		</div>
	{/if}

	<!-- Hidden file input for Attach -->
	<input
		type="file"
		bind:this={fileInputEl}
		onchange={handleFileSelected}
		style="display:none;"
	/>

	<!-- Active goal banner -->
	{#if activeGoal}
		<div class="goal-banner">
			<span class="goal-banner-icon">&#9672;</span>
			<span class="goal-banner-text">Goal: {activeGoal}</span>
			<button class="goal-banner-dismiss" onclick={clearGoal}>dismiss</button>
		</div>
	{/if}

	<!-- Compose area -->
	<div class="compose-shell">
		<div class="compose-inner">
			<div class="compose" class:compose-disabled={isStreaming}>
				<!-- Goal input field -->
				{#if goalMode}
					<div class="goal-input-row">
						<span class="goal-input-icon">&#9672;</span>
						<input
							class="goal-input"
							type="text"
							bind:value={goalText}
							placeholder="Set a persistent goal for this session..."
							onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); setGoal(); } }}
						/>
						<button class="ghost-btn goal-set-btn" onclick={setGoal} disabled={!goalText.trim()}>Set</button>
						<button class="ghost-btn" onclick={() => { goalMode = false; }}>Cancel</button>
					</div>
				{/if}

				<!-- Attached file chip -->
				{#if attachedFile}
					<div class="attach-chip-row">
						<span class="attach-chip">
							<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
							{attachedFile.name}
							<button class="attach-chip-remove" onclick={removeAttachment} aria-label="Remove attachment">&times;</button>
						</span>
					</div>
				{/if}

				<div class="compose-row">
					<textarea
						bind:this={textareaEl}
						bind:value={inputText}
						oninput={autoResize}
						onkeydown={handleKeydown}
						rows="1"
						aria-label="Message ARIA"
						placeholder="Continue the conversation... Ctrl/Cmd + Enter to send"
						disabled={isStreaming}
					></textarea>
					<button
						class="send-btn"
						onclick={sendMessage}
						disabled={isStreaming || !inputText.trim()}
						aria-label="Send message"
					>
						Send
						<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
					</button>
				</div>
				<div class="compose-footer">
					<div class="compose-actions">
						<button class="ghost-btn" aria-label="Attach file" onclick={openFilePicker}>
							<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
							Attach
						</button>
						<button class="ghost-btn" onclick={toggleHistory} aria-label="History">
							<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 2"/></svg>
							History
						</button>
						<button class="ghost-btn" class:ghost-btn-active={goalMode || !!activeGoal} aria-label="Goal" onclick={toggleGoalMode}>
							<span style="font-size:11px;">&#9672;</span>
							Goal
						</button>
					</div>
					<div class="compose-meta">
						<span class="meta-model">{modelName} · {maxTokens} ctx</span>
						<span class="meta-sep">·</span>
						<span class="meta-shortcut">Ctrl/Cmd + Enter</span>
					</div>
				</div>
			</div>
		</div>
	</div>

	<!-- History panel (overlay) -->
	{#if showHistory}
		<div class="history-overlay" role="dialog" aria-label="Conversation history">
			<div class="history-backdrop" onclick={() => (showHistory = false)}></div>
			<div class="history-panel">
				<div class="history-header">
					<h2>Conversations</h2>
					<div class="history-actions">
						<button class="ghost-btn" onclick={startNewChat}>+ New</button>
						<button class="history-close" onclick={() => (showHistory = false)} aria-label="Close history">
							<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
						</button>
					</div>
				</div>
				<div class="history-list">
					{#if loadingHistory}
						<div class="history-empty">Loading conversations...</div>
					{:else if conversations.length === 0}
						<div class="history-empty">No conversations yet.</div>
					{:else}
						{#each conversations as conv (conv.id)}
							<button
								class="history-item"
								onclick={() => loadConversation(conv.id)}
							>
								<div class="history-item-preview">
									{conv.first_message_preview || 'Empty conversation'}
								</div>
								<div class="history-item-meta">
									<span>{formatDate(conv.started_at)}</span>
									<span class="meta-sep">·</span>
									<span>{conv.message_count} messages</span>
								</div>
							</button>
						{/each}
					{/if}
				</div>
			</div>
		</div>
	{/if}
</div>

<style>
	/* ── Layout ──────────────────────────────────────── */
	.workstream {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		position: relative;
	}

	/* ── Status bar ──────────────────────────────────── */
	.status-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		height: 32px;
		padding: 0 20px;
		flex-shrink: 0;
	}
	.status-left {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.diamond-sm {
		display: inline-block;
		width: 6px;
		height: 6px;
		transform: rotate(45deg);
		border-radius: 1px;
	}
	.diamond-ok { background: var(--ok); }
	.diamond-off { background: var(--danger); }
	.diamond-sage {
		background: var(--sage);
		animation: pulse-soft 1.6s ease-in-out infinite;
	}
	.status-label {
		font-family: var(--font-mono);
		font-size: 11px;
		letter-spacing: 0.04em;
		color: var(--text-faint);
	}
	.status-connected { color: var(--ok); opacity: 0.75; }
	.status-latency {
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-faint);
	}
	.status-clock {
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--text-faint);
	}

	/* ── Session meta ────────────────────────────────── */
	.session-meta {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 20px 0;
		animation: reveal-up 350ms var(--ease-arrive) both;
		flex-shrink: 0;
	}
	.diamond-processing {
		display: inline-block;
		width: 8px;
		height: 8px;
		transform: rotate(45deg);
		border-radius: 1px;
		background: var(--accent);
		animation: breathe 2.4s ease-in-out infinite;
	}
	.diamond-lg {
		display: inline-block;
		width: 16px;
		height: 16px;
		transform: rotate(45deg);
		border-radius: 1px;
		background: var(--accent);
		animation: breathe 3s ease-in-out infinite;
	}
	.meta-id {
		font-family: var(--font-mono);
		font-size: 11px;
		letter-spacing: 0.05em;
		color: var(--text-faint);
	}
	.meta-sep { color: var(--text-faint); font-size: 11px; }
	.meta-stats {
		font-family: var(--font-mono);
		font-size: 11px;
		letter-spacing: 0.02em;
		color: var(--text-muted);
	}

	/* ── Transcript ──────────────────────────────────── */
	.transcript {
		flex: 1;
		overflow-y: auto;
		min-height: 0;
	}
	.transcript::-webkit-scrollbar { width: 10px; }
	.transcript::-webkit-scrollbar-track { background: transparent; }
	.transcript::-webkit-scrollbar-thumb {
		background: var(--border-strong);
		border-radius: 10px;
		border: 3px solid var(--bg);
	}
	.transcript::-webkit-scrollbar-thumb:hover { background: var(--border-strong); }
	.transcript-inner {
		max-width: 1000px;
		margin: 0 auto;
		padding: 24px 56px 12px;
	}

	/* ── Empty state ─────────────────────────────────── */
	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 16px;
		padding-top: 120px;
		color: var(--text-faint);
	}
	.empty-title {
		font-size: 18px;
		font-weight: 500;
		color: var(--text-strong);
		margin: 0;
	}
	.empty-sub {
		font-size: 13px;
		color: var(--text-muted);
		margin: 0;
	}

	/* ── Message list ────────────────────────────────── */
	.message-list {
		display: flex;
		flex-direction: column;
		gap: 28px;
	}

	/* Markers */
	.marker {
		font-family: var(--font-mono);
		font-size: 10px;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		font-weight: 500;
		color: var(--text-faint);
		display: inline-flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 8px;
	}
	.marker::before {
		content: "";
		display: inline-block;
		width: 18px;
		height: 1px;
		background: var(--border-strong);
	}
	.marker--user::before { background: rgba(212,160,74,0.30); }
	.marker--aria { color: var(--accent); }
	.marker--aria::before {
		background: var(--accent);
		box-shadow: 0 0 6px var(--accent-glow);
		width: 24px;
	}
	.marker--recall { color: var(--accent-dim); }
	.marker--recall::before { background: var(--accent-dim); width: 22px; }
	.marker--tool { color: var(--sage); }
	.marker--tool::before { background: var(--sage); }

	/* User message */
	.user-line {
		position: relative;
		padding: 4px 0;
		animation: reveal-up 350ms var(--ease-arrive) both;
	}
	.user-line .body {
		color: var(--text-strong);
		font-size: 16px;
		line-height: 1.55;
		font-weight: 500;
		max-width: 72ch;
		white-space: pre-wrap;
		word-break: break-word;
	}

	/* ARIA message */
	.aria-line {
		position: relative;
		padding: 4px 0 4px 18px;
		animation: reveal-up 350ms var(--ease-arrive) both;
	}
	.aria-line::before {
		content: "";
		position: absolute;
		left: 0;
		top: 8px;
		bottom: 8px;
		width: 2px;
		background: linear-gradient(180deg, var(--accent), var(--accent-dim) 70%, transparent);
		border-radius: 1px;
		box-shadow: 0 0 8px var(--accent-glow);
	}
	.aria-line .body {
		font-size: 15px;
		line-height: 1.62;
		color: var(--text);
		max-width: 72ch;
		white-space: pre-wrap;
		word-break: break-word;
	}
	.aria-line .body p { margin: 0; }
	.aria-line .body p + p { margin-top: 10px; }

	/* Tool line */
	.tool-line {
		position: relative;
		padding: 4px 0 4px 18px;
		animation: reveal-up 350ms var(--ease-arrive) both;
		border-left: 2px solid rgba(124,154,142,0.40);
	}
	.tool-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 14px;
		font-family: var(--font-mono);
		font-size: 12px;
		color: var(--text-muted);
		flex-wrap: wrap;
	}
	.tool-info {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	.tool-name { color: var(--text-strong); font-weight: 500; }
	.tool-sources { color: var(--text-faint); font-size: 11px; }
	.tool-status {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.tool-timing {
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-muted);
	}
	.tool-trace {
		position: relative;
		height: 1px;
		width: 100%;
		background: var(--border);
		overflow: hidden;
		margin-top: 6px;
	}
	.tool-trace::after {
		content: "";
		position: absolute;
		top: 0;
		bottom: 0;
		width: 30%;
		background: linear-gradient(90deg, transparent, var(--sage), transparent);
		animation: trace-scan 1.8s ease-in-out infinite;
	}

	/* Recall line */
	.recall-line {
		position: relative;
		padding: 4px 0 4px 18px;
		border-left: 2px solid var(--accent-dim);
	}
	.recall-line .body {
		font-style: italic;
		font-size: 14.5px;
		line-height: 1.65;
		color: var(--text);
		max-width: 68ch;
	}
	.recall-meta {
		margin-top: 8px;
		display: flex;
		align-items: center;
		gap: 14px;
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-faint);
		letter-spacing: 0.04em;
	}
	.strength-bar {
		position: relative;
		height: 2px;
		width: 56px;
		background: var(--border);
		border-radius: 1px;
		overflow: hidden;
	}
	.strength-bar > div {
		position: absolute;
		inset: 0;
		background: var(--accent);
		box-shadow: 0 0 6px var(--accent-glow);
	}

	/* System note */
	.system-note {
		display: flex;
		align-items: center;
		gap: 12px;
		color: var(--text-faint);
		font-family: var(--font-mono);
		font-size: 10px;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		margin: 4px 0 0;
	}
	.hr-line {
		flex: 1;
		height: 1px;
		background: linear-gradient(90deg, var(--border), transparent);
	}

	/* Activity indicator */
	.activity-row {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 12px 0 0 18px;
		color: var(--text-muted);
		font-size: 12px;
	}
	.activity-thread {
		height: 2px;
		background: var(--accent);
		border-radius: 1px;
		animation: thread-draw 2.5s ease-in-out infinite;
		box-shadow: 0 0 6px var(--accent-glow);
	}

	/* Caret */
	.caret {
		display: inline-block;
		width: 7px;
		height: 14px;
		background: var(--accent);
		margin-left: 2px;
		animation: caret-blink 1.1s steps(1) infinite;
		vertical-align: -2px;
	}

	/* ── Error banner ────────────────────────────────── */
	.error-banner {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 12px;
		padding: 8px 20px;
		background: var(--danger-subtle);
		color: var(--danger);
		font-size: 13px;
		flex-shrink: 0;
	}
	.error-dismiss {
		background: none;
		border: none;
		color: var(--danger);
		font-size: 12px;
		cursor: pointer;
		text-decoration: underline;
		font-family: var(--font-mono);
	}

	/* ── Compose area ────────────────────────────────── */
	.compose-shell {
		position: sticky;
		bottom: 0;
		padding: 28px 0;
		background: linear-gradient(to top, var(--bg) 55%, rgba(17,18,16,0.92) 80%, transparent 100%);
		z-index: 4;
		flex-shrink: 0;
	}
	.compose-inner {
		max-width: 1000px;
		margin: 0 auto;
		padding: 0 56px;
	}
	.compose {
		position: relative;
		background: var(--bg-elevated);
		border: 1px solid var(--border);
		border-radius: 14px;
		padding: 14px 16px;
		transition: border-color 180ms var(--ease-micro), box-shadow 180ms var(--ease-micro);
	}
	.compose:focus-within {
		border-color: rgba(212,160,74,0.45);
		box-shadow: 0 0 0 3px rgba(212,160,74,0.10), 0 6px 24px rgba(0,0,0,0.30);
	}
	.compose-disabled {
		opacity: 0.7;
		pointer-events: none;
	}
	.compose-row {
		display: flex;
		align-items: flex-end;
		gap: 12px;
	}
	.compose textarea {
		flex: 1;
		width: 100%;
		background: transparent;
		border: 0;
		color: var(--text);
		font-family: var(--font-body);
		font-size: 14px;
		line-height: 1.55;
		resize: none;
		outline: none;
		min-height: 44px;
		max-height: 200px;
	}
	.compose textarea::placeholder { color: var(--text-faint); }
	.compose textarea:disabled { cursor: not-allowed; }

	.send-btn {
		height: 36px;
		padding: 0 16px;
		background: var(--accent);
		color: #1a1710;
		font-weight: 600;
		font-size: 13px;
		border-radius: 8px;
		border: 1px solid var(--accent);
		box-shadow: 0 1px 8px var(--accent-glow);
		display: inline-flex;
		align-items: center;
		gap: 8px;
		transition: all 180ms var(--ease-micro);
		cursor: pointer;
		flex-shrink: 0;
	}
	.send-btn:hover:not(:disabled) {
		background: var(--accent-hi);
		transform: translateY(-1px);
	}
	.send-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
		transform: none;
	}

	.compose-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-top: 12px;
		padding-top: 12px;
		border-top: 1px solid rgba(42,39,37,0.7);
	}
	.compose-actions {
		display: flex;
		align-items: center;
		gap: 4px;
	}
	.ghost-btn {
		height: 32px;
		padding: 0 12px;
		background: transparent;
		color: var(--text-muted);
		font-size: 12px;
		font-weight: 500;
		border-radius: 8px;
		border: 1px solid transparent;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		transition: all 180ms var(--ease-micro);
		cursor: pointer;
		font-family: var(--font-body);
	}
	.ghost-btn:hover {
		background: var(--bg-hover);
		color: var(--text);
		border-color: var(--border);
	}
	.compose-meta {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.meta-model,
	.meta-shortcut {
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-faint);
	}

	/* ── Goal banner ─────────────────────────────────── */
	.goal-banner {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 20px;
		background: rgba(212,160,74,0.08);
		border-bottom: 1px solid rgba(212,160,74,0.18);
		flex-shrink: 0;
		animation: reveal-up 250ms var(--ease-arrive) both;
	}
	.goal-banner-icon {
		font-size: 11px;
		color: var(--accent);
	}
	.goal-banner-text {
		font-family: var(--font-mono);
		font-size: 12px;
		color: var(--accent);
		letter-spacing: 0.02em;
		flex: 1;
	}
	.goal-banner-dismiss {
		background: none;
		border: none;
		color: var(--text-faint);
		font-size: 11px;
		cursor: pointer;
		text-decoration: underline;
		font-family: var(--font-mono);
		transition: color 150ms;
	}
	.goal-banner-dismiss:hover { color: var(--text); }

	/* ── Goal input row ──────────────────────────────── */
	.goal-input-row {
		display: flex;
		align-items: center;
		gap: 8px;
		padding-bottom: 12px;
		margin-bottom: 12px;
		border-bottom: 1px solid rgba(42,39,37,0.7);
		animation: reveal-up 200ms var(--ease-arrive) both;
	}
	.goal-input-icon {
		font-size: 11px;
		color: var(--accent);
		flex-shrink: 0;
	}
	.goal-input {
		flex: 1;
		background: transparent;
		border: 1px solid var(--border);
		border-radius: 6px;
		color: var(--text);
		font-family: var(--font-mono);
		font-size: 12px;
		padding: 6px 10px;
		outline: none;
		transition: border-color 150ms;
	}
	.goal-input:focus {
		border-color: rgba(212,160,74,0.45);
	}
	.goal-input::placeholder { color: var(--text-faint); }
	.goal-set-btn:disabled { opacity: 0.4; cursor: not-allowed; }

	/* ── Attach chip ─────────────────────────────────── */
	.attach-chip-row {
		padding-bottom: 10px;
		animation: reveal-up 200ms var(--ease-arrive) both;
	}
	.attach-chip {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 4px 10px;
		background: rgba(212,160,74,0.10);
		border: 1px solid rgba(212,160,74,0.22);
		border-radius: 6px;
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--accent);
		letter-spacing: 0.02em;
	}
	.attach-chip-remove {
		background: none;
		border: none;
		color: var(--text-faint);
		font-size: 14px;
		cursor: pointer;
		padding: 0 2px;
		line-height: 1;
		transition: color 150ms;
	}
	.attach-chip-remove:hover { color: var(--danger); }

	/* ── Ghost button active state ───────────────────── */
	.ghost-btn-active {
		background: rgba(212,160,74,0.10);
		color: var(--accent);
		border-color: rgba(212,160,74,0.22);
	}

	/* ── History panel ───────────────────────────────── */
	.history-overlay {
		position: fixed;
		inset: 0;
		z-index: 50;
		display: flex;
		justify-content: flex-end;
	}
	.history-backdrop {
		position: absolute;
		inset: 0;
		background: rgba(0,0,0,0.5);
	}
	.history-panel {
		position: relative;
		width: 380px;
		max-width: 100%;
		background: var(--bg-surface);
		border-left: 1px solid var(--border);
		display: flex;
		flex-direction: column;
		animation: reveal-right 250ms var(--ease-arrive) both;
	}
	.history-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px 20px;
		border-bottom: 1px solid var(--border);
	}
	.history-header h2 {
		font-size: 14px;
		font-weight: 600;
		color: var(--text-strong);
		margin: 0;
	}
	.history-actions {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.history-close {
		width: 28px;
		height: 28px;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: 6px;
		border: none;
		background: none;
		color: var(--text-faint);
		cursor: pointer;
		transition: all 150ms;
	}
	.history-close:hover {
		background: var(--bg-hover);
		color: var(--text);
	}
	.history-list {
		flex: 1;
		overflow-y: auto;
		padding: 8px;
	}
	.history-empty {
		padding: 40px 20px;
		text-align: center;
		color: var(--text-faint);
		font-size: 13px;
	}
	.history-item {
		display: block;
		width: 100%;
		text-align: left;
		padding: 12px 14px;
		border-radius: 8px;
		border: none;
		background: none;
		color: var(--text);
		cursor: pointer;
		transition: background 150ms;
		font-family: var(--font-body);
	}
	.history-item:hover { background: var(--bg-hover); }
	.history-item-preview {
		font-size: 13px;
		line-height: 1.4;
		color: var(--text);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.history-item-meta {
		margin-top: 4px;
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-faint);
		display: flex;
		align-items: center;
		gap: 6px;
	}

	/* ── Keyframes ────────────────────────────────────── */
	@keyframes trace-scan {
		0%   { left: -30%; }
		100% { left: 100%; }
	}
	@keyframes thread-draw {
		0%   { width: 0;    opacity: 0; }
		15%  { width: 24px; opacity: 1; }
		40%  { width: 24px; opacity: 1; }
		60%  { width: 56px; opacity: 0.85; }
		80%  { width: 56px; opacity: 0.4; }
		100% { width: 0;    opacity: 0; }
	}
	@keyframes caret-blink {
		0%, 50%   { opacity: 1; }
		51%, 100% { opacity: 0; }
	}
	@keyframes reveal-right {
		from { transform: translateX(100%); }
		to   { transform: translateX(0); }
	}

	/* ── Responsive ──────────────────────────────────── */
	@media (max-width: 768px) {
		.transcript-inner { padding: 16px; }
		.compose-inner { padding: 0 16px; }
		.compose-shell { padding: 24px 0 80px; }
		.compose-meta { display: none; }
		.history-panel { width: 100%; }
	}
</style>
