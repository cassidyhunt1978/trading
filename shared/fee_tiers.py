"""Fee tier calculations for Kraken exchange"""

# Kraken fee tiers based on 30-day trading volume
# https://www.kraken.com/features/fee-schedule
KRAKEN_FEE_TIERS = [
    {"volume": 0, "maker": 0.0016, "taker": 0.0026},
    {"volume": 50000, "maker": 0.0014, "taker": 0.0024},
    {"volume": 100000, "maker": 0.0012, "taker": 0.0022},
    {"volume": 250000, "maker": 0.0010, "taker": 0.0020},
    {"volume": 500000, "maker": 0.0008, "taker": 0.0018},
    {"volume": 1000000, "maker": 0.0006, "taker": 0.0016},
    {"volume": 2500000, "maker": 0.0004, "taker": 0.0014},
    {"volume": 5000000, "maker": 0.0002, "taker": 0.0012},
    {"volume": 10000000, "maker": 0.0000, "taker": 0.0010},
]

# Coinbase Advanced Trade fees
# https://help.coinbase.com/en/exchange/trading-and-funding/exchange-fees
COINBASE_FEE_TIERS = [
    {"volume": 0, "maker": 0.0040, "taker": 0.0060},
    {"volume": 10000, "maker": 0.0025, "taker": 0.0040},
    {"volume": 50000, "maker": 0.0015, "taker": 0.0025},
    {"volume": 100000, "maker": 0.0010, "taker": 0.0018},
    {"volume": 500000, "maker": 0.0008, "taker": 0.0015},
    {"volume": 1000000, "maker": 0.0005, "taker": 0.0012},
    {"volume": 5000000, "maker": 0.0003, "taker": 0.0010},
    {"volume": 15000000, "maker": 0.0001, "taker": 0.0008},
    {"volume": 75000000, "maker": 0.0000, "taker": 0.0006},
]


def get_kraken_fees(volume_30d: float) -> dict:
    """Get Kraken maker/taker fees based on 30-day volume"""
    tier = KRAKEN_FEE_TIERS[0]  # Default to lowest tier
    
    for fee_tier in reversed(KRAKEN_FEE_TIERS):
        if volume_30d >= fee_tier["volume"]:
            tier = fee_tier
            break
    
    return {
        "maker_fee": tier["maker"],
        "taker_fee": tier["taker"],
        "tier_volume": tier["volume"]
    }


def get_coinbase_fees(volume_30d: float) -> dict:
    """Get Coinbase Advanced Trade fees based on 30-day volume"""
    tier = COINBASE_FEE_TIERS[0]  # Default to lowest tier
    
    for fee_tier in reversed(COINBASE_FEE_TIERS):
        if volume_30d >= fee_tier["volume"]:
            tier = fee_tier
            break
    
    return {
        "maker_fee": tier["maker"],
        "taker_fee": tier["taker"],
        "tier_volume": tier["volume"]
    }


def calculate_fee(amount: float, fee_rate: float) -> float:
    """Calculate fee for a given amount"""
    return amount * fee_rate


def get_trading_volume_30d(user_id: str = None, mode: str = "paper") -> float:
    """
    Calculate 30-day trading volume for fee tier determination
    
    For paper trading, uses accumulated volume from positions table
    For live trading, would query exchange API
    """
    from shared.database import get_connection
    from datetime import datetime, timedelta
    
    thirty_days_ago = datetime.now() - timedelta(days=30)
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(SUM(capital_allocated), 0) as volume
                FROM positions
                WHERE mode = %s 
                AND created_at >= %s
            """, (mode, thirty_days_ago))
            
            result = cur.fetchone()
            return float(result['volume']) if result else 0.0
