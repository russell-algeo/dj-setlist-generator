import Link from "next/link";

type ViewingAsBannerProps = {
  email: string;
  userId: string;
};

export const ViewingAsBanner = ({ email, userId }: ViewingAsBannerProps) => (
  <div className="viewing-as-banner">
    <span>
      Viewing workspace as <strong>{email}</strong>
    </span>
    <div className="viewing-as-banner__nav">
      <Link className="pill-link" href={`/dashboard?viewAs=${userId}`}>
        Dashboard
      </Link>
      <Link className="pill-link" href={`/dashboard/jobs?viewAs=${userId}`}>
        Jobs
      </Link>
      <Link className="pill-link" href={`/artists?viewAs=${userId}`}>
        Artists
      </Link>
      <Link className="pill-link" href={`/sets?viewAs=${userId}`}>
        Sets
      </Link>
      <Link className="pill-link" href={`/dashboard/settings?viewAs=${userId}`}>
        Settings
      </Link>
      <Link className="pill-link" href={`/dashboard/tokens?viewAs=${userId}`}>
        Tokens
      </Link>
      <Link className="pill-link" href="/dashboard/admin">
        ← Back to Admin
      </Link>
    </div>
  </div>
);
