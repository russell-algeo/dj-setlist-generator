import "server-only";

import { notFound, redirect } from "next/navigation";
import { getSessionActor } from "@/lib/auth/session";
import { hasYoonAccess } from "./access.server";

// Page navigation only. API callers still receive the existing private 404.
// Build the return path here; never accept an arbitrary callback URL.
export async function requireYoonPageActor(slug?: string) {
  const collectionPath = "/collections/yoon-fest";
  if (slug === "" || slug === "." || slug === "..") notFound();
  const callbackPath = slug === undefined
    ? collectionPath
    : `${collectionPath}/sets/${encodeURIComponent(slug)}`;

  const actor = await getSessionActor();
  if (!actor) {
    redirect(`/api/auth/signin?callbackUrl=${encodeURIComponent(callbackPath)}`);
  }
  if (!await hasYoonAccess(actor)) notFound();
  return actor;
}
