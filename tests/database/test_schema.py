def test_holdings_table_has_currency_column():
    """Test that holdings table includes currency column."""
    from src.database.connector import DatabaseConnector
    from src.database.schema import initialize_schema
    
    connector = DatabaseConnector(":memory:")
    initialize_schema(connector)
    
    result = connector.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'holdings'
    """)
    columns = [row[0] for row in result.fetchall()]
    
    assert 'currency' in columns
    assert 'derived_from_transaction_id' in columns
    
    connector.close()


def test_schema_auto_increments_id():
    """Test that ID column auto-increments using sequence."""
    from src.database.connector import DatabaseConnector
    from src.database.schema import initialize_schema
    from datetime import date
    
    connector = DatabaseConnector(":memory:")
    initialize_schema(connector)
    
    # Insert without ID
    connector.execute("""
        INSERT INTO holdings (snapshot_date, asset_id, asset_name)
        VALUES (?, ?, ?)
    """, (date.today(), 'TEST1', 'Test Asset 1'))
    
    connector.execute("""
        INSERT INTO holdings (snapshot_date, asset_id, asset_name)
        VALUES (?, ?, ?)
    """, (date.today(), 'TEST2', 'Test Asset 2'))
    
    result = connector.execute("SELECT id, asset_id FROM holdings ORDER BY id")
    rows = result.fetchall()
    
    assert len(rows) == 2
    assert rows[0][0] == 1  # First ID should be 1
    assert rows[1][0] == 2  # Second ID should be 2
    
    connector.close()


def test_run_migrations_bootstraps_ai_reports_debug_columns(tmp_path):
    """Migration bootstrap should add LLM debug columns to ai_reports."""
    from src.database.connector import DatabaseConnector
    from src.database.schema import initialize_schema

    db_path = tmp_path / "test.duckdb"
    connector = DatabaseConnector(str(db_path))
    initialize_schema(connector)

    connector.run_migrations()

    result = connector.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'ai_reports'
        ORDER BY column_name
    """)
    columns = [row[0] for row in result.fetchall()]

    assert "prompt_text" in columns
    assert "raw_response_text" in columns

    connector.close()


def test_run_migrations_adds_trade_logs_linked_memo_id_column(tmp_path):
    """Migration bootstrap should add linked_memo_id to trade_logs."""
    from src.database.connector import DatabaseConnector
    from src.database.schema import initialize_schema

    db_path = tmp_path / "trade_logs_linked_memo.duckdb"
    connector = DatabaseConnector(str(db_path))
    initialize_schema(connector)

    before = connector.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'trade_logs'
        ORDER BY column_name
    """).fetchall()
    assert "linked_memo_id" not in [row[0] for row in before]

    connector.run_migrations()

    after = connector.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'trade_logs'
        ORDER BY column_name
    """).fetchall()
    columns = [row[0] for row in after]
    assert "linked_memo_id" in columns

    connector.close()


def test_run_migrations_adds_trade_logs_verification_status_column(tmp_path):
    """Migration bootstrap should add verification_status to trade_logs."""
    from src.database.connector import DatabaseConnector

    db_path = tmp_path / "trade_logs_verification_status.duckdb"
    connector = DatabaseConnector(str(db_path))
    connector.execute("CREATE SEQUENCE IF NOT EXISTS seq_trade_logs_id START 1")
    connector.execute(
        """
        CREATE TABLE trade_logs (
            id INTEGER PRIMARY KEY DEFAULT nextval('seq_trade_logs_id'),
            log_date DATE NOT NULL,
            asset_id VARCHAR(50) NOT NULL,
            action VARCHAR(20) NOT NULL,
            suggestion_source VARCHAR(50)
        )
        """
    )

    before = connector.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'trade_logs'
        ORDER BY column_name
    """
    ).fetchall()
    assert "verification_status" not in [row[0] for row in before]

    connector.run_migrations()

    after = connector.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'trade_logs'
        ORDER BY column_name
    """
    ).fetchall()
    columns = [row[0] for row in after]
    assert "verification_status" in columns

    connector.close()
