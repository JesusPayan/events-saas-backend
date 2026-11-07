"""merge inventory charge migration heads
Revision ID: bf22df0d8a9d
Revises: 29eafe22476c, 677189ce94ae
"""
from alembic import op
import sqlalchemy as sa

revision = 'bf22df0d8a9d'
down_revision = ('29eafe22476c', '677189ce94ae')
branch_labels = None
depends_on = None

def upgrade():
    pass

def downgrade():
    pass
