"use client";

import { useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";

import styles from "./scope-toggle.module.css";

export function ScopeToggle() {
  const { data: session } = useSession();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const [tooltipVisible, setTooltipVisible] = useState(false);

  const isAuthenticated = Boolean(session?.user);
  const currentScope = searchParams.get("scope");
  const isWorkspace = currentScope === "mine";

  const buildHref = (scope: "global" | "mine") => {
    const params = new URLSearchParams(searchParams.toString());
    if (scope === "mine") {
      params.set("scope", "mine");
    } else {
      params.delete("scope");
    }
    // Reset page when switching scope
    params.delete("page");
    const qs = params.toString();
    return qs ? `${pathname}?${qs}` : pathname;
  };

  const handleWorkspaceClick = () => {
    if (!isAuthenticated) return;
    router.push(buildHref("mine"));
  };

  return (
    <div style={{ position: "relative" }}>
      <div className={styles.toggle}>
        <button
          className={`${styles.option} ${!isWorkspace ? styles.active : ""}`}
          onClick={() => router.push(buildHref("global"))}
          type="button"
        >
          Global
        </button>
        <button
          className={`${styles.option} ${isWorkspace ? styles.active : ""} ${!isAuthenticated ? styles.disabled : ""}`}
          onClick={handleWorkspaceClick}
          onMouseEnter={() => !isAuthenticated && setTooltipVisible(true)}
          onMouseLeave={() => setTooltipVisible(false)}
          type="button"
        >
          My Workspace
        </button>
      </div>
      {tooltipVisible && !isAuthenticated && (
        <div className={styles.tooltip}>You must log in to use My Workspace</div>
      )}
    </div>
  );
}
