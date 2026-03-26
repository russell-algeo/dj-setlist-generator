import Link from "next/link";

export const AppShell = ({
  title,
  eyebrow,
  description,
  children,
}: {
  title: string;
  eyebrow?: string;
  description?: string;
  children: React.ReactNode;
}) => (
  <main className="app-shell">
    <header className="app-shell__hero">
      <div>
        {eyebrow ? <p className="app-shell__eyebrow">{eyebrow}</p> : null}
        <h1>{title}</h1>
        {description ? <p className="app-shell__description">{description}</p> : null}
      </div>
      <nav className="app-shell__nav">
        <Link href="/">Legacy archive</Link>
        <Link href="/artists">Artists</Link>
        <Link href="/sets">Sets</Link>
        <Link href="/dashboard">Dashboard</Link>
      </nav>
    </header>
    {children}
  </main>
);
