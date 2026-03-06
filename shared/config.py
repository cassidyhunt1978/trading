"""Configuration management"""
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # Database
    database_url: str = 'postgresql://postgres:postgres@127.0.0.1:5432/trading_system'
    
    # Redis
    redis_url: str = 'redis://127.0.0.1:6379/0'
    port_redis: int = 6379
    
    # Service Communication (use 127.0.0.1 instead of localhost for consistency)
    service_host: str = '127.0.0.1'
    
    # AI APIs
    anthropic_api_key: str = ''
    openai_api_key: str = ''
    
    # Sentiment APIs
    reddit_client_id: str = ''
    reddit_client_secret: str = ''
    reddit_user_agent: str = 'TradingBot/1.0'
    twitter_bearer_token: str = ''
    newsapi_key: str = ''
    
    # Exchange API (Coinbase preferred for better free tier)
    coinbase_api_key: str = ''
    coinbase_api_secret: str = ''
    
    # Kraken API (legacy/backup)
    kraken_api_key: str = ''
    kraken_secret_key: str = ''
    
    # System
    environment: str = 'development'
    log_level: str = 'INFO'
    
    # Trading
    paper_starting_capital: float = 1000.00
    daily_target_pct: float = 0.05
    min_signal_quality: int = 60  # Temporarily lowered from 70 during optimization
    
    # Server Ports
    port_ai_api: int = 8011
    port_ohlcv_api: int = 8012
    port_backtest_api: int = 8013
    port_optimization_api: int = 8014
    port_signal_api: int = 8015
    port_portfolio_api: int = 8016
    port_trading_api: int = 8017
    port_afteraction_api: int = 8018
    port_testing_api: int = 8019
    port_strategy_config_api: int = 8020
    port_system_monitor_api: int = 8021
    port_ensemble_api: int = 8022  # Phase 8: Vision ensemble engine
    
    class Config:
        env_file = '.env'
        case_sensitive = False
        extra = 'ignore'  # Allow extra fields from .env file

@lru_cache()
def get_settings() -> Settings:
    return Settings()
