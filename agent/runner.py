import logging

TEST_CASES = [
    ("张三的保单号和保费是多少？", "应返回 P20250405001 和 3200"),
    ("李四的电话号码是什么？", "应返回李四的 phone 字段"),
    ("保单号为 P20250405001 的客户是谁？", "应返回 张三"),
]


def run_test_cases(agent, logger: logging.Logger):
    """执行预设测试用例"""
    logger.info("🧪 开始执行测试查询...")
    logger.info("=" * 60)
    
    success_count = 0
    fail_count = 0
    
    for i, (question, expected) in enumerate(TEST_CASES, 1):
        logger.info(f"\n🔍 测试 {i}/{len(TEST_CASES)}: {question}")
        logger.debug(f"💡 预期: {expected}")
        
        try:
            result = agent.invoke({"input": question})
            output = result.get("output", str(result)).strip()
            if not output:
                output = "<空响应>"
            logger.info(f"✅ 回答：{output[:500]}{'...' if len(output) > 500 else ''}")
            success_count += 1
        except Exception as e:
            logger.error(f"❌ 执行错误：{type(e).__name__}: {e}", exc_info=True)
            fail_count += 1
    
    logger.info("=" * 60)
    logger.info(f"📊 测试结果: 成功 {success_count} / 失败 {fail_count}")
    logger.info("=" * 60)


def interactive_mode(agent, logger: logging.Logger):
    """原始交互式问答（无记忆操作指令）"""
    logger.info("\n💬 进入交互模式（输入 quit / exit / q 退出）")
    logger.info("=" * 60)
    
    query_count = 0
    error_count = 0

    while True:
        try:
            user_input = input("\n❓ 您的问题：").strip()
            # 退出指令
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