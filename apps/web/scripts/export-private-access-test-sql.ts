// Compile the actual app predicates for the offline PostgreSQL test.
import { PgDialect } from "drizzle-orm/pg-core";
import { manageableSubmissionPredicate, readableSetPredicate, readableSubmissionPredicate } from "../lib/archive/access-policy";
const dialect = new PgDialect();
console.log(JSON.stringify(Object.fromEntries(["synthetic-russell", "synthetic-hal", "outsider", "admin", null].map((user) => [String(user), {
  sets: dialect.sqlToQuery(readableSetPredicate(user)),
  submissions: user ? dialect.sqlToQuery(readableSubmissionPredicate(user, user === "admin")) : null,
  manage: user ? dialect.sqlToQuery(manageableSubmissionPredicate(user, user === "admin")) : null,
}]))));
