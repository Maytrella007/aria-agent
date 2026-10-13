import { goto } from '$app/navigation';

const SESSION_EXPIRED_MESSAGE = 'session expired';

export function isSessionExpiredError(error: unknown): boolean {
	return error instanceof Error && error.message === SESSION_EXPIRED_MESSAGE;
}

export async function authedFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
	const response = await fetch(input, init);

	if (response.status === 401) {
		void goto('/login?reason=expired', { replaceState: true });
		throw new Error(SESSION_EXPIRED_MESSAGE);
	}

	return response;
}
