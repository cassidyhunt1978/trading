"""Phase 7: Walk-Forward Optimization - Create tables for parameter tracking"""
import psycopg2
import os

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@127.0.0.1:5432/trading_system')

def create_walkforward_tables():
    """Create tables for walk-forward optimization tracking"""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        # Create parameter_versions table
        print("Creating parameter_versions table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS parameter_versions (
                id SERIAL PRIMARY KEY,
                strategy_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                parameters JSONB NOT NULL,
                training_start DATE NOT NULL,
                training_end DATE NOT NULL,
                test_start DATE NOT NULL,
                test_end DATE NOT NULL,
                training_performance JSONB,
                test_performance JSONB,
                status VARCHAR(20) DEFAULT 'testing',
                promoted_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(),
                FOREIGN KEY (strategy_id) REFERENCES strategies(id)
            )
        """)
        print("✓ parameter_versions table created")
        
        # Create index
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_param_versions_strategy_symbol 
            ON parameter_versions(strategy_id, symbol, status)
        """)
        print("✓ Parameter versions index created")
        
        # Create optimization_runs table
        print("Creating optimization_runs table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS optimization_runs (
                id SERIAL PRIMARY KEY,
                run_type VARCHAR(20) NOT NULL,
                started_at TIMESTAMP NOT NULL,
                completed_at TIMESTAMP,
                strategies_processed INTEGER DEFAULT 0,
                parameters_tested INTEGER DEFAULT 0,
                parameters_promoted INTEGER DEFAULT 0,
                status VARCHAR(20) DEFAULT 'running',
                error TEXT,
                results JSONB,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        print("✓ optimization_runs table created")
        
        # Create index
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_optimization_runs_started 
            ON optimization_runs(started_at DESC)
        """)
        print("✓ Optimization runs index created")
        
        # Add parameter_version_id to strategies table if not exists
        print("Adding parameter tracking to strategies table...")
        cur.execute("""
            ALTER TABLE strategies 
            ADD COLUMN IF NOT EXISTS current_parameter_version_id INTEGER,
            ADD COLUMN IF NOT EXISTS last_optimized_at TIMESTAMP
        """)
        print("✓ Strategy parameter tracking added")
        
        conn.commit()
        print("\n✅ Phase 7 Walk-Forward Optimization tables created successfully!")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error: {e}")
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    create_walkforward_tables()
