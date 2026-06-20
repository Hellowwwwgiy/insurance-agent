import logging
import os
from datetime import datetime
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langchain_openai import ChatOpenAI
from urllib.parse import quote_plus
from dotenv import load_dotenv, find_dotenv  # 环境变量库

# ==============================
# 📝 日志配置：严格写入已存在的 ./logs/ 目录
# ==============================
def setup_logger():
    """配置日志系统，日志文件写入 ./logs/（要求该目录已存在）"""
    log_dir = "./logs"
    
    if not os.path.exists(log_dir):
        raise RuntimeError(f"❌ 日志目录 '{log_dir}' 不存在！请按项目结构提前创建。")
    
    log_file = os.path.join(log_dir, f"insurance_agent_{datetime.now().strftime('%Y%m%d')}.log")
    
    log_format = logging.Formatter(
        '[%(asctime)s] %(levelname)-8s | %(filename)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    logger = logging.getLogger('InsuranceAgent')
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

# ==============================
# 🔐 加载环境变量（优先执行）
# ==============================
def load_environment():
    """加载.env文件中的环境变量，验证关键配置是否存在"""
    dotenv_path = find_dotenv()
    if not dotenv_path:
        raise RuntimeError("❌ 未找到.env文件！请在项目根目录创建.env文件")
    
    load_dotenv(dotenv_path)
    logger.info(f"✅ 成功加载环境变量: {dotenv_path}")
    
    required_vars = [
        "DEEPSEEK_API_KEY", "DB_USER", "DB_PASSWORD", 
        "DB_HOST", "DB_PORT", "DB_NAME"
    ]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise RuntimeError(
            f"❌ 缺少必要的环境变量: {', '.join(missing_vars)}\n"
            f"💡 请在.env文件中配置这些变量"
        )
    
    return {var: os.getenv(var) for var in required_vars}

# ==============================
# 🚀 初始化日志 & 环境变量
# ==============================
try:
    logger = setup_logger()
except Exception as e:
    print(f"🚨 日志初始化失败: {e}")
    print("💡 请确保项目根目录下已存在 'logs' 文件夹")
    exit(1)

try:
    env_config = load_environment()
except Exception as e:
    logger.critical(f"🚨 环境变量加载失败: {e}")
    exit(1)

# ==============================
# 🗄️ 数据库连接
# ==============================
try:
    logger.info("=" * 60)
    logger.info("🚀 保险智能助手 - 启动中...")
    logger.info("=" * 60)
    
    DB_USER = env_config["DB_USER"]
    DB_PASSWORD = env_config["DB_PASSWORD"]
    DB_HOST = env_config["DB_HOST"]
    DB_PORT = env_config["DB_PORT"]
    DB_NAME = env_config["DB_NAME"]
    
    encoded_password = quote_plus(DB_PASSWORD)
    db_uri = f"postgresql://{DB_USER}:{encoded_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

    logger.info(f"🔧 连接数据库: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    logger.debug(f"完整的连接 URI: {db_uri}")
    
    logger.info("⏳ 正在连接数据库...")
    db = SQLDatabase.from_uri(
        db_uri,
        sample_rows_in_table_info=3,
        engine_args={
            "connect_args": {
                "client_encoding": "UTF8",
                "options": "-c client_encoding=UTF8"
            }
        }
    )
    tables = db.get_usable_table_names()
    logger.info(f"✅ 数据库连接成功！")
    logger.info(f"📊 可用表: {tables}")
except Exception as e:
    logger.error(f"❌ 数据库连接失败: {e}", exc_info=True)
    logger.error("💡 请检查：1. 数据库是否运行 2. 用户名密码是否正确 3. 网络连接")
    exit(1)

# ==============================
# 🧠 LLM 配置（恢复原生 ChatOpenAI 对接DeepSeek）
# ==============================
try:
    logger.info("⏳ 初始化 DeepSeek LLM...")
    DEEPSEEK_API_KEY = env_config["DEEPSEEK_API_KEY"]
    
    # 沿用原代码写法，无需额外安装langchain-deepseek
    llm = ChatOpenAI(
        model="deepseek-chat",
        temperature=0,
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com/v1"
    )
    logger.info("✅ DeepSeek LLM 初始化成功")
    
    logger.info("⏳ 正在创建 SQL Agent...")
    agent = create_sql_agent(
        llm=llm,
        db=db,
        agent_type="openai-tools",
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=3
    )
    logger.info("✅ SQL Agent 创建成功！")
    logger.info("=" * 60)
except Exception as e:
    logger.error(f"❌ Agent 创建失败: {e}", exc_info=True)
    logger.error("💡 请检查：1. API Key 是否正确 2. 网络连接")
    exit(1)

# ==============================
# 💬 测试问题
# ==============================
def run_test_cases():
    test_cases = [
        ("张三的保单号和保费是多少？", "应返回 P20250405001 和 3200"),
        ("李四的电话号码是什么？", "应返回李四的 phone 字段"),
        ("保单号为 P20250405001 的客户是谁？", "应返回 张三"),
    ]
    
    logger.info("🧪 开始执行测试查询...")
    logger.info("=" * 60)
    
    success_count = 0
    fail_count = 0
    
    for i, (question, expected) in enumerate(test_cases, 1):
        logger.info(f"\n🔍 测试 {i}/{len(test_cases)}: {question}")
        logger.debug(f"💡 预期: {expected}")
        
        try:
            result = agent.invoke({"input": question})
            output = result.get("output", str(result)).strip()
            if not output:
                output = "<空响应>"
            logger.info(f"✅ 回答：{output[:100]}{'...' if len(output) > 100 else ''}")
            success_count += 1
        except Exception as e:
            logger.error(f"❌ 执行错误：{type(e).__name__}: {e}")
            fail_count += 1
    
    logger.info("=" * 60)
    logger.info(f"📊 测试结果: 成功 {success_count} / 失败 {fail_count}")
    logger.info("=" * 60)

# ==============================
# 🎮 交互模式
# ==============================
def interactive_mode():
    logger.info("\n💬 进入交互模式（输入 'quit' 退出）")
    logger.info("=" * 60)
    
    query_count = 0
    error_count = 0
    
    while True:
        try:
            user_input = input("\n❓ 您的问题：").strip()
            if user_input.lower() in ["quit", "exit", "q"]:
                logger.info(f"\n👋 退出程序。")
                logger.info(f"📊 本次会话统计: 查询 {query_count} 次，错误 {error_count} 次")
                break
            if not user_input:
                continue
            
            query_count += 1
            logger.info(f"⏳ 正在查询: '{user_input}'")
            
            result = agent.invoke({"input": user_input})
            ans = result.get("output", str(result)).strip()
            logger.info(f"\n✅ 回答：\n{ans}")
            
        except KeyboardInterrupt:
            logger.info(f"\n\n👋 检测到 Ctrl+C，退出程序。")
            logger.info(f"📊 本次会话统计: 查询 {query_count} 次，错误 {error_count} 次")
            break
        except Exception as e:
            error_count += 1
            logger.error(f"❌ 错误：{e}", exc_info=True)

# ==============================
# 🚀 主程序入口
# ==============================
if __name__ == "__main__":
    try:
        run_test_cases()
        interactive_mode()
    except Exception as e:
        logger.critical(f"❌ 程序异常终止: {e}", exc_info=True)
        logger.critical("💡 请查看 ./logs/ 下的日志文件获取详细信息")
    finally:
        logger.info("=" * 60)
        logger.info("🏁 程序结束")
        logger.info("=" * 60)
