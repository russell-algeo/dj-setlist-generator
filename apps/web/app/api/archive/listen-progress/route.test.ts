import { beforeEach, describe, expect, it, vi } from "vitest";

const getRequestActor = vi.fn();
const listUserSetListenProgress = vi.fn();
const upsertUserSetListenProgress = vi.fn();

vi.mock("@/lib/auth/session", () => ({
  getRequestActor,
}));

vi.mock("@/lib/archive/listen-progress.server", () => ({
  listUserSetListenProgress,
  upsertUserSetListenProgress,
}));

describe("/api/archive/listen-progress", () => {
  beforeEach(() => {
    getRequestActor.mockReset();
    listUserSetListenProgress.mockReset();
    upsertUserSetListenProgress.mockReset();
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
