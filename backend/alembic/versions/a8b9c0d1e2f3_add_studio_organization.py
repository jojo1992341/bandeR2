"""Add studio-scoped preferences and organisation."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='a8b9c0d1e2f3'
down_revision='z7a8b9c0d1e2'
branch_labels=None
depends_on=None

def upgrade():
    u=sa.UUID()
    def table(name, cols, constraints=()):
        op.create_table(name, sa.Column('id',u,primary_key=True), *cols, *constraints)
        op.create_index('ix_'+name+'_studio_id',name,['studio_id'])
    studio=sa.ForeignKey('studios.id',ondelete='CASCADE'); user=sa.ForeignKey('users.id',ondelete='CASCADE')
    table('user_preferences',[sa.Column('studio_id',u,nullable=False),sa.Column('user_id',u,nullable=False),sa.Column('theme',sa.String(30),server_default='system',nullable=False),sa.Column('language',sa.String(10),server_default='fr',nullable=False),sa.Column('shortcuts',sa.JSON(),server_default='{}',nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.text('now()')),sa.ForeignKeyConstraint(['studio_id'],['studios.id'],ondelete='CASCADE'),sa.ForeignKeyConstraint(['user_id'],['users.id'],ondelete='CASCADE')],[sa.UniqueConstraint('studio_id','user_id',name='uq_user_preferences_studio_user')])
    table('project_folders',[sa.Column('studio_id',u,nullable=False),sa.Column('name',sa.String(255),nullable=False),sa.Column('parent_id',u),sa.ForeignKeyConstraint(['studio_id'],['studios.id'],ondelete='CASCADE'),sa.ForeignKeyConstraint(['parent_id'],['project_folders.id'],ondelete='CASCADE')])
    table('project_tags',[sa.Column('studio_id',u,nullable=False),sa.Column('name',sa.String(100),nullable=False),sa.Column('color',sa.String(20)),sa.ForeignKeyConstraint(['studio_id'],['studios.id'],ondelete='CASCADE')],[sa.UniqueConstraint('studio_id','name',name='uq_project_tags_studio_name')])
    table('studio_teams',[sa.Column('studio_id',u,nullable=False),sa.Column('name',sa.String(255),nullable=False),sa.Column('description',sa.Text()),sa.ForeignKeyConstraint(['studio_id'],['studios.id'],ondelete='CASCADE')])
    table('team_members',[sa.Column('studio_id',u,nullable=False),sa.Column('team_id',u,nullable=False),sa.Column('user_id',u,nullable=False),sa.ForeignKeyConstraint(['studio_id'],['studios.id'],ondelete='CASCADE'),sa.ForeignKeyConstraint(['team_id'],['studio_teams.id'],ondelete='CASCADE'),sa.ForeignKeyConstraint(['user_id'],['users.id'],ondelete='CASCADE')],[sa.UniqueConstraint('team_id','user_id',name='uq_team_members_team_user')])
    table('project_assignments',[sa.Column('studio_id',u,nullable=False),sa.Column('project_id',u,nullable=False),sa.Column('assignee_user_id',u),sa.Column('assignee_team_id',u),sa.Column('role',sa.String(80),server_default='contributeur',nullable=False),sa.ForeignKeyConstraint(['studio_id'],['studios.id'],ondelete='CASCADE'),sa.ForeignKeyConstraint(['project_id'],['projects.id'],ondelete='CASCADE'),sa.ForeignKeyConstraint(['assignee_user_id'],['users.id'],ondelete='CASCADE'),sa.ForeignKeyConstraint(['assignee_team_id'],['studio_teams.id'],ondelete='CASCADE')])

def downgrade():
    for n in ('project_assignments','team_members','studio_teams','project_tags','project_folders','user_preferences'): op.drop_table(n)
