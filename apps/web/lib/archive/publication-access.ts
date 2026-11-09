import { z } from "zod";

export type PublicationAccess =
  | { visibility: "public" }
  | { visibility: "private"; setId: string; collectionId: string };

const privateTarget = z.object({ publicationVisibility: z.literal("private"), targetSetId: z.string().uuid(), collectionId: z.string().uuid() });
export function publicationAccessFromRun(run: { publicationVisibility?: string | null; targetSetId?: string | null; collectionId?: string | null }): PublicationAccess {
  if (run.publicationVisibility === "public" && !run.targetSetId && !run.collectionId) return { visibility: "public" };
  const scope = privateTarget.safeParse(run);
  if (!scope.success) throw new Error("Publication scope is missing or invalid");
  return { visibility: "private", setId: scope.data.targetSetId, collectionId: scope.data.collectionId };
}

export function assertPublicationTarget(access: PublicationAccess, target: { id: string; visibility: string; collectionId: string | null } | null | undefined) {
  if (access.visibility === "private") {
    if (!target || target.id !== access.setId || target.visibility !== "private" || target.collectionId !== access.collectionId) throw new Error("Private publication target does not match the trusted run");
  } else if (target && target.visibility !== "public") {
    throw new Error("Public publication cannot overwrite a private item");
  }
}
