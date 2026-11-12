// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { formatDuration } from "@/lib/archive/utils";
import { SetSeekControl } from "./set-seek-control";

describe("commit-on-release set seek control", () => {
  let root: Root;
  let host: HTMLDivElement;
  let onCommit: ReturnType<typeof vi.fn<(seconds: number) => void>>;
  let props: { currentTime: number; duration: number; disabled: boolean; source: string };
  const input = () => host.querySelector("input")!;
  const render = async () => act(async () => root.render(<SetSeekControl key={props.source} {...props} onCommit={onCommit}
    appearance="timeline" className="dock-progress" id="dockProgress"
    renderBefore={(seconds) => <div className="dock-time"><span id="dockCurrentTime">{formatDuration(seconds)}</span><span>{formatDuration(props.duration)}</span></div>} />));
  const pointer = async (type: string, pointerType = "mouse", pointerId = 1, target = input()) => act(async () => {
    const event = new MouseEvent(type, { bubbles: true, button: 0 });
    Object.defineProperties(event, { pointerId: { value: pointerId }, pointerType: { value: pointerType }, isPrimary: { value: true } });
    target.dispatchEvent(event);
  });
  const change = async (seconds: number, target = input()) => act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(target, String(seconds));
    target.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const key = async (type: string, value: string) => act(async () => input().dispatchEvent(new KeyboardEvent(type, { key: value, bubbles: true })));

  beforeEach(async () => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    host = document.createElement("div"); document.body.append(host); root = createRoot(host);
    onCommit = vi.fn(); props = { currentTime: 10, duration: 600, disabled: false, source: "a" };
    await render();
  });
  afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });

  it.each(["mouse", "touch", "pen"])("previews 100 %s samples and commits only the release", async (type) => {
    await pointer("pointerdown", type);
    for (let i = 0; i < 100; i++) await change(100 + i);
    expect(onCommit).not.toHaveBeenCalled();
    expect(input().value).toBe("199");
    expect(input().getAttribute("aria-valuetext")).toBe("3:19 of 10:00");
    expect(host.querySelector("#dockCurrentTime")!.textContent).toBe("3:19");
    expect(parseFloat(host.querySelector<HTMLElement>("#dockProgressFill")!.style.width)).toBeCloseTo(199 / 600 * 100, 3);
    expect(host.textContent).not.toContain("Seek to");
    props.currentTime = 30; await render();
    expect(input().value).toBe("199");
    await pointer("pointerup", type);
    await act(async () => input().click());
    expect(onCommit.mock.calls).toEqual([[199]]);
    expect(host.textContent).not.toContain("Seek to");
  });

  it("supports a tap, ignores another pointer, and retains native bounds", async () => {
    await pointer("pointerdown", "touch"); await change(800);
    await pointer("pointerup", "touch", 2);
    expect(onCommit).not.toHaveBeenCalled();
    await pointer("pointerup", "touch");
    expect(onCommit.mock.calls).toEqual([[600]]);
    await pointer("pointerdown"); await change(-5); await pointer("pointerup");
    expect(onCommit.mock.calls).toEqual([[600], [0]]);
  });

  it.each(["pointercancel", "lostpointercapture"])("cancels on %s without a late commit", async (event) => {
    await pointer("pointerdown"); await change(99); await pointer(event);
    await change(120); await pointer("pointerup");
    expect(onCommit).not.toHaveBeenCalled(); expect(input().value).toBe("10");
    expect(host.querySelector("#dockCurrentTime")!.textContent).toBe("0:10");
    await pointer("pointerdown"); await change(140); await pointer("pointerup");
    expect(onCommit.mock.calls).toEqual([[140]]);
  });

  it("Escape and focus loss cancel edits", async () => {
    await pointer("pointerdown"); await change(40); await key("keydown", "Escape");
    await change(50); await pointer("pointerup"); expect(onCommit).not.toHaveBeenCalled();
    await key("keydown", "ArrowRight"); await change(41);
    await act(async () => input().dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
    await key("keyup", "ArrowRight"); expect(onCommit).not.toHaveBeenCalled();
  });

  it.each(["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"])("commits a %s key sequence once", async (name) => {
    await key("keydown", name); await change(11); await key("keydown", name); await change(12);
    expect(onCommit).not.toHaveBeenCalled();
    await key("keyup", name); expect(onCommit.mock.calls).toEqual([[12]]);
  });

  it("preserves native accessibility and accepts assistive changes without a pointer", async () => {
    expect(input().type).toBe("range"); expect(input().min).toBe("0"); expect(input().max).toBe("600");
    expect(host.querySelector(".dock-progress")!.getAttribute("aria-hidden")).toBe("true");
    expect(input().className).toBe("set-seek-input");
    expect(input().step).toBe("1"); expect(input().getAttribute("aria-label")).toBe("Seek within set");
    await change(35); expect(onCommit.mock.calls).toEqual([[35]]);
  });

  it("cancels when disabled and does not restore the old gesture on re-enable", async () => {
    await pointer("pointerdown"); await change(99);
    props.disabled = true; await render(); expect(input().disabled).toBe(true);
    props.disabled = false; await render(); await pointer("pointerup");
    expect(onCommit).not.toHaveBeenCalled(); expect(input().value).toBe("10");
    expect(host.querySelector("#dockCurrentTime")!.textContent).toBe("0:10");
  });

  it("discards a pending source's gesture and uses the new source's callback", async () => {
    await pointer("pointerdown"); await change(99); const oldInput = input();
    props.source = "b"; props.currentTime = 5; const next = vi.fn(); onCommit = next; await render();
    await pointer("pointerup", "mouse", 1, oldInput); expect(next).not.toHaveBeenCalled(); expect(input().value).toBe("5");
    await pointer("pointerdown"); await change(70); await pointer("pointerup"); expect(next.mock.calls).toEqual([[70]]);
  });
  it("Escape is not undone by held-key auto-repeat", async () => {
    await key("keydown", "ArrowRight"); await change(50); await key("keydown", "Escape");
    await act(async () => input().dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", repeat: true, bubbles: true })));
    await change(60); await key("keyup", "ArrowRight"); expect(onCommit).not.toHaveBeenCalled();
    await key("keydown", "ArrowRight"); await change(11); await key("keyup", "ArrowRight");
    expect(onCommit.mock.calls).toEqual([[11]]);
  });

  it("duration replacement cancels a drag instead of applying an old timeline target", async () => {
    await pointer("pointerdown"); await change(500);
    props.duration = 100; await render(); await pointer("pointerup");
    expect(onCommit).not.toHaveBeenCalled(); expect(input().value).toBe("10");
    expect(host.querySelector("#dockCurrentTime")!.textContent).toBe("0:10");
  });

});
