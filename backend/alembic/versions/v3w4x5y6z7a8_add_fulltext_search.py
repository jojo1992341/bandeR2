"""add full-text search indexes §16.1

Revision ID: v3w4x5y6z7a8
Revises: u2v3w4x5y6z7
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "v3w4x5y6z7a8"
down_revision = "u2v3w4x5y6z7"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # PostgreSQL full-text search avec GIN et français
    # Pour SQLite (tests), on ignore les erreurs (pas de GIN)
    conn = op.get_bind()
    dialect = conn.dialect.name if conn else "sqlite"
    if dialect == "postgresql":
        # Index pour Replica.text
        op.execute("""
            CREATE INDEX IF NOT EXISTS ix_replicas_text_tsvector
            ON replicas USING GIN (to_tsvector('french', text));
        """)
        # Index pour TranscriptSegment.text
        op.execute("""
            CREATE INDEX IF NOT EXISTS ix_transcript_segments_text_tsvector
            ON transcript_segments USING GIN (to_tsvector('french', text));
        """)
        # Index pour Word.text
        op.execute("""
            CREATE INDEX IF NOT EXISTS ix_transcript_words_text_tsvector
            ON transcript_words USING GIN (to_tsvector('french', text));
        """)
        # Optionnel : index pour Project.title
        op.execute("""
            CREATE INDEX IF NOT EXISTS ix_projects_title_tsvector
            ON projects USING GIN (to_tsvector('french', title));
        """)
    else:
        # SQLite : index LIKE classique (déjà index sur text via B-Tree si besoin)
        # On ajoute un index simple sur Replica.text pour accélérer les LIKE
        try:
            op.create_index(op.f("ix_replicas_text"), "replicas", ["text"], unique=False)
        except Exception:
            pass
        try:
            op.create_index(op.f("ix_transcript_segments_text"), "transcript_segments", ["text"], unique=False)
        except Exception:
            pass
        try:
            op.create_index(op.f("ix_transcript_words_text"), "transcript_words", ["text"], unique=False)
        except Exception:
            pass

def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name if conn else "sqlite"
    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_replicas_text_tsvector;")
        op.execute("DROP INDEX IF EXISTS ix_transcript_segments_text_tsvector;")
        op.execute("DROP INDEX IF EXISTS ix_transcript_words_text_tsvector;")
        op.execute("DROP INDEX IF EXISTS ix_projects_title_tsvector;")
    else:
        try:
            op.drop_index(op.f("ix_replicas_text"), table_name="replicas")
        except:
            pass
        try:
            op.drop_index(op.f("ix_transcript_segments_text"), table_name="transcript_segments")
        except:
            pass
        try:
            op.drop_index(op.f("ix_transcript_words_text"), table_name="transcript_words")
        except:
            pass
