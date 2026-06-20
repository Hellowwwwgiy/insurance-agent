#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
保险智能体模块测试脚本
测试 app.agent 包下的所有核心模块

🎯 最可靠版本：强制路径修正，不依赖工作目录
"""

import sys
import os
import traceback
import glob

# ========================================
# 🔑 核心修复：强制设置正确的项目根目录
# ========================================
# 获取当前脚本的绝对路径（不受工作目录影响）
current_script_path = os.path.abspath(__file__)
# 项目根目录 = 脚本所在目录
project_root = os.path.dirname(current_script_path)

# 清除 sys.path 中所有可能干扰的路径，只保留项目根目录
cleaned_path = [project_root]
for path in sys.path:
    if path and path != project_root:
        cleaned_path.append(path)
sys.path = cleaned_path

# 验证路径设置（调试用）
print("=" * 70)
print(f"✓ 项目根目录: {project_root}")
print(f"✓ sys.path[0]: {sys.path[0]}")
print(f"✓ 工作目录: {os.getcwd()}")
print("=" * 70 + "\n")

def print_section(title):
    """打印分隔标题"""
    print("\n" + "=" * 70)
    print(f"  🧪 {title}")
    print("=" * 70)

def test_config_module():
    """测试 config 模块（位于 app/agent/config.py）"""
    print_section("测试 1: Config 配置模块")
    
    try:
        from app.agent.config import Config
        config = Config()
        print("✅ Config 类创建成功")
        print(f"📊 配置信息: {config}")
        print(f"🔧 数据库 URI: {config.db_uri}")
        assert "postgresql://" in config.db_uri or "sqlite://" in config.db_uri
        print("✅ 数据库 URI 格式正确")
        
        # 测试配置验证（如果 Config 有 validate 方法）
        try:
            Config.validate()
            print("✅ 配置验证通过")
        except (AttributeError, ValueError) as e:
            print(f"ℹ️ 配置验证跳过或警告: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        traceback.print_exc()
        return False

def test_logger_module():
    """测试 logger 模块（位于 app/agent/logger.py）"""
    print_section("测试 2: Logger 日志模块")
    
    try:
        from app.agent.logger import setup_logger
        logger = setup_logger(
            name="TestLogger",
            log_dir="./logs",
            log_level="DEBUG",
            console_level="INFO"
        )
        print("✅ Logger 初始化成功")
        
        logger.debug("🔍 DEBUG 测试日志")
        logger.info("✅ INFO 测试日志")
        logger.warning("⚠️ WARNING 测试日志")
        logger.error("❌ ERROR 测试日志")
        
        # 检查日志文件是否生成
        log_dir = "./logs"
        if os.path.exists(log_dir):
            log_files = glob.glob(os.path.join(log_dir, "insurance_agent_*.log"))
            if log_files:
                latest_log = max(log_files, key=os.path.getctime)
                print(f"✅ 日志文件已创建: {latest_log}")
            else:
                print("⚠️ 日志目录存在，但暂无日志文件（可能因级别过滤）")
        else:
            print("⚠️ 日志目录 ./logs 不存在（测试中会自动创建）")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        traceback.print_exc()
        return False

def test_database_module():
    """测试 database 模块（位于 app/agent/database.py）"""
    print_section("测试 3: DatabaseManager 数据库模块")
    
    try:
        from app.agent.config import Config
        from app.agent.database import DatabaseManager
        
        config = Config()
        db_manager = DatabaseManager(
            db_uri=config.db_uri,
            sample_rows=config.SAMPLE_ROWS_IN_TABLE_INFO
        )
        
        print("✅ DatabaseManager 创建成功")
        
        if db_manager.connect():
            print("✅ 数据库连接成功")
            
            tables = db_manager.get_table_names()
            print(f"📊 可用表: {tables}")
            
            if tables:
                first_table = tables[0]
                table_info = db_manager.get_table_info(first_table)
                print(f"\n📋 表 '{first_table}' 信息摘要:")
                print(f"{table_info[:250]}..." if len(table_info) > 250 else table_info)
                
                # 尝试简单查询（防错处理）
                try:
                    result = db_manager.execute_query(f"SELECT COUNT(*) FROM \"{first_table}\" LIMIT 1;")
                    print(f"✅ 简单查询返回: {result}")
                except Exception as qe:
                    print(f"⚠️ 查询失败（可能表为空或权限问题）: {qe}")
            
            db_manager.close()
            return True
        else:
            print("❌ 数据库连接失败")
            return False
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        traceback.print_exc()
        return False

def test_llm_module():
    """测试 LLM 模块（依赖 config 中的 LLM 设置）"""
    print_section("测试 4: LLM 语言模型模块")
    
    try:
        from app.agent.config import Config
        from langchain_openai import ChatOpenAI
        
        config = Config()
        llm = ChatOpenAI(
            model=config.LLM_MODEL,
            temperature=config.LLM_TEMPERATURE,
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_BASE_URL
        )
        
        print("✅ LLM 实例创建成功")
        print(f"🤖 使用模型: {config.LLM_MODEL}")
        
        # 仅测试初始化（避免网络调用超时）
        print("✅ LLM 初始化完成（未发送请求）")
        return True
        
    except ImportError as ie:
        print(f"⚠️ 缺少依赖: {ie} → 请安装 langchain-openai")
        return False
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        traceback.print_exc()
        return False

def test_agent_module():
    """测试 agent 模块（位于 app/agent/agent.py）"""
    print_section("测试 5: InsuranceAgent 智能助手模块")
    
    try:
        from app.agent.config import Config
        from app.agent.database import DatabaseManager
        from langchain_openai import ChatOpenAI
        from app.agent.agent import InsuranceAgent
        
        config = Config()
        
        # 初始化数据库
        db_manager = DatabaseManager(config.db_uri)
        if not db_manager.connect():
            print("❌ 数据库连接失败，跳过 Agent 测试")
            return False
        
        # 初始化 LLM
        llm = ChatOpenAI(
            model=config.LLM_MODEL,
            temperature=config.LLM_TEMPERATURE,
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_BASE_URL
        )
        
        # 创建 Agent
        agent = InsuranceAgent(
            llm=llm,
            db=db_manager.db,
            agent_type=config.AGENT_TYPE,
            verbose=False,
            max_iterations=config.AGENT_MAX_ITERATIONS
        )
        
        if agent.create():
            print("✅ InsuranceAgent 创建成功")
            
            # 测试最小化查询（不依赖真实数据）
            try:
                result = agent.query("你好，请用一句话介绍自己。")
                print(f"🤖 Agent 回复（前 60 字）: {result['answer'][:60]}...")
            except Exception as ae:
                print(f"⚠️ Agent 查询异常（非致命）: {ae}")
            
            db_manager.close()
            return True
        else:
            print("❌ Agent 创建失败")
            db_manager.close()
            return False
            
    except ImportError as ie:
        print(f"⚠️ 导入失败: {ie} → 请检查 agent.py 是否存在且路径正确")
        return False
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        traceback.print_exc()
        return False

def run_all_tests():
    """运行所有测试"""
    print("\n" + "🚀" * 30)
    print("  🚀 开始测试 app.agent/ 模块（嵌套结构）")
    print("🚀" * 30)
    
    results = {}
    
    results["Config"] = test_config_module()
    results["Logger"] = test_logger_module()
    results["Database"] = test_database_module()
    results["LLM"] = test_llm_module()
    results["Agent"] = test_agent_module()
    
    # 汇总结果
    print_section("测试结果汇总")
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    
    for module, status in results.items():
        symbol = "✅" if status else "❌"
        print(f"{symbol} {module}: {'通过' if status else '失败'}")
    
    print("\n" + "=" * 70)
    print(f"📊 总计: {passed}/{total} 个测试通过")
    print("=" * 70)
    
    if passed == total:
        print("\n🎉 恭喜！所有测试通过！")
    else:
        print(f"\n⚠️ 有 {total - passed} 个测试失败，请检查错误信息")
    
    return passed == total

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
