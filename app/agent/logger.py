"""
日志配置模块
"""
import logging
import os
from datetime import datetime
from typing import Optional

def setup_logger(
    name: str = "InsuranceAgent",
    log_dir: str = "./logs",
    log_level: str = "INFO",
    console_level: str = "INFO"
) -> logging.Logger:
    """
    配置日志系统
    
    Args:
        name: Logger 名称
        log_dir: 日志目录路径
        log_level: 文件日志级别
        console_level: 控制台日志级别
        
    Returns:
        配置好的 Logger
    """
    # 检查日志目录是否存在
    if not os.path.exists(log_dir):
        raise RuntimeError(f"❌ 日志目录 '{log_dir}' 不存在！请按项目结构提前创建。")
    
    # 生成日志文件名（按日期）
    log_file = os.path.join(log_dir, f"insurance_agent_{datetime.now().strftime('%Y%m%d')}.log")
    
    # 配置日志格式
    log_format = logging.Formatter(
        '[%(asctime)s] %(levelname)-8s | %(filename)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 创建 logger
    logger = logging.getLogger(name)
    
    # 设置日志级别
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL
    }
    
    logger.setLevel(level_map.get(log_level.upper(), logging.INFO))
    
    # 清除已有 handlers（防止重复）
    logger.handlers.clear()
    
    # 📄 文件 Handler（记录所有级别）
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(level_map.get(log_level.upper(), logging.DEBUG))
    file_handler.setFormatter(log_format)
    
    # 💻 控制台 Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level_map.get(console_level.upper(), logging.INFO))
    console_handler.setFormatter(log_format)
    
    # 添加 handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

def get_logger(name: str = "InsuranceAgent") -> logging.Logger:
    """获取已配置的 logger"""
    return logging.getLogger(name)
