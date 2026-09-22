"""Initial schema: identity, family, content, planning, progress, audit/outbox, and Row-Level Security.

Revision ID: 0001
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UP = """
CREATE SCHEMA IF NOT EXISTS content;

-- identity ------------------------------------------------------------------------------------------------
CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL,
  password_hash text NOT NULL,
  full_name text NOT NULL,
  platform_role text CHECK (platform_role IN ('content_admin', 'super_admin')),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled', 'deleted')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_email_lower_uq ON users (lower(email));

CREATE TABLE refresh_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash text NOT NULL UNIQUE,
  chain_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  replaced_by uuid
);
CREATE INDEX refresh_tokens_user_idx ON refresh_tokens (user_id);
CREATE INDEX refresh_tokens_chain_idx ON refresh_tokens (chain_id);

CREATE TABLE families (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  timezone text NOT NULL DEFAULT 'Asia/Kolkata',
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  version integer NOT NULL DEFAULT 1
);

CREATE TABLE family_memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('owner', 'guardian', 'educator')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (family_id, user_id)
);
CREATE INDEX family_memberships_user_idx ON family_memberships (user_id);

CREATE TABLE guardian_verifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  family_id uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  method text NOT NULL DEFAULT 'otp_declaration',
  phone_last4 text,
  otp_hash text,
  otp_expires_at timestamptz,
  attempts integer NOT NULL DEFAULT 0,
  verified_at timestamptz,
  declaration_notice_version text,
  declared_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX guardian_verifications_family_idx ON guardian_verifications (family_id, user_id);

CREATE TABLE consents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id),
  purpose text NOT NULL CHECK (purpose IN ('core_service', 'media_capture', 'ai_personalization', 'product_analytics')),
  granted boolean NOT NULL,
  notice_version text NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX consents_family_idx ON consents (family_id, purpose, recorded_at DESC);

CREATE TABLE children (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  display_name text NOT NULL,
  birth_year integer CHECK (birth_year BETWEEN 2000 AND 2100),
  level_code text,
  avatar text NOT NULL DEFAULT 'star',
  interests text[] NOT NULL DEFAULT '{}',
  goals text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  version integer NOT NULL DEFAULT 1
);
CREATE INDEX children_family_idx ON children (family_id) WHERE deleted_at IS NULL;

CREATE TABLE parent_pins (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  pin_hash text NOT NULL,
  failed_attempts integer NOT NULL DEFAULT 0,
  locked_until timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE child_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  child_id uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
  family_id uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  device_id text NOT NULL,
  issued_by uuid NOT NULL REFERENCES users(id),
  issued_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz
);
CREATE INDEX child_sessions_child_idx ON child_sessions (child_id);

-- content (curriculum + activities as JSONB) -----------------------------------------------------------------
CREATE TABLE content.levels (
  code text PRIMARY KEY,
  name text NOT NULL,
  indicative_age text,
  description text,
  sort_order integer NOT NULL
);
CREATE TABLE content.subjects (
  code text PRIMARY KEY,
  name text NOT NULL,
  display_order integer NOT NULL,
  scope text
);
CREATE TABLE content.interests (
  code text PRIMARY KEY,
  name text NOT NULL
);
CREATE TABLE content.skills (
  code text PRIMARY KEY,
  subject_code text NOT NULL REFERENCES content.subjects(code),
  level_code text NOT NULL REFERENCES content.levels(code),
  name text NOT NULL,
  typical_evidence text[] NOT NULL DEFAULT '{}'
);
CREATE INDEX skills_subject_level_idx ON content.skills (subject_code, level_code);
CREATE TABLE content.skill_prerequisites (
  skill_code text NOT NULL REFERENCES content.skills(code) ON DELETE CASCADE,
  prerequisite_code text NOT NULL REFERENCES content.skills(code) ON DELETE CASCADE,
  PRIMARY KEY (skill_code, prerequisite_code),
  CHECK (skill_code <> prerequisite_code)
);
CREATE TABLE content.activities (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE,
  title text NOT NULL,
  summary text,
  subject_code text NOT NULL REFERENCES content.subjects(code),
  level_from text NOT NULL REFERENCES content.levels(code),
  level_to text NOT NULL REFERENCES content.levels(code),
  duration_min integer NOT NULL CHECK (duration_min > 0),
  materials text[] NOT NULL DEFAULT '{}',
  interest_tags text[] NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'in_review', 'published', 'archived')),
  version integer NOT NULL DEFAULT 1,
  definition jsonb NOT NULL,
  bundle_version text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
CREATE INDEX activities_status_subject_idx ON content.activities (status, subject_code);
CREATE INDEX activities_search_idx ON content.activities USING gin (to_tsvector('simple', title || ' ' || coalesce(summary, '')));
CREATE TABLE content.activity_versions (
  activity_id uuid NOT NULL REFERENCES content.activities(id) ON DELETE CASCADE,
  version integer NOT NULL,
  definition jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (activity_id, version)
);
CREATE TABLE content.activity_skills (
  activity_id uuid NOT NULL REFERENCES content.activities(id) ON DELETE CASCADE,
  skill_code text NOT NULL REFERENCES content.skills(code),
  PRIMARY KEY (activity_id, skill_code)
);

-- planning, sessions, progress ---------------------------------------------------------------------------------
CREATE TABLE plans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  child_id uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
  week_start date NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1,
  UNIQUE (child_id, week_start)
);
CREATE TABLE plan_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  child_id uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
  plan_id uuid NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  activity_id uuid NOT NULL REFERENCES content.activities(id),
  scheduled_date date NOT NULL,
  position integer NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'in_progress', 'completed', 'skipped')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1
);
CREATE INDEX plan_items_child_date_idx ON plan_items (child_id, scheduled_date);

CREATE TABLE activity_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  child_id uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
  activity_id uuid NOT NULL REFERENCES content.activities(id),
  activity_version integer NOT NULL,
  plan_item_id uuid REFERENCES plan_items(id) ON DELETE SET NULL,
  client_op_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'submitted')),
  started_at timestamptz NOT NULL DEFAULT now(),
  submitted_at timestamptz,
  duration_sec integer NOT NULL DEFAULT 0,
  hints_used integer NOT NULL DEFAULT 0,
  parent_assist boolean NOT NULL DEFAULT false,
  answers jsonb NOT NULL DEFAULT '{}',
  result jsonb,
  version integer NOT NULL DEFAULT 1,
  UNIQUE (family_id, client_op_id)
);
CREATE INDEX activity_sessions_child_idx ON activity_sessions (child_id, submitted_at);

CREATE TABLE skill_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  child_id uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
  skill_code text NOT NULL REFERENCES content.skills(code),
  session_id uuid REFERENCES activity_sessions(id) ON DELETE SET NULL,
  step_id text,
  source text NOT NULL CHECK (source IN ('activity', 'observation', 'assessment', 'baseline')),
  value double precision NOT NULL CHECK (value BETWEEN 0 AND 1),
  base_weight double precision NOT NULL,
  independence text NOT NULL CHECK (independence IN ('independent', 'prompted', 'assisted')),
  weight double precision NOT NULL,
  note text,
  occurred_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX skill_evidence_child_skill_idx ON skill_evidence (child_id, skill_code, occurred_at, created_at);
CREATE UNIQUE INDEX skill_evidence_session_step_uq ON skill_evidence (session_id, step_id, skill_code) WHERE session_id IS NOT NULL;

CREATE TABLE skill_mastery (
  child_id uuid NOT NULL REFERENCES children(id) ON DELETE CASCADE,
  skill_code text NOT NULL REFERENCES content.skills(code),
  family_id uuid NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  score double precision NOT NULL,
  confidence double precision NOT NULL,
  status text NOT NULL CHECK (status IN ('not_started', 'emerging', 'developing', 'secure')),
  evidence_count integer NOT NULL,
  distinct_days integer NOT NULL,
  last_evidence_at timestamptz,
  first_developing_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (child_id, skill_code)
);

-- audit + outbox -------------------------------------------------------------------------------------------------
CREATE TABLE audit_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_user_id uuid,
  actor_child_id uuid,
  family_id uuid,
  action text NOT NULL,
  entity text,
  entity_id text,
  meta jsonb NOT NULL DEFAULT '{}',
  request_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_family_idx ON audit_log (family_id, created_at DESC);
CREATE TABLE outbox_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type text NOT NULL,
  aggregate_id text,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  attempts integer NOT NULL DEFAULT 0
);
CREATE INDEX outbox_unpublished_idx ON outbox_events (created_at) WHERE published_at IS NULL;

-- Row-Level Security (ADR-016) ----------------------------------------------------------------------------------
-- A row is visible when it belongs to the family carried by a child token (app.family_id) or to a family the
-- authenticated parent is a member of (app.user_id). The application sets both per transaction (app/db.py).
CREATE FUNCTION app_can_access_family(fid uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT fid = nullif(current_setting('app.family_id', true), '')::uuid
      OR EXISTS (
        SELECT 1 FROM family_memberships m
        WHERE m.family_id = fid AND m.user_id = nullif(current_setting('app.user_id', true), '')::uuid
      )
$$;
"""

RLS_TABLES = ["children", "consents", "plans", "plan_items", "activity_sessions", "skill_evidence", "skill_mastery"]

DOWN = """
DROP FUNCTION IF EXISTS app_can_access_family(uuid);
DROP TABLE IF EXISTS outbox_events, audit_log, skill_mastery, skill_evidence, activity_sessions, plan_items, plans CASCADE;
DROP TABLE IF EXISTS content.activity_skills, content.activity_versions, content.activities, content.skill_prerequisites, content.skills,
  content.interests, content.subjects, content.levels CASCADE;
DROP TABLE IF EXISTS child_sessions, parent_pins, children, consents, guardian_verifications, family_memberships,
  families, refresh_tokens, users CASCADE;
DROP SCHEMA IF EXISTS content CASCADE;
"""


def upgrade() -> None:
    op.execute(UP)
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY family_isolation ON {table} "
            f"USING (app_can_access_family(family_id)) WITH CHECK (app_can_access_family(family_id))"
        )


def downgrade() -> None:
    op.execute(DOWN)
