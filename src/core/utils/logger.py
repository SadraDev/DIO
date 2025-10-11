import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from enum import Enum

from config.settings import settings


class LoggerType(Enum):
    """Different types of loggers in the system"""
    MAIN = "main"
    TRADING = "trading"
    BACKTEST = "backtest"
    CONNECTION = "connection"
    SYSTEM = "system"
    ORDERS = "orders"
    SIGNALS = "signals"


class TradingLogger:
    """Advanced logging system for trading operations"""
    
    _loggers: Dict[str, logging.Logger] = {}
    _initialized = False
    
    @classmethod
    def initialize(cls, logs_dir: Optional[str] = None):
        """Initialize all loggers with configuration"""
        if cls._initialized:
            return
        
        if logs_dir is None:
            logs_dir = settings.get_paths()['logs']
        
        # Create logs directory if it doesn't exist
        Path(logs_dir).mkdir(parents=True, exist_ok=True)
        
        # Configure each logger type
        for logger_type in LoggerType:
            cls._setup_logger(logger_type, logs_dir)
        
        cls._initialized = True
        cls.get_logger(LoggerType.SYSTEM).info("Logging system initialized successfully")
    
    @classmethod
    def _setup_logger(cls, logger_type: LoggerType, logs_dir: str):
        """Setup individual logger with file and console handlers"""
        logger_name = logger_type.value
        logger = logging.getLogger(logger_name)
        logger.setLevel(getattr(logging, settings.log_level.upper()))
        
        # Clear existing handlers
        logger.handlers.clear()
        
        # Create formatters
        detailed_formatter = logging.Formatter(
            settings.get('logging.format.detailed',
                        '%(asctime)s | %(name)s | %(levelname)s | %(funcName)s:%(lineno)d | %(message)s')
        )
        simple_formatter = logging.Formatter(
            settings.get('logging.format.simple',
                        '%(asctime)s | %(levelname)s | %(message)s')
        )
        
        # File handler with rotation
        if settings.get('logging.log_to_file', True):
            log_filename = settings.get(f'logging.files.{logger_name}', f'{logger_name}.log')
            log_filepath = Path(logs_dir) / log_filename
            
            file_handler = logging.handlers.RotatingFileHandler(
                log_filepath,
                maxBytes=settings.get('logging.max_file_size_mb', 50) * 1024 * 1024,
                backupCount=settings.get('logging.backup_count', 5),
                encoding='utf-8'
            )
            file_handler.setFormatter(detailed_formatter)
            logger.addHandler(file_handler)
        
        # Console handler
        if settings.get('logging.log_to_console', True):
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(simple_formatter)
            
            # Only show INFO+ for main logger in console to reduce noise
            if logger_type == LoggerType.MAIN:
                console_handler.setLevel(logging.INFO)
            else:
                console_handler.setLevel(logging.WARNING)
            
            logger.addHandler(console_handler)
        
        # Store logger
        cls._loggers[logger_name] = logger
    
    @classmethod
    def get_logger(cls, logger_type: LoggerType) -> logging.Logger:
        """Get logger instance by type"""
        if not cls._initialized:
            cls.initialize()
        
        return cls._loggers.get(logger_type.value, cls._loggers[LoggerType.MAIN.value])
    
    @classmethod
    def get_main_logger(cls) -> logging.Logger:
        """Get main system logger"""
        return cls.get_logger(LoggerType.MAIN)
    
    @classmethod
    def get_trading_logger(cls) -> logging.Logger:
        """Get trading operations logger"""
        return cls.get_logger(LoggerType.TRADING)
    
    @classmethod
    def get_backtest_logger(cls) -> logging.Logger:
        """Get backtesting logger"""
        return cls.get_logger(LoggerType.BACKTEST)
    
    @classmethod  
    def get_connection_logger(cls) -> logging.Logger:
        """Get connection status logger"""
        return cls.get_logger(LoggerType.CONNECTION)
    
    @classmethod
    def get_system_logger(cls) -> logging.Logger:
        """Get system events logger"""
        return cls.get_logger(LoggerType.SYSTEM)
    
    @classmethod
    def get_orders_logger(cls) -> logging.Logger:
        """Get order execution logger"""
        return cls.get_logger(LoggerType.ORDERS)
    
    @classmethod
    def get_signals_logger(cls) -> logging.Logger:
        """Get signal generation logger"""
        return cls.get_logger(LoggerType.SIGNALS)


class LogContextManager:
    """Context manager for enhanced logging with structured data"""
    
    def __init__(self, logger: logging.Logger, operation: str, **context):
        self.logger = logger
        self.operation = operation
        self.context = context
        self.start_time = None
    
    def __enter__(self):
        self.start_time = datetime.now()
        context_str = " | ".join(f"{k}={v}" for k, v in self.context.items())
        self.logger.info(f"Starting {self.operation} | {context_str}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = (datetime.now() - self.start_time).total_seconds()
        
        if exc_type is None:
            self.logger.info(f"Completed {self.operation} successfully | Duration: {duration:.2f}s")
        else:
            self.logger.error(f"Failed {self.operation} | Error: {exc_val} | Duration: {duration:.2f}s")
        
        return False


def log_signal_event(signal_type: str, symbol: str, action: str, **kwargs):
    """Log signal-related events with structured format"""
    logger = TradingLogger.get_signals_logger()
    
    context = {
        'signal_type': signal_type,
        'symbol': symbol, 
        'action': action,
        **kwargs
    }
    
    context_str = " | ".join(f"{k}={v}" for k, v in context.items())
    logger.info(f"SIGNAL_EVENT | {context_str}")


def log_order_event(event_type: str, symbol: str, order_type: str, **kwargs):
    """Log order-related events with structured format"""
    logger = TradingLogger.get_orders_logger()
    
    context = {
        'event_type': event_type,
        'symbol': symbol,
        'order_type': order_type,
        **kwargs
    }
    
    context_str = " | ".join(f"{k}={v}" for k, v in context.items())
    logger.info(f"ORDER_EVENT | {context_str}")


def log_connection_event(event_type: str, status: str, **kwargs):
    """Log connection-related events"""
    logger = TradingLogger.get_connection_logger()
    
    context = {
        'event_type': event_type,
        'status': status,
        **kwargs
    }
    
    context_str = " | ".join(f"{k}={v}" for k, v in context.items())
    logger.info(f"CONNECTION_EVENT | {context_str}")


def log_backtest_event(event_type: str, **kwargs):
    """Log backtesting events"""
    logger = TradingLogger.get_backtest_logger()
    
    context = {
        'event_type': event_type,
        **kwargs
    }
    
    context_str = " | ".join(f"{k}={v}" for k, v in context.items())
    logger.info(f"BACKTEST_EVENT | {context_str}")


def log_system_event(event_type: str, **kwargs):
    """Log system events"""
    logger = TradingLogger.get_system_logger()
    
    context = {
        'event_type': event_type,
        **kwargs
    }
    
    context_str = " | ".join(f"{k}={v}" for k, v in context.items())
    logger.info(f"SYSTEM_EVENT | {context_str}")


# Convenience decorators
def log_function_call(logger_type: LoggerType = LoggerType.MAIN):
    """Decorator to automatically log function calls"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger = TradingLogger.get_logger(logger_type)
            func_name = func.__name__
            
            try:
                logger.debug(f"Calling {func_name} with args={args}, kwargs={kwargs}")
                result = func(*args, **kwargs)
                logger.debug(f"Completed {func_name} successfully")
                return result
            except Exception as e:
                logger.error(f"Error in {func_name}: {e}")
                raise
        
        return wrapper
    return decorator


# Initialize logging system on import
TradingLogger.initialize()
