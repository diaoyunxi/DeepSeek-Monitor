# DeepSeek 对话监控工具

自动监控 DeepSeek 对话，当发现新对话且消息以 `@` 开头时，自动执行对应的 bash 命令并回复结果。

## 功能特性

- 🔄 每秒自动监控对话列表变化
- 🔐 支持浏览器 Profile 持久化，无需重复登录
- 🤖 自动检测以 `@` 开头的命令并执行
- 📝 将命令执行结果自动回复到对话中
- 🖥️ 支持无头模式运行，适合服务器部署
- 📊 详细的 DEBUG 级别日志记录

## 环境要求

- Python 3.8+
- Chrome/Chromium 浏览器
- Google ChromeDriver（需与 Chrome 版本匹配）

## 安装步骤

### 1. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

### 2. 安装 ChromeDriver

确保系统中已安装 ChromeDriver，或者让 Selenium 自动下载：

```bash
# 方法一：使用 selenium-manager（Selenium 4.6+ 自动处理）
# 无需额外安装

# 方法二：手动安装
# 访问 https://chromedriver.chromium.org/ 下载对应版本
```

### 3. 配置账号密码

编辑 `config.json` 文件，填入你的 DeepSeek 手机号和验证码：

```json
{
    "phone": "你的DeepSeek手机号",
    "code": "验证码",
    "profile_dir": "./browser_profile"
}
```

**重要**：`config.json` 已在 `.gitignore` 中排除，请勿提交到版本库。

### 4. 安装 ChromeDriver

程序已配置使用 `/usr/local/bin/chromedriver`，确保已安装：

```bash
# 检查 ChromeDriver 版本
chromedriver --version

# 如需重新安装（Chrome 151 对应 ChromeDriver 151）
# 从 https://googlechromelabs.github.io/chrome-for-testing/ 下载
```

### 4. 运行监控

```bash
python deepseek_monitor.py
```

## 使用说明

### 基本用法

程序启动后会：
1. 自动打开 DeepSeek 登录页面
2. 使用配置文件中的账号密码登录
3. 每秒检查一次对话列表
4. 发现新对话时点击并检查消息内容
5. 如果消息以 `@` 开头，执行对应命令并回复结果

### 命令示例

在 DeepSeek 对话中发送以下消息：

```
@ls -la
@echo "Hello World"
@whoami
@date
```

程序会自动执行这些命令并将结果回复到对话中。

### 后台运行

使用 `nohup` 或 `screen` 在后台运行：

```bash
# 使用 nohup
nohup python deepseek_monitor.py > monitor.log 2>&1 &

# 使用 screen
screen -S deepseek-monitor
python deepseek_monitor.py
# 按 Ctrl+A, D 脱离 screen
```

## 文件结构

```
DeepSeek-Monitor/
├── deepseek_monitor.py    # 主程序
├── config.json            # 配置文件（需手动填写账号密码）
├── requirements.txt       # Python 依赖
├── .gitignore            # Git 忽略规则
├── browser_profile/      # 浏览器数据目录（自动生成）
└── deepseek_monitor.log  # 运行日志
```

## 注意事项

1. **首次运行**：首次登录需要在浏览器中手动验证（如果需要），之后会保存登录状态
2. **浏览器窗口**：无头模式下浏览器不可见，如需调试可修改代码中的 `--headless` 参数
3. **命令超时**：单个命令最长执行 60 秒，超时会自动终止
4. **敏感信息**：`config.json` 包含账号密码，请勿提交到版本库

## 故障排除

### 问题：登录失败

- 检查账号密码是否正确
- 确认网络连接正常
- 查看 `deepseek_monitor.log` 日志了解详情

### 问题：找不到对话元素

- DeepSeek 页面可能更新了结构，需要调整 CSS 选择器
- 检查浏览器是否成功加载页面

### 问题：命令执行无响应

- 检查命令是否有语法错误
- 确认命令执行权限
- 查看日志中的错误信息

## 许可证

MIT License
