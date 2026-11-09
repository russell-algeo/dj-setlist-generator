import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { SpotifyExportButton } from "./spotify-export-button";

vi.mock("./use-spotify-export-status", () => ({
  useSpotifyExportStatus: vi.fn().mockReturnValue({
    isAuthenticated: true,
    isLoading: false,
    spotifyConfigured: true,
    spotifyConnected: true,
  }),
}));

describe("SpotifyExportButton", () => {
  it.each(["artist", "set"] as const)("keeps %s export enabled and discloses link-access privacy", (entityType) => {
    const fetchFn = vi.fn();
    vi.stubGlobal("fetch", fetchFn);
    try {
      const html = renderToStaticMarkup(<SpotifyExportButton
        counts={{ all: 2, HIGH: 2, MEDIUM: 0, LOW: 0 }}
        entityType={entityType}
        slug="example"
      />);
      expect(html).toContain("aria-disabled=\"false\"");
      expect(html).toContain("Export to Spotify");
      expect(html).not.toContain("(unavailable)");
      expect(html).toContain("may be accessible by link");
      expect(html).toContain("Use Make private in Spotify");
      expect(html).not.toContain("Private playlist in your connected Spotify account");
      expect(fetchFn).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
