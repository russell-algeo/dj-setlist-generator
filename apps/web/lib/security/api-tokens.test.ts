import { describe, expect, it } from "vitest";

import { hashApiToken, issueApiToken, verifyApiToken } from "./api-tokens";

describe("hashApiToken", () => {
  it("returns a string prefixed with scrypt:", () => {
    const hash = hashApiToken("sl_sometoken");
    expect(hash.startsWith("scrypt:")).toBe(true);
  });

  it("produces different hashes for the same token (random salt)", () => {
    const h1 = hashApiToken("sl_sometoken");
    const h2 = hashApiToken("sl_sometoken");
    expect(h1).not.toBe(h2);
  });

  it("hash has three colon-separated segments: scrypt, salt, hash", () => {
    const hash = hashApiToken("sl_sometoken");
    const parts = hash.split(":");
    expect(parts).toHaveLength(3);
    expect(parts[0]).toBe("scrypt");
    expect(parts[1].length).toBeGreaterThan(0); // salt hex
    expect(parts[2].length).toBeGreaterThan(0); // hash hex
  });
});

describe("verifyApiToken", () => {
  it("returns true for a token that matches its stored hash", () => {
    const token = "sl_correcttoken";
    const stored = hashApiToken(token);
    expect(verifyApiToken(token, stored)).toBe(true);
  });

  it("returns false for a wrong token", () => {
    const stored = hashApiToken("sl_correcttoken");
    expect(verifyApiToken("sl_wrongtoken", stored)).toBe(false);
  });

  it("returns false for a legacy SHA-256 hash (no scrypt: prefix)", () => {
    const legacyHash = "a".repeat(64); // 64-char hex, no prefix
    expect(verifyApiToken("sl_anytoken", legacyHash)).toBe(false);
  });

  it("returns false for an empty stored hash", () => {
    expect(verifyApiToken("sl_anytoken", "")).toBe(false);
  });
});

describe("issueApiToken", () => {
  it("returns a plainTextToken, tokenPrefix, and tokenHash", () => {
    const result = issueApiToken();
    expect(result.plainTextToken).toMatch(/^sl_/);
    expect(result.tokenPrefix).toBe(result.plainTextToken.slice(0, 12));
    expect(result.tokenHash.startsWith("scrypt:")).toBe(true);
  });

  it("tokenHash verifies against plainTextToken", () => {
    const { plainTextToken, tokenHash } = issueApiToken();
    expect(verifyApiToken(plainTextToken, tokenHash)).toBe(true);
  });
});
