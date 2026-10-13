import type { Handle } from '@sveltejs/kit';
import { SESSION_COOKIE_NAME, getSessionUser, cleanupExpired } from '$lib/server/auth';
import { redirect } from '@sveltejs/kit';

// Cleanup expired tokens/sessions every ~100 requests
let requestCount = 0;

export const handle: Handle = async ({ event, resolve }) => {
	requestCount++;
	if (requestCount % 100 === 0) {
		try {
			cleanupExpired();
		} catch {
			// non-critical
		}
	}

	// Public routes that don't require auth
	const publicPaths = ['/login', '/api/auth/'];
	const isPublic = publicPaths.some((p) => event.url.pathname.startsWith(p));

	if (!isPublic) {
		const token = event.cookies.get(SESSION_COOKIE_NAME);
		const user = token ? getSessionUser(token) : null;

		if (!user) {
			// API routes get 401, page routes get redirected
			if (event.url.pathname.startsWith('/api/')) {
				return new Response(JSON.stringify({ error: 'Unauthorized' }), {
					status: 401,
					headers: { 'Content-Type': 'application/json' }
				});
			}
			throw redirect(303, '/login');
		}

		// Attach user to event.locals for downstream use
		event.locals.user = user;
	}

	return resolve(event);
};
