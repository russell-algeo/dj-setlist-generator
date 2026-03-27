-- Revoke all active API tokens issued under the SHA-256 hashing scheme.
-- Tokens will need to be regenerated once the scrypt implementation ships.
--> statement-breakpoint
UPDATE authn.api_tokens
SET revoked_at = now(),
    updated_at = now()
WHERE revoked_at IS NULL;
