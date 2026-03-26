import { DrizzleAdapter } from "@auth/drizzle-adapter";
import { and, eq } from "drizzle-orm";
import type { NextAuthOptions } from "next-auth";
import GoogleProvider from "next-auth/providers/google";

import { getDb } from "@/lib/db/client";
import { authTables, userProfiles, users } from "@/lib/db/schema";
import { env } from "@/lib/env";

const db = getDb();

const buildProviders = () => {
  if (!env.authGoogleId || !env.authGoogleSecret) {
    return [];
  }

  return [
    GoogleProvider({
      clientId: env.authGoogleId,
      clientSecret: env.authGoogleSecret,
    }),
  ];
};

export const bootstrapUserProfile = async (user: {
  id: string;
  email?: string | null;
  name?: string | null;
}) => {
  if (!user.email) {
    return null;
  }

  const normalizedEmail = user.email.toLowerCase();
  const isInitialAdmin = normalizedEmail === env.initialAdminEmail.toLowerCase();

  await db
    .insert(userProfiles)
    .values({
      userId: user.id,
      email: normalizedEmail,
      displayName: user.name ?? normalizedEmail,
      isAllowlisted: isInitialAdmin,
      isAdmin: isInitialAdmin,
    })
    .onConflictDoUpdate({
      target: userProfiles.userId,
      set: {
        email: normalizedEmail,
        displayName: user.name ?? normalizedEmail,
        isAllowlisted: isInitialAdmin ? true : userProfiles.isAllowlisted,
        isAdmin: isInitialAdmin ? true : userProfiles.isAdmin,
        updatedAt: new Date(),
      },
    });

  const [profile] = await db
    .select()
    .from(userProfiles)
    .where(and(eq(userProfiles.userId, user.id), eq(userProfiles.email, normalizedEmail)))
    .limit(1);

  return profile ?? null;
};

export const authOptions: NextAuthOptions = {
  adapter: DrizzleAdapter(db, authTables),
  secret: env.authSecret,
  session: {
    strategy: "database",
  },
  pages: {
    signIn: "/signin",
  },
  providers: buildProviders(),
  callbacks: {
    async session({ session, user }) {
      if (!session.user || !user?.id) {
        return session;
      }

      const profile = await bootstrapUserProfile({
        id: user.id,
        email: user.email,
        name: user.name,
      });

      session.user.id = user.id;
      session.user.email = user.email ?? session.user.email ?? null;
      session.user.name = user.name ?? session.user.name ?? null;
      session.user.isAllowlisted = profile?.isAllowlisted ?? false;
      session.user.isAdmin = profile?.isAdmin ?? false;

      return session;
    },
    async signIn({ user }) {
      if (!user.id || !user.email) {
        return false;
      }

      await bootstrapUserProfile({
        id: user.id,
        email: user.email,
        name: user.name,
      });

      return true;
    },
  },
  events: {
    async createUser({ user }) {
      if (!user.id) {
        return;
      }

      await db
        .update(users)
        .set({
          updatedAt: new Date(),
        })
        .where(eq(users.id, user.id));
    },
  },
};
