import { createHash, randomBytes } from "node:crypto";

const TOKEN_PREFIX_LENGTH = 12;

export const createPlainApiToken = () => `sl_${randomBytes(24).toString("base64url")}`;

export const getTokenPrefix = (token: string) => token.slice(0, TOKEN_PREFIX_LENGTH);

export const hashApiToken = (token: string) =>
  createHash("sha256").update(token, "utf8").digest("hex");

export const issueApiToken = () => {
  const token = createPlainApiToken();

  return {
    plainTextToken: token,
    tokenPrefix: getTokenPrefix(token),
    tokenHash: hashApiToken(token),
  };
};
