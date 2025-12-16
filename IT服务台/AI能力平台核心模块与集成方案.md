# AI能力平台核心模块与集成方案

## 一、RAG引擎详细设计

### 1.1 RAG架构

```
┌─────────────────────────────────────────────────────────────┐
│               RAG引擎（检索增强生成）                          │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Query处理层:                                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Query理解                                            │   │
│  │  ├─ 意图识别（分类：FAQ/工单/诊断/咨询）             │   │
│  │  ├─ 实体抽取（产品型号、错误代码、组件名称）         │   │
│  │  ├─ Query改写（同义词扩展、拼写纠正）                │   │
│  │  └─ Query扩充（生成变体查询）                        │   │
│  └──────────────────────────────────────────────────────┘   │
│                         ↓                                     │
│  检索层:                                                      │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  多路召回                                             │   │
│  │  ├─ 向量检索（Milvus）         权重 70%              │   │
│  │  ├─ 全文检索（Elasticsearch）   权重 20%              │   │
│  │  ├─ BM25检索（稀疏检索）        权重 10%              │   │
│  │  └─ 结果融合（RRF / 加权）                           │   │
│  └──────────────────────────────────────────────────────┘   │
│                         ↓                                     │
│  重排序层:                                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  精排模型                                             │   │
│  │  ├─ BGE-Reranker（相关性打分）                       │   │
│  │  ├─ LLM-Reranker（深度理解，可选）                   │   │
│  │  └─ Top K选择（默认5-10个）                          │   │
│  └──────────────────────────────────────────────────────┘   │
│                         ↓                                     │
│  生成层:                                                      │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  上下文构建                                           │   │
│  │  ├─ Prompt模板选择                                    │   │
│  │  ├─ Context注入（检索到的知识）                      │   │
│  │  └─ Token长度控制（避免超限）                        │   │
│  └──────────────────────────────────────────────────────┘   │
│                         ↓                                     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  LLM生成                                              │   │
│  │  ├─ 云端模型（GPT-4 / 通义千问）                      │   │
│  │  ├─ 本地模型（Qwen-7B）                               │   │
│  │  └─ 流式输出（实时返回）                             │   │
│  └──────────────────────────────────────────────────────┘   │
│                         ↓                                     │
│  后处理层:                                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  答案优化                                             │   │
│  │  ├─ 引用标注（显示知识来源）                         │   │
│  │  ├─ Markdown格式化                                    │   │
│  │  ├─ 敏感信息过滤                                      │   │
│  │  └─ 质量检测（幻觉检测）                             │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 RAG核心代码实现

```python
# rag_engine.py
from typing import List, Dict, Optional, AsyncIterator
from dataclasses import dataclass
import asyncio

@dataclass
class RetrievalResult:
    """检索结果"""
    kb_id: str
    title: str
    content: str
    score: float
    source: str  # "knowledge_base" | "faq" | "ticket_history"

@dataclass
class RAGResponse:
    """RAG响应"""
    answer: str
    references: List[RetrievalResult]
    confidence: float
    metadata: Dict

class RAGEngine:
    """RAG引擎"""

    def __init__(
        self,
        knowledge_retrieval_engine,  # 知识检索引擎
        llm_service_manager,  # LLM服务管理器
        prompt_manager  # Prompt管理器
    ):
        self.retrieval_engine = knowledge_retrieval_engine
        self.llm_manager = llm_service_manager
        self.prompt_manager = prompt_manager

    async def generate(
        self,
        query: str,
        conversation_history: Optional[List[Dict]] = None,
        stream: bool = False,
        **kwargs
    ) -> RAGResponse:
        """
        RAG生成

        Args:
            query: 用户问题
            conversation_history: 对话历史
            stream: 是否流式输出
            kwargs: 其他参数

        Returns:
            RAGResponse: 包含答案和引用
        """
        # 1. Query理解
        processed_query = await self._process_query(query, conversation_history)

        # 2. 检索相关知识
        retrieval_results = await self._retrieve(processed_query, **kwargs)

        # 3. 构建Prompt
        prompt = await self._build_prompt(
            query=query,
            contexts=retrieval_results,
            conversation_history=conversation_history
        )

        # 4. LLM生成
        if stream:
            # 流式生成
            return self._generate_stream(prompt, retrieval_results)
        else:
            # 一次性生成
            answer = await self._generate_once(prompt)

            # 5. 后处理
            final_answer = await self._post_process(answer, retrieval_results)

            return RAGResponse(
                answer=final_answer,
                references=retrieval_results,
                confidence=self._calculate_confidence(retrieval_results),
                metadata={
                    "retrieval_count": len(retrieval_results),
                    "model_used": self.llm_manager.last_used_model
                }
            )

    async def _process_query(
        self,
        query: str,
        conversation_history: Optional[List[Dict]]
    ) -> str:
        """
        Query理解与处理

        步骤:
        1. 意图识别
        2. 实体抽取
        3. 上下文补全（多轮对话）
        4. Query改写
        """
        # 1. 如果是多轮对话，补全上下文
        if conversation_history:
            query = await self._complete_query_context(query, conversation_history)

        # 2. Query改写（同义词、拼写纠正等）
        enhanced_query = await self._enhance_query(query)

        return enhanced_query

    async def _complete_query_context(
        self,
        query: str,
        conversation_history: List[Dict]
    ) -> str:
        """
        上下文补全（针对多轮对话）

        示例:
        用户: "VDI客户端登录失败怎么办？"
        AI: "请问是什么错误提示？"
        用户: "提示密码错误"  ← 需要补全上下文

        补全后: "VDI客户端登录时提示密码错误怎么办？"
        """
        if len(conversation_history) < 2:
            return query

        # 使用LLM补全上下文
        context_messages = conversation_history[-4:]  # 最近2轮对话
        context_messages.append({"role": "user", "content": query})

        completion_prompt = """
        请将以下对话中的最后一条用户消息补全为一个独立完整的问题。
        如果已经是完整问题，直接返回原文。

        对话历史:
        {conversation}

        请只返回补全后的问题，不要有任何解释。
        """

        conversation_text = "\n".join([
            f"{msg['role']}: {msg['content']}"
            for msg in context_messages
        ])

        response = await self.llm_manager.chat(
            messages=[{
                "role": "user",
                "content": completion_prompt.format(conversation=conversation_text)
            }],
            temperature=0.3,
            model_type="local"  # 使用本地模型（快速+低成本）
        )

        return response.strip()

    async def _enhance_query(self, query: str) -> str:
        """Query增强"""
        # 同义词扩展
        synonyms = {
            "密码": "密码 口令 登录密码",
            "卡顿": "卡顿 慢 性能差 延迟高",
            "重启": "重启 重新启动 restart",
            "无法": "无法 不能 失败",
        }

        enhanced = query
        for key, value in synonyms.items():
            if key in query:
                enhanced += " " + value
                break  # 只扩展一次

        return enhanced

    async def _retrieve(
        self,
        query: str,
        top_k: int = 5,
        **kwargs
    ) -> List[RetrievalResult]:
        """检索相关知识"""
        # 调用知识检索引擎
        results = await self.retrieval_engine.search(
            query=query,
            top_k=top_k,
            use_rerank=True,
            **kwargs
        )

        # 转换为RetrievalResult
        retrieval_results = []
        for r in results:
            retrieval_results.append(RetrievalResult(
                kb_id=r['kb_id'],
                title=r['title'],
                content=r['content'],
                score=r['final_score'],
                source='knowledge_base'
            ))

        return retrieval_results

    async def _build_prompt(
        self,
        query: str,
        contexts: List[RetrievalResult],
        conversation_history: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """构建Prompt"""
        # 1. 选择Prompt模板
        template = self.prompt_manager.get_template("rag_qa")

        # 2. 构建上下文文本
        context_text = self._format_contexts(contexts)

        # 3. 构建消息列表
        messages = []

        # 系统Prompt
        system_prompt = template['system'].format(
            current_date=datetime.now().strftime("%Y-%m-%d")
        )
        messages.append({"role": "system", "content": system_prompt})

        # 对话历史（最近3轮）
        if conversation_history:
            messages.extend(conversation_history[-6:])  # 3轮对话 = 6条消息

        # 用户问题 + 上下文
        user_prompt = template['user'].format(
            contexts=context_text,
            query=query
        )
        messages.append({"role": "user", "content": user_prompt})

        # 4. Token长度控制
        messages = self._truncate_messages(messages, max_tokens=4000)

        return messages

    def _format_contexts(self, contexts: List[RetrievalResult]) -> str:
        """格式化上下文"""
        if not contexts:
            return "未找到相关知识。"

        formatted = []
        for i, ctx in enumerate(contexts, 1):
            formatted.append(f"""
【知识{i}】
标题: {ctx.title}
内容: {ctx.content}
相关度: {ctx.score:.2f}
""")

        return "\n".join(formatted)

    def _truncate_messages(
        self,
        messages: List[Dict],
        max_tokens: int = 4000
    ) -> List[Dict]:
        """截断消息以避免Token超限"""
        # 简单实现：从对话历史开始截断
        # 实际应使用tokenizer精确计算
        total_length = sum(len(msg['content']) for msg in messages)

        if total_length > max_tokens * 3:  # 粗略估计1 token ≈ 3 chars
            # 保留系统Prompt和最后的用户消息
            truncated = [messages[0]]  # system
            truncated.extend(messages[-2:])  # 最近1轮对话
            return truncated

        return messages

    async def _generate_once(self, prompt: List[Dict]) -> str:
        """一次性生成"""
        response = await self.llm_manager.chat(
            messages=prompt,
            temperature=0.7,
            stream=False
        )
        return response

    async def _generate_stream(
        self,
        prompt: List[Dict],
        retrieval_results: List[RetrievalResult]
    ) -> AsyncIterator[str]:
        """流式生成"""
        async for chunk in self.llm_manager.chat(
            messages=prompt,
            temperature=0.7,
            stream=True
        ):
            yield chunk

    async def _post_process(
        self,
        answer: str,
        retrieval_results: List[RetrievalResult]
    ) -> str:
        """后处理：添加引用、格式化等"""
        # 1. 添加引用标注
        if retrieval_results:
            references = "\n\n---\n**参考来源：**\n"
            for i, ref in enumerate(retrieval_results[:3], 1):  # 只显示Top3
                references += f"{i}. [{ref.title}] (相关度: {ref.score:.2f})\n"

            answer += references

        # 2. Markdown格式化
        answer = self._format_markdown(answer)

        return answer

    def _format_markdown(self, text: str) -> str:
        """Markdown格式化"""
        # 简单处理：确保代码块正确格式化
        # 实际可以更复杂
        return text

    def _calculate_confidence(self, retrieval_results: List[RetrievalResult]) -> float:
        """计算置信度"""
        if not retrieval_results:
            return 0.0

        # 基于Top1的相关度得分
        top_score = retrieval_results[0].score
        confidence = min(1.0, top_score)

        return confidence


# Prompt管理器
class PromptManager:
    """Prompt模板管理"""

    def __init__(self):
        self.templates = {
            "rag_qa": {
                "system": """你是IT服务台的智能助手。
当前日期: {current_date}

职责:
1. 基于提供的知识库内容回答用户问题
2. 如果知识库中没有答案，明确告知用户
3. 回答要专业、准确、易懂
4. 提供步骤化的解决方案

注意事项:
- 严格基于知识库内容，不要编造信息
- 如果不确定，引导用户创建工单
- 保持专业和友好的语气
""",
                "user": """
请基于以下知识库内容回答用户问题。

知识库内容:
{contexts}

用户问题:
{query}

请提供详细的解决方案。如果知识库中没有相关信息，请明确告知用户并建议创建工单。
"""
            },
            "ticket_extract": {
                "system": """你是工单信息提取助手。
从用户描述中提取结构化的工单信息。
输出JSON格式。
""",
                "user": """
用户描述:
{description}

请提取以下信息（JSON格式）:
{{
    "title": "工单标题（简洁明确）",
    "category": "问题类型",
    "priority": "优先级（low/medium/high/urgent）",
    "tags": ["标签1", "标签2"]
}}
"""
            }
        }

    def get_template(self, template_name: str) -> Dict:
        """获取Prompt模板"""
        return self.templates.get(template_name, {})

    def add_template(self, name: str, template: Dict):
        """添加模板"""
        self.templates[name] = template


# 使用示例
async def main():
    # 初始化
    rag_engine = RAGEngine(
        knowledge_retrieval_engine=knowledge_retrieval_engine,
        llm_service_manager=llm_service_manager,
        prompt_manager=PromptManager()
    )

    # 单轮对话
    response = await rag_engine.generate(
        query="VDI客户端无法登录怎么办？",
        stream=False
    )

    print("答案:", response.answer)
    print("参考来源:", len(response.references))
    print("置信度:", response.confidence)

    # 多轮对话
    conversation_history = [
        {"role": "user", "content": "VDI客户端无法登录"},
        {"role": "assistant", "content": "请问是什么错误提示？"},
    ]

    response = await rag_engine.generate(
        query="提示密码错误",
        conversation_history=conversation_history
    )
    print("答案:", response.answer)
```

---

## 二、Agent服务设计（可选高级功能）

### 2.1 Agent架构

```python
# agent_service.py
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass
from enum import Enum

class ToolType(Enum):
    """工具类型"""
    KNOWLEDGE_SEARCH = "knowledge_search"
    TICKET_QUERY = "ticket_query"
    TICKET_CREATE = "ticket_create"
    DATA_ANALYSIS = "data_analysis"
    SYSTEM_COMMAND = "system_command"

@dataclass
class Tool:
    """Agent工具"""
    name: str
    description: str
    func: Callable
    parameters: Dict

class ITServiceAgent:
    """IT服务台Agent"""

    def __init__(
        self,
        llm_service_manager,
        tools: List[Tool]
    ):
        self.llm_manager = llm_service_manager
        self.tools = {tool.name: tool for tool in tools}
        self.max_iterations = 5  # 最多执行5轮

    async def execute(
        self,
        task: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> Dict:
        """
        执行任务

        流程:
        1. 理解任务
        2. 制定计划
        3. 执行计划（调用工具）
        4. 结果汇总
        """
        # 1. 理解任务并制定计划
        plan = await self._plan(task)

        # 2. 执行计划
        execution_log = []
        final_result = None

        for iteration in range(self.max_iterations):
            # 2.1 决定下一步行动
            action = await self._decide_next_action(
                task=task,
                plan=plan,
                execution_log=execution_log
            )

            if action['type'] == 'finish':
                final_result = action['result']
                break

            # 2.2 执行行动
            try:
                result = await self._execute_action(action)
                execution_log.append({
                    "iteration": iteration + 1,
                    "action": action,
                    "result": result,
                    "status": "success"
                })
            except Exception as e:
                execution_log.append({
                    "iteration": iteration + 1,
                    "action": action,
                    "error": str(e),
                    "status": "failed"
                })

        # 3. 生成最终答案
        if not final_result:
            final_result = await self._synthesize_answer(
                task=task,
                execution_log=execution_log
            )

        return {
            "answer": final_result,
            "execution_log": execution_log,
            "iterations": len(execution_log)
        }

    async def _plan(self, task: str) -> List[str]:
        """制定计划"""
        planning_prompt = f"""
        任务: {task}

        请制定一个执行计划，列出需要执行的步骤。
        每个步骤用一句话描述。

        可用工具:
        {self._format_tools()}

        请只返回步骤列表，每行一个步骤。
        """

        response = await self.llm_manager.chat(
            messages=[{"role": "user", "content": planning_prompt}],
            temperature=0.3
        )

        # 解析步骤
        steps = [line.strip() for line in response.split('\n') if line.strip()]
        return steps

    async def _decide_next_action(
        self,
        task: str,
        plan: List[str],
        execution_log: List[Dict]
    ) -> Dict:
        """
        决定下一步行动（ReAct模式）

        返回格式:
        {
            "type": "tool_call" | "finish",
            "tool": "tool_name",
            "parameters": {...},
            "reason": "思考过程"
        }
        """
        # 构建当前状态
        current_state = self._format_execution_log(execution_log)

        decision_prompt = f"""
        任务: {task}

        计划:
        {chr(10).join([f"{i+1}. {step}" for i, step in enumerate(plan)])}

        已执行:
        {current_state}

        可用工具:
        {self._format_tools()}

        请决定下一步行动:
        1. 如果需要调用工具，输出: TOOL: 工具名 | 参数: {{...}} | 原因: ...
        2. 如果任务已完成，输出: FINISH: 最终答案

        请只返回一行决策。
        """

        response = await self.llm_manager.chat(
            messages=[{"role": "user", "content": decision_prompt}],
            temperature=0.3
        )

        # 解析决策
        if response.startswith("FINISH:"):
            return {
                "type": "finish",
                "result": response.replace("FINISH:", "").strip()
            }
        elif response.startswith("TOOL:"):
            # 解析工具调用
            parts = response.replace("TOOL:", "").split("|")
            tool_name = parts[0].strip()
            # 简化实现，实际需要更严谨的参数解析
            return {
                "type": "tool_call",
                "tool": tool_name,
                "parameters": {},  # 需要从parts[1]解析
                "reason": parts[2].replace("原因:", "").strip() if len(parts) > 2 else ""
            }

        return {"type": "finish", "result": "无法决策"}

    async def _execute_action(self, action: Dict) -> str:
        """执行行动"""
        tool_name = action['tool']
        parameters = action['parameters']

        if tool_name not in self.tools:
            raise ValueError(f"Tool {tool_name} not found")

        tool = self.tools[tool_name]
        result = await tool.func(**parameters)

        return result

    async def _synthesize_answer(
        self,
        task: str,
        execution_log: List[Dict]
    ) -> str:
        """综合生成最终答案"""
        synthesis_prompt = f"""
        任务: {task}

        执行过程:
        {self._format_execution_log(execution_log)}

        请基于以上执行结果，生成一个完整的答案。
        """

        response = await self.llm_manager.chat(
            messages=[{"role": "user", "content": synthesis_prompt}],
            temperature=0.7
        )

        return response

    def _format_tools(self) -> str:
        """格式化工具列表"""
        formatted = []
        for tool in self.tools.values():
            formatted.append(f"- {tool.name}: {tool.description}")
        return "\n".join(formatted)

    def _format_execution_log(self, execution_log: List[Dict]) -> str:
        """格式化执行日志"""
        if not execution_log:
            return "无"

        formatted = []
        for log in execution_log:
            formatted.append(f"""
步骤 {log['iteration']}:
  行动: {log.get('action', {}).get('tool', 'N/A')}
  结果: {log.get('result', log.get('error', 'N/A'))}
  状态: {log['status']}
""")
        return "\n".join(formatted)


# 定义工具
async def knowledge_search_tool(query: str) -> str:
    """知识检索工具"""
    results = await knowledge_retrieval_engine.search(query, top_k=3)
    return "\n".join([r['title'] for r in results])

async def ticket_query_tool(user_id: int) -> str:
    """工单查询工具"""
    # 调用业务平台API
    tickets = await business_api_client.get_tickets(user_id)
    return f"找到 {len(tickets)} 个工单"

async def ticket_create_tool(title: str, description: str) -> str:
    """工单创建工具"""
    ticket_id = await business_api_client.create_ticket(title, description)
    return f"工单已创建，编号: {ticket_id}"

# 初始化Agent
tools = [
    Tool(
        name="knowledge_search",
        description="搜索知识库，查找相关解决方案",
        func=knowledge_search_tool,
        parameters={"query": "str"}
    ),
    Tool(
        name="ticket_query",
        description="查询用户的工单列表",
        func=ticket_query_tool,
        parameters={"user_id": "int"}
    ),
    Tool(
        name="ticket_create",
        description="创建新工单",
        func=ticket_create_tool,
        parameters={"title": "str", "description": "str"}
    )
]

agent = ITServiceAgent(
    llm_service_manager=llm_service_manager,
    tools=tools
)
```

---

## 三、两平台集成方案

### 3.1 接口协议设计

#### IT服务台业务平台 → AI能力平台

```yaml
# 业务平台调用AI平台的接口

1. 智能问答接口
   POST /api/ai/chat
   {
     "session_id": "session_123",
     "message": "VDI登录失败怎么办？",
     "user_id": 12345,
     "conversation_history": [...]
   }
   响应:
   {
     "answer": "...",
     "references": [...],
     "confidence": 0.85
   }

2. 工单信息提取接口
   POST /api/ai/extract-ticket-info
   {
     "description": "用户描述的问题..."
   }
   响应:
   {
     "title": "VDI客户端登录失败",
     "category": "软件故障",
     "priority": "high",
     "tags": ["VDI", "登录"]
   }

3. 智能派单推荐接口
   POST /api/ai/recommend-engineer
   {
     "ticket_id": 12345,
     "category": "软件故障",
     "description": "..."
   }
   响应:
   {
     "engineer_id": 67890,
     "engineer_name": "张工",
     "confidence": 0.92,
     "reason": "该工程师处理过10个类似问题"
   }

4. 知识推荐接口
   POST /api/ai/recommend-knowledge
   {
     "ticket_id": 12345,
     "description": "..."
   }
   响应:
   {
     "knowledge_list": [
       {
         "kb_id": "KB001",
         "title": "...",
         "relevance_score": 0.88
       }
     ]
   }

5. 智能诊断接口（可选）
   POST /api/ai/diagnose
   {
     "logs": "...",
     "error_message": "..."
   }
   响应:
   {
     "diagnosis": "问题原因是...",
     "suggestions": ["建议1", "建议2"]
   }
```

#### AI能力平台 → IT服务台业务平台

```yaml
# AI平台调用业务平台的接口（Agent模式需要）

1. 查询工单接口
   GET /api/tickets?user_id=12345
   响应:
   {
     "tickets": [...]
   }

2. 创建工单接口
   POST /api/tickets
   {
     "user_id": 12345,
     "title": "...",
     "description": "..."
   }

3. 查询工程师信息接口
   GET /api/engineers?skills=VDI
   响应:
   {
     "engineers": [...]
   }

4. 查询用户信息接口
   GET /api/users/{user_id}
   响应:
   {
     "user": {...}
   }
```

### 3.2 集成SDK设计

```python
# ai_platform_sdk.py
"""IT服务台业务平台调用AI平台的SDK"""

import httpx
from typing import List, Dict, Optional

class AIPlatformClient:
    """AI平台客户端SDK"""

    def __init__(self, base_url: str, api_key: str, timeout: int = 60):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-API-Key": api_key},
            timeout=timeout
        )

    async def chat(
        self,
        message: str,
        session_id: str,
        user_id: int,
        conversation_history: Optional[List[Dict]] = None,
        stream: bool = False
    ) -> Dict:
        """
        智能问答

        Args:
            message: 用户消息
            session_id: 会话ID
            user_id: 用户ID
            conversation_history: 对话历史
            stream: 是否流式输出

        Returns:
            Dict: {answer, references, confidence}
        """
        payload = {
            "message": message,
            "session_id": session_id,
            "user_id": user_id,
            "conversation_history": conversation_history or [],
            "stream": stream
        }

        response = await self.client.post("/api/ai/chat", json=payload)
        response.raise_for_status()
        return response.json()

    async def extract_ticket_info(self, description: str) -> Dict:
        """
        提取工单信息

        Args:
            description: 用户描述

        Returns:
            Dict: {title, category, priority, tags}
        """
        payload = {"description": description}
        response = await self.client.post("/api/ai/extract-ticket-info", json=payload)
        response.raise_for_status()
        return response.json()

    async def recommend_engineer(
        self,
        ticket_id: int,
        category: str,
        description: str
    ) -> Dict:
        """
        推荐工程师

        Returns:
            Dict: {engineer_id, engineer_name, confidence, reason}
        """
        payload = {
            "ticket_id": ticket_id,
            "category": category,
            "description": description
        }
        response = await self.client.post("/api/ai/recommend-engineer", json=payload)
        response.raise_for_status()
        return response.json()

    async def recommend_knowledge(
        self,
        ticket_id: int,
        description: str,
        top_k: int = 5
    ) -> Dict:
        """
        推荐知识

        Returns:
            Dict: {knowledge_list: [...]}
        """
        payload = {
            "ticket_id": ticket_id,
            "description": description,
            "top_k": top_k
        }
        response = await self.client.post("/api/ai/recommend-knowledge", json=payload)
        response.raise_for_status()
        return response.json()

    async def diagnose(self, logs: str, error_message: str) -> Dict:
        """
        智能诊断

        Returns:
            Dict: {diagnosis, suggestions}
        """
        payload = {
            "logs": logs,
            "error_message": error_message
        }
        response = await self.client.post("/api/ai/diagnose", json=payload)
        response.raise_for_status()
        return response.json()

    async def close(self):
        """关闭客户端"""
        await self.client.aclose()


# business_platform_sdk.py
"""AI平台调用IT服务台业务平台的SDK"""

class BusinessPlatformClient:
    """业务平台客户端SDK"""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-API-Key": api_key}
        )

    async def get_tickets(self, user_id: int, status: Optional[str] = None) -> List[Dict]:
        """查询工单"""
        params = {"user_id": user_id}
        if status:
            params["status"] = status

        response = await self.client.get("/api/tickets", params=params)
        response.raise_for_status()
        return response.json()['data']

    async def create_ticket(self, ticket_data: Dict) -> int:
        """创建工单"""
        response = await self.client.post("/api/tickets", json=ticket_data)
        response.raise_for_status()
        return response.json()['ticket_id']

    async def get_engineers(self, skills: Optional[str] = None) -> List[Dict]:
        """查询工程师"""
        params = {}
        if skills:
            params["skills"] = skills

        response = await self.client.get("/api/engineers", params=params)
        response.raise_for_status()
        return response.json()['data']

    async def get_user(self, user_id: int) -> Dict:
        """查询用户信息"""
        response = await self.client.get(f"/api/users/{user_id}")
        response.raise_for_status()
        return response.json()['data']
```

### 3.3 使用示例

```python
# 业务平台使用AI能力示例

from ai_platform_sdk import AIPlatformClient

# 初始化AI平台客户端
ai_client = AIPlatformClient(
    base_url="http://ai-platform:8000",
    api_key="your-api-key"
)

# 场景1：用户发起智能问答
async def handle_user_question(user_id: int, message: str, session_id: str):
    """处理用户问题"""
    # 1. 调用AI平台
    result = await ai_client.chat(
        message=message,
        session_id=session_id,
        user_id=user_id
    )

    # 2. 返回给前端
    return {
        "answer": result['answer'],
        "references": result['references'],
        "can_solve": result['confidence'] > 0.7  # 是否能解决
    }

# 场景2：用户提交工单时AI辅助
async def create_ticket_with_ai(user_id: int, description: str):
    """创建工单（AI辅助）"""
    # 1. 提取工单信息
    ticket_info = await ai_client.extract_ticket_info(description)

    # 2. 创建工单
    ticket_data = {
        "user_id": user_id,
        "title": ticket_info['title'],
        "description": description,
        "category": ticket_info['category'],
        "priority": ticket_info['priority'],
        "tags": ticket_info['tags']
    }

    ticket_id = await business_db.create_ticket(ticket_data)

    # 3. AI推荐工程师
    engineer_recommendation = await ai_client.recommend_engineer(
        ticket_id=ticket_id,
        category=ticket_info['category'],
        description=description
    )

    # 4. 自动派单
    if engineer_recommendation['confidence'] > 0.8:
        await business_db.assign_ticket(
            ticket_id=ticket_id,
            engineer_id=engineer_recommendation['engineer_id']
        )

    return ticket_id

# 场景3：工程师处理工单时AI推荐解决方案
async def get_solution_recommendations(ticket_id: int):
    """获取解决方案推荐"""
    # 1. 获取工单信息
    ticket = await business_db.get_ticket(ticket_id)

    # 2. AI推荐知识
    recommendations = await ai_client.recommend_knowledge(
        ticket_id=ticket_id,
        description=ticket['description'],
        top_k=5
    )

    return recommendations['knowledge_list']
```

---

## 四、部署架构

### 4.1 部署拓扑

```
┌─────────────────────────────────────────────────────────────┐
│                      负载均衡层                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Nginx / HAProxy                                      │   │
│  │  - SSL终止                                             │   │
│  │  - 负载均衡                                            │   │
│  │  - 静态资源                                            │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
           ↓                                    ↓
┌────────────────────────┐        ┌────────────────────────────┐
│  业务平台集群           │        │   AI平台集群                │
│  ┌──────────────────┐  │        │  ┌──────────────────────┐ │
│  │  工单服务 × 3     │  │        │  │  对话服务 × 2         │ │
│  └──────────────────┘  │        │  └──────────────────────┘ │
│  ┌──────────────────┐  │        │  ┌──────────────────────┐ │
│  │  用户服务 × 2     │  │        │  │  LLM服务 × 2          │ │
│  └──────────────────┘  │        │  │  (云端+本地)          │ │
│  ┌──────────────────┐  │        │  └──────────────────────┘ │
│  │  通知服务 × 2     │  │        │  ┌──────────────────────┐ │
│  └──────────────────┘  │        │  │  RAG引擎 × 2          │ │
│                        │        │  └──────────────────────┘ │
│                        │        │  ┌──────────────────────┐ │
│                        │        │  │  知识库服务 × 2       │ │
│                        │        │  └──────────────────────┘ │
└────────────────────────┘        └────────────────────────────┘
           ↓                                    ↓
┌────────────────────────┐        ┌────────────────────────────┐
│  业务数据层             │        │   AI数据层                  │
│  ┌──────────────────┐  │        │  ┌──────────────────────┐ │
│  │  MySQL主从        │  │        │  │  PostgreSQL主从       │ │
│  └──────────────────┘  │        │  └──────────────────────┘ │
│  ┌──────────────────┐  │        │  ┌──────────────────────┐ │
│  │  Redis Cluster    │  │        │  │  Milvus集群           │ │
│  └──────────────────┘  │        │  └──────────────────────┘ │
│  ┌──────────────────┐  │        │  ┌──────────────────────┐ │
│  │  MongoDB副本集    │  │        │  │  Elasticsearch集群    │ │
│  └──────────────────┘  │        │  └──────────────────────┘ │
│                        │        │  ┌──────────────────────┐ │
│                        │        │  │  Redis Cluster        │ │
│                        │        │  └──────────────────────┘ │
└────────────────────────┘        └────────────────────────────┘
```

### 4.2 资源配置建议

```yaml
# 业务平台（500用户场景）
工单服务:
  实例数: 3
  配置: 4核 8GB
  语言: Go

用户服务:
  实例数: 2
  配置: 4核 8GB
  语言: Java

通知服务:
  实例数: 2
  配置: 2核 4GB
  语言: Node.js

MySQL:
  配置: 8核 32GB 500GB SSD
  架构: 1主2从

Redis:
  配置: 8核 16GB
  架构: 3主3从集群

# AI平台（500用户场景）
对话服务:
  实例数: 2
  配置: 4核 8GB
  语言: Python + FastAPI

LLM服务:
  云端: 按需调用
  本地:
    配置: 8核 32GB + 1×3090(24GB)
    推理: vLLM
    模型: Qwen-7B-Chat INT4

RAG引擎:
  实例数: 2
  配置: 4核 8GB

知识库服务:
  实例数: 2
  配置: 4核 8GB

PostgreSQL:
  配置: 8核 32GB 500GB SSD
  架构: 1主2从

Milvus:
  配置: 16核 64GB 500GB SSD
  架构: 单节点（可扩展到集群）

Elasticsearch:
  配置: 16核 64GB 1TB SSD
  架构: 3节点集群

Redis:
  配置: 8核 16GB
  架构: 3主3从集群

# 总计资源（仅核心服务）
CPU: 约120核
内存: 约400GB
存储: 约5TB SSD
GPU: 1×3090 (可选，用于本地LLM)

月度成本（云服务器租用）:
  - 纯云端LLM: ¥20,000 - ¥30,000
  - 本地LLM: ¥25,000 - ¥35,000
```

---

## 五、监控与运维

### 5.1 监控指标

```yaml
业务平台监控:
  - QPS、响应时间
  - 工单创建/处理速率
  - 数据库连接池
  - 缓存命中率

AI平台监控:
  - LLM调用次数、成本
  - RAG检索延迟
  - 知识库检索准确率
  - 向量数据库性能
  - GPU使用率（本地LLM）

告警规则:
  - 响应时间 > 1s
  - 错误率 > 1%
  - LLM成本超预算
  - GPU温度 > 80°C
  - 磁盘使用率 > 80%
```

---

*AI能力平台核心模块与集成方案设计完成*
