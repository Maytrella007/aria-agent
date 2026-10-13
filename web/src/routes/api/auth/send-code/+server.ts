import { json } from '@sveltejs/kit';
import {
	RESEND_COOLDOWN_SECONDS,
	createAuthCode,
	generateAuthCode,
	getSendCodeCooldown,
	invalidateActiveCodes,
	isAllowedEmail,
	normalizeEmail,
	sendOtpEmail
} from '$lib/server/auth';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export const POST = async ({ request }) => {
	try {
		const body = await request.json();
		const email = normalizeEmail(typeof body?.email === 'string' ? body.email : '');

		if (!EMAIL_RE.test(email)) {
			return json({ error: 'Invalid email' }, { status: 400 });
		}

		const cooldownSeconds = getSendCodeCooldown(email);
		if (cooldownSeconds) {
			return json({
				success: true,
				cooldown: true,
				cooldownSeconds
			});
		}

		const allowed = isAllowedEmail(email);
		if (!allowed) {
			// Never reveal whether the email is in the whitelist
			return json({ allowed: false });
		}

		invalidateActiveCodes(email);
		const code = generateAuthCode();
		createAuthCode(email, code);
		await sendOtpEmail(email, code);

		return json({
			success: true,
			cooldown: false,
			cooldownSeconds: RESEND_COOLDOWN_SECONDS
		});
	} catch (error) {
		console.error('Send code failed:', error);
		return json({ error: 'Failed to send access code' }, { status: 500 });
	}
};
