"""
保险智能助手 Agent 模块
"""
import logging
from typing import Optional, Dict, Any
from langchain_openai import ChatOpenAI
from langchain_community.agent_toolkits import create_sql_agent

logger = logging.getLogger(__name__)

class InsuranceAgent:
    """保险智能助手 Agent"""
    
    def __init__(
        self,
        llm: ChatOpenAI,
        db,
        agent_type: str = "openai-tools",
        verbose: bool = True,
        max_iterations: int = 3,
        handle_parsing_errors: bool = True
    ):
        """
        初始化保险助手 Agent
        
        Args:
            llm: 语言模型实例
            db: 数据库实例
            agent_type: Agent 类型
            verbose: 是否显示详细日志
            max_iterations: 最大迭代次数
            handle_parsing_errors: 是否处理解析错误
        """
        self.llm = llm
        self.db = db
        self.agent_type = agent_type
        self.verbose = verbose
        self.max_iterations = max_iterations
        self.handle_parsing_errors = handle_parsing_errors
        self.agent = None
        
    def create(self):
        """创建 Agent"""
        try:
            logger.info("⏳ 正在创建 SQL Agent...")
            
            self.agent = create_sql_agent(
                llm=self.llm,
                db=self.db,
                agent_type=self.agent_type,
                verbose=self.verbose,
                handle_parsing_errors=self.handle_parsing_errors,
                max_iterations=self.max_iterations
            )
            
            logger.info("✅ SQL Agent 创建成功！")
            return True
            
        except Exception as e:
            logger.error(f"❌ Agent 创建失败: {e}", exc_info=True)
            return False
    
    def query(self, question: str) -> Dict[str, Any]:
        """
        执行查询
        
        Args:
            question: 用户问题
            
        Returns:
            包含结果的字典
        """
        if not self.agent:
            raise RuntimeError("Agent 未初始化，请先调用 create() 方法")
        
        try:
            logger.info(f"🔍 查询: {question}")
            
            result = self.agent.invoke({"input": question})
            output = result.get("output", str(result)).strip()
            
            logger.info(f"✅ 回答: {output[:100]}{'...' if len(output) > 100 else ''}")
            
            return {
                "success": True,
                "question": question,
                "answer": output,
                "raw_result": result
            }
            
        except Exception as e:
            logger.error(f"❌ 查询失败: {e}", exc_info=True)
            return {
                "success": False,
                "question": question,
                "error": str(e),
                "answer": None
            }
    
    def batch_query(self, questions: list) -> list:
        """
        批量查询
        
        Args:
            questions: 问题列表
            
        Returns:
            结果列表
        """
        results = []
        for i, question in enumerate(questions, 1):
            logger.info(f"🔍 批量查询 {i}/{len(questions)}: {question}")
            result = self.query(question)
            results.append(result)
        return results
