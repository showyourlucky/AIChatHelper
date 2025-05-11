-- 聊天记录表结构
CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    problem TEXT NOT NULL,      -- 用户输入的问题
    answer TEXT,                -- aichat返回的答案或要执行的命令
    output TEXT,                -- 实际输出的结果
    role TEXT DEFAULT 'default' -- 角色：default, code, 或自定义角色
);

-- 会话管理表
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,   -- 会话ID
    start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1 -- 1表示活跃会话，0表示已结束
);

-- 会话消息关联表
CREATE TABLE IF NOT EXISTS session_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    message_id INTEGER,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (message_id) REFERENCES chat_history(id)
); 