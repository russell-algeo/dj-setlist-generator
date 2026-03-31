import Link from "next/link";
import { redirect } from "next/navigation";

import { requireSessionActor } from "@/lib/auth/session";
import { formatTimestamp } from "@/lib/format";
import { listAllSubmissionsWithUser, listUsers, type SubmissionWithUserRow, type UserRow } from "@/lib/admin/users";

type AdminPageProps = {
  searchParams: Promise<{ tab?: string }>;
};

const MODE_LABEL: Record<string, string> = {
  url: "Single Set URL",
  artist: "Artist Discovery",
  curated_artist: "Curated Artist",
};

const STATUS_COLOR: Record<string, string> = {
  queued: "#555",
  running: "#7a7a3a",
  partial: "#7a5a3a",
  completed: "#3a7a3a",
  failed: "#8a3a3a",
  cancelled: "#555",
};

export default async function AdminPage({ searchParams }: AdminPageProps) {
  const actor = await requireSessionActor("/admin");

  if (!actor.isAdmin) {
    redirect("/");
  }

  const { tab = "users" } = await searchParams;

  const [users, allSubmissions]: [UserRow[], SubmissionWithUserRow[]] = await Promise.all([
    listUsers(),
    listAllSubmissionsWithUser(),
  ]);

  const totalAdmins = users.filter((u) => u.isAdmin).length;

  return (
    <div style={{ minHeight: "100vh", background: "#0a0a0a", color: "#ccc", fontFamily: "monospace" }}>
      <div style={{ maxWidth: 1000, margin: "0 auto", padding: "40px 24px" }}>
        <div style={{ marginBottom: 20, fontSize: 10, color: "#444", letterSpacing: "0.06em" }}>
          <Link href="/" style={{ color: "#666" }}>← Archive</Link>
        </div>

        <h1 style={{ color: "#fff", fontSize: 14, letterSpacing: "0.1em", textTransform: "uppercase", margin: "0 0 4px" }}>Admin Panel</h1>
        <p style={{ color: "#444", fontSize: 10, margin: "0 0 24px" }}>Manage users and audit system activity</p>

        {/* Stats */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 28 }}>
          {[
            { value: users.length, label: "Total Users" },
            { value: totalAdmins, label: "Admins" },
            { value: allSubmissions.length, label: "Total Submissions" },
          ].map(({ value, label }) => (
            <div key={label} style={{ background: "#111", border: "1px solid #1c1c1c", borderRadius: 6, padding: "14px 16px" }}>
              <div style={{ color: "#ddd", fontSize: 20, marginBottom: 4 }}>{value}</div>
              <div style={{ color: "#444", fontSize: 9, letterSpacing: "0.12em", textTransform: "uppercase" }}>{label}</div>
            </div>
          ))}
          <div style={{ background: "#111", border: "1px solid #1c1c1c", borderRadius: 6, padding: "14px 16px" }}>
            <div style={{ color: "#444", fontSize: 9, letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 4 }}>Sets Processed</div>
            <div style={{ color: "#555", fontSize: 9 }}>—</div>
          </div>
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", borderBottom: "1px solid #1a1a1a", marginBottom: 20 }}>
          {["users", "activity"].map((t) => (
            <Link
              key={t}
              href={`/admin?tab=${t}`}
              style={{
                fontSize: 10,
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                padding: "8px 16px",
                color: tab === t ? "#ccc" : "#444",
                borderBottom: tab === t ? "1px solid #ccc" : "1px solid transparent",
                marginBottom: -1,
                textDecoration: "none",
              }}
            >
              {t === "users" ? "Users" : "Activity"}
            </Link>
          ))}
        </div>

        {tab === "users" && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 80px 80px 80px", gap: 12, padding: "0 0 8px", borderBottom: "1px solid #1a1a1a", fontSize: 9, color: "#444", letterSpacing: "0.1em", textTransform: "uppercase" }}>
              <span>User</span>
              <span>Joined</span>
              <span>Submissions</span>
              <span>Admin</span>
              <span>Spotify</span>
              <span>View As</span>
            </div>

            {users.map((user) => {
              const userSubCount = allSubmissions.filter((s) => s.userEmail === user.email).length;
              const isSelf = user.userId === actor.userId;

              return (
                <div key={user.userId} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 80px 80px 80px", gap: 12, padding: "10px 0", borderBottom: "1px solid #0f0f0f", alignItems: "center" }}>
                  <div>
                    <div style={{ color: "#ccc", fontSize: 11 }}>
                      {user.displayName ?? user.email}
                      {isSelf && <span style={{ color: "#333", fontSize: 9, marginLeft: 6, fontStyle: "italic" }}>(you)</span>}
                    </div>
                    <div style={{ color: "#444", fontSize: 9, marginTop: 2 }}>{user.email}</div>
                  </div>
                  <span style={{ color: "#555", fontSize: 10 }}>
                    {user.createdAt
                      ? new Date(user.createdAt).toLocaleDateString("en-US", { month: "short", year: "numeric" })
                      : "—"}
                  </span>
                  <span style={{ color: "#555", fontSize: 10 }}>{userSubCount}</span>

                  {/* Admin toggle */}
                  <form action={`/api/admin/users/${user.userId}`} method="POST">
                    <input type="hidden" name="isAdmin" value={user.isAdmin ? "false" : "true"} />
                    <button
                      disabled={isSelf}
                      style={{
                        fontSize: 9,
                        color: user.isAdmin ? "#3a7a3a" : "#555",
                        border: "1px solid",
                        borderColor: user.isAdmin ? "#1a3a1a" : "#2a2a2a",
                        borderRadius: 3,
                        padding: "3px 8px",
                        background: user.isAdmin ? "#0d1f0d" : "none",
                        cursor: isSelf ? "not-allowed" : "pointer",
                        opacity: isSelf ? 0.4 : 1,
                        letterSpacing: "0.06em",
                      }}
                      type="submit"
                    >
                      {user.isAdmin ? "On" : "Off"}
                    </button>
                  </form>

                  {/* Spotify indicator (read-only) */}
                  <span style={{ fontSize: 9, color: "#333", letterSpacing: "0.06em" }}>—</span>

                  {/* View As */}
                  {!isSelf ? (
                    <Link
                      href={`/artists?viewAs=${user.userId}`}
                      style={{ fontSize: 9, color: "#555", border: "1px solid #222", borderRadius: 3, padding: "3px 8px", letterSpacing: "0.08em", textDecoration: "none" }}
                    >
                      View As →
                    </Link>
                  ) : (
                    <span style={{ color: "#333", fontSize: 9 }}>—</span>
                  )}
                </div>
              );
            })}
          </>
        )}

        {tab === "activity" && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr 1fr 1fr 80px", gap: 12, padding: "0 0 8px", borderBottom: "1px solid #1a1a1a", fontSize: 9, color: "#444", letterSpacing: "0.1em", textTransform: "uppercase" }}>
              <span>User</span>
              <span>Submission</span>
              <span>Mode</span>
              <span>Time</span>
              <span style={{ textAlign: "right" }}>Status</span>
            </div>

            {allSubmissions.map((sub) => {
              const color = STATUS_COLOR[sub.status] ?? "#555";
              return (
                <Link
                  key={sub.id}
                  href={`/submissions/${sub.id}`}
                  style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr 1fr 1fr 80px", gap: 12, padding: "10px 0", borderBottom: "1px solid #0f0f0f", alignItems: "center", textDecoration: "none", color: "inherit" }}
                >
                  <span style={{ color: "#aaa", fontSize: 11 }}>{sub.userDisplayName ?? sub.userEmail}</span>
                  <span style={{ color: "#666", fontSize: 10 }}>{sub.artistName ?? sub.id.slice(0, 8)}</span>
                  <span style={{ color: "#555", fontSize: 10 }}>{MODE_LABEL[sub.mode] ?? sub.mode}</span>
                  <span style={{ color: "#444", fontSize: 10 }}>{formatTimestamp(sub.createdAt)}</span>
                  <span style={{ textAlign: "right", fontSize: 9, letterSpacing: "0.08em", padding: "2px 7px", borderRadius: 3, border: "1px solid", color, borderColor: color }}>
                    {sub.status}
                  </span>
                </Link>
              );
            })}

            {allSubmissions.length === 0 && (
              <div style={{ padding: "40px 0", color: "#444", fontSize: 11, textAlign: "center" }}>
                No submissions yet.
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
