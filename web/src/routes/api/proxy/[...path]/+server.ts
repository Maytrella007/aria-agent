/**
 * BFF Proxy — forwards authenticated requests from the browser to FastAPI.
 *
 * Browser → SvelteKit (cookie auth) → FastAPI (X-Internal-Auth header)
 *
 * This catch-all route handles GET, POST, PUT, PATCH, DELETE for any
 * path under /api/proxy/*. The frontend calls /api/proxy/mirror/pending
 * and this route forwards it to http://localhost:8000/api/mirror/pending
 * with the internal auth header attached.
 */
import { env } from '$env/dynamic/private';
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

const FASTAPI_BASE = env.ARIA_FASTAPI_URL || 'http://localhost:8000';
const INTERNAL_SECRET = env.ARIA_INTERNAL_SECRET || '';

async function proxyRequest(event: Parameters<RequestHandler>[0]) {
	const { params, request, url } = event;
	const targetPath = params.path;
	const targetUrl = `${FASTAPI_BASE}/api/${targetPath}${url.search}`;

	const headers: Record<string, string> = {
		'Content-Type': 'application/json',
	};

	if (INTERNAL_SECRET) {
		headers['X-Internal-Auth'] = INTERNAL_SECRET;
	}

	const init: RequestInit = {
		method: request.method,
		headers,
	};

	// Forward body for POST/PUT/PATCH/DELETE
	if (request.method !== 'GET' && request.method !== 'HEAD') {
		try {
			const body = await request.text();
			if (body) init.body = body;
		} catch {
			// no body — that's fine for some POSTs
		}
	}

	try {
		const upstream = await fetch(targetUrl, init);

		// For SSE streams, pipe the response directly
		if (upstream.headers.get('content-type')?.includes('text/event-stream')) {
			return new Response(upstream.body, {
				status: upstream.status,
				headers: {
					'Content-Type': 'text/event-stream',
					'Cache-Control': 'no-cache',
					'Connection': 'keep-alive',
				},
			});
		}

		const data = await upstream.text();
		return new Response(data, {
			status: upstream.status,
			headers: { 'Content-Type': 'application/json' },
		});
	} catch (err) {
		return json(
			{ error: 'proxy_error', detail: 'FastAPI is not reachable', status_code: 502 },
			{ status: 502 }
		);
	}
}

export const GET: RequestHandler = proxyRequest;
export const POST: RequestHandler = proxyRequest;
export const PUT: RequestHandler = proxyRequest;
export const PATCH: RequestHandler = proxyRequest;
export const DELETE: RequestHandler = proxyRequest;
