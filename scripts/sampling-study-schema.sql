-- Explicit opt-in schema only. NOT part of automatic application migrations.
-- No application runs, submissions, sets, playlists or Yoon metadata are written.
BEGIN;
CREATE TABLE ops.sampling_exclusive_grants_v1 (
  id uuid PRIMARY KEY,
  enabled boolean NOT NULL DEFAULT false,
  controller_terminal_receipt_sha256 text NOT NULL CHECK(controller_terminal_receipt_sha256 ~ '^[0-9a-f]{64}$'),
  reviewed_source_ref text NOT NULL CHECK(reviewed_source_ref ~ '^[0-9a-f]{40}$'),
  not_before timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  CHECK(expires_at > not_before AND expires_at <= not_before + interval '2 hours')
);
CREATE TABLE ops.sampling_studies_v1 (
  id uuid PRIMARY KEY,
  grant_id uuid NOT NULL REFERENCES ops.sampling_exclusive_grants_v1(id),
  manifest jsonb NOT NULL CHECK(jsonb_typeof(manifest)='object'),
  manifest_sha256 text NOT NULL CHECK(manifest_sha256 ~ '^[0-9a-f]{64}$'),
  reference_sha256 text NOT NULL CHECK(reference_sha256 ~ '^[0-9a-f]{64}$'),
  status text NOT NULL DEFAULT 'ready' CHECK(status IN ('ready','running','paused','completed','cancelled','uncertain')),
  owner text,
  used_owners jsonb NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(used_owners)='array'),
  requests integer NOT NULL DEFAULT 0 CHECK(requests BETWEEN 0 AND 720),
  request_limit integer NOT NULL CHECK(request_limit BETWEEN 1 AND 720),
  next_allowed_at double precision NOT NULL DEFAULT 0 CHECK(next_allowed_at>=0 AND next_allowed_at<'Infinity'::float8),
  throttle_streak integer NOT NULL DEFAULT 0 CHECK(throttle_streak>=0),
  cancelled boolean NOT NULL DEFAULT false,
  reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK(requests<=request_limit)
);
CREATE UNIQUE INDEX sampling_one_active_v1 ON ops.sampling_studies_v1 ((true)) WHERE status IN ('running','uncertain');
CREATE TABLE ops.sampling_attempts_v1 (
  ticket uuid PRIMARY KEY,
  study_id uuid NOT NULL REFERENCES ops.sampling_studies_v1(id),
  number integer NOT NULL CHECK(number BETWEEN 1 AND 720),
  window_id text NOT NULL,
  input_sha256 text NOT NULL CHECK(input_sha256 ~ '^[0-9a-f]{64}$'),
  owner text NOT NULL,
  outcome text NOT NULL DEFAULT 'reserved' CHECK(outcome IN ('reserved','matched','no_match','throttled','failed','unknown')),
  receipt jsonb,
  receipt_sha256 text,
  delay_seconds double precision NOT NULL DEFAULT 0 CHECK(delay_seconds>=0 AND delay_seconds<'Infinity'::float8),
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  UNIQUE(study_id,number)
);
CREATE UNIQUE INDEX sampling_one_inflight_v1 ON ops.sampling_attempts_v1(study_id) WHERE outcome IN ('reserved','unknown');
CREATE UNIQUE INDEX sampling_one_terminal_window_v1 ON ops.sampling_attempts_v1(study_id,window_id) WHERE outcome IN ('matched','no_match');
REVOKE ALL ON ops.sampling_exclusive_grants_v1,ops.sampling_studies_v1,ops.sampling_attempts_v1 FROM PUBLIC;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='set_list_worker') THEN
  REVOKE ALL ON ops.sampling_exclusive_grants_v1,ops.sampling_studies_v1,ops.sampling_attempts_v1 FROM set_list_worker;
  GRANT SELECT ON ops.sampling_exclusive_grants_v1,ops.sampling_studies_v1,ops.sampling_attempts_v1 TO set_list_worker;
  GRANT UPDATE(status,owner,used_owners,requests,next_allowed_at,throttle_streak,cancelled,reason,updated_at) ON ops.sampling_studies_v1 TO set_list_worker;
  GRANT INSERT ON ops.sampling_attempts_v1 TO set_list_worker;
  GRANT UPDATE(outcome,receipt,receipt_sha256,delay_seconds,finished_at) ON ops.sampling_attempts_v1 TO set_list_worker;
 END IF;
END $$;
COMMIT;
