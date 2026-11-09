import { PgDialect } from "drizzle-orm/pg-core";
import { describe, expect, it } from "vitest";
import { archiveCollections } from "@/lib/db/schema";
import { collectionMemberPredicate, manageableSubmissionPredicate, readableSetPredicate, readableSubmissionPredicate } from "./access-policy";
const compile = (query: ReturnType<typeof readableSetPredicate>) => new PgDialect().sqlToQuery(query);
describe("shared item access predicates", () => {
  it("anonymous set access has no member branch", () => {
    const query = compile(readableSetPredicate(null)); expect(query.sql).toContain('"visibility" =');
    expect(query.sql).toContain("false"); expect(query.sql).not.toContain("archive_collection_members");
  });
  it("uses exact user IDs and collection membership, never email", () => {
    const query = compile(collectionMemberPredicate(archiveCollections.id, "synthetic-user"));
    expect(query.sql).toContain("member.collection_id"); expect(query.sql).toContain("member.user_id");
    expect(query.params).toEqual(["synthetic-user"]);
  });
  it.each([false, true])("admin=%s does not bypass the private submission membership branch", (admin) => {
    const query = compile(readableSubmissionPredicate("synthetic-user", admin));
    expect(query.sql).toContain("archive_collection_members"); expect(query.params).toContain("private");
    expect(query.params.at(-1)).toBe("synthetic-user");
  });
  it("requires manager membership for private mutations", () => {
    const read = compile(readableSubmissionPredicate("synthetic-user", true));
    const manage = compile(manageableSubmissionPredicate("synthetic-user", true));
    expect(read.sql).not.toContain("member.role"); expect(manage.sql).toContain("member.role = 'manager'");
  });
});
