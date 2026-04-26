import Link from "next/link";
import { redirect } from "next/navigation";
import type { CSSProperties } from "react";

import {
  OperatorFrame,
  OperatorMetricCard,
  OperatorPageHeader,
  operatorUiStyles,
} from "@/components/operator/operator-ui";
import { requireSessionActor } from "@/lib/auth/session";
import { formatTimestamp } from "@/lib/format";
import {
  listAllSubmissionsWithUser,
  listUsers,
  type SubmissionWithUserRow,
  type UserRow,
} from "@/lib/admin/users";

import { StatusPill } from "../submissions/status-pill";

type AdminPageProps = {
  searchParams: Promise<{ tab?: string }>;
};

const MODE_LABEL: Record<string, string> = {
  artist: "Artist Discovery",
  curated_artist: "Curated Artist",
  url: "Single Set URL",
};

const userColumns = {
  "--operator-columns": "minmax(220px, 2fr) 120px 120px 110px 90px",
  "--operator-min-width": "740px",
} as CSSProperties;

const activityColumns = {
  "--operator-columns": "minmax(220px, 1.5fr) minmax(180px, 1fr) 140px 180px 120px",
  "--operator-min-width": "900px",
} as CSSProperties;

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

  const totalAdmins = users.filter((user) => user.isAdmin).length;
  const headerNavLinks = [
    { href: "/submissions", label: "My Submissions" },
    { href: "/admin", label: "Admin Panel" },
  ];

  return (
    <OperatorFrame
      activeNavHref="/admin"
      backHref="/"
      backLabel="← Archive"
      headerNavLinks={headerNavLinks}
      width="wide"
    >
      <OperatorPageHeader
        eyebrow="Operator admin"
        meta={
          <>
            <span>
              <strong>Signed in as</strong> {actor.displayName ?? actor.email}
            </span>
            <span>
              <strong>Role</strong> Admin
            </span>
          </>
        }
        subtitle="Manage users and audit submission activity from the same dark operator surface."
        titleFont="sans"
        titleSize="display"
        title="Admin Panel"
      />

      <div className={operatorUiStyles.stack}>
        <section className={operatorUiStyles.metricGrid}>
          <OperatorMetricCard label="Total Users" value={users.length} />
          <OperatorMetricCard label="Admins" value={totalAdmins} />
          <OperatorMetricCard label="Total Submissions" value={allSubmissions.length} />
          <OperatorMetricCard label="Sets Processed" value="—" />
        </section>

        <div className={operatorUiStyles.tabRow}>
          <Link
            className={`${operatorUiStyles.tabLink} ${tab === "users" ? operatorUiStyles.tabLinkActive : ""}`}
            href="/admin?tab=users"
          >
            Users
          </Link>
          <Link
            className={`${operatorUiStyles.tabLink} ${tab === "activity" ? operatorUiStyles.tabLinkActive : ""}`}
            href="/admin?tab=activity"
          >
            Activity
          </Link>
        </div>

        {tab === "users" ? (
          <section className={operatorUiStyles.panel}>
            <div className={operatorUiStyles.panelBody}>
              <div className={operatorUiStyles.label}>User Access</div>
              <div className={operatorUiStyles.tableScroller}>
                <div className={operatorUiStyles.tableGrid} style={userColumns}>
                  <div className={operatorUiStyles.tableHeaderRow} style={userColumns}>
                    <span>User</span>
                    <span>Joined</span>
                    <span>Submissions</span>
                    <span>Admin</span>
                    <span>Spotify</span>
                  </div>

                  {users.map((user) => {
                    const userSubCount = allSubmissions.filter(
                      (submission) => submission.userEmail === user.email,
                    ).length;
                    const isSelf = user.userId === actor.userId;

                    return (
                      <div className={operatorUiStyles.tableRow} key={user.userId} style={userColumns}>
                        <div>
                          <div className={operatorUiStyles.cellTitle}>
                            {user.displayName ?? user.email}
                            {isSelf ? (
                              <span className={operatorUiStyles.cellMeta}> (you)</span>
                            ) : null}
                          </div>
                          <div className={operatorUiStyles.cellMeta}>{user.email}</div>
                        </div>
                        <span className={operatorUiStyles.muted}>
                          {user.createdAt
                            ? new Date(user.createdAt).toLocaleDateString("en-US", {
                                month: "short",
                                year: "numeric",
                              })
                            : "—"}
                        </span>
                        <span className={operatorUiStyles.muted}>{userSubCount}</span>
                        <div>
                          <form action={`/api/admin/users/${user.userId}`} method="POST">
                            <input name="isAdmin" type="hidden" value={user.isAdmin ? "false" : "true"} />
                            <button
                              className={`${operatorUiStyles.button} ${user.isAdmin ? operatorUiStyles.buttonSuccess : operatorUiStyles.buttonGhost}`}
                              disabled={isSelf}
                              type="submit"
                            >
                              {user.isAdmin ? "On" : "Off"}
                            </button>
                          </form>
                        </div>
                        <span className={operatorUiStyles.dim}>—</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </section>
        ) : (
          <section className={operatorUiStyles.panel}>
            <div className={operatorUiStyles.panelBody}>
              <div className={operatorUiStyles.label}>Submission Activity</div>
              {allSubmissions.length > 0 ? (
                <div className={operatorUiStyles.tableScroller}>
                  <div className={operatorUiStyles.tableGrid} style={activityColumns}>
                    <div className={operatorUiStyles.tableHeaderRow} style={activityColumns}>
                      <span>User</span>
                      <span>Submission</span>
                      <span>Mode</span>
                      <span>Time</span>
                      <span className={operatorUiStyles.alignRight}>Status</span>
                    </div>

                    {allSubmissions.map((submission) => (
                      <Link
                        className={`${operatorUiStyles.tableRow} ${operatorUiStyles.tableRowInteractive}`}
                        href={`/submissions/${submission.id}`}
                        key={submission.id}
                        style={activityColumns}
                      >
                        <div>
                          <div className={operatorUiStyles.cellTitle}>
                            {submission.userDisplayName ?? submission.userEmail}
                          </div>
                          <div className={operatorUiStyles.cellMeta}>{submission.userEmail}</div>
                        </div>
                        <span className={operatorUiStyles.muted}>
                          {submission.artistName ?? submission.id.slice(0, 8)}
                        </span>
                        <span className={operatorUiStyles.muted}>
                          {MODE_LABEL[submission.mode] ?? submission.mode}
                        </span>
                        <span className={operatorUiStyles.dim}>
                          {formatTimestamp(submission.createdAt)}
                        </span>
                        <StatusPill align="right" status={submission.status} />
                      </Link>
                    ))}
                  </div>
                </div>
              ) : (
                <div className={operatorUiStyles.emptyState}>No submissions yet.</div>
              )}
            </div>
          </section>
        )}
      </div>
    </OperatorFrame>
  );
}
