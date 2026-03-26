"use client";

import { signIn, signOut } from "next-auth/react";

export const GoogleSignInButton = ({
  callbackUrl,
  label = "Continue with Google",
}: {
  callbackUrl?: string;
  label?: string;
}) => (
  <button
    className="button"
    onClick={() => void signIn("google", { callbackUrl })}
    type="button"
  >
    {label}
  </button>
);

export const SignOutButton = () => (
  <button className="button button--ghost" onClick={() => void signOut({ callbackUrl: "/" })} type="button">
    Sign out
  </button>
);
