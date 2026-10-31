#!/usr/bin/env python3
"""
Bearer token credentials for the 50 Cent LIS.

Each credential is a random token issued to one email address. Only a SHA-256
hash of the token is stored, so the token itself is shown once when created.
"""

import hashlib
import re
import secrets


EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class CredentialError(ValueError):
    pass


def ensure_schema(db):
    """Create the credentials table if it does not exist."""
    db.execute('''
    CREATE TABLE IF NOT EXISTS credentials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        token_hint TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_used_at TIMESTAMP,
        revoked_at TIMESTAMP
    )
    ''')
    db.commit()


def _hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def create(db, email):
    """Issue a new token for an email address. Returns the token, which is not stored."""
    email = email.strip().lower()
    if not EMAIL_PATTERN.match(email):
        raise CredentialError(f'"{email}" is not a valid email address')
    token = 'lis_' + secrets.token_urlsafe(32)
    db.execute('INSERT INTO credentials (email, token_hash, token_hint) VALUES (?, ?, ?)',
               (email, _hash(token), token[-4:]))
    db.commit()
    return token


def verify(db, token):
    """Return the email address of an active credential matching the token, or None."""
    if not token:
        return None
    token_hash = _hash(token)
    row = db.execute('SELECT id, email FROM credentials WHERE token_hash = ? AND revoked_at IS NULL',
                     (token_hash,)).fetchone()
    if not row:
        return None
    db.execute('UPDATE credentials SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?', (row['id'],))
    db.commit()
    return row['email']


def revoke(db, credential_id):
    db.execute('UPDATE credentials SET revoked_at = CURRENT_TIMESTAMP WHERE id = ? AND revoked_at IS NULL',
               (credential_id,))
    db.commit()


def list_all(db):
    return db.execute('SELECT * FROM credentials ORDER BY revoked_at IS NOT NULL, created_at DESC, id DESC').fetchall()
