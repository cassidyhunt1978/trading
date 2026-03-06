"""Phase 6: AI Agent - Create agent decision audit table"""
import psycopg2
import os

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@127.0.0.1:5432/trading_system')

def create_agent_tables():
    """Create tables for AI agent audit trail"""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        # Create agent_decisions table for audit trail
        print("Creating agent_decisions table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_decisions (
                id SERIAL PRIMARY KEY,
                cycle_timestamp TIMESTAMP NOT NULL,
                system_state JSONB NOT NULL,
                ai_response TEXT NOT NULL,
                decisions JSONB NOT NULL,
                actions_executed JSONB NOT NULL,
                execution_results JSONB NOT NULL,
                reasoning TEXT,
                portfolio_value_before DECIMAL(20, 8),
                portfolio_value_after DECIMAL(20, 8),
                mode VARCHAR(20) DEFAULT 'dry_run',
                error TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        print("✓ agent_decisions table created")
        
        # Create index on timestamp for efficient querying
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent_decisions_timestamp 
            ON agent_decisions(cycle_timestamp DESC)
        """)
        print("✓ Timestamp index created")
        
        # Create agent_config table for settings
        print("Creating agent_config table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_config (
                id SERIAL PRIMARY KEY,
                enabled BOOLEAN DEFAULT FALSE,
                mode VARCHAR(20) DEFAULT 'dry_run',
                max_trades_per_day INTEGER DEFAULT 20,
                max_position_size_pct DECIMAL(5, 2) DEFAULT 50.0,
                max_daily_loss_pct DECIMAL(5, 2) DEFAULT 10.0,
                min_confidence_threshold DECIMAL(5, 2) DEFAULT 70.0,
                active_symbols TEXT[] DEFAULT ARRAY[]::TEXT[],
                excluded_strategies INTEGER[] DEFAULT ARRAY[]::INTEGER[],
                run_interval_minutes INTEGER DEFAULT 60,
                provider VARCHAR(20) DEFAULT 'anthropic',
                model VARCHAR(50) DEFAULT 'claude-3-5-sonnet-20241022',
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        print("✓ agent_config table created")
        
        # Insert default config
        cur.execute("""
            INSERT INTO agent_config (enabled, mode)
            VALUES (FALSE, 'dry_run')
            ON CONFLICT DO NOTHING
        """)
        print("✓ Default config inserted")
        
        conn.commit()
        print("\n✅ Phase 6 AI Agent tables created successfully!")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error: {e}")
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    create_agent_tables()
