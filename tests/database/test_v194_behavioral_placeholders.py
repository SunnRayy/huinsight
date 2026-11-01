"""V194: stored behavioral placeholder scores are nulled; measured rows are kept."""
import json

from src.database.connector import DatabaseConnector
from src.database.schema import initialize_schema


def _row(conn, dimension, score, raw, label):
    conn.execute(
        """INSERT INTO ai_behavioral_log (dimension, score, raw_value, computation_window_days, metadata_json)
           VALUES (?, ?, ?, 90, ?)""",
        [dimension, score, raw, json.dumps({"label": label, "description": ""})],
    )


def test_v194_nulls_placeholders_and_keeps_measurements(tmp_path):
    conn = DatabaseConnector(str(tmp_path / "v194.duckdb"))
    initialize_schema(conn)
    conn.run_migrations()

    _row(conn, "decision_speed", 0.5, 0.0, "Insufficient transaction data")        # placeholder
    _row(conn, "strategy_compliance", 0.5, 50.0, "No AI advisory data yet")         # placeholder
    _row(conn, "loss_tolerance", 0.5, 20.0, "avg loss 20.0%")                        # real computed 0.5
    _row(conn, "manual_contrarian", 0.5, 40.0, "40% of manual buys in drawdown")    # pinned score, real rate
    _row(conn, "manual_contrarian", 0.5, 0.0, "No data")                             # pinned + placeholder

    conn.execute("DELETE FROM schema_version WHERE version = 194")
    conn.run_migrations()

    rows = {
        (r[0], r[3]): (r[1], r[2])
        for r in conn.execute(
            "SELECT dimension, score, raw_value, json_extract_string(metadata_json, '$.label') FROM ai_behavioral_log"
        ).fetchall()
    }
    assert rows[("decision_speed", "Insufficient transaction data")] == (None, None)
    assert rows[("strategy_compliance", "No AI advisory data yet")] == (None, None)
    assert float(rows[("loss_tolerance", "avg loss 20.0%")][0]) == 0.5
    assert rows[("manual_contrarian", "40% of manual buys in drawdown")][0] is None
    assert float(rows[("manual_contrarian", "40% of manual buys in drawdown")][1]) == 40.0
    assert rows[("manual_contrarian", "No data")] == (None, None)
