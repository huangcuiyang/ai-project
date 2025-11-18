"""
Flask Web应用主文件
"""
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit, disconnect
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import os
import sys
import io

# 修复Windows控制台编码问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_agent.models import db, User, Conversation, Message
from web_agent.config import Config
from web_agent.agent_service import AgentService

# 创建Flask应用
app = Flask(__name__)
app.config.from_object(Config)

# 初始化扩展
db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_page'

# 创建数据库表
with app.app_context():
    db.create_all()
    # 创建默认测试用户（如果不存在）
    if not User.query.filter_by(username='test').first():
        test_user = User(username='test', role='developer')
        test_user.set_password('test123')
        db.session.add(test_user)
        db.session.commit()
        print("✅ 创建测试用户: test / test123")

# 初始化智能体服务
agent_service = AgentService(
    api_key=Config.DEEPSEEK_API_KEY,
    base_url=Config.DEEPSEEK_BASE_URL,
    model_name=Config.DEEPSEEK_MODEL
)


# ==================== Flask-Login配置 ====================

@login_manager.user_loader
def load_user(user_id):
    """加载用户"""
    return User.query.get(int(user_id))


# ==================== 路由 - 页面 ====================

@app.route('/')
def index():
    """首页 - 重定向到登录或聊天"""
    if current_user.is_authenticated:
        return redirect(url_for('chat_page'))
    return redirect(url_for('login_page'))


@app.route('/login')
def login_page():
    """登录页面"""
    return render_template('login.html')


@app.route('/chat')
@login_required
def chat_page():
    """聊天页面"""
    return render_template('chat.html', user=current_user.to_dict())


# ==================== 路由 - API ====================

@app.route('/api/register', methods=['POST'])
def register():
    """用户注册"""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400

    # 检查用户是否已存在
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'message': '用户名已存在'}), 400

    # 创建新用户
    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return jsonify({'success': True, 'message': '注册成功'})


@app.route('/api/login', methods=['POST'])
def login():
    """用户登录"""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400

    # 查找用户
    user = User.query.filter_by(username=username).first()

    if not user or not user.check_password(password):
        return jsonify({'success': False, 'message': '用户名或密码错误'}), 401

    # 登录用户
    login_user(user)

    return jsonify({
        'success': True,
        'user': user.to_dict()
    })


@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    """用户登出"""
    logout_user()
    return jsonify({'success': True})


@app.route('/api/conversations', methods=['GET'])
@login_required
def get_conversations():
    """获取用户的所有对话"""
    conversations = Conversation.query.filter_by(user_id=current_user.id)\
        .order_by(Conversation.updated_at.desc()).all()

    return jsonify({
        'success': True,
        'conversations': [conv.to_dict() for conv in conversations]
    })


@app.route('/api/conversations/<int:conv_id>/messages', methods=['GET'])
@login_required
def get_messages(conv_id):
    """获取对话的所有消息"""
    conversation = Conversation.query.get(conv_id)

    if not conversation or conversation.user_id != current_user.id:
        return jsonify({'success': False, 'message': '对话不存在'}), 404

    messages = Message.query.filter_by(conversation_id=conv_id)\
        .order_by(Message.created_at).all()

    return jsonify({
        'success': True,
        'messages': [msg.to_dict() for msg in messages]
    })


@app.route('/api/conversations', methods=['POST'])
@login_required
def create_conversation():
    """创建新对话"""
    data = request.get_json()
    title = data.get('title', '新对话')

    conversation = Conversation(user_id=current_user.id, title=title)
    db.session.add(conversation)
    db.session.commit()

    return jsonify({
        'success': True,
        'conversation': conversation.to_dict()
    })


# ==================== WebSocket事件处理 ====================

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    if not current_user.is_authenticated:
        disconnect()
        return False
    print(f"✅ 用户 {current_user.username} 已连接")


@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开连接"""
    if current_user.is_authenticated:
        print(f"❌ 用户 {current_user.username} 已断开连接")


@socketio.on('send_message')
def handle_message(data):
    """处理用户发送的消息"""
    if not current_user.is_authenticated:
        emit('error', {'message': '未登录'})
        return

    conversation_id = data.get('conversation_id')
    user_message = data.get('message')

    if not user_message:
        emit('error', {'message': '消息不能为空'})
        return

    # 验证对话是否属于当前用户
    conversation = Conversation.query.get(conversation_id)
    if not conversation or conversation.user_id != current_user.id:
        emit('error', {'message': '对话不存在'})
        return

    # 保存用户消息到数据库
    user_msg = Message(
        conversation_id=conversation_id,
        role='user',
        content=user_message
    )
    db.session.add(user_msg)
    db.session.commit()

    # 向客户端发送确认
    emit('message_saved', {
        'message': user_msg.to_dict()
    })

    # 调用智能体处理消息（流式输出）
    assistant_content = ""

    def stream_callback(event):
        """流式回调函数"""
        nonlocal assistant_content

        event_type = event.get('type')
        event_data = event.get('data', {})

        if event_type == 'tool_call':
            # 工具调用
            emit('tool_call', {
                'tool_name': event_data.get('tool_name'),
                'parameters': event_data.get('parameters')
            })

        elif event_type == 'assistant_message':
            # AI回复
            content = event_data.get('content', '')
            is_complete = event_data.get('is_complete', False)

            assistant_content = content

            emit('agent_response', {
                'content': content,
                'is_complete': is_complete
            })

            if is_complete:
                # 保存AI消息到数据库
                assistant_msg = Message(
                    conversation_id=conversation_id,
                    role='assistant',
                    content=content
                )
                db.session.add(assistant_msg)

                # 更新对话的更新时间
                conversation.updated_at = db.func.now()

                db.session.commit()

                emit('message_complete', {
                    'message': assistant_msg.to_dict()
                })

        elif event_type == 'error':
            # 错误
            emit('error', {
                'message': event_data.get('message', '处理消息时发生错误')
            })

        elif event_type == 'complete':
            # 完成
            print(f"✅ 消息处理完成")

    # 使用智能体服务处理消息
    agent_service.chat_stream(user_message, stream_callback)


# ==================== 主函数 ====================

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 智能体授权测试系统 - Web版本")
    print("="*60)
    print("\n访问地址: http://localhost:5000")
    print("测试账号: test / test123\n")

    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
