import { writable } from 'svelte/store';

export type PulseData = {
	status: string;
	llm_available: boolean;
	memory_count: number | null;
	cycle_status: string;
	last_cycle_run: string | null;
	mirror_sync: string;
	mirror_pending: number;
	channels_active: number;
	version: string;
};

export const pulse = writable<PulseData>({
	status: 'loading',
	llm_available: false,
	memory_count: null,
	cycle_status: 'idle',
	last_cycle_run: null,
	mirror_sync: 'unknown',
	mirror_pending: 0,
	channels_active: 0,
	version: 'v0.7.0',
});

let interval: ReturnType<typeof setInterval> | null = null;

export async function fetchPulse() {
	try {
		const r = await fetch('/api/proxy/status/full');
		if (r.ok) {
			const data = await r.json();
			pulse.set(data);
		}
	} catch {
		// silent — sidebar shows stale data
	}
}

export function startPulsePolling(intervalMs = 30000) {
	fetchPulse();
	if (interval) clearInterval(interval);
	interval = setInterval(fetchPulse, intervalMs);
}

export function stopPulsePolling() {
	if (interval) {
		clearInterval(interval);
		interval = null;
	}
}
