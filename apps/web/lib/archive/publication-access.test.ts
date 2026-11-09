import { describe, expect, it } from "vitest";
import { publicationAccessFromRun, assertPublicationTarget } from "./publication-access";
const setId = "10000000-0000-4000-8000-000000000001";
const collectionId = "20000000-0000-4000-8000-000000000001";
const access = { visibility: "private" as const, setId, collectionId };
const target = { id: setId, visibility: "private", collectionId };
describe("trusted publication scope", () => {
  it("resolves explicit public and precreated private runs", () => {
    expect(publicationAccessFromRun({ publicationVisibility: "public" })).toEqual({ visibility: "public" });
    expect(publicationAccessFromRun({ publicationVisibility: "private", targetSetId: setId, collectionId })).toEqual(access);
    expect(() => assertPublicationTarget(access, target)).not.toThrow();
  });
  it.each([{}, { publicationVisibility: "private" }, { publicationVisibility: "public", targetSetId: setId }, { publicationVisibility: "unlisted" }, { publicationVisibility: "private", targetSetId: "not-uuid", collectionId }])("denies absent or malformed scope %j", (run) => expect(() => publicationAccessFromRun(run)).toThrow());
  it.each([null, { ...target, id: collectionId }, { ...target, collectionId: setId }, { ...target, visibility: "public" }])("rejects private target mismatch %j", (row) => expect(() => assertPublicationTarget(access, row)).toThrow());
  it("cannot overwrite a private row through the public pipeline", () => expect(() => assertPublicationTarget({ visibility: "public" }, target)).toThrow());
});
