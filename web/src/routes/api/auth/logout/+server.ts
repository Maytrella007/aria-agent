import { json } from '@sveltejs/kit';
import {
	SESSION_COOKIE_NAME,
	clearSessionCookie,
	invalidateSession
} from '$lib/server/auth';

export const POST = async ({ cookies }) => {
	const sessionToken = cookies.get(SESSION_COOKIE_NAME);

	if (sessionToken) {
		try {
			invalidateSession(sessionToken);
		} catch (error) {
			console.error('Logout failed:', error);
		}
	}

	clearSessionCookie(cookies);
	return json({ success: true });
};
