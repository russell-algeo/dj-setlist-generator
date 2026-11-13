import { and, eq, or, sql, type SQL, type SQLWrapper } from "drizzle-orm";
import { sets, submissions } from "@/lib/db/schema";

// This policy uses existing authn user IDs. General admin status never grants
// access to a private collection. SQL predicates are evaluated on every read.
export function collectionMemberPredicate(collectionId: SQLWrapper, userId: string | null): SQL {
  if (!userId) return sql`false`;
  return sql`exists (select 1 from app.archive_collection_members member
    where member.collection_id = ${collectionId} and member.user_id = ${userId})
    and ${pinnedAudiencePredicate(collectionId)}`;
}

// The private Yoon collection is readable only while its live audience still
// equals the pinned two-person audience. Other collections are unaffected.
export function pinnedAudiencePredicate(collectionId: SQLWrapper): SQL {
  return sql`(app.yoon_audience_intact(${collectionId}) or not exists (select 1 from app.archive_collections pinned
    where pinned.id = ${collectionId} and pinned.slug = 'yoon-fest'))`;
}

export function readableSetPredicate(userId: string | null, privateAccess = true): SQL {
  return or(eq(sets.visibility, "public"), and(eq(sets.visibility, "private"), privateAccess ? sql`true` : sql`false`, sql`app.yoon_version_readable(${sets.id}, false)`, collectionMemberPredicate(sets.collectionId, userId)))!;
}

// Private collections are never readable through API tokens: pass
// privateAccess=false for any actor that is not an interactive session.
export function readableSubmissionPredicate(userId: string, isAdmin: boolean, privateAccess = true): SQL {
  return or(
    and(eq(submissions.visibility, "public"), isAdmin ? sql`true` : eq(submissions.requestedBy, userId)),
    and(eq(submissions.visibility, "private"), privateAccess ? sql`true` : sql`false`, sql`app.yoon_submission_version_readable(${submissions.id})`, collectionMemberPredicate(submissions.collectionId, userId)),
  )!;
}

// Reading a collection is not permission to restart or cancel its processing.
export function manageableSubmissionPredicate(userId: string, isAdmin: boolean, privateAccess = true): SQL {
  return or(
    and(eq(submissions.visibility, "public"), isAdmin ? sql`true` : eq(submissions.requestedBy, userId)),
    and(eq(submissions.visibility, "private"), privateAccess ? sql`true` : sql`false`, pinnedAudiencePredicate(submissions.collectionId), sql`app.yoon_submission_version_readable(${submissions.id})`, sql`exists (select 1 from app.archive_collection_members member
      where member.collection_id = ${submissions.collectionId} and member.user_id = ${userId} and member.role = 'manager')`),
  )!;
}
