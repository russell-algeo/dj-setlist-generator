"use client";

import { useEffect } from "react";

const ARCHIVE_SCROLL_ROOT_CLASS = "archive-scroll-root";

export function ArchiveScrollRoot() {
  useEffect(() => {
    document.documentElement.classList.add(ARCHIVE_SCROLL_ROOT_CLASS);
    document.body.classList.add(ARCHIVE_SCROLL_ROOT_CLASS);

    return () => {
      document.documentElement.classList.remove(ARCHIVE_SCROLL_ROOT_CLASS);
      document.body.classList.remove(ARCHIVE_SCROLL_ROOT_CLASS);
    };
  }, []);

  return null;
}
