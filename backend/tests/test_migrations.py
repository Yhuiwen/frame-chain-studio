from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config


def alembic_config(db_path: Path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config


def table_names(db_path: Path) -> set[str]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)
    return set(inspector.get_table_names())


def columns(db_path: Path, table_name: str) -> set[str]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)
    return {column["name"] for column in inspector.get_columns(table_name)}


def test_upgrade_empty_database_creates_phase_one_and_task_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"

    command.upgrade(alembic_config(db_path), "head")
    command.upgrade(alembic_config(db_path), "head")

    tables = table_names(db_path)
    assert {"project", "shot", "asset", "generationrequest", "generationtask", "taskstatechange"} <= tables
    assert "taskcommand" in tables
    assert "generationtaskresult" in tables
    assert "task_id" in columns(db_path, "tasklog")
    assert "result_urls_json" in columns(db_path, "generationtask")
    assert "cancel_requested_at" in columns(db_path, "generationtask")
    assert "last_retry_delay_seconds" in columns(db_path, "generationtask")
    assert "next_result_retry_at" in columns(db_path, "generationtask")
    assert "sha256" in columns(db_path, "asset")


def test_upgrade_phase_one_database_preserves_existing_rows_and_adds_defaults(tmp_path: Path) -> None:
    db_path = tmp_path / "phase-one.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE project (
                    name VARCHAR(160) NOT NULL,
                    description VARCHAR NOT NULL,
                    id INTEGER NOT NULL PRIMARY KEY,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE TABLE shot (
                    title VARCHAR(160) NOT NULL,
                    description VARCHAR NOT NULL,
                    duration_seconds FLOAT NOT NULL,
                    prompt VARCHAR NOT NULL,
                    negative_prompt VARCHAR NOT NULL,
                    id INTEGER NOT NULL PRIMARY KEY,
                    project_id INTEGER NOT NULL,
                    sort_order INTEGER NOT NULL,
                    status VARCHAR NOT NULL,
                    start_frame_asset_id INTEGER,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE TABLE asset (
                    id INTEGER NOT NULL PRIMARY KEY,
                    project_id INTEGER NOT NULL,
                    shot_id INTEGER,
                    type VARCHAR NOT NULL,
                    path VARCHAR NOT NULL,
                    mime_type VARCHAR NOT NULL,
                    source_asset_id INTEGER,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE TABLE generationrequest (
                    id INTEGER NOT NULL PRIMARY KEY,
                    project_id INTEGER NOT NULL,
                    shot_id INTEGER NOT NULL,
                    kind VARCHAR NOT NULL,
                    provider_name VARCHAR NOT NULL,
                    status VARCHAR NOT NULL,
                    prompt_snapshot VARCHAR NOT NULL,
                    negative_prompt_snapshot VARCHAR NOT NULL,
                    input_asset_ids VARCHAR NOT NULL,
                    output_asset_ids VARCHAR NOT NULL,
                    error_code VARCHAR,
                    error_message VARCHAR,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE TABLE tasklog (
                    id INTEGER NOT NULL PRIMARY KEY,
                    request_id INTEGER,
                    shot_id INTEGER,
                    level VARCHAR(16) NOT NULL,
                    message VARCHAR NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO project (id, name, description, created_at, updated_at)
                VALUES (1, 'Old Project', '', '2026-07-18 00:00:00', '2026-07-18 00:00:00')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO shot (
                    id, project_id, title, description, duration_seconds, prompt,
                    negative_prompt, sort_order, status, created_at, updated_at
                )
                VALUES (1, 1, 'Old Shot', '', 4.0, '', '', 0, 'DRAFT',
                        '2026-07-18 00:00:00', '2026-07-18 00:00:00')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO generationrequest (
                    id, project_id, shot_id, kind, provider_name, status,
                    prompt_snapshot, negative_prompt_snapshot, input_asset_ids,
                    output_asset_ids, created_at, updated_at
                )
                VALUES (1, 1, 1, 'KEYFRAME', 'mock', 'PENDING', '', '', '[]', '[]',
                        '2026-07-18 00:00:00', '2026-07-18 00:00:00')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO tasklog (id, request_id, shot_id, level, message, created_at)
                VALUES (1, 1, 1, 'INFO', 'old log', '2026-07-18 00:00:00')
                """
            )
        )

    command.upgrade(alembic_config(db_path), "head")

    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM project")).scalar_one() == 1
        assert connection.execute(sa.text("SELECT COUNT(*) FROM shot")).scalar_one() == 1
        assert connection.execute(sa.text("SELECT COUNT(*) FROM generationrequest")).scalar_one() == 1
        assert connection.execute(sa.text("SELECT COUNT(*) FROM tasklog")).scalar_one() == 1
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == "20260719_0007"
    assert "task_id" in columns(db_path, "tasklog")
    assert "result_urls_json" in columns(db_path, "generationtask")
    assert "job_deadline_at" in columns(db_path, "generationtask")
    assert "result_retry_count" in columns(db_path, "generationtask")
    assert "raw_result_urls_json" in columns(db_path, "generationtask")
    assert "taskcommand" in table_names(db_path)
    assert "generationtaskresult" in table_names(db_path)
    assert "sha256" in columns(db_path, "asset")
    assert "generationtask" in table_names(db_path)
    assert "image_provider_id" in columns(db_path, "project")
    assert "generation_mode" in columns(db_path, "generationrequest")
    assert "remote_progress" in columns(db_path, "generationtask")
    assert "workerheartbeat" in table_names(db_path)
    assert "projectrender" in table_names(db_path)
    assert "lock_version" in columns(db_path, "projectrender")


def test_reliability_hardening_migration_normalizes_duplicate_shot_sort_orders(tmp_path: Path) -> None:
    db_path = tmp_path / "duplicate-sort.db"
    config = alembic_config(db_path)
    command.upgrade(config, "20260718_0006")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO project (id, name, description, created_at, updated_at)
                VALUES (1, 'P', '', '2026-07-18 00:00:00', '2026-07-18 00:00:00')
                """
            )
        )
        for shot_id, title in [(1, "A"), (2, "B"), (3, "C")]:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO shot (
                        id, project_id, title, description, duration_seconds, prompt,
                        negative_prompt, sort_order, status, start_frame_asset_id,
                        created_at, updated_at
                    )
                    VALUES (:shot_id, 1, :title, '', 4.0, '', '', 0, 'DRAFT', NULL,
                            '2026-07-18 00:00:00', '2026-07-18 00:00:00')
                    """
                ),
                {"shot_id": shot_id, "title": title},
            )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        orders = connection.execute(
            sa.text("SELECT sort_order FROM shot WHERE project_id = 1 ORDER BY sort_order")
        ).scalars().all()
        assert orders == [0, 1, 2]
