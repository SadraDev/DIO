from abc import ABC, abstractmethod
from typing import List, Any, Dict
from src.core.models.bar import Bar


class BaseIndicator(ABC):
    """Base class for all technical indicators"""
    
    def __init__(self, name: str):
        self.name = name
        self.parameters = {}
    
    @abstractmethod
    def calculate(self, bars: List[Bar]) -> Any:
        """Calculate indicator values from bars"""
        pass
    
    def set_parameter(self, key: str, value: Any):
        """Set indicator parameter"""
        self.parameters[key] = value
    
    def get_parameter(self, key: str, default: Any = None) -> Any:
        """Get indicator parameter"""
        return self.parameters.get(key, default)
    
    def __str__(self):
        return f"{self.name}({self.parameters})"
