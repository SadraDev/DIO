"""
Configuration Management Module
Handles loading and accessing configuration from YAML file
"""
import yaml
from typing import Any, Dict, Optional
from pathlib import Path


class Settings:
    """Singleton configuration manager"""
    
    _instance = None
    _config = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Settings, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._config is None:
            self.load_config()
    
    def load_config(self, config_path: Optional[str] = None):
        """Load configuration from YAML file"""
        if config_path is None:
            # Default to config.yaml in the config directory
            config_dir = Path(__file__).parent
            config_path = config_dir / "config.yaml"
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f)
            
            self._validate_config()

        except FileNotFoundError:
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        except yaml.YAMLError as e:
            raise ValueError(f"Error parsing configuration file: {e}")

    def _validate_config(self):
        """Validate configuration values"""
        required_fields = [
            'system.name',
            'account.initial_balance', 
            'trading.symbols',
            'market.standard_pip_size',
            'mt5.magic_number'
        ]
        
        for field in required_fields:
            if self.get(field) is None:
                raise ValueError(f"Required configuration field missing: {field}")
        
        # Validate value ranges
        if self.get('account.initial_balance', 0) <= 0:
            raise ValueError("initial_balance must be positive")
        
        if not isinstance(self.get('trading.symbols', []), list):
            raise ValueError("trading.symbols must be a list")
        
        risk_percent = self.get('account.default_risk_percent', 0)
        if not 0 < risk_percent <= 0.1:
            raise ValueError("default_risk_percent must be between 0 and 0.1")

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation
        
        Args:
            key_path: Dot-separated path to config value (e.g., 'trading.risk.default_risk_percent')
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        if self._config is None:
            self.load_config()
        
        keys = key_path.split('.')
        value = self._config
        
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key_path: str, value: Any):
        """
        Set configuration value using dot notation
        
        Args:
            key_path: Dot-separated path to config value
            value: Value to set
        """
        if self._config is None:
            self.load_config()
        
        keys = key_path.split('.')
        config = self._config
        
        # Navigate to the parent dictionary
        for key in keys[:-1]:
            if key not in config:
                config[key] = {}
            config = config[key]
        
        # Set the final value
        config[keys[-1]] = value
    
    def get_all(self) -> Dict[str, Any]:
        """Get entire configuration dictionary"""
        if self._config is None:
            self.load_config()
        return self._config.copy()
    
    def save_config(self, config_path: Optional[str] = None):
        """Save current configuration to YAML file"""
        if config_path is None:
            config_dir = Path(__file__).parent
            config_path = config_dir / "config.yaml"
        
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(self._config, f, default_flow_style=False, indent=2)
    
    # Convenience methods for common configuration access
    @property
    def system_name(self) -> str:
        return self.get('system.name', 'Trading System')
    
    @property
    def system_version(self) -> str:
        return self.get('system.version', '2.0.0')
    
    @property
    def log_level(self) -> str:
        return self.get('logging.level', 'INFO')
    
    @property
    def symbols(self) -> list:
        return self.get('market.symbols', ['EURUSD.', 'GBPUSD.'])
    
    @property
    def initial_balance(self) -> float:
        return self.get('account.initial_balance', 10000)
    
    @property
    def default_risk_percent(self) -> float:
        return self.get('trading.risk.default_risk_percent', 0.01)
    
    @property
    def max_signals_per_symbol(self) -> int:
        return self.get('trading.max_signals_per_symbol', 2)
    
    @property
    def work_interval(self) -> int:
        return self.get('trading.work_interval', 1)
    
    @property
    def mt5_magic_number(self) -> int:
        return self.get('mt5.magic_number', 234000)
    
    @property
    def mt5_deviation(self) -> int:
        return self.get('mt5.deviation', 10)
    
    def get_strategy_config(self, strategy_name: str) -> Dict[str, Any]:
        """Get configuration for specific strategy"""
        return self.get(f'strategy.{strategy_name}', {})
    
    def get_indicator_config(self, strategy_name: str, indicator_name: str) -> Dict[str, Any]:
        """Get indicator configuration for specific strategy"""
        return self.get(f'strategy.{strategy_name}.{indicator_name}', {})
    
    def get_paths(self) -> Dict[str, str]:
        """Get all configured paths"""
        return {
            'logs': self.get('paths.logs_dir', 'logs'),
            'data': self.get('paths.data_dir', 'data'),
            'outputs': self.get('paths.outputs_dir', 'outputs'),
            'config': self.get('paths.config_dir', 'config')
        }


# Global settings instance
settings = Settings()


def get_config(key_path: str, default: Any = None) -> Any:
    """Convenience function to get configuration value"""
    return settings.get(key_path, default)


def set_config(key_path: str, value: Any):
    """Convenience function to set configuration value"""
    settings.set(key_path, value)
