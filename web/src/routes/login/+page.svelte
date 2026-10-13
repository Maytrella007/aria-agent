<svelte:head>
	<title>Sign In — ARIA</title>
	<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet" />
</svelte:head>

<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onDestroy, tick } from 'svelte';

	type LoginView = 'email' | 'code' | 'denied';

	const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
	const DIGIT_RE = /^\d$/;
	const OTP_LENGTH = 6;

	let view = $state<LoginView>('email');
	let email = $state('');
	let submittedEmail = $state('');
	let rejectedEmail = $state('');
	let codeDigits = $state(Array.from({ length: OTP_LENGTH }, () => ''));
	let emailError = $state('');
	let codeError = $state('');
	let codeFeedback = $state('');
	let sendingCode = $state(false);
	let verifyingCode = $state(false);
	let resendingCode = $state(false);
	let verified = $state(false);
	let resendRemaining = $state(0);
	let resendInterval: ReturnType<typeof setInterval> | null = null;

	const sessionExpired = $derived(view === 'email' && page.url.searchParams.get('reason') === 'expired');
	const codeValue = $derived(codeDigits.join(''));
	const resendLabel = $derived(
		resendRemaining > 0 ? `resend code (${resendRemaining}s)` : 'resend code'
	);

	onDestroy(() => stopResendTimer());

	function stopResendTimer() {
		if (resendInterval) { clearInterval(resendInterval); resendInterval = null; }
	}

	function startResendCooldown(seconds: number) {
		stopResendTimer();
		resendRemaining = Math.max(0, Math.ceil(seconds));
		if (resendRemaining === 0) return;
		resendInterval = setInterval(() => {
			resendRemaining = Math.max(0, resendRemaining - 1);
			if (resendRemaining === 0) stopResendTimer();
		}, 1000);
	}

	function clearCode() {
		for (let i = 0; i < OTP_LENGTH; i++) codeDigits[i] = '';
		codeError = '';
		verified = false;
	}

	function focusCodeInput(index: number) {
		const input = document.getElementById(`otp-${index}`) as HTMLInputElement | null;
		input?.focus();
		input?.select();
	}

	function clearReasonFlag() {
		if (page.url.searchParams.get('reason')) {
			window.history.replaceState(window.history.state, '', '/login');
		}
	}

	async function moveToCodeState(nextEmail: string, cooldownSeconds: number, message: string) {
		view = 'code';
		submittedEmail = nextEmail;
		email = nextEmail;
		rejectedEmail = '';
		clearCode();
		codeFeedback = message;
		startResendCooldown(cooldownSeconds);
		await tick();
		focusCodeInput(0);
	}

	async function submitEmail() {
		const normalized = email.trim().toLowerCase();
		email = normalized;
		emailError = '';
		codeFeedback = '';
		if (!EMAIL_RE.test(normalized)) { emailError = 'Enter a valid email address.'; return; }
		sendingCode = true;
		try {
			clearReasonFlag();
			const response = await fetch('/api/auth/send-code', {
				method: 'POST',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ email: normalized })
			});
			const body = await response.json().catch(() => null);
			if (!response.ok) { emailError = body?.error ?? 'Could not send access code.'; return; }
			if (body?.allowed === false) { view = 'denied'; rejectedEmail = normalized; submittedEmail = ''; return; }
			const message = body?.cooldown ? 'A code was already sent recently.' : 'Code sent!';
			await moveToCodeState(normalized, body?.cooldownSeconds ?? 60, message);
		} catch { emailError = 'Could not send access code.'; }
		finally { sendingCode = false; }
	}

	async function resendCode() {
		if (resendRemaining > 0 || resendingCode || !submittedEmail) return;
		resendingCode = true;
		codeError = '';
		codeFeedback = '';
		try {
			const response = await fetch('/api/auth/send-code', {
				method: 'POST',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ email: submittedEmail })
			});
			const body = await response.json().catch(() => null);
			if (!response.ok) { codeError = body?.error ?? 'Could not resend code.'; return; }
			if (body?.allowed === false) { view = 'denied'; rejectedEmail = submittedEmail; return; }
			clearCode();
			codeFeedback = 'Code sent!';
			startResendCooldown(body?.cooldownSeconds ?? 60);
			await tick();
			focusCodeInput(0);
		} catch { codeError = 'Could not resend code.'; }
		finally { resendingCode = false; }
	}

	async function verifyCode() {
		const code = codeDigits.join('');
		if (code.length !== OTP_LENGTH || verifyingCode || verified) return;
		verifyingCode = true;
		codeError = '';
		codeFeedback = '';
		try {
			const response = await fetch('/api/auth/verify', {
				method: 'POST',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ email: submittedEmail, code })
			});
			const body = await response.json().catch(() => null);
			if (!response.ok) { codeError = body?.error ?? 'Could not verify code.'; return; }
			if (!body?.valid) {
				codeError = body?.locked
					? 'Too many attempts. Request a new code.'
					: 'Invalid or expired code. Please try again.';
				return;
			}
			verified = true;
			stopResendTimer();
			await new Promise((r) => setTimeout(r, 400));
			await goto('/', { replaceState: true });
		} catch { codeError = 'Could not verify code.'; }
		finally { verifyingCode = false; }
	}

	function handleOtpInput(index: number, event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const digits = input.value.replace(/\D/g, '');
		if (!digits) { codeDigits[index] = ''; codeError = ''; return; }
		codeDigits[index] = digits.at(-1) ?? '';
		codeError = '';
		if (index < OTP_LENGTH - 1) focusCodeInput(index + 1);
		if (codeDigits.every((d) => d !== '')) void verifyCode();
	}

	function handleOtpKeydown(index: number, event: KeyboardEvent) {
		if (event.key === 'Backspace') {
			event.preventDefault();
			if (codeDigits[index]) { codeDigits[index] = ''; return; }
			if (index > 0) { codeDigits[index - 1] = ''; focusCodeInput(index - 1); }
			return;
		}
		if (event.key === 'ArrowLeft') { event.preventDefault(); if (index > 0) focusCodeInput(index - 1); return; }
		if (event.key === 'ArrowRight') { event.preventDefault(); if (index < OTP_LENGTH - 1) focusCodeInput(index + 1); return; }
		if (event.key === 'Tab') return;
		if (event.key.length === 1 && !DIGIT_RE.test(event.key)) event.preventDefault();
	}

	function handleOtpPaste(event: ClipboardEvent) {
		const pasted = event.clipboardData?.getData('text').replace(/\D/g, '').slice(0, OTP_LENGTH) ?? '';
		if (!pasted) return;
		event.preventDefault();
		clearCode();
		for (let i = 0; i < OTP_LENGTH; i++) codeDigits[i] = pasted[i] ?? '';
		if (pasted.length === OTP_LENGTH) { void verifyCode(); return; }
		focusCodeInput(Math.min(pasted.length, OTP_LENGTH - 1));
	}

	function backToEmail() {
		view = 'email'; codeError = ''; codeFeedback = ''; verified = false;
		clearCode(); stopResendTimer();
	}

	function tryDifferentEmail() {
		view = 'email'; email = ''; submittedEmail = ''; rejectedEmail = '';
		emailError = ''; codeFeedback = ''; clearCode(); stopResendTimer(); clearReasonFlag();
	}
</script>

<div class="login-shell">
	<div class="login-ambient"></div>

	<main class="auth-stage">
		{#if view === 'denied'}
			<header class="brand-block brand-outside">
				<span class="logo-mark"></span>
				<span class="brand-name">ARIA</span>
			</header>

			<section class="auth-card denied-card">
				<div class="shield-badge">◆</div>
				<div class="denied-copy">
					<h1>Access Denied</h1>
					<p>The email address <strong>{rejectedEmail}</strong> is not authorized.</p>
				</div>
				<button type="button" class="ghost-button" onclick={tryDifferentEmail}>
					Try a different email
				</button>
			</section>
		{:else}
			<section class="auth-card">
				<header class="brand-block">
					<span class="logo-mark"></span>
					<span class="brand-name">ARIA</span>
					<span class="brand-sub">personal ai assistant</span>
				</header>

				<div class="brand-divider"></div>

				{#if view === 'email'}
					<div class="content-block">
						{#if sessionExpired}
							<div class="message-banner message-warning" role="alert">
								<span>⏱</span>
								<span>Your session has expired. Please sign in again.</span>
							</div>
						{/if}

						<div class="copy-block">
							<h1>Sign In</h1>
							<p>Enter your email to receive a one-time access code</p>
						</div>

						<form class="stack" onsubmit={(e) => { e.preventDefault(); void submitEmail(); }}>
							<label class="sr-only" for="email">Email</label>
							<input
								id="email"
								bind:value={email}
								class="email-input"
								type="email"
								autocomplete="email"
								placeholder="you@example.com"
								disabled={sendingCode}
							/>

							{#if emailError}
								<div class="message-banner message-error" role="alert">
									<span>{emailError}</span>
								</div>
							{/if}

							<button type="submit" class="primary-button" disabled={sendingCode}>
								{#if sendingCode}
									sending...
								{:else}
									send access code
								{/if}
							</button>
						</form>
					</div>
				{:else}
					<div class="content-block">
						<button type="button" class="back-button" onclick={backToEmail}>
							← back
						</button>

						<div class="copy-block">
							<h1>Check your email</h1>
							<p>
								We sent a 6-digit code to
								<strong class="accent-email">{submittedEmail}</strong>
							</p>
						</div>

						<form class="stack" onsubmit={(e) => { e.preventDefault(); void verifyCode(); }}>
							<div class="otp-grid">
								{#each codeDigits as digit, index (index)}
									<input
										id={`otp-${index}`}
										class="otp-input {codeError ? 'otp-error' : ''} {verified ? 'otp-success' : ''}"
										type="text"
										inputmode="numeric"
										pattern="[0-9]"
										maxlength="1"
										autocomplete={index === 0 ? 'one-time-code' : 'off'}
										aria-label={`Digit ${index + 1} of ${OTP_LENGTH}`}
										value={digit}
										disabled={verifyingCode || verified}
										oninput={(e) => handleOtpInput(index, e)}
										onkeydown={(e) => handleOtpKeydown(index, e)}
										onpaste={handleOtpPaste}
									/>
								{/each}
							</div>

							{#if codeError}
								<div class="message-banner message-error" role="alert">{codeError}</div>
							{:else if codeFeedback}
								<div class="message-banner message-info" role="status">{codeFeedback}</div>
							{/if}

							<button
								type="submit"
								class="primary-button"
								disabled={codeValue.length !== OTP_LENGTH || verifyingCode || verified}
							>
								{#if verified}
									verified ✓
								{:else if verifyingCode}
									verifying...
								{:else}
									verify code
								{/if}
							</button>
						</form>

						<div class="resend-row">
							<span>Didn't receive it?</span>
							<button
								type="button"
								class="link-button"
								disabled={resendRemaining > 0 || resendingCode || verifyingCode}
								onclick={() => void resendCode()}
							>
								{resendingCode ? 'sending...' : resendLabel}
							</button>
						</div>
					</div>
				{/if}
			</section>
		{/if}
	</main>
</div>

<style>
	:global(body) {
		margin: 0;
		background: #111210;
	}

	/* ── Shell ── */
	.login-shell {
		position: relative;
		display: flex;
		min-height: 100vh;
		align-items: center;
		justify-content: center;
		padding: 3vh 4vw;
		color: #cdc8c0;
		overflow: hidden;
		font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
		-webkit-font-smoothing: antialiased;
	}

	.login-ambient {
		position: absolute;
		inset: 0;
		background-image:
			radial-gradient(circle at 20% 20%, rgba(212, 160, 74, 0.06), transparent 50%),
			radial-gradient(circle at 80% 80%, rgba(124, 154, 142, 0.04), transparent 50%);
		pointer-events: none;
	}

	/* ── Stage ── */
	.auth-stage {
		position: relative;
		z-index: 1;
		width: min(100%, 26rem);
	}

	/* ── Card ── */
	.auth-card {
		position: relative;
		border-radius: 14px;
		background: linear-gradient(168deg, rgba(30, 28, 26, 0.98), rgba(21, 20, 19, 1));
		box-shadow:
			0 2px 0 0 rgba(255, 255, 255, 0.02) inset,
			0 40px 80px -20px rgba(0, 0, 0, 0.5);
		padding: clamp(2rem, 5vw, 2.5rem);
		overflow: hidden;
		border: 1px solid #2a2725;
	}

	/* ── Brand ── */
	.brand-block {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.5rem;
	}

	.brand-outside {
		margin-bottom: 1.4rem;
	}

	.logo-mark {
		position: relative;
		display: inline-block;
		width: 20px;
		height: 20px;
		border: 2px solid #d4a04a;
		transform: rotate(45deg);
		border-radius: 2px;
	}
	.logo-mark::after {
		content: '';
		position: absolute;
		inset: 0;
		margin: auto;
		width: 4px;
		height: 4px;
		background: #d4a04a;
		border-radius: 50%;
		box-shadow: 0 0 8px rgba(212, 160, 74, 0.3);
	}

	.brand-name {
		font-family: 'JetBrains Mono', monospace;
		font-size: 0.7rem;
		font-weight: 500;
		letter-spacing: 0.28em;
		text-transform: uppercase;
		color: #9a948a;
	}

	.brand-sub {
		font-size: 0.7rem;
		letter-spacing: 0.08em;
		color: #8a857d;
		text-transform: lowercase;
	}

	.brand-divider {
		height: 1px;
		background: #2a2725;
		margin: 1.4rem 0;
	}

	/* ── Content ── */
	.content-block {
		display: flex;
		flex-direction: column;
		gap: 1.2rem;
	}

	.copy-block h1 {
		font-size: 1.4rem;
		font-weight: 600;
		color: #ede9e3;
		margin: 0 0 0.3rem;
		letter-spacing: -0.01em;
	}

	.copy-block p {
		margin: 0;
		font-size: 0.9rem;
		color: #8a857d;
		line-height: 1.5;
	}

	.accent-email {
		color: #d4a04a;
	}

	.stack {
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
	}

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}

	/* ── Email input ── */
	.email-input {
		width: 100%;
		padding: 0.8rem 1rem;
		border-radius: 8px;
		border: 1px solid #3d3935;
		background: #111210;
		font-family: 'JetBrains Mono', monospace;
		font-size: 0.9rem;
		color: #ede9e3;
		outline: none;
		transition: border-color 160ms ease, box-shadow 160ms ease;
		box-sizing: border-box;
	}

	.email-input::placeholder {
		color: #8a857d;
	}

	.email-input:focus {
		border-color: rgba(212, 160, 74, 0.5);
		box-shadow: 0 0 0 3px rgba(212, 160, 74, 0.08);
	}

	/* ── OTP grid ── */
	.otp-grid {
		display: grid;
		grid-template-columns: repeat(6, 1fr);
		gap: 0.5rem;
	}

	.otp-input {
		width: 100%;
		aspect-ratio: 1 / 1.15;
		border-radius: 8px;
		border: 1px solid #3d3935;
		background: #1a1918;
		text-align: center;
		font-family: 'JetBrains Mono', monospace;
		font-size: 1.4rem;
		font-weight: 700;
		color: #d4a04a;
		outline: none;
		transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
		box-sizing: border-box;
	}

	.otp-input:focus {
		border-color: rgba(212, 160, 74, 0.6);
		box-shadow: 0 0 0 3px rgba(212, 160, 74, 0.1);
		background: #242220;
	}

	.otp-error {
		border-color: rgba(199, 90, 90, 0.6);
		background: rgba(199, 90, 90, 0.05);
	}

	.otp-success {
		border-color: rgba(94, 184, 122, 0.6);
		background: rgba(94, 184, 122, 0.05);
	}

	/* ── Buttons ── */
	.primary-button,
	.ghost-button,
	.link-button,
	.back-button {
		border: 0;
		cursor: pointer;
		font-family: 'DM Sans', sans-serif;
	}

	.primary-button {
		display: inline-flex;
		width: 100%;
		align-items: center;
		justify-content: center;
		gap: 0.4rem;
		border-radius: 8px;
		padding: 0.8rem 1rem;
		background: linear-gradient(135deg, #d4a04a 0%, #b88a3a 100%);
		color: #111210;
		font-family: 'JetBrains Mono', monospace;
		font-size: 0.85rem;
		font-weight: 600;
		letter-spacing: 0.03em;
		text-transform: lowercase;
		box-shadow: 0 8px 24px -4px rgba(212, 160, 74, 0.25);
		transition: transform 140ms ease, filter 140ms ease, box-shadow 140ms ease;
	}

	.primary-button:hover:not(:disabled) {
		filter: brightness(1.08);
		transform: translateY(-1px);
		box-shadow: 0 12px 28px -4px rgba(212, 160, 74, 0.3);
	}

	.primary-button:active:not(:disabled) {
		transform: translateY(0);
	}

	.primary-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.ghost-button {
		padding: 0.7rem 1.2rem;
		border-radius: 8px;
		background: transparent;
		border: 1px solid #3d3935;
		color: #cdc8c0;
		font-size: 0.85rem;
		transition: all 140ms ease;
	}

	.ghost-button:hover {
		border-color: #d4a04a;
		color: #d4a04a;
		background: rgba(212, 160, 74, 0.06);
	}

	.back-button {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		background: none;
		color: #9a948a;
		font-size: 0.8rem;
		padding: 0;
		margin-bottom: 0.4rem;
		transition: color 140ms ease;
	}

	.back-button:hover {
		color: #d4a04a;
	}

	.link-button {
		background: none;
		color: #d4a04a;
		font-size: 0.82rem;
		text-decoration: none;
		padding: 0;
		transition: opacity 140ms ease;
	}

	.link-button:hover:not(:disabled) {
		text-decoration: underline;
	}

	.link-button:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	/* ── Messages ── */
	.message-banner {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.4rem;
		border-radius: 8px;
		padding: 0.65rem 0.8rem;
		font-size: 0.82rem;
		text-align: center;
	}

	.message-error {
		background: rgba(199, 90, 90, 0.08);
		border: 1px solid rgba(199, 90, 90, 0.25);
		color: #c75a5a;
	}

	.message-warning {
		background: rgba(212, 160, 74, 0.08);
		border: 1px solid rgba(212, 160, 74, 0.25);
		color: #d4a04a;
	}

	.message-info {
		background: rgba(124, 154, 142, 0.08);
		border: 1px solid rgba(124, 154, 142, 0.25);
		color: #7c9a8e;
	}

	/* ── Resend row ── */
	.resend-row {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.5rem;
		font-size: 0.8rem;
		color: #8a857d;
	}

	/* ── Denied ── */
	.denied-card {
		text-align: center;
	}

	.shield-badge {
		font-size: 2rem;
		color: #c75a5a;
		margin-bottom: 1rem;
	}

	.denied-copy h1 {
		font-size: 1.3rem;
		font-weight: 600;
		color: #ede9e3;
		margin: 0 0 0.5rem;
	}

	.denied-copy p {
		font-size: 0.88rem;
		color: #8a857d;
		margin: 0 0 1.4rem;
		line-height: 1.5;
	}
</style>
