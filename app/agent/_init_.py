"""
Insurance Agent Application
保险智能助手核心应用模块
"""
__version__ = "1.0.0"
__author__ = "Insurance Agent Team"

from .config import Config
from .database import DatabaseManager
from .agent import InsuranceAgent
from .logger import setup_logger

__all__ = [
    'Config',
    'DatabaseManager',
    'InsuranceAgent',
    'setup_logger'
]
