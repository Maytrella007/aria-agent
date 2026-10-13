<script lang="ts">
	import '../app.css';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import AmbientNet from '$lib/components/AmbientNet.svelte';
	import { pulse, startPulsePolling, stopPulsePolling } from '$lib/stores/pulse';
	import { page } from '$app/state';
	import { onMount, onDestroy } from 'svelte';

	let { children } = $props();

	const isLogin = $derived(page.url.pathname === '/login');

	onMount(() => {
		if (!isLogin) startPulsePolling();
	});

	onDestroy(() => stopPulsePolling());
</script>

<svelte:head>
	<link rel="preconnect" href="https://fonts.googleapis.com" />
	<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="anonymous" />
	<link
		href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap"
		rel="stylesheet"
	/>
</svelte:head>

{#if isLogin}
	{@render children()}
{:else}
	<AmbientNet />
	<div class="shell">
		<Sidebar pulse={$pulse} />
		<main class="content">
			{@render children()}
		</main>
	</div>
{/if}

<style>
	.shell {
		display: flex;
		min-height: 100vh;
		position: relative;
		z-index: 1;
	}

	.content {
		flex: 1;
		min-width: 0;
		position: relative;
		display: flex;
		flex-direction: column;
	}
</style>
