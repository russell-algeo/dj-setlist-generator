import { redirect } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { requireSessionActor } from "@/lib/auth/session";
import { listUsers } from "@/lib/admin/users";

export default async function AdminPage() {
  const actor = await requireSessionActor("/dashboard/admin");

  if (!actor.isAdmin) {
    redirect("/dashboard");
  }

  const users = await listUsers();

  return (
    <AppShell
      title="User management"
      eyebrow="Admin"
      description="Manage allowlist and admin status for all signed-in users."
    >
      <section className="panel">
        <div className="list-toolbar">
          <h2>Users ({users.length})</h2>
        </div>
        {users.length > 0 ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>User</th>
                <th>Allowlisted</th>
                <th>Admin</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.userId}>
                  <td>
                    <div>{user.email}</div>
                    {user.displayName && <div className="muted">{user.displayName}</div>}
                  </td>
                  <td>
                    <form method="POST" action={`/api/admin/users/${user.userId}`}>
                      <input
                        type="hidden"
                        name="isAllowlisted"
                        value={user.isAllowlisted ? "false" : "true"}
                      />
                      <button type="submit" className="pill-link">
                        {user.isAllowlisted ? "Revoke" : "Allow"}
                      </button>
                    </form>
                  </td>
                  <td>
                    {user.userId === actor.userId ? (
                      <span className="muted">You</span>
                    ) : (
                      <form method="POST" action={`/api/admin/users/${user.userId}`}>
                        <input
                          type="hidden"
                          name="isAdmin"
                          value={user.isAdmin ? "false" : "true"}
                        />
                        <button type="submit" className="pill-link">
                          {user.isAdmin ? "Demote" : "Promote"}
                        </button>
                      </form>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty-state">No users have signed in yet.</div>
        )}
      </section>
    </AppShell>
  );
}
