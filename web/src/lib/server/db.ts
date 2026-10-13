import Database from 'better-sqlite3';
import path from 'node:path';

const DB_PATH = path.resolve(
	process.env.ARIA_AUTH_DB || path.join(process.cwd(), '..', 'data', 'auth', 'auth.db')
);

const db = Database(DB_PATH);

// WAL mode for better concurrent performance
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

// Create tables if they don't exist
db.exec(`
	CREATE TABLE IF NOT EXISTS allowed_emails (
		email TEXT PRIMARY KEY,
		created_at TEXT DEFAULT (datetime('now'))
	);

	CREATE TABLE IF NOT EXISTS auth_codes (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		email TEXT NOT NULL,
		code TEXT NOT NULL,
		attempts INTEGER DEFAULT 0,
		used INTEGER DEFAULT 0,
		created_at TEXT DEFAULT (datetime('now')),
		expires_at TEXT NOT NULL
	);

	CREATE TABLE IF NOT EXISTS auth_sessions (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		email TEXT NOT NULL,
		token TEXT NOT NULL UNIQUE,
		created_at TEXT DEFAULT (datetime('now')),
		expires_at TEXT NOT NULL
	);

	CREATE INDEX IF NOT EXISTS idx_auth_codes_email ON auth_codes(email);
	CREATE INDEX IF NOT EXISTS idx_auth_sessions_token ON auth_sessions(token);
`);

// Seed the allowed emails from env if the table is empty
const count = db.prepare('SELECT COUNT(*) as c FROM allowed_emails').get() as { c: number };
if (count.c === 0) {
	const emails = (process.env.ARIA_ALLOWED_EMAILS || '').split(',').map(e => e.trim()).filter(Boolean);
	const insert = db.prepare('INSERT OR IGNORE INTO allowed_emails (email) VALUES (?)');
	for (const email of emails) {
		insert.run(email.toLowerCase());
	}
	if (emails.length > 0) {
		console.log(`[auth] seeded ${emails.length} allowed email(s) from ARIA_ALLOWED_EMAILS`);
	}
}

export default db;
