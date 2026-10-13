/**
 * ARIA Auth — OTP-based email authentication via Resend.
 *
 * Adapted from an earlier internal dashboard's auth system. The only
 * structural difference is SQLite instead of Postgres: every query is
 * synchronous (better-sqlite3) and the date functions use SQLite syntax.
 */
import { env } from '$env/dynamic/private';
import type { Cookies } from '@sveltejs/kit';
import db from './db';
import crypto from 'node:crypto';

export const SESSION_COOKIE_NAME = 'aria_session';
export const SESSION_MAX_AGE = 30 * 24 * 60 * 60; // 30 days (the original used 7)
export const RESEND_COOLDOWN_SECONDS = 60;
export const MAX_AUTH_CODE_ATTEMPTS = 5;
export const AUTH_CODE_LENGTH = 6;

export type AuthUser = { email: string };

// ── Helpers ─────────────────────────────────────────────────────────

export function normalizeEmail(value: string): string {
	return value.trim().toLowerCase();
}

export function generateAuthCode(): string {
	return String(crypto.randomInt(100000, 1000000));
}

export function createSessionToken(): string {
	return crypto.randomBytes(32).toString('hex');
}

// ── Whitelist ───────────────────────────────────────────────────────

export function isAllowedEmail(email: string): boolean {
	const row = db
		.prepare('SELECT 1 FROM allowed_emails WHERE email = ?')
		.get(email) as { 1: number } | undefined;
	return Boolean(row);
}

// ── OTP codes ───────────────────────────────────────────────────────

export function getSendCodeCooldown(email: string): number | null {
	const row = db
		.prepare(
			`SELECT MAX(0, CAST(
				(julianday(created_at, '+60 seconds') - julianday('now')) * 86400
			AS INTEGER)) AS remaining_seconds
			FROM auth_codes
			WHERE email = ?
				AND datetime(expires_at) > datetime('now')
				AND datetime(created_at) > datetime('now', '-60 seconds')
			ORDER BY created_at DESC
			LIMIT 1`
		)
		.get(email) as { remaining_seconds: number } | undefined;

	const remaining = row?.remaining_seconds ?? null;
	return remaining && remaining > 0 ? remaining : null;
}

export function invalidateActiveCodes(email: string): void {
	db.prepare(
		`UPDATE auth_codes SET used = 1 WHERE email = ? AND used = 0`
	).run(email);
}

export function createAuthCode(email: string, code: string): void {
	db.prepare(
		`INSERT INTO auth_codes (email, code, expires_at)
		 VALUES (?, ?, datetime('now', '+10 minutes'))`
	).run(email, code);
}

export function markAuthCodeUsed(id: number): void {
	db.prepare('UPDATE auth_codes SET used = 1 WHERE id = ?').run(id);
}

/**
 * Atomically fetch the latest active code AND increment attempts.
 * Returns the code row or null if no active code / already locked.
 */
export function claimAuthCodeAttempt(
	email: string
): { id: number; code: string; attempts: number } | null {
	// SQLite doesn't have UPDATE...RETURNING with subquery as cleanly,
	// so we do SELECT + UPDATE in a transaction.
	const txn = db.transaction(() => {
		const row = db
			.prepare(
				`SELECT id, code, attempts FROM auth_codes
				 WHERE email = ?
					AND datetime(expires_at) > datetime('now')
					AND used = 0
					AND attempts < ?
				 ORDER BY created_at DESC
				 LIMIT 1`
			)
			.get(email, MAX_AUTH_CODE_ATTEMPTS) as
			| { id: number; code: string; attempts: number }
			| undefined;

		if (!row) return null;

		db.prepare('UPDATE auth_codes SET attempts = attempts + 1 WHERE id = ?').run(
			row.id
		);
		return { id: row.id, code: row.code, attempts: row.attempts + 1 };
	});
	return txn();
}

/**
 * Constant-time comparison of OTP codes (prevents timing attacks).
 */
export function verifyCodeConstantTime(submitted: string, stored: string): boolean {
	const a = Buffer.from(submitted.padEnd(AUTH_CODE_LENGTH, '0'));
	const b = Buffer.from(stored.padEnd(AUTH_CODE_LENGTH, '0'));
	return a.length === b.length && crypto.timingSafeEqual(a, b);
}

// ── Sessions ────────────────────────────────────────────────────────

export function getSessionUser(token: string): AuthUser | null {
	const row = db
		.prepare(
			`SELECT s.email FROM auth_sessions s
			 JOIN allowed_emails a ON a.email = s.email
			 WHERE s.token = ?
				AND datetime(s.expires_at) > datetime('now')
			 LIMIT 1`
		)
		.get(token) as { email: string } | undefined;
	return row ? { email: row.email } : null;
}

export function createAuthSession(email: string): string {
	const token = createSessionToken();
	db.prepare(
		`INSERT INTO auth_sessions (email, token, expires_at)
		 VALUES (?, ?, datetime('now', '+30 days'))`
	).run(email, token);
	return token;
}

export function invalidateSession(token: string): void {
	db.prepare('DELETE FROM auth_sessions WHERE token = ?').run(token);
}

export function setSessionCookie(cookies: Cookies, token: string): void {
	cookies.set(SESSION_COOKIE_NAME, token, {
		httpOnly: true,
		sameSite: 'lax',
		path: '/',
		secure: env.NODE_ENV === 'production',
		maxAge: SESSION_MAX_AGE
	});
}

export function clearSessionCookie(cookies: Cookies): void {
	cookies.delete(SESSION_COOKIE_NAME, {
		httpOnly: true,
		sameSite: 'lax',
		path: '/',
		secure: env.NODE_ENV === 'production'
	});
}

// ── Resend email ────────────────────────────────────────────────────

export async function sendOtpEmail(email: string, code: string): Promise<void> {
	const apiKey = env.RESEND_API_KEY;
	if (!apiKey) {
		throw new Error('RESEND_API_KEY is not configured');
	}

	const from = env.RESEND_FROM_EMAIL || 'ARIA <onboarding@resend.dev>';

	const response = await fetch('https://api.resend.com/emails', {
		method: 'POST',
		headers: {
			Authorization: `Bearer ${apiKey}`,
			'Content-Type': 'application/json'
		},
		body: JSON.stringify({
			from,
			to: [email],
			subject: 'Your ARIA access code',
			html: `
				<div style="font-family:'DM Sans',Arial,sans-serif;background:#111210;color:#cdc8c0;padding:32px;">
					<div style="max-width:480px;margin:0 auto;background:#1e1c1a;border:1px solid #2a2725;border-radius:18px;padding:32px;">
						<div style="font-size:12px;letter-spacing:0.22em;text-transform:uppercase;color:#9a948a;margin-bottom:12px;">ARIA</div>
						<h1 style="font-size:28px;line-height:1.15;margin:0 0 12px;color:#ede9e3;">Your access code</h1>
						<p style="margin:0 0 24px;color:#cdc8c0;">Use this one-time code to sign in. It expires in 10 minutes.</p>
						<div style="font-family:'JetBrains Mono',monospace;font-size:36px;font-weight:700;letter-spacing:0.35em;color:#d4a04a;background:#111210;border:1px solid #2a2725;border-radius:14px;padding:20px 24px;text-align:center;">
							${code}
						</div>
						<p style="margin:24px 0 0;color:#9a948a;font-size:13px;">If you did not request access, you can ignore this email.</p>
					</div>
				</div>
			`,
			text: `Your ARIA access code is ${code}. It expires in 10 minutes.`
		})
	});

	if (!response.ok) {
		const body = await response.text();
		throw new Error(`Resend request failed (${response.status}): ${body}`);
	}
}

// ── Cleanup (call periodically) ─────────────────────────────────────

export function cleanupExpired(): void {
	db.prepare(`DELETE FROM auth_codes WHERE datetime(expires_at) < datetime('now')`).run();
	db.prepare(`DELETE FROM auth_sessions WHERE datetime(expires_at) < datetime('now')`).run();
}
