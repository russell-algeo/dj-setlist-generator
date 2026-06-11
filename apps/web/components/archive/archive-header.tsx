"use client";

import { useState } from "react";
import Link from "next/link";

import { AuthDropdown } from "@/components/archive/auth-dropdown";
import { ArchiveGlobalSearch } from "@/components/archive/archive-global-search";
import { ScopeToggle } from "@/components/archive/scope-toggle";
import { SubmitPanel } from "@/components/archive/submit-panel";

import styles from "./archive-header.module.css";

type NavLink = { label: string; href: string };

type ArchiveHeaderProps = {
  activeHref?: string;
  hideAuth?: boolean;
  hideSearch?: boolean;
  hideScopeToggle?: boolean;
  hideSubmit?: boolean;
  navLinks: NavLink[];
};

export function ArchiveHeader({
  activeHref,
  hideAuth,
  hideSearch,
  hideScopeToggle,
  hideSubmit,
  navLinks,
}: ArchiveHeaderProps) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const hasControls = !hideSearch || !hideScopeToggle || !hideSubmit || !hideAuth;

  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <Link className={styles.brand} href="/">[SET SIGNAL ARCHIVE]</Link>
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
          {!hideSearch && <ArchiveGlobalSearch />}
          {!hideScopeToggle && <ScopeToggle />}
          {!hideScopeToggle && (!hideSubmit || !hideAuth) ? <div className={styles.divider} /> : null}
          {!hideSubmit && <SubmitPanel />}
          {!hideAuth && <AuthDropdown />}
        </div>
        {/* Mobile menu trigger — hidden on desktop via CSS */}
        {hasControls && (
          <button
            aria-expanded={mobileMenuOpen}
            aria-label={mobileMenuOpen ? "Close controls" : "Open controls"}
            className={styles.mobileMenuTrigger}
            onClick={() => setMobileMenuOpen((v) => !v)}
            type="button"
          >
            {mobileMenuOpen ? (
              <span aria-hidden="true" className={styles.mobileMenuCloseIcon} />
            ) : (
              <span aria-hidden="true" className={styles.mobileMenuIcon}>
                <span />
                <span />
                <span />
              </span>
            )}
          </button>
        )}
      </div>
      {/* Mobile controls panel — only rendered when open */}
      {mobileMenuOpen && (
        <div className={styles.mobileMenuPanel}>
          <div className={styles.mobileControlGroup}>
            {!hideSearch && <ArchiveGlobalSearch />}
            {!hideScopeToggle && <ScopeToggle />}
          </div>
          <div className={`${styles.mobileControlGroup} ${styles.mobileControlGroupRight}`}>
            {!hideSubmit && <SubmitPanel />}
            {!hideAuth && <AuthDropdown />}
          </div>
        </div>
      )}
    </header>
  );
}
