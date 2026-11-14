import { vi } from "vitest";

// The explorer tests stub HTMLMediaElement's prototype, which a real off-page
// standby element would share. Give the seam preloader an inert element that
// never becomes ready, so these tests keep exercising the ordinary file switch.
export function stubStandbyAudio() {
  vi.stubGlobal("Audio", class {
    src = ""; preload = ""; paused = true; ended = false; currentTime = 0; readyState = 0;
    load() {} pause() {} play() { return Promise.resolve(); }
    addEventListener() {} removeEventListener() {}
  });
}
