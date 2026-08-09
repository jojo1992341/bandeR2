"""Enable and force tenant RLS for all studio-owned tables (CDC §9.6)."""
from alembic import op
revision='b9c0d1e2f3a4'
down_revision='a8b9c0d1e2f3'
branch_labels=None
depends_on=None

# Tables expose studio_id directly. FORCE also protects table owners; the
# application role must not be a PostgreSQL superuser or BYPASSRLS role.
TABLES = ('projects','studio_memberships','studio_invitations',
          'audit_logs','security_alerts','api_keys','webhook_endpoints',
          'sso_configurations','typographic_profiles','user_preferences',
          'project_folders','project_tags','studio_teams','team_members',
          'project_assignments')

def upgrade():
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(f'''CREATE POLICY "{table}_tenant_isolation" ON "{table}"
            USING (studio_id = NULLIF(current_setting('app.current_studio_id', true), '')::uuid)
            WITH CHECK (studio_id = NULLIF(current_setting('app.current_studio_id', true), '')::uuid)''')

def downgrade():
    for table in reversed(TABLES):
        op.execute(f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
