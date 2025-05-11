import argparse
import json
import os
import sqlite3
import subprocess
import sys
import uuid
import stat
from datetime import datetime
from pathlib import Path

# Windows平台特定导入
if sys.platform == 'win32':
    # 导入Windows特定的subprocess标志
    from subprocess import CREATE_NO_WINDOW
else:
    # 为非Windows平台定义一个假的CREATE_NO_WINDOW常量
    CREATE_NO_WINDOW = 0

# 全局数据库连接对象
conn = None


# 数据库路径（修改：使用sys.executable定位exe所在目录）
DB_PATH = Path(sys.executable).parent / "ai_chat_history.db" if getattr(sys, 'frozen', False) else Path(__file__).parent / "ai_chat_history.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# 获取系统默认 shell
def get_system_shell():
    """获取系统默认 shell"""
    if sys.platform == 'win32':
        return os.environ.get('COMSPEC', 'C:\\Windows\\System32\\cmd.exe')
    else:
        return os.environ.get('SHELL', '/bin/bash')

# 移除原有的数据库连接装饰器

# 初始化数据库连接
def init_db_connection():
    global conn
    try:
        conn = sqlite3.connect(DB_PATH)
        return conn.cursor()
    except Exception as e:
        raise

# 关闭数据库连接
def close_db_connection():
    global conn
    if conn:
        try:
            conn.close()
        except Exception as e:
            print(f"数据库关闭失败: {str(e)}")

# 修改后的数据库操作函数
def init_db(cursor):
    """初始化数据库"""
    # 检查表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('chat_history', 'sessions', 'session_messages')")
    existing_tables = [row[0] for row in cursor.fetchall()]

    # 如果所有表都存在，无需创建
    if set(['chat_history', 'sessions', 'session_messages']).issubset(set(existing_tables)):
        return

    if SCHEMA_PATH.exists():
        with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
            schema_sql = f.read()
            cursor.executescript(schema_sql)
    else:
        # 如果不存在，则直接创建表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            problem TEXT NOT NULL,
            answer TEXT,
            output TEXT,
            role TEXT DEFAULT 'default'
        )
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS session_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            message_id INTEGER,
            FOREIGN KEY (session_id) REFERENCES sessions(id),
            FOREIGN KEY (message_id) REFERENCES chat_history(id)
        )
        ''')

# 其他数据库操作函数类似修改，添加cursor参数
def save_chat_record(cursor, problem, answer, output, role='default'):
    """保存聊天记录到数据库"""
    cursor.execute(
        "INSERT INTO chat_history (problem, answer, output, role) VALUES (?, ?, ?, ?)",
        (problem, answer, output, role)
    )
    
    chat_id = cursor.lastrowid
    
    # 检查是否有活跃会话，如果有则关联消息
    cursor.execute("SELECT id FROM sessions WHERE is_active = 1 ORDER BY id DESC LIMIT 1")
    session_row = cursor.fetchone()
    if session_row:
        session_id = session_row[0]
        cursor.execute(
            "INSERT INTO session_messages (session_id, message_id) VALUES (?, ?)",
            (session_id, chat_id)
        )
    conn.commit()
    return chat_id


def start_session(cursor):
    """开始一个新的会话"""
    # 先将所有活跃会话设为非活跃
    cursor.execute("UPDATE sessions SET is_active = 0 WHERE is_active = 1")
    
    # 创建新会话
    session_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO sessions (session_id) VALUES (?)",
        (session_id,)
    )
    return session_id


def get_chat_history(cursor, count=5):
    """获取最近的聊天记录"""
    cursor.execute(
        "SELECT id, problem, answer, output, role FROM chat_history ORDER BY id DESC LIMIT ?",
        (count,)
    )
    
    return cursor.fetchall()


def get_active_session_messages(cursor):
    """获取当前活跃会话的所有消息"""
    # 先获取活跃会话ID
    cursor.execute("SELECT id FROM sessions WHERE is_active = 1 ORDER BY id DESC LIMIT 1")
    session_row = cursor.fetchone()
    
    if not session_row:
        # 没有活跃会话
        return []
    
    # 获取会话关联的所有消息ID
    session_id = session_row[0]
    cursor.execute("""
        SELECT ch.id, ch.problem, ch.answer, ch.output, ch.role FROM chat_history ch
        JOIN session_messages sm ON ch.id = sm.message_id
        WHERE sm.session_id = ?
        ORDER BY ch.id
    """, (session_id,))
    
    return cursor.fetchall()


def get_chat_by_ids(cursor, ids):
    """根据ID列表获取聊天记录"""
    if not ids:
        return []
    
    # 构建IN子句的参数
    placeholders = ','.join('?' for _ in ids)
    query = f"SELECT id, problem, output, role FROM chat_history WHERE id IN ({placeholders}) ORDER BY id"
    
    cursor.execute(query, ids)
    return cursor.fetchall()


def get_last_n_records(cursor, count):
    """获取最后N条记录的ID"""
    cursor.execute(
        "SELECT id FROM chat_history ORDER BY id DESC LIMIT ?",
        (count,)
    )
    
    return [row[0] for row in cursor.fetchall()]


def has_active_session(cursor):
    """检查是否有活跃的会话"""
    cursor.execute("SELECT COUNT(*) FROM sessions WHERE is_active = 1")
    count = cursor.fetchone()[0]
    
    return count > 0

# 检查文件是否存在并是否可执行
def check_executable(cmd_path):
    """检查文件是否存在并是否可执行"""
    cmd_file = Path(cmd_path)
    
    # 如果是绝对路径且文件存在
    if cmd_file.exists():
        # 在 Linux/Mac 上检查可执行权限
        if sys.platform != 'win32':
            return os.access(cmd_file, os.X_OK)
        return True
    
    # 搜索 PATH 环境变量
    for path_dir in os.environ.get('PATH', '').split(os.pathsep):
        exe_file = Path(path_dir) / cmd_path
        if exe_file.exists():
            if sys.platform != 'win32':
                return os.access(exe_file, os.X_OK)
            return True
    
    return False

# 确保文件可执行（Linux 系统）
def ensure_executable(file_path):
    """确保文件在 Linux 系统下具有可执行权限"""
    if sys.platform != 'win32':
        path = Path(file_path)
        if path.exists():
            current_mode = os.stat(path).st_mode
            # 添加用户可执行权限
            os.chmod(path, current_mode | stat.S_IXUSR)

# 封装命令执行逻辑
def run_command(cmd, capture_output=False, text=True, encoding='utf-8'):
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=text,
            encoding=encoding,
            check=True
        )
        return result.stdout if capture_output else "", None
    except subprocess.CalledProcessError as e:
        error_msg = f"命令执行失败，返回码: {e.returncode}, 错误信息: {e.stderr}" if e.stderr else f"命令执行失败，返回码: {e.returncode}"
        return error_msg, None
    except Exception as e:
        return f"错误: 无法执行命令 - {str(e)}", None

# 重构run_aichat_command函数
def run_aichat_command(args, history_param=None):
    """运行aichat命令并捕获输出"""
    cmd = ["aichat"]
    
    # 检查 aichat 是否存在且可执行
    if not check_executable("aichat"):
        # 如果当前目录有 aichat 文件但不可执行
        local_aichat = Path("./aichat")
        if local_aichat.exists() and sys.platform != 'win32':
            ensure_executable(local_aichat)
            cmd = ["./aichat"]
    
    # 检查是否是代码执行模式
    is_code_mode = '-e' in args
    
    # 如果有历史记录参数，添加到命令中
    if history_param:
        cmd.append(json.dumps(history_param))
    else:
        # 否则添加用户输入的参数
        cmd.extend(args)
    
    try:
        print(f"执行命令: {' '.join(cmd)}")
        
        # 代码执行模式需要先获取命令建议，再交互执行
        if is_code_mode:
            # Linux系统下的特殊处理
            if sys.platform != 'win32':
                # 1. 先以非交互模式运行，获取命令建议
                preview_cmd = cmd.copy()
                # 将命令的标准输出和标准错误重定向到管道
                process = subprocess.Popen(
                    preview_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8'
                )
                
                # 读取输出和错误信息
                stdout, stderr = process.communicate()
                output_preview = stdout if stdout else ""
                
                # 提取建议的命令
                suggested_command = ""
                if output_preview:
                    lines = output_preview.strip().split('\n')
                    if lines:
                        suggested_command = lines[0]  # 第一行通常是命令建议
                
                # 2. 再以交互模式运行命令，允许用户选择
                # 对于Linux，使用终端直接执行以保持交互性
                try:
                    interactive_process = subprocess.Popen(cmd)
                    interactive_process.wait()
                except Exception as e:
                    print(f"交互执行失败: {str(e)}")
                
                # 3. 如果用户选择执行(e)，尝试捕获命令执行结果
                actual_output = ""
                if suggested_command:
                    try:
                        # 执行实际命令并捕获输出
                        actual_cmd = ["bash", "-c", suggested_command]
                        actual_process = subprocess.Popen(
                            actual_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            encoding='utf-8'
                        )
                        stdout, stderr = actual_process.communicate()
                        actual_output = stdout if stdout else stderr if stderr else ""
                    except Exception as e:
                        actual_output = f"无法捕获命令执行结果: {str(e)}"
                
                # 返回提示信息、建议的命令和实际执行结果
                complete_output = f"命令已执行: {suggested_command}\n\n{actual_output}"
                return complete_output, suggested_command
            
            else:  # Windows系统处理逻辑保持不变
                # 1. 先以捕获输出模式运行，获取命令建议
                preview_cmd = cmd.copy()
                output_preview, _ = run_command(preview_cmd, capture_output=True)
                
                # 提取建议的命令
                suggested_command = ""
                if output_preview:
                    lines = output_preview.strip().split('\n')
                    if lines:
                        suggested_command = lines[0]  # 第一行通常是命令建议
                
                # 2. 再以交互模式运行命令，允许用户选择
                run_command(cmd, capture_output=False)
                
                # 3. 如果用户选择执行(e)，尝试捕获命令执行结果
                actual_output = ""
                if suggested_command:
                    try:
                        # 执行实际命令并捕获输出
                        actual_cmd = ["powershell", "-Command", "$OutputEncoding = [System.Text.Encoding]::UTF8; " + suggested_command]
                        actual_output, _ = run_command(actual_cmd, capture_output=True, text=False)
                        # 尝试使用UTF-8解码，如果失败则使用GBK解码（Windows中文系统默认）
                        try:
                            actual_output = actual_output.decode('utf-8')
                        except UnicodeDecodeError:
                            actual_output = actual_output.decode('gbk', errors='replace')
                    except Exception as e:
                        actual_output = f"无法捕获命令执行结果: {str(e)}"
                
                # 返回提示信息、建议的命令和实际执行结果
                complete_output = f"命令已执行: {suggested_command}\n\n{actual_output}"
                return complete_output, suggested_command
        else:
            # 非代码执行模式，优化为字符级流式输出
            output = []
            
            if sys.platform != 'win32':
                # Linux/Mac 流式输出处理
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,  # 合并错误流到输出流
                    text=False,  # 使用二进制模式，手动处理编码
                    bufsize=0    # 无缓冲，立即输出每个字符
                )
                
                # 逐字符读取并实时打印
                while True:
                    char = process.stdout.read(1)  # 一次读取一个字节
                    if not char:  # 结束标志
                        break
                    
                    try:
                        # 尝试解码字符
                        decoded_char = char.decode('utf-8')
                        sys.stdout.write(decoded_char)  # 直接写入标准输出
                        sys.stdout.flush()  # 立即刷新输出
                        output.append(decoded_char)
                    except UnicodeDecodeError:
                        # 可能是多字节字符的一部分，继续读取
                        buffer = char
                        while True:
                            try:
                                decoded_char = buffer.decode('utf-8')
                                sys.stdout.write(decoded_char)
                                sys.stdout.flush()
                                output.append(decoded_char)
                                break
                            except UnicodeDecodeError:
                                next_char = process.stdout.read(1)
                                if not next_char:  # 到达流末尾
                                    # 处理不完整的多字节字符
                                    try:
                                        decoded_char = buffer.decode('utf-8', errors='replace')
                                        sys.stdout.write(decoded_char)
                                        sys.stdout.flush()
                                        output.append(decoded_char)
                                    except:
                                        pass
                                    break
                                buffer += next_char
                
                process.wait()
                final_output = ''.join(output)
                return final_output.strip(), None
            else:
                # Windows 流式输出处理
                try:
                    # 创建子进程并设置无缓冲输出
                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=False,
                        bufsize=0,
                        creationflags=CREATE_NO_WINDOW if sys.platform == 'win32' else 0  # 避免闪现命令行窗口
                    )
                    
                    # 逐字符读取并实时打印
                    while True:
                        char = process.stdout.read(1)  # 一次读取一个字节
                        if not char:  # 结束标志
                            break
                        
                        try:
                            # 尝试用UTF-8解码
                            decoded_char = char.decode('utf-8')
                            sys.stdout.write(decoded_char)
                            sys.stdout.flush()
                            output.append(decoded_char)
                        except UnicodeDecodeError:
                            # 可能是多字节字符的一部分，继续读取
                            buffer = char
                            while True:
                                try:
                                    # 尝试解码
                                    decoded_char = buffer.decode('utf-8')
                                    sys.stdout.write(decoded_char)
                                    sys.stdout.flush()
                                    output.append(decoded_char)
                                    break
                                except UnicodeDecodeError:
                                    next_char = process.stdout.read(1)
                                    if not next_char:  # 到达流末尾
                                        # 处理不完整的多字节字符
                                        try:
                                            decoded_char = buffer.decode('utf-8', errors='replace')
                                            sys.stdout.write(decoded_char)
                                            sys.stdout.flush()
                                            output.append(decoded_char)
                                        except:
                                            pass
                                        break
                                    buffer += next_char
                    
                    process.wait()
                    final_output = ''.join(output)
                    return final_output.strip(), None
                except Exception as e:
                    error_msg = f"字符级流式输出失败: {str(e)}"
                    print(error_msg)
                    
                    # 回退到兼容模式
                    print("切换到行级流式输出...")
                    # 使用shell=True确保Windows下可以正确处理编码
                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding='utf-8',
                        bufsize=1,
                        universal_newlines=True,
                        shell=sys.platform == 'win32'  # Windows需要shell处理
                    )
                    output = []
                    for line in process.stdout:
                        print(line.strip())
                        output.append(line)
                    process.wait()
                    final_output = ''.join(output)
                    return final_output.strip(), None
    except Exception as e:
        return f"错误: 无法执行aichat命令 - {str(e)}", None
    
def extract_answer_from_output(output, is_code_mode=False):
    """从输出中提取答案部分"""
    if is_code_mode and "?" in output and "execute | revise | describe | copy | quit" in output:
        # 对于代码模式，提取第一行作为要执行的命令
        lines = output.split('\n')
        return lines[0] if lines else ""
    return output

def parse_range(range_str, max_count=10):
    """解析范围字符串，返回对应的ID列表"""
    try:
        if ',' in range_str:
            # 处理多个单独的数字 "1,3,5"
            indices = [int(idx.strip()) for idx in range_str.split(',')]
            return indices
        elif '-' in range_str:
            # 处理范围 "2-5"
            start, end = map(int, range_str.split('-'))
            return list(range(start, end + 1))
        else:
            # 处理单个数字
            return [int(range_str)]
    except ValueError:
        print(f"错误：无效的范围格式 '{range_str}'")
        return []


def format_history_list(records):
    """格式化历史记录列表显示"""
    if not records:
        return "没有可用的聊天记录"
    
    result = []
    # 记录已经是从新到旧排序，直接使用
    for idx, (id, problem, answer, output, role) in enumerate(records, 1):
        role_display = f"[{role}]" if role != "default" else ""
        problem_short = problem[:50] + "..." if len(problem) > 50 else problem
        if role == "code":
            # 对于代码模式，显示建议的命令
            problem_short = f"{problem_short} | {answer}"
        result.append(f"{idx}. {id} {role_display} {problem_short}")
    
    return "\n".join(result)

def create_param_list(records):
    """根据记录创建参数列表"""
    param_list = []
    for record in records:
        # 根据记录中的字段数量判断格式
        if len(record) == 5:  # 包含id, problem, answer, output, role
            _, problem, _, output, _ = record
        elif len(record) == 4:  # 包含id, problem, output, role
            _, problem, output, _ = record
        else:
            continue  # 跳过无法识别的记录格式
            
        item = {"problem": problem}
        if output:
            item["output"] = output
        param_list.append(item)
    return param_list

# 修改main函数
def main():
    global conn
    
    # 初始化数据库连接
    cursor = init_db_connection()
    
    # 初始化数据库
    init_db(cursor)
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='AI聊天助手工具')
    parser.add_argument('-e', action='store_true', help='代码执行模式')
    parser.add_argument('-r', metavar='ROLE', help='指定角色')
    parser.add_argument('-m', metavar='MODE', nargs='?', const='',
                      help='会话模式：start, list(l), 数字(1-5)或范围(2-4)，不带参数则使用当前活跃会话')
    parser.add_argument('message', nargs='*', help='要发送给AI的消息')
    
    args = parser.parse_args()
    
    # 确定角色
    role = 'default'
    if args.e:
        role = 'code'
    elif args.r:
        role = args.r
    
    # 处理会话模式
    if args.m is not None:  # 注意：args.m可能是空字符串
        # 处理list命令及其简写形式
        if args.m == 'list' or args.m == 'l':
            # 列出最近的聊天记录
            records = get_chat_history(cursor, 5)  # 已经是从新到旧排序
            print(format_history_list(records))
            return
        
        if args.m == 'start'  or args.m == 's':
            # 开始新会话
            session_id = start_session(cursor)
            print(f"已开始新会话")
            
            # 处理消息
            if args.message:
                message = ' '.join(args.message)
                
                # 在非代码执行和自定义角色模式下，添加中文回答提示
                if not args.e and not args.r:
                    message = message + " ;answer by Chinese"
                
                cmd_args = []
                if args.e:
                    cmd_args.append('-e')
                if args.r:
                    cmd_args.extend(['-r', args.r])
                cmd_args.append(message)
                
                output, suggested_cmd = run_aichat_command(cmd_args)
                
                # 代码执行模式下，使用捕获的命令建议作为答案
                if args.e and suggested_cmd:
                    answer = suggested_cmd
                else:
                    answer = extract_answer_from_output(output, args.e)
                
                save_chat_record(cursor, message, answer, output, role)
                
                # 对于代码执行模式，output已经在终端显示，不需要再次打印
                if not args.e:
                    print(output)
            
            return
        
        elif args.m == '':  # -m不带参数
            # 检查是否有活跃会话
            if not has_active_session(cursor):
                print("错误：没有活跃的会话，请先使用 '-m start' 开始一个新会话")
                return
            
            message = ' '.join(args.message)
            if not message:
                print("错误：请提供要发送给AI的消息")
                return
            
            # 在非代码执行和自定义角色模式下，添加中文回答提示
            original_message = message
            if not args.e and not args.r:
                message = message + "; answer by Chinese"
                
            # 获取当前活跃会话的所有消息
            records = get_active_session_messages(cursor)
            param_list = create_param_list(records)
            
            # 添加当前问题
            param_list.append({"problem": message})
            
            # 调用aichat并传入历史记录
            cmd_args = []
            if args.e:
                cmd_args.append('-e')
            
            output, suggested_cmd = run_aichat_command(cmd_args, param_list)
            
            # 代码执行模式下，使用捕获的命令建议作为答案
            if args.e and suggested_cmd:
                answer = suggested_cmd
            else:
                answer = extract_answer_from_output(output, args.e)
            
            # 保存原始问题，而不是添加了提示的问题
            save_chat_record(cursor, original_message, answer, output, role)
            
            # 对于代码执行模式，output已经在终端显示，不需要再次打印
            if not args.e:
                print(output)
            return
        
        else:
            # 处理指定的历史记录范围
            message = ' '.join(args.message)
            if not message:
                print("错误：使用-m参数时需要提供消息内容")
                return
            
            # 在非代码执行和自定义角色模式下，添加中文回答提示
            original_message = message
            if not args.e and not args.r:
                message = message + "; answer by Chinese"
            
            # 解析范围并获取对应的记录
            ids = []
            if '-' in args.m or ',' in args.m:
                # 处理范围或多个ID
                indices = parse_range(args.m)
                if indices:
                    last_ids = get_last_n_records(cursor, max(indices) + 1)
                    indices = [i-1 for i in indices if 1 <= i <= len(last_ids)]
                    ids = [last_ids[i] for i in indices]
            else:
                try:
                    # 处理单个数字
                    count = int(args.m)
                    ids = get_last_n_records(cursor, count)
                except ValueError:
                    print(f"错误：无效的-m参数值 '{args.m}'")
                    return
            
            records = get_chat_by_ids(cursor, ids)
            param_list = create_param_list(records)
            
            # 添加当前问题
            param_list.append({"problem": message})
            
            # 调用aichat并传入历史记录
            cmd_args = []
            if args.e:
                cmd_args.append('-e')
                
            output, suggested_cmd = run_aichat_command(cmd_args, param_list)
            
            # 代码执行模式下，使用捕获的命令建议作为答案
            if args.e and suggested_cmd:
                answer = suggested_cmd
            else:
                answer = extract_answer_from_output(output, args.e)
            
            # 保存原始问题，而不是添加了提示的问题
            save_chat_record(cursor, original_message, answer, output, role)
            
            # 对于代码执行模式，output已经在终端显示，不需要再次打印
            if not args.e:
                print(output)
            return
    
    # 普通模式处理
    message = ' '.join(args.message)
    if not message:
        print("请提供要发送给AI的消息")
        return
    
    # 在非代码执行和自定义角色模式下，添加中文回答提示
    original_message = message
    if not args.e and not args.r:
        message = message + "; answer by Chinese"
    
    cmd_args = []
    if args.e:
        cmd_args.append('-e')
    if args.r:
        cmd_args.extend(['-r', args.r])
    cmd_args.append(message)
    
    output, suggested_cmd = run_aichat_command(cmd_args)
    
    # 代码执行模式下，使用捕获的命令建议作为答案
    if args.e and suggested_cmd:
        answer = suggested_cmd
    else:
        answer = extract_answer_from_output(output, args.e)
    
    # 保存原始问题，而不是添加了提示的问题
    save_chat_record(cursor, original_message, answer, output, role)
    
    # 对于代码执行模式，output已经在终端显示，不需要再次打印
    if not args.e:
        print(output)
    
    # 关闭数据库连接
    close_db_connection()

if __name__ == "__main__":
    main()