import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";

import { env } from "@/lib/env";

const ALGORITHM = "aes-256-gcm";

const decodeKeyMaterial = (value: string) => {
  try {
    const base64 = Buffer.from(value, "base64");
    if (base64.length === 32) {
      return base64;
    }
  } catch {}

  try {
    const hex = Buffer.from(value, "hex");
    if (hex.length === 32) {
      return hex;
    }
  } catch {}

  if (Buffer.byteLength(value, "utf8") === 32) {
    return Buffer.from(value, "utf8");
  }

  return createHash("sha256").update(value, "utf8").digest();
};

const getKey = () => {
  if (!env.tokenEncryptionKey) {
    throw new Error("TOKEN_ENCRYPTION_KEY is required for encrypted Spotify tokens");
  }

  return decodeKeyMaterial(env.tokenEncryptionKey);
};

export const encryptSecret = (plainText: string) => {
  const iv = randomBytes(12);
  const cipher = createCipheriv(ALGORITHM, getKey(), iv);
  const encrypted = Buffer.concat([cipher.update(plainText, "utf8"), cipher.final()]);
  const authTag = cipher.getAuthTag();

  return Buffer.concat([iv, authTag, encrypted]).toString("base64url");
};

export const decryptSecret = (cipherText: string) => {
  const payload = Buffer.from(cipherText, "base64url");
  const iv = payload.subarray(0, 12);
  const authTag = payload.subarray(12, 28);
  const encrypted = payload.subarray(28);
  const decipher = createDecipheriv(ALGORITHM, getKey(), iv);

  decipher.setAuthTag(authTag);

  return Buffer.concat([decipher.update(encrypted), decipher.final()]).toString("utf8");
};
