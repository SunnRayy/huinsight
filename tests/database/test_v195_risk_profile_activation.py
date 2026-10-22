"""V195: risk_profiles.activated_by_user_at — the drift-alert "(default)" marker
(Round 7 #1) comes from a stored fact, never from the profile's name."""
from src.database.connector import DatabaseConnector
from src.database.schema import bootstrap_database


def _active(conn):
    return conn.execute(
        "SELECT id, activated_by_user_at, updated_at FROM risk_profiles WHERE is_active = TRUE"
    ).fetchone()


def test_fresh_install_default_profile_is_not_user_chosen(tmp_path):
    conn = DatabaseConnector(str(tmp_path / "fresh.duckdb"))
    bootstrap_database(conn)

    profile_id, activated_by_user_at, _ = _active(conn)
    assert profile_id is not None
    assert activated_by_user_at is None
    assert conn.execute("SELECT 1 FROM schema_version WHERE version = 195").fetchone()


def test_backfill_marks_a_profile_someone_already_activated(tmp_path):
    """An existing DB where a person used activate_profile() before V195: its
    updated_at moved past created_at, and that is the evidence V195 uses."""
    conn = DatabaseConnector(str(tmp_path / "existing.duckdb"))
    bootstrap_database(conn)
    conn.execute(
        "UPDATE risk_profiles SET updated_at = created_at + INTERVAL 1 DAY, "
        "activated_by_user_at = NULL WHERE is_active = TRUE"
    )
    conn.execute("DELETE FROM schema_version WHERE version = 195")

    conn.run_migrations()

    _, activated_by_user_at, updated_at = _active(conn)
    assert activated_by_user_at == updated_at


def test_backfill_leaves_the_untouched_seed_default_alone(tmp_path):
    conn = DatabaseConnector(str(tmp_path / "seeded.duckdb"))
    bootstrap_database(conn)
    conn.execute("DELETE FROM schema_version WHERE version = 195")

    conn.run_migrations()

    assert _active(conn)[1] is None
