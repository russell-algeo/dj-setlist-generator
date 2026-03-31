"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";

import styles from "./submit-panel.module.css";

type SubmitState = { status: "idle" } | { status: "submitting" } | { status: "error"; message: string };

async function postSubmission(body: Record<string, string>): Promise<{ submissionId: string }> {
  const res = await fetch("/api/jobs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { error?: string }).error ?? `HTTP ${res.status}`);
  }

  return res.json() as Promise<{ submissionId: string }>;
}

function UrlForm({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [state, setState] = useState<SubmitState>({ status: "idle" });

  const handleSubmit = async () => {
    setState({ status: "submitting" });
    try {
      const { submissionId } = await postSubmission({ mode: "url", sourceUrl: url });
      onClose();
      router.push(`/submissions/${submissionId}`);
    } catch (err) {
      setState({ status: "error", message: (err as Error).message });
    }
  };

  return (
    <>
      <input
        className={styles.input}
        placeholder="https://www.youtube.com/watch?v=…"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
      />
      <div className={styles.btnRow}>
        <button
          className={styles.submitBtn}
          disabled={!url.trim() || state.status === "submitting"}
          onClick={handleSubmit}
          type="button"
        >
          {state.status === "submitting" ? "Submitting…" : "Submit"}
        </button>
        <button className={styles.cancelBtn} onClick={onClose} type="button">
          Cancel
        </button>
      </div>
      {state.status === "error" && <div className={styles.error}>{state.message}</div>}
    </>
  );
}

function ArtistForm({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [state, setState] = useState<SubmitState>({ status: "idle" });

  const handleSubmit = async () => {
    setState({ status: "submitting" });
    try {
      const { submissionId } = await postSubmission({ mode: "artist", artistName: name });
      onClose();
      router.push(`/submissions/${submissionId}`);
    } catch (err) {
      setState({ status: "error", message: (err as Error).message });
    }
  };

  return (
    <>
      <input
        className={styles.input}
        placeholder="e.g. Floating Points"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <div className={styles.btnRow}>
        <button
          className={styles.submitBtn}
          disabled={!name.trim() || state.status === "submitting"}
          onClick={handleSubmit}
          type="button"
        >
          {state.status === "submitting" ? "Submitting…" : "Start Scan"}
        </button>
        <button className={styles.cancelBtn} onClick={onClose} type="button">
          Cancel
        </button>
      </div>
      {state.status === "error" && <div className={styles.error}>{state.message}</div>}
    </>
  );
}

function CuratedForm({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [urls, setUrls] = useState("");
  const [state, setState] = useState<SubmitState>({ status: "idle" });

  const handleSubmit = async () => {
    setState({ status: "submitting" });
    try {
      const { submissionId } = await postSubmission({
        mode: "curated_artist",
        artistName: name,
        sourceUrls: urls,
      });
      onClose();
      router.push(`/submissions/${submissionId}`);
    } catch (err) {
      setState({ status: "error", message: (err as Error).message });
    }
  };

  return (
    <>
      <input
        className={styles.input}
        placeholder="Artist name"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <textarea
        className={styles.textarea}
        placeholder="Paste URLs, one per line"
        value={urls}
        onChange={(e) => setUrls(e.target.value)}
      />
      <div className={styles.btnRow}>
        <button
          className={styles.submitBtn}
          disabled={!name.trim() || !urls.trim() || state.status === "submitting"}
          onClick={handleSubmit}
          type="button"
        >
          {state.status === "submitting" ? "Submitting…" : "Submit"}
        </button>
        <button className={styles.cancelBtn} onClick={onClose} type="button">
          Cancel
        </button>
      </div>
      {state.status === "error" && <div className={styles.error}>{state.message}</div>}
    </>
  );
}

export function SubmitPanel() {
  const { data: session } = useSession();
  const [open, setOpen] = useState(false);

  if (!session?.user) return null;

  return (
    <>
      <button
        className={`${styles.trigger} ${open ? styles.open : ""}`}
        onClick={() => setOpen((v) => !v)}
        type="button"
      >
        + Submit {open ? "▴" : "▾"}
      </button>

      {open && (
        <>
          <div className={styles.overlay} onClick={() => setOpen(false)} />
          <div className={styles.panel}>
            <div className={styles.panelTitle}>What would you like to process?</div>
            <div className={styles.modes}>
              <div className={styles.mode}>
                <span className={styles.modeTitle}>Single Set URL</span>
                <span className={styles.modeDesc}>Paste a YouTube or SoundCloud URL for one mix</span>
                <UrlForm onClose={() => setOpen(false)} />
              </div>
              <div className={styles.mode}>
                <span className={styles.modeTitle}>Artist Discovery</span>
                <span className={styles.modeDesc}>Enter a DJ name — auto-finds all their recorded sets</span>
                <ArtistForm onClose={() => setOpen(false)} />
              </div>
              <div className={styles.mode}>
                <span className={styles.modeTitle}>Curated Artist</span>
                <span className={styles.modeDesc}>Hand-pick URLs for a named artist</span>
                <CuratedForm onClose={() => setOpen(false)} />
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
