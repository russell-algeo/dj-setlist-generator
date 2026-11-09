import { isValidElement, type ReactElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InlineSubmitButton } from "./inline-submit-button";

const harness = vi.hoisted(() => ({
  states: [] as unknown[],
  index: 0,
  reportValidity: vi.fn(),
  push: vi.fn(),
}));

// Exercise the component's actual event handlers without adding a DOM dependency.
vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();
  return {
    ...actual,
    useId: () => "discovery-limit",
    useRef: () => ({ current: { reportValidity: harness.reportValidity } }),
    useState: (initial: unknown) => [harness.states[harness.index++] ?? initial, vi.fn()],
  };
});
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: harness.push }) }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { user: { id: "test-user" } } }) }));

type Element = ReactElement<Record<string, unknown>>;
const elements = (value: ReactNode): Element[] => {
  if (Array.isArray(value)) return value.flatMap(elements);
  if (!isValidElement<Record<string, unknown>>(value)) return [];
  return [value, ...elements(value.props.children as ReactNode)];
};

const render = (maximumSets = "", aliases = ["Alias One", "Alias Two"], allowDiscoveryMaxSets: boolean | undefined = true) => {
  // open, tooltip, discovery name, aliases, maximum sets, curated name, URLs, status.
  harness.states = [true, false, "Phil Weeks", aliases, maximumSets, "Curated DJ", "https://example.test/set", { status: "idle" }];
  harness.index = 0;
  return elements(InlineSubmitButton({ allowDiscoveryMaxSets, mode: "scan-artist" }));
};
const scanButton = (tree: Element[]) => tree.find((node) => node.type === "button" && node.props.children === "Start Scan")!;
const click = async (element: Element) => (element.props.onClick as () => Promise<void>)();

describe("Artist Discovery maximum sets", () => {
  const fetchFn = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    harness.reportValidity.mockReturnValue(true);
    fetchFn.mockResolvedValue({ ok: true, json: async () => ({ submissionId: "new-submission" }) });
    vi.stubGlobal("fetch", fetchFn);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("sends cap 1 through the existing field, preserving aliases and playlist default off", async () => {
    const aliases = ["Alias One", "Alias Two"];
    const button = scanButton(render("1", aliases));
    expect(button.props.disabled).toBe(false);
    await click(button);
    expect(fetchFn).toHaveBeenCalledOnce();
    expect(fetchFn).toHaveBeenCalledWith("/api/jobs", expect.objectContaining({ method: "POST" }));
    const body = JSON.parse(fetchFn.mock.calls[0][1].body);
    expect(body).toEqual({ mode: "artist", artistName: "Phil Weeks", artistAliases: aliases, maxSetsOverride: "1" });
    expect(body).not.toHaveProperty("createPlaylist");
    expect(aliases).toEqual(["Alias One", "Alias Two"]);
    expect(harness.push).toHaveBeenCalledWith("/submissions/new-submission");
  });

  it.each(["", "  "])("omits a blank cap (%j) and keeps the prior request shape", async (value) => {
    await click(scanButton(render(value)));
    const body = JSON.parse(fetchFn.mock.calls[0][1].body);
    expect(body).toEqual({ mode: "artist", artistName: "Phil Weeks", artistAliases: ["Alias One", "Alias Two"] });
    expect(body).not.toHaveProperty("maxSetsOverride");
    expect(body).not.toHaveProperty("createPlaylist");
  });

  it.each(["0", "-1", "1.5", "not-a-number", "Infinity", "9007199254740992"])("blocks invalid cap %j before any request", async (value) => {
    const tree = render(value);
    const button = scanButton(tree);
    expect(button.props.disabled).toBe(true);
    expect(tree.find((node) => node.props.name === "maxSetsOverride")?.props["aria-invalid"]).toBe(true);
    expect(tree.find((node) => node.props.role === "alert")?.props.children).toBe("Enter a whole number greater than zero.");
    // The handler itself must remain safe even if called despite disabled state.
    await click(button);
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("does not mistake a native bad numeric input's empty value for an uncapped request", async () => {
    harness.reportValidity.mockReturnValue(false);
    await click(scanButton(render("")));
    expect(harness.reportValidity).toHaveBeenCalledOnce();
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("has a visible linked optional label and native positive-integer validation", () => {
    const tree = render();
    const input = tree.find((node) => node.props.name === "maxSetsOverride")!;
    expect(input.props).toMatchObject({ id: "discovery-limit", type: "number", min: 1, step: 1, value: "" });
    expect(tree.find((node) => node.type === "label" && node.props.htmlFor === input.props.id)?.props.children).toBe("Maximum sets (optional)");
    expect(tree.find((node) => node.props.id === "discovery-limit-hint")?.props.children).toContain("not duration");
  });

  it("does not add the discovery cap or playlist option to curated requests", async () => {
    const tree = render("1");
    const button = tree.find((node) => node.type === "button" && node.props.children === "Submit")!;
    await click(button);
    expect(JSON.parse(fetchFn.mock.calls[0][1].body)).toEqual({
      mode: "curated_artist", artistName: "Curated DJ", sourceUrls: "https://example.test/set",
    });
  });

  it.each([false, undefined])("hides and omits the cap when server capability is %j, regardless of stale browser state", async (allowDiscoveryMaxSets) => {
    // Avoid render's default argument so this also tests a genuinely absent prop.
    render("1");
    harness.index = 0;
    const tree = elements(InlineSubmitButton({ allowDiscoveryMaxSets, mode: "scan-artist" }));
    expect(tree.some((node) => node.props.name === "maxSetsOverride")).toBe(false);
    await click(scanButton(tree));
    expect(harness.reportValidity).not.toHaveBeenCalled();
    expect(JSON.parse(fetchFn.mock.calls[0][1].body)).not.toHaveProperty("maxSetsOverride");
  });
});
