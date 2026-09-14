"""Create the twelve Phase 2A identity/facility and authentication/RBAC tables.

Revision ID: 20260914_01
Revises: None
"""

from alembic import op
import sqlalchemy as sa

revision = "20260914_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('facility_profile',
        sa.Column('facility_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('facility_name', sa.String(length=150), nullable=False),
        sa.Column('facility_type', sa.String(length=80), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('contact_number', sa.String(length=30), nullable=True),
        sa.Column('email', sa.String(length=254), nullable=True),
        sa.Column('website', sa.String(length=150), nullable=True),
        sa.Column('logo_path', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('facility_id', name=op.f('pk_facility_profile')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_table('patient',
        sa.Column('patient_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('patient_code', sa.String(length=20), nullable=False),
        sa.Column('first_name', sa.String(length=60), nullable=False),
        sa.Column('middle_name', sa.String(length=60), nullable=True),
        sa.Column('last_name', sa.String(length=60), nullable=False),
        sa.Column('suffix', sa.String(length=20), nullable=True),
        sa.Column('birth_date', sa.Date(), nullable=True),
        sa.Column('sex', sa.Enum('M', 'F', 'Other', name='patient_sex'), nullable=True),
        sa.Column('civil_status', sa.String(length=20), nullable=True),
        sa.Column('nationality', sa.String(length=60), nullable=True),
        sa.Column('contact_number', sa.String(length=30), nullable=True),
        sa.Column('email', sa.String(length=254), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('patient_id', name=op.f('pk_patient')),
        sa.UniqueConstraint('patient_code', name=op.f('uq_patient_patient_code')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index('ix_patient_last_name_first_name', 'patient', ['last_name', 'first_name'], unique=False)
    op.create_table('permission',
        sa.Column('permission_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('permission_code', sa.String(length=80), nullable=False),
        sa.Column('permission_name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('permission_id', name=op.f('pk_permission')),
        sa.UniqueConstraint('permission_code', name=op.f('uq_permission_permission_code')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_table('referring_facility',
        sa.Column('referring_facility_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('facility_name', sa.String(length=150), nullable=False),
        sa.Column('facility_type', sa.String(length=80), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('contact_number', sa.String(length=30), nullable=True),
        sa.PrimaryKeyConstraint('referring_facility_id', name=op.f('pk_referring_facility')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_table('role',
        sa.Column('role_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('role_code', sa.String(length=40), nullable=False),
        sa.Column('role_name', sa.String(length=80), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.PrimaryKeyConstraint('role_id', name=op.f('pk_role')),
        sa.UniqueConstraint('role_code', name=op.f('uq_role_role_code')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_table('staff',
        sa.Column('staff_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('staff_code', sa.String(length=20), nullable=False),
        sa.Column('first_name', sa.String(length=60), nullable=False),
        sa.Column('middle_name', sa.String(length=60), nullable=True),
        sa.Column('last_name', sa.String(length=60), nullable=False),
        sa.Column('suffix', sa.String(length=20), nullable=True),
        sa.Column('position_title', sa.String(length=100), nullable=True),
        sa.Column('license_number', sa.String(length=50), nullable=True),
        sa.Column('contact_number', sa.String(length=30), nullable=True),
        sa.Column('email', sa.String(length=254), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('staff_id', name=op.f('pk_staff')),
        sa.UniqueConstraint('staff_code', name=op.f('uq_staff_staff_code')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_table('user_account',
        sa.Column('user_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('username', sa.String(length=60), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('account_status', sa.Enum('ACTIVE', 'INACTIVE', 'LOCKED', name='account_status'), nullable=False),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('user_id', name=op.f('pk_user_account')),
        sa.UniqueConstraint('username', name=op.f('uq_user_account_username')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_table('patient_account_link',
        sa.Column('patient_id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['patient_id'], ['patient.patient_id'], name=op.f('fk_patient_account_link_patient_id_patient')),
        sa.ForeignKeyConstraint(['user_id'], ['user_account.user_id'], name=op.f('fk_patient_account_link_user_id_user_account')),
        sa.PrimaryKeyConstraint('patient_id', name=op.f('pk_patient_account_link')),
        sa.UniqueConstraint('user_id', name=op.f('uq_patient_account_link_user_id')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_table('requesting_physician',
        sa.Column('physician_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('first_name', sa.String(length=60), nullable=False),
        sa.Column('middle_name', sa.String(length=60), nullable=True),
        sa.Column('last_name', sa.String(length=60), nullable=False),
        sa.Column('suffix', sa.String(length=20), nullable=True),
        sa.Column('license_number', sa.String(length=50), nullable=True),
        sa.Column('specialization', sa.String(length=100), nullable=True),
        sa.Column('referring_facility_id', sa.BigInteger(), nullable=True),
        sa.Column('contact_number', sa.String(length=30), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.ForeignKeyConstraint(['referring_facility_id'], ['referring_facility.referring_facility_id'], name=op.f('fk_requesting_physician_referring_facility_id_referring_facility')),
        sa.PrimaryKeyConstraint('physician_id', name=op.f('pk_requesting_physician')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_requesting_physician_referring_facility_id'), 'requesting_physician', ['referring_facility_id'], unique=False)
    op.create_table('role_permission',
        sa.Column('role_permission_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('role_id', sa.BigInteger(), nullable=False),
        sa.Column('permission_id', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['permission_id'], ['permission.permission_id'], name=op.f('fk_role_permission_permission_id_permission')),
        sa.ForeignKeyConstraint(['role_id'], ['role.role_id'], name=op.f('fk_role_permission_role_id_role')),
        sa.PrimaryKeyConstraint('role_permission_id', name=op.f('pk_role_permission')),
        sa.UniqueConstraint('role_id', 'permission_id', name=op.f('uq_role_permission_role_id_permission_id')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_role_permission_permission_id'), 'role_permission', ['permission_id'], unique=False)
    op.create_table('staff_account_link',
        sa.Column('staff_id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['staff_id'], ['staff.staff_id'], name=op.f('fk_staff_account_link_staff_id_staff')),
        sa.ForeignKeyConstraint(['user_id'], ['user_account.user_id'], name=op.f('fk_staff_account_link_user_id_user_account')),
        sa.PrimaryKeyConstraint('staff_id', name=op.f('pk_staff_account_link')),
        sa.UniqueConstraint('user_id', name=op.f('uq_staff_account_link_user_id')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_table('user_role',
        sa.Column('user_role_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('role_id', sa.BigInteger(), nullable=False),
        sa.Column('assigned_at', sa.DateTime(), nullable=False),
        sa.Column('assigned_by', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['assigned_by'], ['user_account.user_id'], name=op.f('fk_user_role_assigned_by_user_account')),
        sa.ForeignKeyConstraint(['role_id'], ['role.role_id'], name=op.f('fk_user_role_role_id_role')),
        sa.ForeignKeyConstraint(['user_id'], ['user_account.user_id'], name=op.f('fk_user_role_user_id_user_account')),
        sa.PrimaryKeyConstraint('user_role_id', name=op.f('pk_user_role')),
        sa.UniqueConstraint('user_id', 'role_id', name=op.f('uq_user_role_user_id_role_id')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_user_role_assigned_by'), 'user_role', ['assigned_by'], unique=False)
    op.create_index(op.f('ix_user_role_role_id'), 'user_role', ['role_id'], unique=False)



def downgrade() -> None:
    # Table drops also remove indexes; FK-supporting indexes cannot be dropped first.
    op.drop_table('user_role')
    op.drop_table('staff_account_link')
    op.drop_table('role_permission')
    op.drop_table('requesting_physician')
    op.drop_table('patient_account_link')
    op.drop_table('user_account')
    op.drop_table('staff')
    op.drop_table('role')
    op.drop_table('referring_facility')
    op.drop_table('permission')
    op.drop_table('patient')
    op.drop_table('facility_profile')
