"""Create the nine Phase 2B laboratory master/setup tables.

Revision ID: 20260914_02
Revises: 20260914_01
"""

from alembic import op
import sqlalchemy as sa

revision = "20260914_02"
down_revision = "20260914_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('lab_department',
        sa.Column('department_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('department_code', sa.String(length=30), nullable=False),
        sa.Column('department_name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.PrimaryKeyConstraint('department_id', name=op.f('pk_lab_department')),
        sa.UniqueConstraint('department_code', name=op.f('uq_lab_department_department_code')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_table('sample_type',
        sa.Column('sample_type_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('sample_name', sa.String(length=80), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.PrimaryKeyConstraint('sample_type_id', name=op.f('pk_sample_type')),
        sa.UniqueConstraint('sample_name', name=op.f('uq_sample_type_sample_name')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_table('test_catalog',
        sa.Column('test_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('test_code', sa.String(length=30), nullable=False),
        sa.Column('test_name', sa.String(length=150), nullable=False),
        sa.Column('department_id', sa.BigInteger(), nullable=False),
        sa.Column('default_unit', sa.String(length=50), nullable=True),
        sa.Column('result_type', sa.Enum('NUMERIC', 'TEXT', 'POS_NEG', name='test_result_type'), nullable=False),
        sa.Column('methodology', sa.String(length=150), nullable=True),
        sa.Column('default_sort_order', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.ForeignKeyConstraint(['department_id'], ['lab_department.department_id'], name=op.f('fk_test_catalog_department_id_lab_department')),
        sa.PrimaryKeyConstraint('test_id', name=op.f('pk_test_catalog')),
        sa.UniqueConstraint('test_code', name=op.f('uq_test_catalog_test_code')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_test_catalog_department_id'), 'test_catalog', ['department_id'], unique=False)
    op.create_table('test_sample_type',
        sa.Column('test_sample_type_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('test_id', sa.BigInteger(), nullable=False),
        sa.Column('sample_type_id', sa.BigInteger(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['sample_type_id'], ['sample_type.sample_type_id'], name=op.f('fk_test_sample_type_sample_type_id_sample_type')),
        sa.ForeignKeyConstraint(['test_id'], ['test_catalog.test_id'], name=op.f('fk_test_sample_type_test_id_test_catalog')),
        sa.PrimaryKeyConstraint('test_sample_type_id', name=op.f('pk_test_sample_type')),
        sa.UniqueConstraint('test_id', 'sample_type_id', name=op.f('uq_test_sample_type_test_id_sample_type_id')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_test_sample_type_sample_type_id'), 'test_sample_type', ['sample_type_id'], unique=False)
    op.create_table('test_panel',
        sa.Column('panel_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('panel_code', sa.String(length=30), nullable=False),
        sa.Column('panel_name', sa.String(length=120), nullable=False),
        sa.Column('department_id', sa.BigInteger(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.ForeignKeyConstraint(['department_id'], ['lab_department.department_id'], name=op.f('fk_test_panel_department_id_lab_department')),
        sa.PrimaryKeyConstraint('panel_id', name=op.f('pk_test_panel')),
        sa.UniqueConstraint('panel_code', name=op.f('uq_test_panel_panel_code')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_test_panel_department_id'), 'test_panel', ['department_id'], unique=False)
    # Unique section/panel key supports the same-panel FK without new columns.
    op.create_table('panel_section',
        sa.Column('section_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('panel_id', sa.BigInteger(), nullable=False),
        sa.Column('section_name', sa.String(length=120), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.ForeignKeyConstraint(['panel_id'], ['test_panel.panel_id'], name=op.f('fk_panel_section_panel_id_test_panel')),
        sa.PrimaryKeyConstraint('section_id', name=op.f('pk_panel_section')),
        sa.UniqueConstraint('section_id', 'panel_id', name=op.f('uq_panel_section_section_id_panel_id')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_panel_section_panel_id'), 'panel_section', ['panel_id'], unique=False)
    op.create_table('panel_test',
        sa.Column('panel_test_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('panel_id', sa.BigInteger(), nullable=False),
        sa.Column('section_id', sa.BigInteger(), nullable=True),
        sa.Column('test_id', sa.BigInteger(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('is_required', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['panel_id'], ['test_panel.panel_id'], name=op.f('fk_panel_test_panel_id_test_panel')),
        sa.ForeignKeyConstraint(['section_id', 'panel_id'], ['panel_section.section_id', 'panel_section.panel_id'], name='fk_panel_test_section_id_panel_id_panel_section'),
        sa.ForeignKeyConstraint(['section_id'], ['panel_section.section_id'], name=op.f('fk_panel_test_section_id_panel_section')),
        sa.ForeignKeyConstraint(['test_id'], ['test_catalog.test_id'], name=op.f('fk_panel_test_test_id_test_catalog')),
        sa.PrimaryKeyConstraint('panel_test_id', name=op.f('pk_panel_test')),
        sa.UniqueConstraint('panel_id', 'test_id', name=op.f('uq_panel_test_panel_id_test_id')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index('ix_panel_test_section_id_panel_id', 'panel_test', ['section_id', 'panel_id'], unique=False)
    op.create_index(op.f('ix_panel_test_test_id'), 'panel_test', ['test_id'], unique=False)
    op.create_table('reference_range',
        sa.Column('range_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('test_id', sa.BigInteger(), nullable=False),
        sa.Column('sex', sa.Enum('M', 'F', 'ANY', name='reference_range_sex'), nullable=False),
        sa.Column('age_min', sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column('age_max', sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column('normal_low', sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column('normal_high', sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column('critical_low', sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column('critical_high', sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column('qualitative_normal', sa.String(length=80), nullable=True),
        sa.Column('unit', sa.String(length=50), nullable=True),
        sa.Column('effective_from', sa.Date(), nullable=True),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.ForeignKeyConstraint(['test_id'], ['test_catalog.test_id'], name=op.f('fk_reference_range_test_id_test_catalog')),
        sa.PrimaryKeyConstraint('range_id', name=op.f('pk_reference_range')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index(op.f('ix_reference_range_test_id'), 'reference_range', ['test_id'], unique=False)
    op.create_table('test_interpretation_rule',
        sa.Column('rule_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('test_id', sa.BigInteger(), nullable=False),
        sa.Column('flag', sa.Enum('NORMAL', 'LOW', 'HIGH', 'CRITICAL_LOW', 'CRITICAL_HIGH', 'ABNORMAL', name='interpretation_flag'), nullable=False),
        sa.Column('interpretation_text', sa.Text(), nullable=True),
        sa.Column('possible_causes', sa.Text(), nullable=True),
        sa.Column('recommendation', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.ForeignKeyConstraint(['test_id'], ['test_catalog.test_id'], name=op.f('fk_test_interpretation_rule_test_id_test_catalog')),
        sa.PrimaryKeyConstraint('rule_id', name=op.f('pk_test_interpretation_rule')),
        sa.UniqueConstraint('test_id', 'flag', name=op.f('uq_test_interpretation_rule_test_id_flag')),
        mysql_charset='utf8mb4',
        mysql_engine='InnoDB'
    )


def downgrade() -> None:
    # Drop dependent tables first; their FK-supporting indexes go with them.
    op.drop_table('test_interpretation_rule')
    op.drop_table('reference_range')
    op.drop_table('panel_test')
    op.drop_table('panel_section')
    op.drop_table('test_panel')
    op.drop_table('test_sample_type')
    op.drop_table('test_catalog')
    op.drop_table('sample_type')
    op.drop_table('lab_department')
