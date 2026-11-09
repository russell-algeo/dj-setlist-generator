import { and, eq, or, sql, type SQL, type SQLWrapper } from "drizzle-orm";
import { sets, submissions } from "@/lib/db/schema";

// This policy uses existing authn user IDs. General admin status never grants
// access to a private collection. SQL predicates are evaluated on every read.
export function collectionMemberPredicate(collectionId: SQLWrapper, userId: string | null): SQL {
  if (!userId) return sql`false`;
  return sql`exists (select 1 from app.archive_collection_members member
    where member.collection_id = ${collectionId} and member.user_id = ${userId})`;
}

export function readableSetPredicate(userId: string | null): SQL {
  return or(eq(sets.visibility, "public"), and(eq(sets.visibility, "private"), collectionMemberPredicate(sets.collectionId, userId)))!;
}

export function readableSubmissionPredicate(userId: string, isAdmin: boolean): SQL {
  return or(
    and(eq(submissions.visibility, "public"), isAdmin ? sql`true` : eq(submissions.requestedBy, userId)),
    and(eq(submissions.visibility, "private"), collectionMemberPredicate(submissions.collectionId, userId)),
  )!;
}

// Reading a collection is not permission to restart or cancel its processing.
export function manageableSubmissionPredicate(userId: string, isAdmin: boolean): SQL {
  return or(
    and(eq(submissions.visibility, "public"), isAdmin ? sql`true` : eq(submissions.requestedBy, userId)),
    and(eq(submissions.visibility, "private"), sql`exists (select 1 from app.archive_collection_members member
      where member.collection_id = ${submissions.collectionId} and member.user_id = ${userId} and member.role = 'manager')`),
  )!;
}
