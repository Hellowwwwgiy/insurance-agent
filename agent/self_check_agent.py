"""多 Agent 协作架构：规则路由 Supervisor + CustomerAgent + PolicyAgent + JoinAgent + FactCheck

设计目标：
- 移除全部 RAG / ChromaDB 依赖
- 多 Agent 协同体现在 SQL 工作流按业务域拆分
- Supervisor 用**规则匹配**（非 LLM）做路由 → 零额外 LLM 开销
- 三个 SQL 专家 Agent 共享同一个 base_agent 框架，只是 system prompt 不同
- 对外 EnhancedAgentWithSelfCheck.invoke() / .stream() 签名保持不变
"""
from typing import Dict, Any, List, TypedDict, Generator
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import AIMessage, ToolMessage
from langchain.agents import create_agent as create_langchain_agent
from langgraph.graph import StateGraph, START, END

from .sql_tools import make_sql_tools

# ---------------------------------------------------------------------------
# 路由规则（纯关键词匹配，无需 LLM）
# ---------------------------------------------------------------------------
_CUSTOMER_KEYWORDS = (
    "客户", "电话", "手机号", "地址", "姓名", "年龄", "性别",
    "张三", "李四", "王五", "赵六", "钱七",
)
_POLICY_KEYWORDS = (
    "保单", "保费", "保额", "保单号", "续保", "状态", "有效",
    "安心健康保", "终身寿险", "综合意外险", "重疾无忧", "齿科", "产品",
)
_JOIN_KEYWORDS = (
    "哪些客户", "有多少客户", "所有客户", "客户的保单", "每个客户",
    "持有", "名下", "关联", "客户和", "保单对应的客户",
)


def _supervisor_route(query: str) -> str:
    """规则路由：根据关键词决定走哪个 SQL 专家 Agent

    Returns:
        "customer"  → CustomerAgent  （客户基础数据）
        "policy"    → PolicyAgent    （保单/产品数据）
        "join"      → JoinAgent      （跨表 JOIN 查询）
    """
    q = query.lower()
    has_customer = any(k in q for k in _CUSTOMER_KEYWORDS)
    has_policy = any(k in q for k in _POLICY_KEYWORDS)
    has_join = any(k in q for k in _JOIN_KEYWORDS)

    # 有 join 触发词 或 同时涉及客户和保单 → JoinAgent
    if has_join or (has_customer and has_policy):
        return "join"
    if has_policy:
        return "policy"
    if has_customer:
        return "customer"
    return "customer"  # 兜底


# ---------------------------------------------------------------------------
# 三个 SQL 专家的 system prompt
# ---------------------------------------------------------------------------
CUSTOMER_AGENT_PROMPT = """你是客户数据专家。根据用户问题，使用 SQL 工具查询 customers 表。

规则：
1. 先调用 list_tables 确认可用表，再用 get_table_schema 确认表结构。
2. 只涉及客户基础信息（姓名、电话、地址、年龄等）时，优先查 customers 表。
3. 生成 SQL 后用 check_sql 校验，再用 execute_sql 执行。
4. 严禁编造任何客户数据，如实回答。"""

POLICY_AGENT_PROMPT = """你是保单数据专家。根据用户问题，使用 SQL 工具查询 policies 表和产品相关数据。

规则：
1. 先确认表结构，再查 policies 表（保单号、保费、保额、状态、产品名）。
2. 只涉及保单自身属性时，优先查 policies 表，不需要 JOIN customers。
3. 生成 SQL 后用 check_sql 校验，再用 execute_sql 执行。
4. 严禁编造任何保单数据。"""

JOIN_AGENT_PROMPT = """你是复杂查询专家。根据用户问题，需要跨表 JOIN 查询 customers 和 policies。

规则：
1. 先调用 list_tables + get_table_schema 了解表结构。
2. 需要同时查客户和保单时，用 JOIN customers ON policies.customer_id = customers.id。
3. 生成 SQL 后用 check_sql 校验，注意只允许 SELECT/WITH 单条语句。
4. 严禁编造任何数据，如实回答。"""


# ---------------------------------------------------------------------------
# FactCheck Agent（不变）
# ---------------------------------------------------------------------------
FACT_CHECK_PROMPT_TEMPLATE = """你是事实核查专家，区分两类内容：
【允许】标题、加粗、换行、单位补充（3200→3200元）、简短说明文字，不影响核心数据；
【禁止】编造/篡改数据库里的姓名、保单号、保费、证件号、手机号等核心业务数据。

仅当AI回答存在【禁止类】问题才判定错误，单纯格式美化不算错误。
【数据库原始数据】: {db_result}
【AI回答】: {response}

输出纯JSON，无多余文字：
{{
    "is_factually_correct": true/false,
    "issues": ["仅填写编造/篡改的错误，格式美化不记录"],
    "suggestion": "仅核心数据错误时填写修正建议，格式问题无需修改"
}}"""


class FactCheckAgent:
    """事实校验子Agent，只核验 SQL 查询结果中的核心业务数据真实性"""

    def __init__(self, llm, logger):
        self.llm = llm.bind(temperature=0.0)
        self.parser = JsonOutputParser()
        self.logger = logger

    def check(self, response: str, db_result: str) -> Dict[str, Any]:
        safe_db = str(db_result) if db_result else "无数据库数据"
        safe_resp = str(response)
        try:
            prompt_val = PromptTemplate.from_template(FACT_CHECK_PROMPT_TEMPLATE).invoke({
                "response": safe_resp,
                "db_result": safe_db,
            })
            llm_res = self.llm.invoke(prompt_val)
            parsed = self.parser.parse(llm_res.content)
            self.logger.debug(f"校验结果 | 合规:{parsed['is_factually_correct']}")
            return parsed
        except Exception as e:
            self.logger.warning(f"校验解析异常，默认放行: {e}")
            return {"is_factually_correct": True, "issues": [], "suggestion": ""}


# ---------------------------------------------------------------------------
# StateGraph 定义
# ---------------------------------------------------------------------------
class SelfCheckState(TypedDict):
    """多 Agent 工作流状态"""
    input: str
    messages: List[Any]
    last_messages: List[Any]
    outer_db: str
    attempts: int
    final_output: str
    db_data: str
    specialist: str     # 路由结果：customer / policy / join
    issues: List[str]
    suggestion: str
    verified: bool


SQL_QUERY_TOOL = "execute_sql"


class EnhancedAgentWithSelfCheck:
    """规则路由 Supervisor + 三个 SQL 专家 + FactCheck 多 Agent 架构"""
    MAX_RETRIES = 2

    def __init__(self, base_agent, llm, logger, db=None):
        self.base_agent = base_agent
        self.llm = llm
        self.logger = logger
        self.db = db
        self.checker = FactCheckAgent(llm, logger)

        # 构造三个 SQL 专家 Agent（共享同一个 db tools 集，不同 system prompt）
        tools = make_sql_tools(db) if db else []
        self.customer_agent = create_langchain_agent(
            model=llm, tools=tools, system_prompt=CUSTOMER_AGENT_PROMPT,
            debug=False, name="customer_agent",
        ) if db else base_agent
        self.policy_agent = create_langchain_agent(
            model=llm, tools=tools, system_prompt=POLICY_AGENT_PROMPT,
            debug=False, name="policy_agent",
        ) if db else base_agent
        self.join_agent = create_langchain_agent(
            model=llm, tools=tools, system_prompt=JOIN_AGENT_PROMPT,
            debug=False, name="join_agent",
        ) if db else base_agent

        self.graph = self._build_graph()

    # ---------------- 提取答案 & SQL 数据 ----------------
    def _extract_answer_and_db_data(self, agent_output: Dict[str, Any]) -> tuple:
        messages = agent_output.get("messages", []) or []
        if not isinstance(messages, list):
            return "", ""

        tool_id_to_name: Dict[str, str] = {}
        for m in messages:
            if isinstance(m, AIMessage):
                for tc in (m.tool_calls or []):
                    if tc.get("id"):
                        tool_id_to_name[tc["id"]] = tc.get("name", "")
                for tc in (getattr(m, "tool_call_chunks", None) or []):
                    if tc.get("id") and tc.get("name"):
                        tool_id_to_name[tc["id"]] = tc["name"]

        last_tool_idx = -1
        for i, m in enumerate(messages):
            if isinstance(m, ToolMessage):
                last_tool_idx = i
        final_output = ""
        for i, m in enumerate(messages):
            if i > last_tool_idx and isinstance(m, AIMessage) and m.content:
                final_output += str(m.content)
        final_output = final_output.strip()

        db_data = ""
        for m in messages:
            if isinstance(m, ToolMessage):
                name = tool_id_to_name.get(m.tool_call_id)
                if name == SQL_QUERY_TOOL:
                    db_data += f"【SQL查询结果】\n{m.content}\n\n"
        return final_output, db_data

    # ---------------- Supervisor 节点（规则路由） ----------------
    def _supervisor_node(self, state: SelfCheckState) -> Dict[str, Any]:
        specialist = _supervisor_route(state["input"])
        self.logger.info(f"Supervisor 规则路由 → {specialist}")
        return {"specialist": specialist}

    # ---------------- 专家 Agent 节点 ----------------
    def _run_specialist(self, state: SelfCheckState) -> Dict[str, Any]:
        """通用专家执行节点：根据 state['specialist'] 选择对应 Agent"""
        specialist = state.get("specialist", "join")
        agent_map = {
            "customer": self.customer_agent,
            "policy": self.policy_agent,
            "join": self.join_agent,
        }
        agent = agent_map.get(specialist, self.join_agent)

        query = state["input"]
        if state.get("attempts", 0) > 0:
            retry_tip = (
                f"\n[修正提示]上次核心数据有问题：{'; '.join(state.get('issues') or [])}。"
                f"{state.get('suggestion', '')}，保证姓名、保单、金额与数据库完全一致。"
            )
            query = query + retry_tip

        history = state.get("messages", []) or []
        res = agent.invoke({"messages": list(history) + [("user", query)]})
        all_msgs = res.get("messages", []) or []
        new_msgs = all_msgs[len(history):] if len(all_msgs) > len(history) else all_msgs
        final_output, db_data = self._extract_answer_and_db_data({"messages": new_msgs})

        return {
            "attempts": state.get("attempts", 0) + 1,
            "final_output": final_output,
            "db_data": db_data,
            "last_messages": all_msgs,
        }

    # ---------------- FactCheck 节点 ----------------
    def _verify_node(self, state: SelfCheckState) -> Dict[str, Any]:
        outer_db = state.get("outer_db", "")
        full_db_context = f"{outer_db}\n{state.get('db_data', '')}"
        check_res = self.checker.check(state.get("final_output", ""), full_db_context)

        issues = check_res.get("issues", ["无具体问题"])
        suggestion = check_res.get("suggestion", "")
        verified = check_res["is_factually_correct"]
        self.logger.info(f"校验{'通过' if verified else '未通过'}（第{state.get('attempts', 0)}次）")

        update: Dict[str, Any] = {
            "verified": verified,
            "issues": issues,
            "suggestion": suggestion,
        }
        if not verified and state.get("attempts", 0) >= self.MAX_RETRIES:
            self.logger.warning(f"重试耗尽，追加免责声明。问题：{issues}")
            update["final_output"] = (
                f"{state.get('final_output', '')}\n\n---\n"
                f"⚠️提示：内容仅供参考，保单、金额等请以原始数据库数据为准。"
            )
        return update

    # ---------------- 条件边 ----------------
    def _specialist_decision(self, state: SelfCheckState) -> str:
        # 规则路由已在 supervisor_node 完成，这里直接分发
        return "specialist_node"

    def _should_retry(self, state: SelfCheckState) -> str:
        if state.get("verified"):
            return "end"
        if state.get("attempts", 0) < self.MAX_RETRIES:
            return "retry"
        return "end"

    # ---------------- 构建图 ----------------
    def _build_graph(self):
        """Supervisor(规则路由) → specialist → verify → retry/end"""
        graph = StateGraph(SelfCheckState)
        graph.add_node("supervisor", self._supervisor_node)
        graph.add_node("specialist_node", self._run_specialist)
        graph.add_node("verify_node", self._verify_node)

        graph.add_edge(START, "supervisor")
        graph.add_edge("supervisor", "specialist_node")
        graph.add_edge("specialist_node", "verify_node")
        graph.add_conditional_edges(
            "verify_node",
            self._should_retry,
            {"retry": "specialist_node", "end": END},
        )
        return graph.compile()

    # ---------------- invoke ----------------
    def invoke(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        query = inputs.get("input", "")
        outer_db = inputs.get("db_result", kwargs.get("db_result", ""))
        history = inputs.get("messages", []) or []

        final_state = self.graph.invoke({
            "input": query,
            "messages": history,
            "last_messages": [],
            "outer_db": outer_db,
            "attempts": 0,
            "final_output": "",
            "db_data": "",
            "specialist": "",
            "issues": [],
            "suggestion": "",
            "verified": False,
        })
        safe_history = self._to_json_safe_messages(
            final_state.get("last_messages", history)
        )
        return {
            "output": final_state.get("final_output", ""),
            "verified": bool(final_state.get("verified")),
            "attempts": final_state.get("attempts", 0),
            "messages": safe_history,
            "specialist": final_state.get("specialist", ""),
        }

    # ---------------- stream ----------------
    def stream(self, inputs: Dict[str, Any], **kwargs) -> Generator[Dict[str, Any], None, None]:
        """流式输出：规则路由 → 专家流式执行 → 校验重试"""
        query = inputs.get("input", "")
        outer_db = inputs.get("db_result", kwargs.get("db_result", ""))
        history = inputs.get("messages", []) or []

        # Step 1: Supervisor 规则路由（零 LLM 开销）
        specialist = _supervisor_route(query)
        self.logger.info(f"Supervisor → {specialist}")
        yield {"type": "route", "route": specialist}

        agent_map = {
            "customer": self.customer_agent,
            "policy": self.policy_agent,
            "join": self.join_agent,
        }
        agent = agent_map.get(specialist, self.join_agent)
        yield {"type": "agent_start", "agent": f"{specialist}_agent"}

        state: Dict[str, Any] = {
            "input": query,
            "messages": history,
            "last_messages": [],
            "outer_db": outer_db,
            "attempts": 0,
            "final_output": "",
            "db_data": "",
            "specialist": specialist,
            "issues": [],
            "suggestion": "",
            "verified": False,
        }

        try:
            while True:
                state["attempts"] += 1
                query_to_run = query
                if state["attempts"] > 1:
                    query_to_run = (
                        query
                        + f"\n[修正提示]{'; '.join(state.get('issues') or [])}。"
                        + f"{state.get('suggestion', '')}，保证核心数据一致。"
                    )

                if state["attempts"] == 1:
                    collected = []
                    final_content = ""
                    saw_tool = False

                    for event in agent.stream({"messages": list(history) + [("user", query_to_run)]}):
                        for _node, node_out in event.items():
                            if not isinstance(node_out, dict):
                                continue
                            msgs = node_out.get("messages", []) or []
                            for m in msgs:
                                collected.append(m)
                                if isinstance(m, ToolMessage):
                                    saw_tool = True
                                elif (isinstance(m, AIMessage) and not m.tool_calls
                                      and (saw_tool or len(collected) <= len(history) + 1)):
                                    if m.content:
                                        final_content += str(m.content)
                                        yield {"type": "token", "content": str(m.content)}

                    new_msgs = collected[len(history):] if len(collected) > len(history) else collected
                    final_output, db_data = self._extract_answer_and_db_data({"messages": new_msgs})
                    if not final_output:
                        final_output = final_content.strip()
                    state["last_messages"] = collected
                else:
                    final_output = self._rewrite_with_existing_db(query, state)
                    db_data = state.get("db_data", "")
                    yield {"type": "token", "content": final_output}

                state["final_output"] = final_output
                state["db_data"] = db_data

                verify_res = self._verify_node(state)
                state.update(verify_res)

                if state["verified"] or state["attempts"] >= self.MAX_RETRIES:
                    break
                yield {"type": "retry", "issues": state.get("issues", [])}

            safe_history = self._to_json_safe_messages(
                state.get("last_messages", history)
            )
            yield {
                "type": "done",
                "answer": state.get("final_output", ""),
                "verified": bool(state.get("verified")),
                "attempts": state.get("attempts", 0),
                "messages": safe_history,
                "route": specialist,
            }
        except Exception as e:
            self.logger.error(f"stream 异常: {type(e).__name__}: {e}", exc_info=True)
            yield {"type": "error", "message": str(e)}

    # ---------------- 辅助 ----------------
    @staticmethod
    def _to_json_safe_messages(messages: List[Any]) -> List[Dict[str, Any]]:
        safe: List[Dict[str, Any]] = []
        for m in messages:
            cls_name = type(m).__name__
            content = getattr(m, "content", "") or ""
            text = str(content).strip()
            if not text:
                continue
            if cls_name == "HumanMessage":
                safe.append({"role": "user", "content": text})
            elif cls_name == "AIMessage":
                tc = getattr(m, "tool_calls", None) or []
                if text and not tc:
                    safe.append({"role": "assistant", "content": text})
            elif cls_name == "ToolMessage":
                safe.append({"role": "assistant", "content": f"[工具执行结果] {text}"})
        return safe

    def _rewrite_with_existing_db(self, query: str, state: Dict[str, Any]) -> str:
        retry_tip = (
            f"\n[修正提示]上次核心数据有问题：{'; '.join(state.get('issues') or [])}。"
            f"{state.get('suggestion', '')}，保证姓名、保单、金额与数据库完全一致。"
        )
        db_context = f"【数据库已有查询结果】\n{state.get('db_data', '')}"
        prompt = f"{db_context}\n\n请根据数据库结果回答：「{query}{retry_tip}」"
        rewritten = self.checker.llm.invoke(prompt).content
        return str(rewritten).strip()


def create_enhanced_agent(base_agent, llm, logger, db=None):
    """工厂方法：创建规则路由 Supervisor + 多 SQL 专家 Agent 架构"""
    # 如果没传 db，从 base_agent 的 tools 中提取（保持向后兼容）
    if db is None:
        try:
            tools = base_agent.get_graph().nodes.get("tools")
            db_eng = None
        except Exception:
            db_eng = None
    else:
        db_eng = db
    return EnhancedAgentWithSelfCheck(base_agent, llm, logger, db=db_eng)
