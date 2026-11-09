import { beforeEach, describe, expect, it, vi } from "vitest";

const getRequestActor = vi.fn();
const listUserSetListenProgress = vi.fn();
const setUserSetListened = vi.fn();
const upsertUserSetListenProgress = vi.fn();

vi.mock("@/lib/auth/session", () => ({
  getRequestActor,
}));

vi.mock("@/lib/archive/listen-progress.server", () => ({
  ListenProgressAccessError: class ListenProgressAccessError extends Error {},
  listUserSetListenProgress,
  setUserSetListened,
  upsertUserSetListenProgress,
}));

describe("/api/archive/listen-progress", () => {
  beforeEach(() => {
    getRequestActor.mockReset();
    listUserSetListenProgress.mockReset();
    setUserSetListened.mockReset();
    upsertUserSetListenProgress.mockReset();
  });

  it("does not reveal a private set on unauthorized progress writes", async () => {
    getRequestActor.mockResolvedValue({ userId: "outsider" });
    const { ListenProgressAccessError } = await import("@/lib/archive/listen-progress.server");
    upsertUserSetListenProgress.mockRejectedValue(new ListenProgressAccessError("Set not found"));
    const { POST } = await import("./route");
    const response = await POST(new Request("http://localhost/api/archive/listen-progress", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ setId: "4e1b45fc-1a38-4bfd-8831-5b7e98fb2c99", duration: 100, intervals: [[0, 10]], lastPosition: 10 }),
    }));
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "Set not found" });
  });

  it("requires authentication for bulk reads", async () => {
    getRequestActor.mockResolvedValue(null);

    const { GET } = await import("./route");
    const response = await GET(
      new Request("http://localhost/api/archive/listen-progress?setIds=4e1b45fc-1a38-4bfd-8831-5b7e98fb2c99"),
    );

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({ error: "Authentication required" });
    expect(listUserSetListenProgress).not.toHaveBeenCalled();
  });

  it("returns listened progress for requested set ids", async () => {
    getRequestActor.mockResolvedValue({ userId: "user-123" });
    listUserSetListenProgress.mockResolvedValue([
      {
        coverageRatio: 0.8,
        intervals: [[0, 80]],
        listened: true,
        listenedAt: "2026-06-08T23:00:00.000Z",
        setId: "4e1b45fc-1a38-4bfd-8831-5b7e98fb2c99",
      },
    ]);

    const { GET } = await import("./route");
    const response = await GET(
      new Request("http://localhost/api/archive/listen-progress?setIds=4e1b45fc-1a38-4bfd-8831-5b7e98fb2c99"),
    );

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({
      progress: [
        {
          coverageRatio: 0.8,
          intervals: [[0, 80]],
          listened: true,
          listenedAt: "2026-06-08T23:00:00.000Z",
          setId: "4e1b45fc-1a38-4bfd-8831-5b7e98fb2c99",
        },
      ],
    });
    expect(listUserSetListenProgress).toHaveBeenCalledWith("user-123", [
      "4e1b45fc-1a38-4bfd-8831-5b7e98fb2c99",
    ]);
  });

  it("normalizes intervals before upserting progress", async () => {
    getRequestActor.mockResolvedValue({ userId: "user-123" });
    upsertUserSetListenProgress.mockResolvedValue({
      coverageRatio: 0.75,
      intervals: [[0, 75]],
      listened: true,
      listenedAt: "2026-06-08T23:00:00.000Z",
      setId: "4e1b45fc-1a38-4bfd-8831-5b7e98fb2c99",
    });

    const { POST } = await import("./route");
    const response = await POST(
      new Request("http://localhost/api/archive/listen-progress", {
        body: JSON.stringify({
          duration: 100,
          intervals: [
            [0, 50],
            [49.8, 75],
          ],
          lastPosition: 75,
          setId: "4e1b45fc-1a38-4bfd-8831-5b7e98fb2c99",
          sourceUrl: "https://www.youtube.com/watch?v=demo",
        }),
        headers: {
          "content-type": "application/json",
        },
        method: "POST",
      }),
    );

    expect(response.status).toBe(200);
    expect(upsertUserSetListenProgress).toHaveBeenCalledWith("user-123", {
      duration: 100,
      intervals: [[0, 75]],
      lastPosition: 75,
      setId: "4e1b45fc-1a38-4bfd-8831-5b7e98fb2c99",
      sourceUrl: "https://www.youtube.com/watch?v=demo",
    });
  });
});

const markerSetId = "4e1b45fc-1a38-4bfd-8831-5b7e98fb2c99";
const markerRequest = (body: unknown) => new Request("http://localhost/api/archive/listen-progress", {
  body: JSON.stringify(body), headers: { "content-type": "application/json" }, method: "PATCH",
});

describe("PATCH /api/archive/listen-progress", () => {
  beforeEach(() => {
    getRequestActor.mockReset();
    setUserSetListened.mockReset();
  });

  it("requires authentication before changing any marker", async () => {
    getRequestActor.mockResolvedValue(null);
    const { PATCH } = await import("./route");
    const response = await PATCH(markerRequest({ setId: markerSetId, listened: true }));
    expect(response.status).toBe(401);
    expect(setUserSetListened).not.toHaveBeenCalled();
  });

  it.each([true, false])("saves listened=%s for the authenticated user", async (listened) => {
    getRequestActor.mockResolvedValue({ userId: "user-123" });
    const progress = { setId: markerSetId, listened, intervals: [], coverageRatio: listened ? 1 : 0, listenedAt: null };
    setUserSetListened.mockResolvedValue(progress);
    const { PATCH } = await import("./route");
    const response = await PATCH(markerRequest({ setId: markerSetId, listened, userId: "someone-else" }));
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ progress });
    expect(setUserSetListened).toHaveBeenCalledWith("user-123", markerSetId, listened);
  });

  it.each([
    {}, { setId: "invalid", listened: true }, { setId: markerSetId },
    { setId: markerSetId, listened: "false" }, { setId: markerSetId, listened: null },
  ])("rejects invalid marker payload %j", async (body) => {
    getRequestActor.mockResolvedValue({ userId: "user-123" });
    const { PATCH } = await import("./route");
    expect((await PATCH(markerRequest(body))).status).toBe(400);
    expect(setUserSetListened).not.toHaveBeenCalled();
  });

  it("rejects malformed JSON", async () => {
    getRequestActor.mockResolvedValue({ userId: "user-123" });
    const { PATCH } = await import("./route");
    const response = await PATCH(new Request("http://localhost/api/archive/listen-progress", {
      body: "{", headers: { "content-type": "application/json" }, method: "PATCH",
    }));
    expect(response.status).toBe(400);
    expect(setUserSetListened).not.toHaveBeenCalled();
  });

  it("returns 404 for a set that no longer exists", async () => {
    getRequestActor.mockResolvedValue({ userId: "user-123" });
    setUserSetListened.mockResolvedValue(null);
    const { PATCH } = await import("./route");
    const response = await PATCH(markerRequest({ setId: markerSetId, listened: true }));
    expect(response.status).toBe(404);
    await expect(response.json()).resolves.toEqual({ error: "Set not found" });
  });
});
