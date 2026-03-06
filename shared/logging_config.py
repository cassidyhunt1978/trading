"""Logging configuration"""
import structlog
import logging
import sys

def setup_logging(service_name: str, log_level: str = 'INFO'):
    """Configure structured logging"""
    
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=get_logger(log_level),
    )
    
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(get_logger(log_level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    
    logger = structlog.get_logger(service_name)
    return logger

def get_logger(log_level: str):
    """Convert string log level to logging constant"""
    levels = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    return levels.get(log_level.upper(), logging.INFO)
