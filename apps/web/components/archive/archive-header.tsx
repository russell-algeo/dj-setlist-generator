"use client";

import { AuthDropdown } from "@/components/archive/auth-dropdown";
import { ScopeToggle } from "@/components/archive/scope-toggle";
import { SubmitPanel } from "@/components/archive/submit-panel";

import styles from "./archive-header.module.css";

type NavLink = { label: string; href: string };

type ArchiveHeaderProps = {
  navLinks: NavLink[];
};

export function ArchiveHeader({ navLinks }: ArchiveHeaderProps) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand">[SET SIGNAL ARCHIVE]</div>
        <nav className="topnav">
          {navLinks.map((link) => (
            <a href={link.href} key={link.href}>
              {link.label}
            </a>
          ))}
        </nav>
        <div className={styles.topbarRight}>
          <ScopeToggle />
          <div className={styles.divider} />
          <SubmitPanel />
          <AuthDropdown />
        </div>
      </div>
    </header>
  );
}
