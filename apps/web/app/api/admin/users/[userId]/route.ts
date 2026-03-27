import { NextResponse } from "next/server";

import { assertAdmin, getSessionActor } from "@/lib/auth/session";
import { updateUserProfile } from "@/lib/admin/users";

type Params = {
  params: Promise<{ userId: string }>;
};

const parseUpdates = (body: Record<string, unknown>) => {
  const updates: { isAllowlisted?: boolean; isAdmin?: boolean } = {};
  if ("isAllowlisted" in body) updates.isAllowlisted = body.isAllowlisted === true || body.isAllowlisted === "true";
  if ("isAdmin" in body) updates.isAdmin = body.isAdmin === true || body.isAdmin === "true";
  return updates;
};

export async function PATCH(request: Request, { params }: Params) {
  const actor = await getSessionActor();
  const denial = assertAdmin(actor);
  if (denial) return denial;

  const { userId } = await params;
  const updated = await updateUserProfile(userId, parseUpdates(await request.json()));
  if (!updated) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  return NextResponse.json(updated);
}

// POST supports HTML form-based toggling with a redirect back to the admin page.
export async function POST(request: Request, { params }: Params) {
  const actor = await getSessionActor();
  const denial = assertAdmin(actor);
  if (denial) return denial;

  const { userId } = await params;
  const formData = await request.formData();
  const updates: Record<string, unknown> = {};
  if (formData.has("isAllowlisted")) updates.isAllowlisted = formData.get("isAllowlisted");
  if (formData.has("isAdmin")) updates.isAdmin = formData.get("isAdmin");

  const updated = await updateUserProfile(userId, parseUpdates(updates));
  if (!updated) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  return NextResponse.redirect(new URL("/dashboard/admin", request.url), { status: 303 });
}
