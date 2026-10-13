<script lang="ts">
	import { api } from '$lib/api';
	import { onMount } from 'svelte';

	/* ── Types ── */
	interface Memory {
		id: string;
		content: string;
		context: string;
		emotional_tone: string | null;
		emotional_intensity: number;
		origin: string | null;
		involves_people: string[];
		tags: string[];
		strength: number;
		recall_count: number;
		created_at: string | null;
		consolidated_count: number;
		importance: number;
		is_mine: boolean;
		last_recalled: string | null;
		connected_memories: string[];
		relationship_impact: Record<string, any>;
		duration_feeling: string;
		confidence: number;
		consolidated: boolean;
		encoding_context: string;
	}

	interface Dashboard {
		total: number;
		forgotten: number;
		oldest_days: number;
		origins: Record<string, number>;
		emotions: Record<string, number>;
		people: Record<string, number>;
	}

	interface MemoriesResponse {
		items: Memory[];
		total: number;
		limit: number;
		offset: number;
	}

	/* ── State ── */
	let dashboard: Dashboard | null = $state(null);
	let memories: Memory[] = $state([]);
	let total: number = $state(0);
	let loading: boolean = $state(true);
	let loadingMore: boolean = $state(false);
	let error: string | null = $state(null);

	let activeFilter: string = $state('all');
	let sortBy: string = $state('recent');
	let searchQuery: string = $state('');
	let offset: number = $state(0);
	const LIMIT = 20;

	let debounceTimer: ReturnType<typeof setTimeout> | undefined;
	let searchInput: HTMLInputElement | undefined = $state(undefined);

	/* ── Tone color map ── */
	const toneColors: Record<string, string> = {
		curious: 'var(--info)',
		inspired: 'var(--accent)',
		connected: 'var(--accent)',
		peaceful: 'var(--sage)',
		anxious: 'var(--danger)',
		confused: 'var(--text-muted)'
	};

	/* ── Strength class ── */
	function strengthClass(s: number): string {
		if (s >= 0.75) return 'high';
		if (s >= 0.4) return 'mid';
		return 'low';
	}

	/* ── Time ago ── */
	function timeAgo(iso: string | null): string {
		if (!iso) return 'unknown';
		const diff = Date.now() - new Date(iso).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hours = Math.floor(mins / 60);
		if (hours < 24) return `${hours}h ago`;
		const days = Math.floor(hours / 24);
		if (days < 30) return `${days}d ago`;
		const months = Math.floor(days / 30);
		return `${months}mo ago`;
	}

	/* ── Build params ── */
	function buildParams(): Record<string, string | number | undefined> {
		const p: Record<string, string | number | undefined> = {
			limit: LIMIT,
			offset: 0,
			sort: sortBy
		};
		if (searchQuery.trim()) p.q = searchQuery.trim();

		if (activeFilter === 'lived' || activeFilter === 'reflected' || activeFilter === 'discovered') {
			p.origin = activeFilter;
		} else if (activeFilter === 'consolidated') {
			// consolidated is not an origin filter, but we can use it as a tag or special handling
			// The API doesn't have a dedicated consolidated param, so we filter client-side or pass as tag
			p.origin = undefined;
		} else if (activeFilter === 'with_person') {
			// People filter: use the top person from dashboard
			if (dashboard?.people) {
				const topPerson = Object.keys(dashboard.people)[0];
				if (topPerson) p.person = topPerson;
			}
		}

		return p;
	}

	/* ── Fetch dashboard ── */
	async function fetchDashboard() {
		try {
			dashboard = await api<Dashboard>('memories/dashboard');
		} catch (e: any) {
			if (e?.statusCode === 503) {
				error = 'Memory system not available';
			}
		}
	}

	/* ── Fetch memories ── */
	async function fetchMemories(append = false) {
		if (!append) {
			loading = true;
			offset = 0;
		} else {
			loadingMore = true;
		}

		try {
			const params = buildParams();
			if (append) params.offset = offset;

			const res = await api<MemoriesResponse>('memories', { params });

			if (append) {
				memories = [...memories, ...res.items];
			} else {
				memories = res.items;
			}
			total = res.total;
			error = null;
		} catch (e: any) {
			if (!append) error = e?.detail || 'Failed to load memories';
		} finally {
			loading = false;
			loadingMore = false;
		}
	}

	/* ── Filter change ── */
	function setFilter(f: string) {
		activeFilter = f;
		fetchMemories();
	}

	/* ── Sort change ── */
	function handleSort(e: Event) {
		const target = e.target as HTMLSelectElement;
		const val = target.value;
		const sortMap: Record<string, string> = {
			'recent': 'recent',
			'strongest': 'strongest',
			'most recalled': 'recalled',
			'oldest': 'oldest'
		};
		sortBy = sortMap[val] || 'recent';
		fetchMemories();
	}

	/* ── Search debounce ── */
	function handleSearch(e: Event) {
		const target = e.target as HTMLInputElement;
		searchQuery = target.value;
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => fetchMemories(), 300);
	}

	/* ── Load more ── */
	function loadMore() {
		offset += LIMIT;
		fetchMemories(true);
	}

	/* ── Keyboard shortcut ── */
	function handleKeydown(e: KeyboardEvent) {
		if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
			e.preventDefault();
			searchInput?.focus();
		}
	}

	/* ── Top entries helper ── */
	function topEntries(obj: Record<string, number> | undefined, max: number): [string, number][] {
		if (!obj) return [];
		const entries = Object.entries(obj).sort((a, b) => b[1] - a[1]);
		return entries.slice(0, max);
	}

	function othersCount(obj: Record<string, number> | undefined, shown: number): { count: number; total: number } {
		if (!obj) return { count: 0, total: 0 };
		const entries = Object.entries(obj).sort((a, b) => b[1] - a[1]);
		if (entries.length <= shown) return { count: 0, total: 0 };
		const rest = entries.slice(shown);
		return {
			count: rest.length,
			total: rest.reduce((s, [, v]) => s + v, 0)
		};
	}

	/* ── Derived: top person name for chip label ── */
	let topPersonName: string = $derived((() => {
		const d = dashboard as Dashboard | null;
		if (!d?.people) return '';
		const keys = Object.keys(d.people);
		keys.sort((a, b) => (d.people[b] ?? 0) - (d.people[a] ?? 0));
		return keys[0] ?? '';
	})());

	/* ── Init ── */
	onMount(() => {
		fetchDashboard();
		fetchMemories();
	});
</script>

<svelte:head>
	<title>ARIA — Memories</title>
</svelte:head>

<svelte:window on:keydown={handleKeydown} />

<div class="page">

	<!-- Header -->
	<header class="header">
		<h1>memories</h1>
		<span class="meta">
			<span class="live">remembering</span>
		</span>
	</header>

	<!-- Dashboard -->
	{#if dashboard}
		<section class="dash">
			<div class="dash-cell">
				<div class="dash-label">total &middot; experiential</div>
				<div class="dash-total">{dashboard.total ?? 0}</div>
				<div class="dash-total-sub">
					{#each topEntries(dashboard.origins, 3) as [name, count], i}
						{#if i > 0} &middot; {/if}{count} {name}
					{/each}
					<br>
					<span class="faint">{dashboard.forgotten ?? 0} forgotten &middot; {dashboard.oldest_days ?? 0}d old</span>
				</div>
			</div>

			<div class="dash-cell">
				<div class="dash-label">emotional tone</div>
				<div class="dash-list">
					{#each topEntries(dashboard.emotions, 4) as [name, count], i}
						<div class="dash-row">
							<span class="name" class:hi={i < 2}>{name}</span>
							<span class="num" class:hi={i < 2}>{count}</span>
						</div>
					{/each}
					{#if othersCount(dashboard.emotions, 4).count > 0}
						<div class="dash-row">
							<span class="name">+ {othersCount(dashboard.emotions, 4).count} others</span>
							<span class="num">{othersCount(dashboard.emotions, 4).total}</span>
						</div>
					{/if}
				</div>
			</div>

			<div class="dash-cell">
				<div class="dash-label">people</div>
				<div class="dash-list">
					{#each topEntries(dashboard.people, 4) as [name, count], i}
						<div class="dash-row">
							<span class="name" class:hi={i === 0}>{name}</span>
							<span class="num" class:hi={i === 0}>{count}</span>
						</div>
					{/each}
					{#if othersCount(dashboard.people, 4).count > 0}
						<div class="dash-row">
							<span class="name">+ {othersCount(dashboard.people, 4).count} others</span>
							<span class="num">{othersCount(dashboard.people, 4).total}</span>
						</div>
					{/if}
				</div>
			</div>
		</section>
	{/if}

	<!-- Search -->
	<div class="search">
		<span class="icon" aria-hidden="true">⌕</span>
		<input
			type="text"
			bind:this={searchInput}
			aria-label="Search memories"
			placeholder="search memories...  e.g. 'cuando hablamos de olvido'"
			value={searchQuery}
			oninput={handleSearch}
		/>
		<span class="kbd" aria-hidden="true">⌘K</span>
	</div>

	<!-- Filters -->
	<div class="filters" role="group" aria-label="Filter memories">
		<button type="button" class="chip" aria-pressed={activeFilter === 'all'} onclick={() => setFilter('all')}>all</button>
		<button type="button" class="chip" aria-pressed={activeFilter === 'lived'} onclick={() => setFilter('lived')}>lived</button>
		<button type="button" class="chip" aria-pressed={activeFilter === 'reflected'} onclick={() => setFilter('reflected')}>reflected</button>
		<button type="button" class="chip" aria-pressed={activeFilter === 'discovered'} onclick={() => setFilter('discovered')}>discovered</button>
		<span class="sep" aria-hidden="true"></span>
		<button type="button" class="chip" aria-pressed={activeFilter === 'consolidated'} onclick={() => setFilter('consolidated')}>consolidated</button>
		{#if topPersonName}
			<button type="button" class="chip" aria-pressed={activeFilter === 'with_person'} onclick={() => setFilter('with_person')}>with {topPersonName}</button>
		{/if}
		<span class="spacer"></span>
		<select aria-label="Sort memories" onchange={handleSort}>
			<option>recent</option>
			<option>strongest</option>
			<option>most recalled</option>
			<option>oldest</option>
		</select>
	</div>

	<!-- Error state -->
	{#if error}
		<div class="empty-state">
			<span class="diamond" aria-hidden="true"></span>
			<p>{error}</p>
		</div>
	{/if}

	<!-- Loading state -->
	{#if loading}
		<div class="empty-state">
			<span class="diamond diamond--breathing" aria-hidden="true"></span>
			<p>loading memories...</p>
		</div>
	{:else if memories.length === 0 && !error}
		<div class="empty-state">
			<span class="diamond" aria-hidden="true"></span>
			<p>ARIA doesn't have any memories yet.</p>
		</div>
	{:else}
		<!-- Memory list -->
		<section class="memlist">
			{#each memories as mem, i}
				<article class="mem" role="button" tabindex="0" style="animation-delay: {200 + Math.min(i, 5) * 60}ms;">
					<div class="mem-content">{mem.content}</div>
					<div class="mem-meta">
						{#if mem.emotional_tone}
							<span class="tone" style="color: {toneColors[mem.emotional_tone] ?? 'var(--text-faint)'};">
								{mem.emotional_tone}
							</span>
							<span class="dot">&middot;</span>
						{/if}
						{#if mem.origin}
							<span class="origin">{mem.origin}</span>
							<span class="dot">&middot;</span>
						{/if}
						{#each mem.involves_people as person}
							<span class="with">with {person}</span>
							<span class="dot">&middot;</span>
						{/each}
						<span>{timeAgo(mem.created_at)}</span>
						{#if mem.consolidated_count > 0}
							<span>&middot; consolidated &times;{mem.consolidated_count}</span>
						{/if}
						{#each mem.tags as tag}
							<span class="tag">{tag}</span>
						{/each}
					</div>
					<div class="mem-side">
						<div class="strength {strengthClass(mem.strength)}">
							<i style="width: {Math.round(mem.strength * 100)}%;"></i>
						</div>
						<div class="num"><span class="v">{mem.strength.toFixed(2)}</span> &middot; recalled {mem.recall_count}&times;</div>
					</div>
				</article>
			{/each}
		</section>

		<!-- Footer -->
		<div class="footer">
			{#if memories.length < total}
				<button onclick={loadMore} disabled={loadingMore}>
					{loadingMore ? 'loading...' : 'load more'}
				</button>
			{/if}
			<div class="count">showing {memories.length} of {total}</div>
		</div>
	{/if}

</div>

<style>
	/* === Page layout === */
	.page {
		max-width: 880px;
		margin: 0 auto;
		padding: 48px 32px 96px;
		position: relative;
		z-index: 2;
	}

	/* === Header === */
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

	/* === Dashboard === */
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

	.dash-total-sub {
		font-size: 11px;
		color: var(--text-muted);
		margin-top: 6px;
		line-height: 1.5;
	}

	.dash-total-sub .faint {
		color: var(--text-faint);
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

	.dash-row .name.hi {
		color: var(--accent);
	}

	.dash-row .num.hi {
		color: var(--accent);
	}

	/* === Search === */
	.search {
		position: relative;
		margin-bottom: 14px;
		animation: reveal-up 350ms var(--ease-arrive) both;
		animation-delay: 120ms;
	}

	.search input {
		width: 100%;
		height: 48px;
		background: var(--bg-card);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 0 16px 0 42px;
		font-size: 14px;
		color: var(--text-strong);
		font-family: var(--font-body);
		transition: border-color 150ms, box-shadow 150ms;
	}

	.search input::placeholder {
		color: var(--text-faint);
		font-style: italic;
	}

	.search input:focus {
		outline: none;
		border-color: var(--accent);
		box-shadow: 0 0 0 3px var(--accent-subtle);
	}

	.search .icon {
		position: absolute;
		left: 16px;
		top: 50%;
		transform: translateY(-50%);
		color: var(--accent);
		font-size: 16px;
	}

	.search .kbd {
		position: absolute;
		right: 14px;
		top: 50%;
		transform: translateY(-50%);
		font-family: var(--font-mono);
		font-size: 10px;
		color: var(--text-faint);
		background: var(--bg-hover);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 3px 7px;
	}

	/* === Filters === */
	.filters {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
		margin-bottom: 24px;
		font-size: 12px;
		animation: reveal-up 350ms var(--ease-arrive) both;
		animation-delay: 160ms;
	}

	.chip {
		padding: 7px 12px;
		border-radius: 999px;
		min-height: 32px;
		background: var(--bg-card);
		border: 1px solid var(--border);
		color: var(--text-muted);
		cursor: pointer;
		transition: all 120ms;
		font-family: var(--font-body);
		font-size: 12px;
		font-weight: inherit;
		line-height: 1;
		display: inline-flex;
		align-items: center;
	}

	.chip:hover {
		color: var(--text);
		border-color: var(--border-strong);
	}

	.chip[aria-pressed='true'] {
		background: var(--accent-subtle);
		color: var(--accent);
		border-color: rgba(212, 160, 74, 0.35);
	}

	.sep {
		width: 1px;
		height: 14px;
		background: var(--border);
		margin: 0 4px;
	}

	.spacer {
		flex: 1;
	}

	.filters select {
		background: var(--bg-card);
		border: 1px solid var(--border);
		color: var(--text-muted);
		font-size: 12px;
		padding: 5px 26px 5px 11px;
		border-radius: 999px;
		appearance: none;
		cursor: pointer;
		font-family: var(--font-body);
		background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path d='M1 1l4 4 4-4' stroke='%238a857d' stroke-width='1.4' fill='none' stroke-linecap='round' stroke-linejoin='round'/></svg>");
		background-repeat: no-repeat;
		background-position: right 10px center;
	}

	/* === Memory list === */
	.memlist {
		display: flex;
		flex-direction: column;
		gap: 1px;
		background: var(--border);
		border: 1px solid var(--border);
		border-radius: 8px;
		overflow: hidden;
	}

	.mem {
		background: var(--bg-card);
		padding: 18px 20px;
		display: grid;
		grid-template-columns: 1fr auto;
		gap: 6px 16px;
		cursor: pointer;
		transition: background 120ms;
		animation: reveal-up 350ms var(--ease-arrive) both;
	}

	.mem:hover {
		background: var(--bg-hover);
	}

	.mem-content {
		font-size: 14px;
		line-height: 1.55;
		color: var(--text);
		grid-column: 1;
	}

	.mem-meta {
		grid-column: 1;
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
		font-family: var(--font-mono);
		font-size: 10.5px;
		color: var(--text-faint);
		margin-top: 2px;
	}

	.mem-meta .tone {
		font-weight: 500;
		text-transform: lowercase;
	}

	.mem-meta .origin {
		color: var(--text-muted);
	}

	.mem-meta .dot {
		color: var(--text-faint);
	}

	.mem-meta .tag {
		background: var(--bg-hover);
		color: var(--text-muted);
		padding: 1px 7px;
		border-radius: 3px;
		font-size: 10px;
	}

	.mem-meta .with {
		color: var(--accent);
	}

	.mem-side {
		grid-column: 2;
		grid-row: 1 / span 2;
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 6px;
		min-width: 90px;
	}

	.strength {
		width: 80px;
		height: 3px;
		background: var(--bg-hover);
		border-radius: 2px;
		overflow: hidden;
	}

	.strength i {
		display: block;
		height: 100%;
		background: var(--accent-dim);
		border-radius: 2px;
	}

	.strength.high i {
		background: var(--accent);
		box-shadow: 0 0 6px var(--accent-glow);
	}

	.strength.mid i {
		background: var(--sage);
	}

	.strength.low i {
		background: var(--text-faint);
	}

	.mem-side .num {
		font-family: var(--font-mono);
		font-size: 10px;
		color: var(--text-faint);
	}

	.mem-side .num .v {
		color: var(--text-muted);
	}

	/* === Footer === */
	.footer {
		margin-top: 24px;
		text-align: center;
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--text-faint);
		animation: reveal-up 350ms var(--ease-arrive) both;
		animation-delay: 560ms;
	}

	.footer button {
		background: none;
		border: 1px solid var(--border);
		color: var(--accent);
		padding: 8px 18px;
		border-radius: 6px;
		font-family: var(--font-mono);
		font-size: 11px;
		cursor: pointer;
		transition: all 120ms;
	}

	.footer button:hover {
		border-color: var(--accent);
		background: var(--accent-subtle);
	}

	.footer button:disabled {
		opacity: 0.5;
		cursor: wait;
	}

	.footer .count {
		margin-top: 10px;
	}

	/* === Empty / loading state === */
	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 16px;
		padding: 64px 0;
		color: var(--text-faint);
	}

	.empty-state p {
		font-size: 13px;
		margin: 0;
		color: var(--text-muted);
	}

	.diamond {
		display: inline-block;
		width: 12px;
		height: 12px;
		transform: rotate(45deg);
		border-radius: 1px;
		background: var(--text-faint);
	}

	.diamond--breathing {
		background: var(--accent);
		animation: breathe 3s ease-in-out infinite;
	}

	/* === Responsive === */
	@media (max-width: 680px) {
		.dash {
			grid-template-columns: 1fr;
		}

		.page {
			padding: 32px 20px 64px;
		}

		.mem {
			grid-template-columns: 1fr;
		}

		.mem-side {
			grid-column: 1;
			grid-row: auto;
			flex-direction: row;
			align-items: center;
		}
	}
</style>
