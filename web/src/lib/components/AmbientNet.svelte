<script lang="ts">
	import { onMount, onDestroy } from 'svelte';

	let el: HTMLDivElement;
	let effect: any;

	onMount(async () => {
		if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

		const THREE = await import('three');
		const VANTA = await import('vanta/dist/vanta.net.min');

		effect = VANTA.default({
			el,
			THREE,
			color: 0xd4a04a,
			backgroundColor: 0x111210,
			points: 9.0,
			maxDistance: 22.0,
			spacing: 18.0,
			showDots: true,
			mouseControls: true,
			touchControls: false,
			gyroControls: false,
			minHeight: 200.0,
			minWidth: 200.0,
			scale: 1.0,
			scaleMobile: 1.0,
		});
	});

	onDestroy(() => {
		if (effect) effect.destroy();
	});
</script>

<div bind:this={el} class="vanta-bg"></div>

<style>
	.vanta-bg {
		position: fixed;
		inset: 0;
		z-index: 0;
		pointer-events: none;
		opacity: 0.85;
	}
</style>
