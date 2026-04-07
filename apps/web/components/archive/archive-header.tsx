"use client";

import { useState } from "react";

import { AuthDropdown } from "@/components/archive/auth-dropdown";
import { ScopeToggle } from "@/components/archive/scope-toggle";
import { SubmitPanel } from "@/components/archive/submit-panel";

import styles from "./archive-header.module.css";

type NavLink = { label: string; href: string };

type ArchiveHeaderProps = {
  activeHref?: string;
  hideAuth?: boolean;
  hideScopeToggle?: boolean;
  hideSubmit?: boolean;
  navLinks: NavLink[];
};

export function ArchiveHeader({
  activeHref,
  hideAuth,
  hideScopeToggle,
  hideSubmit,
  navLinks,
}: ArchiveHeaderProps) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const hasControls = !hideScopeToggle || !hideSubmit || !hideAuth;

  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <a className={styles.brand} href="/">[SET SIGNAL ARCHIVE]</a>
        <nav className={styles.nav}>
          {navLinks.map((link) => (
            <a
              className={`${styles.navLink} ${activeHref === link.href ? styles.navLinkActive : ""}`}
              href={link.href}
              key={link.href}
            >
              {link.label}
            </a>
          ))}
        </nav>
        {/* Desktop controls */}
        <div className={styles.topbarRight}>
          {!hideScopeToggle && <ScopeToggle />}
          {!hideScopeToggle && (!hideSubmit || !hideAuth) ? <div className={styles.divider} /> : null}
          {!hideSubmit && <SubmitPanel />}
          {!hideAuth && <AuthDropdown />}
        </div>
        {/* Mobile menu trigger — hidden on desktop via CSS */}
        {hasControls && (
          <button
            aria-expanded={mobileMenuOpen}
            aria-label="Toggle menu"
            className={styles.mobileMenuTrigger}
            onClick={() => setMobileMenuOpen((v) => !v)}
            type="button"
          >
            {mobileMenuOpen ? "✕" : "☰"}
          </button>
        )}
      </div>
      {/* Mobile controls panel — only rendered when open */}
      {mobileMenuOpen && (
        <div className={styles.mobileMenuPanel}>
          {!hideScopeToggle && <ScopeToggle />}
          {!hideSubmit && <SubmitPanel />}
          {!hideAuth && <AuthDropdown />}
        </div>
      )}
    </header>
  );
}
