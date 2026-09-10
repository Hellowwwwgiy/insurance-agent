import logging
import os
from datetime import datetime

from .config import Settings


def setup_logger(name: str = "InsuranceAgent", log_dir: str = "./logs",
                 settings: Settings = None) -> logging.Logger:
    """配置日志系统，日志文件写入指定目录；传入 settings 时 log_dir 优先取配置值"""
    if settings:
        log_dir = settings.log_dir

    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    log_file = os.path.join(log_dir, f"insurance_agent_{datetime.now().strftime('%Y%m%d')}.log")
    
    log_format = logging.Formatter(
        '[%(asctime)s] %(levelname)-8s | %(filename)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(log_format)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_format)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger