#!/usr/bin/env python3
"""CLI 入口：整合配置加载、数据库连接、LLM创建、Agent构建和运行模式选择"""
import sys

from . import (
    setup_logger,
    load_environment,
    create_database_connection,
    create_llm,
    create_agent,
    create_enhanced_agent,
    run_test_cases,
    interactive_mode,
)


def main():
    """主函数：按顺序完成环境准备、Agent创建和运行"""

    # 1️⃣ 加载环境变量 & 初始化日志
    settings = load_environment()
    logger = setup_logger(settings=settings)
    logger.info("=" * 60)
    logger.info("🚀 SQL Agent 启动中...")
    logger.info("=" * 60)

    # 2️⃣ 建立数据库连接
    engine = None
    try:
        engine = create_database_connection(settings, logger)
        logger.info("✅ 数据库连接成功")
    except Exception as e:
        logger.error(f"❌ 数据库连接失败: {e}", exc_info=True)
        logger.error("💡 请检查 .env 中的 DB_* 配置是否正确")
        sys.exit(1)

    # 3️⃣ 验证 API Key
    api_key = settings.deepseek_api_key
    if not api_key or api_key == "your-api-key-here":
        logger.error("❌ 未配置 DEEPSEEK_API_KEY")
        logger.error("💡 请在 .env 文件中设置有效的 API Key")
        sys.exit(1)
    logger.info(f"✅ API Key 已配置 ({api_key[:8]}...)")

    # 4️⃣ 创建 LLM & Agent（无记忆参数）
    try:
        llm = create_llm(settings, logger)
        base_agent = create_agent(llm, engine, logger)
        # 用自检模块包装原始Agent
        agent = create_enhanced_agent(base_agent, llm, logger)
        logger.info("✅ 自检模块已成功接入")

    except Exception as e:
        logger.error(f"❌ Agent 创建失败: {e}", exc_info=True)
        logger.error("💡 请检查：1. API Key 是否正确 2. 网络连接是否正常")
        sys.exit(1)

    # 5️⃣ 运行测试用例 & 进入交互模式
    try:
        run_test_cases(agent, logger)
        interactive_mode(agent, logger)
    except KeyboardInterrupt:
        logger.info("\n👋 用户中断，程序退出")
    except Exception as e:
        logger.error(f"❌ 运行时异常: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # 6️⃣ 清理资源
        if engine is not None:
            engine.dispose()
            logger.info("🔒 数据库连接已关闭")
        logger.info("🏁 SQL Agent 已停止")


if __name__ == "__main__":
    main()
