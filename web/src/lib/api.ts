/**
 * ARIA API client — all frontend API calls go through here.
 *
 * Calls /api/proxy/* which SvelteKit forwards to FastAPI with the
 * internal auth header. The browser never talks to FastAPI directly.
 */
import { goto } from '$app/navigation';

const BASE = '/api/proxy';

export class ApiError extends Error {
	constructor(
		public code: string,
		public detail: string | null,
		public statusCode: number
	) {
		super(detail || code);
	}
}

export async function api<T = any>(
	path: string,
	options: {
		method?: string;
		body?: any;
		params?: Record<string, string | number | undefined>;
	} = {}
): Promise<T> {
	const { method = 'GET', body, params } = options;

	let url = `${BASE}/${path.replace(/^\//, '')}`;

	if (params) {
		const search = new URLSearchParams();
		for (const [k, v] of Object.entries(params)) {
			if (v !== undefined && v !== null) search.set(k, String(v));
		}
		const qs = search.toString();
		if (qs) url += `?${qs}`;
	}

	const init: RequestInit = { method };
	if (body) {
		init.headers = { 'Content-Type': 'application/json' };
		init.body = JSON.stringify(body);
	}

	const res = await fetch(url, init);

	if (res.status === 401) {
		void goto('/login?reason=expired', { replaceState: true });
		throw new ApiError('unauthorized', 'Session expired', 401);
	}

	if (!res.ok) {
		let errBody: any;
		try {
			errBody = await res.json();
		} catch {
			errBody = { error: 'unknown', detail: res.statusText };
		}
		// Handle both api_error() format and raw HTTPException
		const code = errBody?.error || errBody?.detail?.error || 'unknown';
		const detail = typeof errBody?.detail === 'string'
			? errBody.detail
			: errBody?.detail?.detail || res.statusText;
		throw new ApiError(code, detail, res.status);
	}

	return res.json();
}

/**
 * Subscribe to an SSE stream from FastAPI (via proxy).
 * Returns an abort function.
 */
export function subscribe(
	path: string,
	onEvent: (data: any) => void,
	onError?: (err: Error) => void
): () => void {
	const controller = new AbortController();
	const url = `${BASE}/${path.replace(/^\//, '')}`;

	(async () => {
		try {
			const res = await fetch(url, { signal: controller.signal });
			if (!res.ok || !res.body) return;

			const reader = res.body.getReader();
			const decoder = new TextDecoder();
			let buffer = '';

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				buffer += decoder.decode(value, { stream: true });
				const lines = buffer.split('\n');
				buffer = lines.pop() || '';

				for (const line of lines) {
					if (line.startsWith('data: ')) {
						try {
							onEvent(JSON.parse(line.slice(6)));
						} catch { /* malformed JSON, skip */ }
					}
				}
			}
		} catch (err) {
			if (!controller.signal.aborted) {
				onError?.(err as Error);
			}
		}
	})();

	return () => controller.abort();
}
