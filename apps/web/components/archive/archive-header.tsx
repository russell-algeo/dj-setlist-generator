"use client";

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
  return (
    <header className={`topbar ${styles.header}`}>
      <div className={`topbar-inner ${styles.inner}`}>
        <div className={`brand ${styles.brand}`}>[SET SIGNAL ARCHIVE]</div>
        <nav className={`topnav ${styles.nav}`}>
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
        <div className={styles.topbarRight}>
          {!hideScopeToggle && <ScopeToggle />}
          {!hideScopeToggle && (!hideSubmit || !hideAuth) ? <div className={styles.divider} /> : null}
          {!hideSubmit && <SubmitPanel />}
          {!hideAuth && <AuthDropdown />}
        </div>
      </div>
    </header>
  );
}
