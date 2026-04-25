"use client";

import { signIn, signOut } from "next-auth/react";

type SignInProvider = "google" | "spotify";

const defaultLabels: Record<SignInProvider, string> = {
  google: "Sign in with Google",
  spotify: "Sign in with Spotify",
};

export const ProviderSignInButton = ({
  callbackUrl,
  className = "button",
  label,
  provider,
}: {
  callbackUrl?: string;
  className?: string;
  label?: string;
  provider: SignInProvider;
}) => (
  <button
    className={className}
    onClick={() => void signIn(provider, { callbackUrl })}
    type="button"
  >
    {label ?? defaultLabels[provider]}
  </button>
);

export const GoogleSignInButton = ({
  callbackUrl,
  label,
}: {
  callbackUrl?: string;
  label?: string;
}) => <ProviderSignInButton callbackUrl={callbackUrl} label={label} provider="google" />;

export const SpotifySignInButton = ({
  callbackUrl,
  className,
  label,
}: {
  callbackUrl?: string;
  className?: string;
  label?: string;
}) => (
  <ProviderSignInButton
    callbackUrl={callbackUrl}
    className={className}
    label={label}
    provider="spotify"
  />
);

export const SignOutButton = () => (
  <button className="button button--ghost" onClick={() => void signOut({ callbackUrl: "/" })} type="button">
    Sign out
  </button>
);
