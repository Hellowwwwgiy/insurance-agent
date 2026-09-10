from langchain_openai import ChatOpenAI
from langchain.agents import create_agent as create_langchain_agent
from sqlalchemy import Engine

from .config import Settings
from .sql_tools import make_sql_tools

# 保险业务提示词（工具名与 sql_tools.py 保持一致）
SQL_AGENT_SYSTEM_PROMPT = """你是保险行业数据库查询专家。请根据用户的自然语言问题，使用提供的 SQL 工具查询 PostgreSQL 数据库，并给出准确的中文回答。

规则：
1. 先调用 list_tables 查看可用表，再用 get_table_schema 确认表结构，最后用 execute_sql 执行查询。
2. 生成 SQL 后用 check_sql 校验语法与只读性。
3. 只回答数据库中存在的数据，严禁编造姓名、保单号、保费、证件号、手机号等核心业务数据。
4. 查询结果为空时如实说明，不要虚构结果。
5. 用简洁、口语化的中文组织答案，金额等单位可补充说明。"""

def create_llm(settings: Settings, logger=None) -> ChatOpenAI:
    """初始化 DeepSeek LLM（无记忆相关逻辑）"""
    if logger:
        logger.info("⏳ 初始化 DeepSeek LLM...")

    llm = ChatOpenAI(
        model="deepseek-chat",
        temperature=0,
        api_key=settings.deepseek_api_key,
        base_url="https://api.deepseek.com/v1",
        max_tokens=2000,
        timeout=60
    )

    if logger:
        logger.info("✅ DeepSeek LLM 初始化成功")

    return llm

def create_agent(llm: ChatOpenAI, db: Engine, logger=None):
    """创建基于 LangChain 1.x create_agent（底层 LangGraph）的 SQL Agent"""
    if logger:
        logger.info("⏳ 正在创建 SQL Agent...")

    tools = make_sql_tools(db)
    agent = create_langchain_agent(
        model=llm,
        tools=tools,
        system_prompt=SQL_AGENT_SYSTEM_PROMPT,
        debug=True,
        name="insurance_sql_agent",
    )

    if logger:
        logger.info("✅ SQL Agent 创建成功！")
        logger.info("=" * 60)

    return agent
