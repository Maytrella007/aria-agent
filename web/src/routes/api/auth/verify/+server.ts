import { json } from '@sveltejs/kit';
import {
	MAX_AUTH_CODE_ATTEMPTS,
	claimAuthCodeAttempt,
	createAuthSession,
	isAllowedEmail,
	markAuthCodeUsed,
	normalizeEmail,
	setSessionCookie,
	verifyCodeConstantTime
} from '$lib/server/auth';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const CODE_RE = /^\d{6}$/;

export const POST = async ({ request, cookies }) => {
	try {
		const body = await request.json();
		const email = normalizeEmail(typeof body?.email === 'string' ? body.email : '');
		const code = typeof body?.code === 'string' ? body.code.replace(/\D/g, '').slice(0, 6) : '';

		if (!EMAIL_RE.test(email) || !CODE_RE.test(code)) {
			return json({ valid: false });
		}

		// Atomic: fetch + increment attempts
		const claimed = claimAuthCodeAttempt(email);
		if (!claimed) {
			return json({ valid: false, locked: true });
		}

		if (claimed.attempts >= MAX_AUTH_CODE_ATTEMPTS) {
			markAuthCodeUsed(claimed.id);
			return json({ valid: false, locked: true });
		}

		// Constant-time comparison (prevents timing attacks)
		if (!verifyCodeConstantTime(code, claimed.code)) {
			return json({ valid: false });
		}

		markAuthCodeUsed(claimed.id);

		if (!isAllowedEmail(email)) {
			return json({ valid: false });
		}

		const token = createAuthSession(email);
		setSessionCookie(cookies, token);

		return json({ valid: true });
	} catch (error) {
		console.error('Verify code failed:', error);
		return json({ error: 'Failed to verify code' }, { status: 500 });
	}
};
