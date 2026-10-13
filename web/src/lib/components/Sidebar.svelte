<script lang="ts">
	import { page } from '$app/state';

	type PulseData = {
		memory_count?: number | null;
		mirror_pending?: number;
		channels_active?: number;
		cycle_status?: string;
		version?: string;
		[key: string]: any;
	};

	let { pulse = {} as PulseData } = $props();

	const nav: Array<{ path: string; icon: string; label: string; countKey?: string }> = [
		{ path: '/', icon: '◈', label: 'ARIA' },
		{ path: '/memories', icon: '◎', label: 'Memories', countKey: 'memory_count' },
		{ path: '/mirror', icon: '◇', label: 'Mirror', countKey: 'mirror_pending' },
		{ path: '/channels', icon: '⊞', label: 'Channels', countKey: 'channels_active' },
		{ path: '/credentials', icon: '⊙', label: 'Credentials' },
	];

	function isActive(path: string): boolean {
		if (path === '/') return page.url.pathname === '/';
		return page.url.pathname.startsWith(path);
	}
</script>

<aside class="sidebar">
	<div class="brand">
		<span class="logo-mark"></span>
		<span class="brand-text">{pulse.version || 'v0.7.0'}</span>
	</div>

	<nav>
		{#each nav as item}
			<a
				href={item.path}
				class="nav-item"
				class:active={isActive(item.path)}
				aria-current={isActive(item.path) ? 'page' : undefined}
			>
				<span class="nav-icon" aria-hidden="true">{item.icon}</span>
				<span class="nav-label">{item.label}</span>
				{#if item.countKey && pulse[item.countKey as keyof PulseData]}
					<span class="nav-count">{pulse[item.countKey as keyof PulseData]}</span>
				{/if}
			</a>
		{/each}
	</nav>

	<div class="pulse-section">
		<div class="pulse-row">
			<span class="pulse-label">Cycle</span>
			<span class="pulse-value">{pulse.cycle_status || 'idle'}</span>
		</div>
		<div class="pulse-row">
			<span class="pulse-label">Memories</span>
			<span class="pulse-value accent">{pulse.memory_count ?? '—'}</span>
		</div>
		<div class="pulse-row">
			<span class="pulse-label">Pending</span>
			<span class="pulse-value accent">{pulse.mirror_pending ?? 0}</span>
		</div>
	</div>

	<div class="footer">
		<span class="diamond" aria-hidden="true"></span>
		<span class="version">{pulse.version || 'v0.7.0'}</span>
	</div>
</aside>

<style>
	.sidebar {
		width: 240px;
		background: var(--bg-surface);
		border-right: 1px solid var(--border);
		display: flex;
		flex-direction: column;
		flex-shrink: 0;
		height: 100vh;
		position: sticky;
		top: 0;
	}

	.brand {
		height: 56px;
		padding: 0 16px;
		display: flex;
		align-items: center;
		gap: 10px;
		border-bottom: 1px solid var(--border);
	}

	.logo-mark {
		position: relative;
		display: inline-block;
		width: 14px; height: 14px;
		border: 1.5px solid var(--accent);
		transform: rotate(45deg);
		border-radius: 1px;
	}
	.logo-mark::after {
		content: '';
		position: absolute;
		inset: 0; margin: auto;
		width: 3px; height: 3px;
		background: var(--accent);
		border-radius: 50%;
		box-shadow: 0 0 6px var(--accent-glow);
	}

	.brand-text {
		font-family: var(--font-mono);
		font-size: 10px;
		letter-spacing: 0.22em;
		text-transform: uppercase;
		color: var(--text-faint);
	}

	nav { padding: 12px 0 8px; }

	.nav-item {
		position: relative;
		height: 38px;
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 0 12px;
		margin: 1px 8px;
		border-radius: 8px;
		color: var(--text-muted);
		font-size: 13px;
		font-weight: 500;
		letter-spacing: -0.005em;
		text-decoration: none;
		transition: all 200ms var(--ease-micro);
	}
	.nav-item:hover { background: var(--bg-hover); color: var(--text); }
	.nav-icon {
		color: var(--text-faint);
		width: 18px;
		text-align: center;
		font-size: 14px;
		transition: color 200ms;
	}
	.nav-item:hover .nav-icon { color: var(--text-muted); }
	.nav-item.active {
		color: var(--text-strong);
		background: var(--accent-subtle);
	}
	.nav-item.active .nav-icon { color: var(--accent); }
	.nav-item.active::after {
		content: '';
		position: absolute;
		bottom: 4px; left: 14px; right: 14px;
		height: 2px;
		background: var(--accent);
		border-radius: 1px;
		opacity: .7;
		box-shadow: 0 1px 6px var(--accent-glow);
	}
	.nav-count {
		margin-left: auto;
		font-family: var(--font-mono);
		font-size: 11px;
		font-weight: 500;
		color: var(--accent);
		letter-spacing: 0.02em;
	}

	.pulse-section {
		margin: auto 12px 0;
		border-top: 1px solid var(--border);
		padding: 14px 0 6px;
	}
	.pulse-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		height: 24px;
		font-size: 11.5px;
	}
	.pulse-label {
		color: var(--text-faint);
		letter-spacing: 0.04em;
		font-weight: 500;
	}
	.pulse-value {
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--text-muted);
	}
	.pulse-value.accent { color: var(--accent); }

	.footer {
		height: 48px;
		margin-top: 8px;
		border-top: 1px solid var(--border);
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
	}
	.diamond {
		display: inline-block;
		width: 8px; height: 8px;
		transform: rotate(45deg);
		border-radius: 1px;
		background: var(--accent);
		animation: breathe 3s ease-in-out infinite;
	}
	.version {
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--text-faint);
	}

	@media (max-width: 768px) {
		.sidebar { display: none; }
	}
</style>
