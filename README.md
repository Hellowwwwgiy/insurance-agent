# Insurance Agent - 保险智能助手

基于 LangChain + DeepSeek 构建的保险行业 SQL 智能助手，支持自然语言转 SQL 并执行数据库查询，内置交互查询、日志记录、模块自测能力。

## 📋 目录

- [功能特性](#-功能特性)
- [项目结构](#-项目结构)
- [环境要求](#️-环境要求)
- [快速开始](#-快速开始)
- [常见问题](#-常见问题)
- [扩展开发](#-扩展开发)
- [许可证](#-许可证)

## 🎯 功能特性

- **数据库对接**：对接 PostgreSQL，自动读取表结构、执行 SQL 语句
- **智能转换**：DeepSeek 大模型实现自然语言自动转 SQL
- **日志管理**：日志按日期分文件存储，控制台 + 文件双输出
- **灵活查询**：支持交互式单条查询、批量查询
- **全面测试**：全覆盖模块自测：配置、数据库、LLM、Agent
- **模块化设计**：模块化分层设计，易拓展、易维护

## 📁 项目结构
insurance-agent/
├── main.py # 程序入口
├── test_app_modules.py # 模块测试脚本
├── .env # 环境变量配置文件（需手动创建）
├── .env.example # 环境变量示例文件
├── app/
│ └── agent/ # 核心模块（配置/数据库/Agent/日志）
└── logs/ # 日志目录（需手动创建）

## 🛠️ 环境要求

- Python 3.8+
- 本地运行 PostgreSQL，提前创建 insurance_db 数据库
- 有效的 DeepSeek API Key

## 🚀 快速开始

### 1. 拉取代码并安装依赖

```bash
git clone <项目仓库地址>
cd insurance-agent

# 创建虚拟环境
python -m venv venv

# Linux/Mac 激活虚拟环境
source venv/bin/activate

# Windows 激活虚拟环境
venv\Scripts\activate

# 安装依赖
pip install langchain-openai langchain-community python-dotenv psycopg2-binary SQLAlchemy
```
### 2. 配置环境变量
```bash
# 复制示例文件
cp .env.example .env
# 编辑 .env 文件，填入配置信息
# Linux/Mac: nano .env 或 vim .env
# Windows: notepad .env
.env 文件配置示例：
env
# DeepSeek API 配置
DEEPSEEK_API_KEY=your_api_key_here
# 数据库配置
DB_HOST=localhost
DB_PORT=5432
DB_NAME=insurance_db
DB_USER=your_username
DB_PASSWORD=your_password
```
### 3. 创建日志文件夹
```bash
mkdir logs
```
### 4. 运行程序
```bash
python main.py
```
### 5. 独立模块测试
```bash
python test_app_modules.py
```
批量校验配置、数据库、大模型、Agent 运行状态，输出各模块检测结果。

## 常见问题
1.日志目录缺失
执行以下命令手动创建文件夹：
```bash
mkdir logs
```
2.数据库连接失败
检查 PostgreSQL 服务是否运行
3.核实账号权限
检查 .env 文件中数据库参数配置
4.LLM 初始化失败
核对 .env 文件中 DEEPSEEK_API_KEY 有效性
检查网络连通性
5.查询无结果
查看 logs 日志文件
校验生成 SQL 与库内数据匹配度

## 扩展开发
1.更换数据源
修改 app/agent/database.py 数据库连接地址，安装对应驱动。
2.切换大模型
在 main.py 和 .env 文件中修改以下参数：
LLM_MODEL
LLM_BASE_URL
DEEPSEEK_API_KEY
3.批量查询
调用 InsuranceAgent.batch_query(questions) 方法进行批量查询。
4.自定义测试问题
修改 main.py 中 test_cases 列表添加自定义测试问题。

## 许可证
本项目采用 MIT License 许可。
