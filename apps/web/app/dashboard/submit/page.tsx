import { AppShell } from "@/components/app-shell";
import { requireSessionActor } from "@/lib/auth/session";

import { DashboardSubmitForms } from "./dashboard-submit-forms";

export default async function DashboardSubmitPage() {
  const actor = await requireSessionActor("/dashboard/submit");

  return (
    <AppShell
      title="Submit work"
      eyebrow="Operator actions"
      description="Queue artist discovery or curated artist batches. Every submitted set now stays attached to an artist page so archive navigation remains native."
    >
      {!actor.isAllowlisted ? (
        <section className="panel">
          <h2>Allowlist required</h2>
          <p>Your account is authenticated but cannot submit jobs until an admin promotes it.</p>
        </section>
      ) : (
        <DashboardSubmitForms
          curatedHelperText="Select an existing artist to add additional sets to their existing page"
          discoveryHelperText={'If the artist you are looking for has already been submitted, use "Curated Artist" mode to add new sets to their existing page.'}
        />
      )}
    </AppShell>
  );
}
