"""
智能体服务层 - 封装LangGraph智能体并支持流式回调
"""
import json
import time
from typing import Dict, Any, List, Callable, TypedDict, Annotated, Literal
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages


# ==================== 工具定义（复用之前的代码） ====================

@tool
def check_device_connection(device_ip: str, username: str, password: str) -> Dict[str, Any]:
    """
    检查目标设备是否在线并获取基本信息

    Args:
        device_ip: 设备IP地址或域名
        username: 设备登录用户名
        password: 设备登录密码

    Returns:
        包含设备连接状态和基本信息的字典
    """
    time.sleep(1)

    # 模拟不同场景
    if device_ip == "192.168.1.999":
        return {
            "success": False,
            "error": "设备无法访问",
            "message": "连接超时"
        }

    if password == "wrong":
        return {
            "success": False,
            "error": "认证失败",
            "message": "用户名或密码错误"
        }

    return {
        "success": True,
        "data": {
            "online": True,
            "product_name": "存储系统A" if "192.168.1" in device_ip else "存储系统B",
            "version": "v2.3.5",
            "device_id": f"SN{device_ip.replace('.', '')}"
        },
        "message": "设备连接成功"
    }


@tool
def execute_auth_test(
    device_ip: str,
    username: str,
    password: str,
    product_name: str,
    version: str,
    timeout: int = 300
) -> Dict[str, Any]:
    """
    执行设备授权测试的完整流程

    包括获取特征文件、上传授权系统、下载授权文件、导入设备、验证激活状态

    Args:
        device_ip: 设备IP地址
        username: 设备登录用户名
        password: 设备登录密码
        product_name: 产品名称
        version: 产品版本
        timeout: 超时时间（秒），默认300

    Returns:
        包含测试执行结果的字典
    """
    test_id = f"TEST-{datetime.now().strftime('%Y%m%d')}-{int(time.time()) % 1000:03d}"

    steps = [
        {"step": 1, "name": "登录设备门户", "status": "pending"},
        {"step": 2, "name": "获取硬件特征文件", "status": "pending"},
        {"step": 3, "name": "上传到授权系统", "status": "pending"},
        {"step": 4, "name": "生成授权文件", "status": "pending"},
        {"step": 5, "name": "导入授权文件到设备", "status": "pending"},
        {"step": 6, "name": "验证授权激活状态", "status": "pending"}
    ]

    # 模拟执行过程
    for step in steps:
        time.sleep(0.5)

        # 模拟第3步可能失败（10.0.0网段设备）
        if step['step'] == 3 and device_ip.startswith("10.0.0"):
            step['status'] = 'failed'
            step['error'] = {
                "code": "NETWORK_TIMEOUT",
                "message": "连接授权系统超时",
                "suggestion": "请检查授权系统网络连通性，或稍后重试"
            }
            return {
                "success": False,
                "test_id": test_id,
                "data": {
                    "steps": steps,
                    "summary": {
                        "total_steps": 6,
                        "success_steps": 2,
                        "failed_steps": 1,
                        "failed_at_step": 3
                    }
                },
                "message": f"授权测试在第{step['step']}步失败"
            }

        step['status'] = 'success'
        step['duration'] = round(0.5 + (step['step'] % 3) * 0.5, 1)

    total_duration = sum(s.get('duration', 0) for s in steps)

    return {
        "success": True,
        "test_id": test_id,
        "data": {
            "steps": steps,
            "total_duration": total_duration,
            "summary": {
                "total_steps": 6,
                "success_steps": 6,
                "failed_steps": 0
            }
        },
        "message": "授权测试执行成功"
    }


@tool
def generate_test_report(test_id: str, report_format: str = "html") -> Dict[str, Any]:
    """
    根据测试结果生成详细的测试验收报告

    Args:
        test_id: 测试任务ID
        report_format: 报告格式，可选值: html, pdf, json，默认html

    Returns:
        包含报告下载链接的字典
    """
    time.sleep(0.5)

    report_id = f"REPORT-{test_id.split('-', 1)[1]}"
    return {
        "success": True,
        "data": {
            "report_id": report_id,
            "download_url": f"https://auth-system.com/reports/{report_id}.{report_format}",
            "file_size": 153600,
            "expire_at": "2025-01-21T10:00:00Z"
        },
        "message": "报告生成成功"
    }


@tool
def save_test_record(test_id: str, operator: str, tags: List[str] = None) -> Dict[str, Any]:
    """
    将测试验证记录持久化保存到数据库

    Args:
        test_id: 测试任务ID
        operator: 操作人员（产品开发人员）
        tags: 标签列表，用于分类查询

    Returns:
        包含记录保存结果的字典
    """
    time.sleep(0.3)

    record_id = f"REC-{test_id.split('-', 1)[1]}"
    return {
        "success": True,
        "data": {
            "record_id": record_id,
            "saved_at": datetime.now().isoformat()
        },
        "message": "测试记录保存成功"
    }


@tool
def query_test_history(
    product_name: str = None,
    version: str = None,
    operator: str = None,
    status: str = "all",
    limit: int = 10
) -> Dict[str, Any]:
    """
    查询历史测试验证记录，支持多种筛选条件

    Args:
        product_name: 产品名称（可选）
        version: 产品版本（可选）
        operator: 操作人员（可选）
        status: 测试状态筛选，可选值: success, failed, all，默认all
        limit: 返回记录数量限制，默认10

    Returns:
        包含历史记录列表的字典
    """
    time.sleep(0.5)

    # 模拟返回历史记录
    mock_records = [
        {
            "test_id": "TEST-20250114-001",
            "product_name": "存储系统A",
            "version": "v2.3.5",
            "device_ip": "192.168.1.100",
            "operator": "张三",
            "status": "success",
            "created_at": "2025-01-14T10:00:00Z",
            "report_url": "https://auth-system.com/reports/REPORT-20250114-001.html"
        },
        {
            "test_id": "TEST-20250113-008",
            "product_name": "存储系统A",
            "version": "v2.3.5",
            "device_ip": "192.168.1.101",
            "operator": "李四",
            "status": "success",
            "created_at": "2025-01-13T16:20:00Z",
            "report_url": "https://auth-system.com/reports/REPORT-20250113-008.html"
        },
        {
            "test_id": "TEST-20250112-005",
            "product_name": "存储系统A",
            "version": "v2.3.4",
            "device_ip": "192.168.1.102",
            "operator": "王五",
            "status": "failed",
            "created_at": "2025-01-12T09:15:00Z",
            "report_url": "https://auth-system.com/reports/REPORT-20250112-005.html"
        }
    ]

    # 简单过滤
    if product_name:
        mock_records = [r for r in mock_records if r['product_name'] == product_name]

    if status != "all":
        mock_records = [r for r in mock_records if r['status'] == status]

    return {
        "success": True,
        "data": {
            "total": len(mock_records),
            "records": mock_records[:limit]
        },
        "message": "查询成功"
    }


# ==================== LangGraph 状态定义 ====================

class AgentState(TypedDict):
    """智能体状态"""
    messages: Annotated[List, add_messages]


# ==================== 智能体服务类 ====================

class AgentService:
    """智能体服务 - 支持流式回调"""

    def __init__(self, api_key: str, base_url: str, model_name: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name

        # 初始化LLM
        self.llm = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model_name,
            temperature=0,
            streaming=False
        )

        # 定义工具列表
        self.tools = [
            check_device_connection,
            execute_auth_test,
            generate_test_report,
            save_test_record,
            query_test_history
        ]

        # 绑定工具到LLM
        self.llm_with_tools = self.llm.bind_tools(self.tools)

        # 构建LangGraph
        self.graph = self._build_graph()

        # 系统提示词
        self.system_prompt = """你是一个专业的设备授权测试助手。你的任务是帮助产品开发人员完成设备授权系统的对接验证测试。

你可以使用以下工具：
1. check_device_connection - 检查设备连通性
2. execute_auth_test - 执行完整的授权测试流程
3. generate_test_report - 生成测试报告
4. save_test_record - 保存测试记录
5. query_test_history - 查询历史测试记录

工作流程：
1. 当用户要进行设备测试时，先收集必要信息（设备IP、产品名称、版本、登录凭证）
2. 使用check_device_connection验证设备连通性
3. 使用execute_auth_test执行授权测试
4. 测试完成后，自动调用generate_test_report生成报告
5. 调用save_test_record保存记录（operator参数使用"系统用户"）
6. 向用户展示完整的测试结果和报告链接

注意事项：
- 如果信息不完整，主动询问用户
- 测试成功后，必须自动生成报告和保存记录，不要询问用户
- 测试失败时，给出明确的错误原因和建议
- 使用友好、专业的语言与用户交流
- 结果展示要清晰、结构化，包含测试ID和报告下载链接

请用中文回复用户。"""

    def _build_graph(self) -> StateGraph:
        """构建LangGraph流程图"""

        def call_model(state: AgentState) -> AgentState:
            """调用LLM节点"""
            messages = state["messages"]

            # 添加系统提示
            if len(messages) == 1 or not any(isinstance(m, SystemMessage) for m in messages):
                system_message = SystemMessage(content=self.system_prompt)
                messages = [system_message] + messages

            response = self.llm_with_tools.invoke(messages)
            return {"messages": [response]}

        def should_continue(state: AgentState) -> Literal["tools", "end"]:
            """判断是否需要调用工具"""
            messages = state["messages"]
            last_message = messages[-1]

            if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                return "tools"
            return "end"

        # 创建图
        workflow = StateGraph(AgentState)

        # 添加节点
        workflow.add_node("agent", call_model)
        workflow.add_node("tools", ToolNode(self.tools))

        # 设置入口点
        workflow.set_entry_point("agent")

        # 添加条件边
        workflow.add_conditional_edges(
            "agent",
            should_continue,
            {
                "tools": "tools",
                "end": END
            }
        )

        # 工具执行后返回到agent
        workflow.add_edge("tools", "agent")

        # 编译图
        return workflow.compile()

    def chat_stream(self, user_message: str, callback: Callable):
        """
        流式对话 - 通过回调函数实时推送状态

        Args:
            user_message: 用户输入
            callback: 回调函数，接收事件字典 {"type": "...", "data": {...}}
        """
        # 创建初始状态
        initial_state = {
            "messages": [HumanMessage(content=user_message)]
        }

        try:
            # 流式运行图
            for event in self.graph.stream(initial_state):
                for node_name, node_output in event.items():
                    if node_name == "agent":
                        messages = node_output.get("messages", [])
                        if messages:
                            last_msg = messages[-1]
                            if isinstance(last_msg, AIMessage):
                                if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
                                    # LLM决定调用工具
                                    for tool_call in last_msg.tool_calls:
                                        callback({
                                            "type": "tool_call",
                                            "data": {
                                                "tool_name": tool_call.get('name', ''),
                                                "parameters": tool_call.get('args', {})
                                            }
                                        })
                                elif last_msg.content:
                                    # LLM回复内容
                                    callback({
                                        "type": "assistant_message",
                                        "data": {
                                            "content": last_msg.content,
                                            "is_complete": True
                                        }
                                    })
                    elif node_name == "tools":
                        # 工具执行完成（可以在这里添加更多回调）
                        pass

            callback({
                "type": "complete",
                "data": {}
            })

        except Exception as e:
            callback({
                "type": "error",
                "data": {
                    "message": str(e)
                }
            })
