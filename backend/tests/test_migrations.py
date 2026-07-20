import json
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
import pytest
from sqlmodel import Session, select

from app.models.entities import Asset, AssetStatus, Shot
from app.services import studio


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
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == "20260720_0014"
        assert connection.execute(sa.text("SELECT COUNT(*) FROM providerprofile WHERE provider_key='toapis'")).scalar_one() == 1
        assert connection.execute(sa.text("SELECT COUNT(*) FROM providermodelprofile WHERE remote_model IN ('doubao-seedream-5-0', 'viduq3-pro')")).scalar_one() == 2
        for table in ("scriptdocument", "scriptblock", "storyboarddraft", "shotdraft", "shotdraftcharacter"):
            assert connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0
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
    assert "shotspec" in table_names(db_path)
    assert "character" in table_names(db_path)
    assert "structured_payload_json" in columns(db_path, "generationrequest")
    assert "compiler_version" in columns(db_path, "generationrequest")
    assert "scriptdocument" in table_names(db_path)
    assert "scriptblock" in table_names(db_path)
    assert "storyboarddraft" in table_names(db_path)
    assert "shotdraft" in table_names(db_path)
    assert "shotdraftcharacter" in table_names(db_path)
    assert "provider_key" in columns(db_path, "generationrequest")
    assert "provider_model_key" in columns(db_path, "generationrequest")
    assert "provider_capability_snapshot_json" in columns(db_path, "generationrequest")
    assert "pricing_snapshot_json" in columns(db_path, "generationrequest")
    assert "providerprofile" in table_names(db_path)
    assert "providermodelprofile" in table_names(db_path)
    assert "generationusagerecord" in table_names(db_path)
    assert "projectbudgetpolicy" in table_names(db_path)
    assert "providerverificationrun" in table_names(db_path)


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


def test_continuity_revision_migration_backfills_completed_shot_asset_pointers(tmp_path: Path) -> None:
    db_path = tmp_path / "continuity-backfill.db"
    config = alembic_config(db_path)
    command.upgrade(config, "20260719_0007")
    engine = sa.create_engine(f"sqlite:///{db_path}")

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO project (id, name, description, created_at, updated_at)
                VALUES (1, 'Migrated Project', '', '2026-07-19 00:00:00', '2026-07-19 00:00:00')
                """
            )
        )
        for shot_id, title, status, sort_order, start_frame_asset_id in [
            (1, "Complete", "COMPLETED", 0, None),
            (2, "Keyframe Only", "KEYFRAME_APPROVED", 1, 7),
            (3, "Draft", "DRAFT", 2, None),
        ]:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO shot (
                        id, project_id, title, description, duration_seconds, prompt,
                        negative_prompt, sort_order, status, start_frame_asset_id,
                        created_at, updated_at
                    )
                    VALUES (:id, 1, :title, '', 4.0, '', '', :sort_order, :status,
                            :start_frame_asset_id, '2026-07-19 00:00:00', '2026-07-19 00:00:00')
                    """
                ),
                {
                    "id": shot_id,
                    "title": title,
                    "status": status,
                    "sort_order": sort_order,
                    "start_frame_asset_id": start_frame_asset_id,
                },
            )
        for asset_id, shot_id, asset_type, source_asset_id, created_at in [
            (1, 1, "KEYFRAME", None, "2026-07-19 00:01:00"),
            (2, 1, "KEYFRAME", None, "2026-07-19 00:02:00"),
            (3, 1, "VIDEO", None, "2026-07-19 00:03:00"),
            (4, 1, "VIDEO", None, "2026-07-19 00:04:00"),
            (5, 1, "TAIL_FRAME", 4, "2026-07-19 00:05:00"),
            (6, 1, "TAIL_FRAME", 3, "2026-07-19 00:06:00"),
            (7, 2, "START_FRAME", 5, "2026-07-19 00:07:00"),
            (8, 2, "KEYFRAME", None, "2026-07-19 00:08:00"),
        ]:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO asset (
                        id, project_id, shot_id, type, path, mime_type, source_asset_id,
                        created_at, sha256
                    )
                    VALUES (
                        :id, 1, :shot_id, :type, :path, :mime_type, :source_asset_id,
                        :created_at, :sha256
                    )
                    """
                ),
                {
                    "id": asset_id,
                    "shot_id": shot_id,
                    "type": asset_type,
                    "path": f"asset-{asset_id}",
                    "mime_type": "video/mp4" if asset_type == "VIDEO" else "image/png",
                    "source_asset_id": source_asset_id,
                    "created_at": created_at,
                    "sha256": f"sha-{asset_id}",
                },
            )
        for request_id, shot_id, kind, status, input_ids, output_ids, updated_at in [
            (1, 1, "KEYFRAME", "FAILED", "[]", "[1]", "2026-07-19 00:01:30"),
            (2, 1, "KEYFRAME", "SUCCEEDED", "[]", "[2]", "2026-07-19 00:02:30"),
            (3, 1, "VIDEO", "FAILED", "[2]", "[3]", "2026-07-19 00:03:30"),
            (4, 1, "VIDEO", "SUCCEEDED", "[2]", "[4]", "2026-07-19 00:04:30"),
            (5, 2, "KEYFRAME", "SUCCEEDED", "[7]", "[8]", "2026-07-19 00:08:30"),
        ]:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO generationrequest (
                        id, project_id, shot_id, kind, provider_name, status,
                        prompt_snapshot, negative_prompt_snapshot, input_asset_ids,
                        output_asset_ids, created_at, updated_at
                    )
                    VALUES (:id, 1, :shot_id, :kind, 'mock', :status, '', '', :input_ids,
                            :output_ids, '2026-07-19 00:00:00', :updated_at)
                    """
                ),
                {
                    "id": request_id,
                    "shot_id": shot_id,
                    "kind": kind,
                    "status": status,
                    "input_ids": input_ids,
                    "output_ids": output_ids,
                    "updated_at": updated_at,
                },
            )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        completed = connection.execute(
            sa.text(
                """
                SELECT approved_keyframe_asset_id, approved_video_asset_id, locked_tail_frame_asset_id
                FROM shot
                WHERE id = 1
                """
            )
        ).one()
        assert tuple(completed) == (2, 4, 5)
        keyframe_only = connection.execute(
            sa.text(
                """
                SELECT approved_keyframe_asset_id, approved_video_asset_id, locked_tail_frame_asset_id,
                       start_frame_source_type
                FROM shot
                WHERE id = 2
                """
            )
        ).one()
        assert tuple(keyframe_only) == (8, None, None, "INHERITED")
        assert connection.execute(
            sa.text("SELECT status FROM asset WHERE id IN (2, 4, 5) ORDER BY id")
        ).scalars().all() == ["APPROVED", "APPROVED", "APPROVED"]
        assert connection.execute(
            sa.text("SELECT status FROM asset WHERE id IN (1, 3, 6) ORDER BY id")
        ).scalars().all() == ["ACTIVE", "ACTIVE", "ACTIVE"]
        assert connection.execute(sa.text("PRAGMA foreign_key_check")).all() == []
        assert connection.execute(sa.text("PRAGMA integrity_check")).scalar_one() == "ok"

    with Session(engine) as session:
        shot = session.get(Shot, 1)
        assert shot is not None
        assert studio.get_current_approved_video(session, shot) is not None
        assets = list(session.exec(select(Asset).where(Asset.project_id == 1)).all())
        completion = studio.project_completion([shot], assets)
        assert completion["can_render"] is True
        stale_failed_video = session.get(Asset, 3)
        assert stale_failed_video is not None
        assert stale_failed_video.status == AssetStatus.ACTIVE


def test_asset_revision_identity_migration_allows_same_sha_across_revisions(tmp_path: Path) -> None:
    db_path = tmp_path / "asset-identity.db"
    config = alembic_config(db_path)
    command.upgrade(config, "20260720_0008")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO project (id, name, description, created_at, updated_at)
                VALUES (1, 'P', '', '2026-07-20 00:00:00', '2026-07-20 00:00:00')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO shot (
                    id, project_id, title, description, duration_seconds, prompt,
                    negative_prompt, sort_order, status, start_frame_asset_id, spec_revision,
                    approved_keyframe_asset_id, approved_video_asset_id, locked_tail_frame_asset_id,
                    start_frame_source_type, created_at, updated_at
                )
                VALUES (1, 1, 'S', '', 4.0, '', '', 0, 'DRAFT', NULL, 1, NULL, NULL, NULL,
                        'NONE', '2026-07-20 00:00:00', '2026-07-20 00:00:00')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO asset (
                    id, project_id, shot_id, type, status, revision, path, mime_type,
                    source_asset_id, sha256, created_at
                )
                VALUES (1, 1, 1, 'KEYFRAME', 'APPROVED', 1, 'same.png', 'image/png',
                        NULL, 'same-sha', '2026-07-20 00:00:00')
                """
            )
        )

    command.upgrade(config, "head")

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO asset (
                    id, project_id, shot_id, type, status, revision, path, mime_type,
                    source_asset_id, sha256, created_at
                )
                VALUES (2, 1, 1, 'KEYFRAME', 'APPROVED', 2, 'same.png', 'image/png',
                        NULL, 'same-sha', '2026-07-20 00:00:01')
                """
            )
        )
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(
                sa.text(
                    """
                    INSERT INTO asset (
                        id, project_id, shot_id, type, status, revision, path, mime_type,
                        source_asset_id, sha256, created_at
                    )
                    VALUES (3, 1, 1, 'KEYFRAME', 'ACTIVE', 2, 'same.png', 'image/png',
                            NULL, 'same-sha', '2026-07-20 00:00:02')
                    """
                )
            )

    with engine.connect() as connection:
        assert connection.execute(sa.text("PRAGMA foreign_key_check")).all() == []
        assert connection.execute(sa.text("PRAGMA integrity_check")).scalar_one() == "ok"
        indexes = [row[1] for row in connection.execute(sa.text("PRAGMA index_list(asset)")).all()]
        assert "ix_asset_project_shot_type_sha256" not in indexes
        assert "ix_asset_project_shot_type_revision_sha256" in indexes


def test_quality_result_identity_migration_rejects_duplicate_current_checks(tmp_path: Path) -> None:
    db_path = tmp_path / "quality-identity.db"
    config = alembic_config(db_path)
    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO project (id, name, description, created_at, updated_at)
                VALUES (1, 'P', '', '2026-07-20 00:00:00', '2026-07-20 00:00:00')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO shot (
                    id, project_id, title, description, duration_seconds, prompt,
                    negative_prompt, sort_order, status, start_frame_asset_id, spec_revision,
                    approved_keyframe_asset_id, approved_video_asset_id, locked_tail_frame_asset_id,
                    start_frame_source_type, created_at, updated_at
                )
                VALUES (1, 1, 'S', '', 4.0, '', '', 0, 'VIDEO_REVIEW', NULL, 1, NULL, NULL, NULL,
                        'NONE', '2026-07-20 00:00:00', '2026-07-20 00:00:00')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO asset (
                    id, project_id, shot_id, type, status, revision, path, mime_type,
                    source_asset_id, sha256, created_at
                )
                VALUES (1, 1, 1, 'VIDEO', 'ACTIVE', 1, 'v.mp4', 'video/mp4',
                        NULL, 'video-sha', '2026-07-20 00:00:00')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO qualitycheckresult (
                    project_id, shot_id, asset_id, reference_asset_id, check_type, severity,
                    score, threshold, message, details_json, algorithm_version, created_at
                )
                VALUES (1, 1, 1, NULL, 'DURATION_DEVIATION', 'INFO',
                        0.0, 0.12, 'ok', '{}', 'quality-v1', '2026-07-20 00:00:00')
                """
            )
        )
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(
                sa.text(
                    """
                    INSERT INTO qualitycheckresult (
                        project_id, shot_id, asset_id, reference_asset_id, check_type, severity,
                        score, threshold, message, details_json, algorithm_version, created_at
                    )
                    VALUES (1, 1, 1, NULL, 'DURATION_DEVIATION', 'INFO',
                            0.0, 0.12, 'dupe', '{}', 'quality-v1', '2026-07-20 00:00:01')
                    """
                )
            )


def test_structured_continuity_migration_backfills_current_shot_specs(tmp_path: Path) -> None:
    db_path = tmp_path / "structured-continuity.db"
    config = alembic_config(db_path)
    command.upgrade(config, "20260720_0009")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO project (id, name, description, created_at, updated_at)
                VALUES (1, 'P', '', '2026-07-20 00:00:00', '2026-07-20 00:00:00')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO shot (
                    id, project_id, title, description, duration_seconds, prompt,
                    negative_prompt, sort_order, status, start_frame_asset_id, spec_revision,
                    approved_keyframe_asset_id, approved_video_asset_id, locked_tail_frame_asset_id,
                    start_frame_source_type, created_at, updated_at
                )
                VALUES (1, 1, 'S', 'desc', 4.0, 'prompt', 'avoid blur', 0, 'DRAFT', NULL, 4,
                        NULL, NULL, NULL, 'NONE', '2026-07-20 00:00:00', '2026-07-20 00:00:00')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO generationrequest (
                    id, project_id, shot_id, kind, provider_name, effective_provider_id,
                    status, prompt_snapshot, negative_prompt_snapshot, input_asset_ids,
                    output_asset_ids, shot_spec_revision, allow_capability_fallback,
                    created_at, updated_at
                )
                VALUES (1, 1, 1, 'KEYFRAME', 'mock', 'mock', 'PENDING', 'prompt', 'avoid blur',
                        '[]', '[]', 4, 0, '2026-07-20 00:00:00', '2026-07-20 00:00:00')
                """
            )
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        spec = connection.execute(
            sa.text(
                """
                SELECT shot_id, revision, summary, compiled_prompt, compiled_negative_prompt,
                       compiler_version
                FROM shotspec
                """
            )
        ).one()
        assert tuple(spec) == (1, 4, "desc", "prompt", "avoid blur", "structured-continuity-v1")
        request = connection.execute(
            sa.text("SELECT structured_payload_json, compiler_version FROM generationrequest WHERE id = 1")
        ).one()
        payload = json.loads(request.structured_payload_json)
        assert request.compiler_version == "structured-continuity-v1"
        assert payload["compiler_version"] == "structured-continuity-v1"
        assert payload["shot_revision"] == 4
        assert payload["shot"]["summary"] == "desc"
        assert payload["shot"]["free_prompt"] == "prompt"
        assert payload["shot"]["negative_prompt"] == "avoid blur"


def test_asset_revision_identity_migration_safe_downgrade(tmp_path: Path) -> None:
    db_path = tmp_path / "asset-identity-downgrade.db"
    config = alembic_config(db_path)
    command.upgrade(config, "head")
    command.downgrade(config, "20260720_0008")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == "20260720_0008"
        indexes = [row[1] for row in connection.execute(sa.text("PRAGMA index_list(asset)")).all()]
        assert "ix_asset_project_shot_type_sha256" in indexes


def test_toapis_live_enable_migration_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "toapis-live-enable-roundtrip.db"
    config = alembic_config(db_path)
    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT live_orchestration_enabled FROM providerprofile WHERE provider_key='toapis'")).scalar_one() == 0
        assert connection.execute(sa.text("SELECT COUNT(*) FROM providermodelprofile WHERE billing_unit='TOAPIS_CREDIT' AND pricing_review_status='PENDING'")).scalar_one() == 2
        assert connection.execute(sa.text("PRAGMA foreign_key_check")).all() == []
        assert connection.execute(sa.text("PRAGMA integrity_check")).scalar_one() == "ok"
    command.downgrade(config, "20260720_0013")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(sa.text("PRAGMA foreign_key_check")).all() == []
        assert connection.execute(sa.text("PRAGMA integrity_check")).scalar_one() == "ok"


def test_asset_revision_identity_migration_rejects_unsafe_downgrade(tmp_path: Path) -> None:
    db_path = tmp_path / "asset-identity-unsafe-downgrade.db"
    config = alembic_config(db_path)
    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO project (id, name, description, created_at, updated_at)
                VALUES (1, 'P', '', '2026-07-20 00:00:00', '2026-07-20 00:00:00')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO shot (
                    id, project_id, title, description, duration_seconds, prompt,
                    negative_prompt, sort_order, status, start_frame_asset_id, spec_revision,
                    approved_keyframe_asset_id, approved_video_asset_id, locked_tail_frame_asset_id,
                    start_frame_source_type, created_at, updated_at
                )
                VALUES (1, 1, 'S', '', 4.0, '', '', 0, 'DRAFT', NULL, 2, NULL, NULL, NULL,
                        'NONE', '2026-07-20 00:00:00', '2026-07-20 00:00:00')
                """
            )
        )
        for asset_id, revision in [(1, 1), (2, 2)]:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO asset (
                        id, project_id, shot_id, type, status, revision, path, mime_type,
                        source_asset_id, sha256, created_at
                    )
                    VALUES (:asset_id, 1, 1, 'KEYFRAME', 'APPROVED', :revision, 'same.png',
                            'image/png', NULL, 'same-sha', '2026-07-20 00:00:00')
                    """
                ),
                {"asset_id": asset_id, "revision": revision},
            )
    with pytest.raises(RuntimeError, match="Cannot downgrade asset identity"):
        command.downgrade(config, "20260720_0008")
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == "20260720_0009"
