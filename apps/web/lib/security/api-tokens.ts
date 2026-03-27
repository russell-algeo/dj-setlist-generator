import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";

const TOKEN_PREFIX_LENGTH = 12;

// scrypt parameters — N=16384 (2^14), r=8, p=1, keylen=32 bytes
const SCRYPT_N = 16384;
const SCRYPT_R = 8;
const SCRYPT_P = 1;
const SCRYPT_KEYLEN = 32;

export const createPlainApiToken = () => `sl_${randomBytes(24).toString("base64url")}`;

export const getTokenPrefix = (token: string) => token.slice(0, TOKEN_PREFIX_LENGTH);

/**
 * Hash a token using scrypt with a fresh random salt.
 * Stored format: "scrypt:<salt_hex>:<hash_hex>"
 */
export const hashApiToken = (token: string): string => {
  const salt = randomBytes(16);
  const hash = scryptSync(token, salt, SCRYPT_KEYLEN, { N: SCRYPT_N, r: SCRYPT_R, p: SCRYPT_P });
  return `scrypt:${salt.toString("hex")}:${hash.toString("hex")}`;
};

/**
 * Verify a plain token against a stored scrypt hash.
 * Returns false for any non-scrypt stored value (e.g. legacy SHA-256).
 */
export const verifyApiToken = (token: string, storedHash: string): boolean => {
  if (!storedHash.startsWith("scrypt:")) {
    return false;
  }

  const parts = storedHash.split(":");
  if (parts.length !== 3) {
    return false;
  }

  const salt = Buffer.from(parts[1], "hex");
  const expected = Buffer.from(parts[2], "hex");

  if (salt.length === 0 || expected.length !== SCRYPT_KEYLEN) {
    return false;
  }

  const actual = scryptSync(token, salt, SCRYPT_KEYLEN, { N: SCRYPT_N, r: SCRYPT_R, p: SCRYPT_P });

  return timingSafeEqual(actual, expected);
};

export const issueApiToken = () => {
  const token = createPlainApiToken();

  return {
    plainTextToken: token,
    tokenPrefix: getTokenPrefix(token),
    tokenHash: hashApiToken(token),
  };
};
