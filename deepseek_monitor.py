#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek 对话监控与命令执行工具
================================
功能：自动登录 DeepSeek，每秒监控对话列表变化，
当发现新对话且消息以 @ 开头时，执行对应 bash 命令并回复结果。
"""

import json
import logging
import subprocess
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("deepseek_monitor.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# DeepSeek 登录页面 URL
LOGIN_URL = "https://chat.deepseek.com/"


class DeepSeekMonitor:
    """DeepSeek 对话监控器"""

    def __init__(self, config_path: str = "config.json"):
        """
        初始化监控器

        Args:
            config_path: 配置文件路径，包含 phone、code 和 profile_dir
        """
        self.config = self._load_config(config_path)
        self.driver: Optional[webdriver.Chrome] = None
        self.last_conversations: set = set()  # 上一秒的对话集合（存储url_id）
        self.processed_conversations: set = set()  # 已处理过的对话集合（存储url_id）
        self.is_first_run: bool = True  # 是否首次运行
        self.conversation_titles: dict = {}  # url_id -> title 的映射
        self.profile_dir = self.config.get("profile_dir", "./browser_profile")
        self.chrome_driver_path = "/usr/local/bin/chromedriver"

    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            # 验证必需字段：至少需要 phone
            if "phone" not in config:
                raise ValueError("配置文件中缺少 phone 字段")
            # 密码登录需要 password，验证码登录需要 code
            login_type = config.get("login_type", "code")
            if login_type == "password" and "password" not in config:
                raise ValueError("密码登录模式需要 password 字段")
            elif login_type == "code" and "code" not in config:
                raise ValueError("验证码登录模式需要 code 字段")
            logger.info(f"成功加载配置文件: {config_path}")
            return config
        except FileNotFoundError:
            logger.error(f"配置文件不存在: {config_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"配置文件 JSON 解析错误: {e}")
            raise

    def _kill_stale_processes(self):
        """
        杀死所有残留的 Chrome 和 ChromeDriver 进程
        """
        try:
            logger.info("正在清理残留的 Chrome 进程...")
            # 杀死所有 chrome 和 chromedriver 进程
            subprocess.run(
                "pkill -9 -f 'chrome|chromedriver' 2>/dev/null || true",
                shell=True,
                capture_output=True
            )
            logger.info("Chrome 进程清理完成")
        except Exception as e:
            logger.warning(f"清理进程时出错: {e}")

    def _setup_driver(self) -> webdriver.Chrome:
        """
        配置并创建 Chrome 浏览器驱动

        Returns:
            配置好的 Chrome WebDriver 实例
        """
        chrome_options = Options()

        # 无头模式
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")

        # 保存浏览器数据目录
        if self.profile_dir:
            chrome_options.add_argument(f"--user-data-dir={self.profile_dir}")

        # 创建 WebDriver 实例，使用已安装的 ChromeDriver
        service = Service(executable_path=self.chrome_driver_path)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(30)
        driver.implicitly_wait(10)
        return driver

    def login(self) -> bool:
        """
        执行登录流程（手机号 + 验证码）

        Returns:
            登录是否成功
        """
        try:
            # 先清理可能存在的旧进程
            self._kill_stale_processes()

            self.driver = self._setup_driver()
            logger.info("正在打开 DeepSeek 登录页面...")
            self.driver.get(LOGIN_URL)

            # 等待页面加载
            

            # 检查是否已经登录
            if self._is_logged_in():
                logger.info("检测到已登录状态，跳过登录流程")
                return True

            # 执行登录
            logger.info("检测到需要登录，正在执行登录流程...")
            return self._perform_login()

        except Exception as e:
            logger.error(f"登录过程中发生错误: {e}")
            return False

    def _is_logged_in(self) -> bool:
        """检查是否已登录"""
        try:
            # 如果 URL 包含 sign_in，说明未登录
            if "sign_in" in self.driver.current_url.lower():
                return False
            # 尝试获取页面标题或内容判断
            title = self.driver.title.lower()
            if "deepseek" in title and "log in" not in title:
                return True
            return False
        except Exception:
            return False

    def _perform_login(self) -> bool:
        """
        执行登录操作（支持密码登录和验证码登录）

        Returns:
            登录是否成功
        """
        try:
            phone = self.config["phone"]
            login_type = self.config.get("login_type", "code")  # "password" 或 "code"

            # 等待登录表单加载
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "input"))
            )

            # 如果是密码登录，先点击"密码登录"按钮
            if login_type == "password":
                self._click_password_login()

            # 获取所有输入框
            inputs = self.driver.find_elements(By.TAG_NAME, "input")

            # 填写手机号
            if len(inputs) >= 1:
                inputs[0].clear()
                inputs[0].send_keys(phone)

            # 根据登录方式填写密码或验证码
            if login_type == "password":
                password = self.config.get("password", "")
                if len(inputs) >= 2:
                    inputs[1].clear()
                    inputs[1].send_keys(password)
            else:
                code = self.config.get("code", "")
                if len(inputs) >= 2:
                    inputs[1].clear()
                    inputs[1].send_keys(code)

            # 查找并点击登录按钮
            self._click_login_button()

            # 等待登录完成
            WebDriverWait(self.driver, 30).until(
                lambda d: "sign_in" not in d.current_url.lower()
            )

            # 额外等待页面加载
            

            logger.info("登录成功！")
            return True

        except TimeoutException:
            logger.error("登录超时，请检查账号信息是否正确")
            return False
        except NoSuchElementException as e:
            logger.error(f"找不到登录元素: {e}")
            return False
        except Exception as e:
            logger.error(f"登录过程中发生未知错误: {e}")
            return False

    def _click_password_login(self) -> bool:
        """点击密码登录按钮"""
        try:
            # 查找"密码登录"或"Login with password"按钮
            selectors = [
                (By.XPATH, "//div[contains(@class, 'ds-button')]//span[contains(text(), '密码登录')]"),
                (By.XPATH, "//div[contains(@class, 'ds-button')]//span[contains(text(), 'Login with password')]"),
                (By.CSS_SELECTOR, ".ds-sign-in-form__social-link span:contains('密码登录')"),
                (By.CSS_SELECTOR, ".ds-sign-in-form__social-link span:contains('Login with password')"),
            ]

            for selector in selectors:
                try:
                    elements = self.driver.find_elements(selector[0], selector[1])
                    for elem in elements:
                        if elem.is_displayed():
                            elem.click()
                            
                            return True
                except Exception:
                    continue

            # 备用方案：查找包含"password"或"密码"的元素
            all_elements = self.driver.find_elements(By.TAG_NAME, "*")
            for elem in all_elements:
                text = elem.text.lower()
                if "password" in text or "密码" in text:
                    parent = elem.parent or elem
                    try:
                        # 尝试点击父元素或祖父元素
                        for _ in range(3):
                            parent = parent.parent
                            if parent and parent.is_displayed():
                                parent.click()
                                
                                return True
                    except Exception:
                        continue

            logger.warning("未找到密码登录按钮")
            return False

        except Exception as e:
            logger.error(f"点击密码登录按钮时出错: {e}")
            return False

    def _click_login_button(self) -> bool:
        """点击登录按钮"""
        try:
            # 尝试多种选择器
            selectors = [
                (By.CSS_SELECTOR, "div.ds-button[role='button']:has-text('Log in')"),
                (By.XPATH, "//div[@role='button' and contains(text(), 'Log in')]"),
                (By.XPATH, "//div[@role='button' and contains(text(), '登录')]"),
                (By.CSS_SELECTOR, ".ds-button[role='button']"),
            ]

            for selector in selectors:
                try:
                    elements = self.driver.find_elements(selector[0], selector[1])
                    for elem in elements:
                        if elem.is_displayed() and elem.is_enabled():
                            text = elem.text.strip()
                            if "log in" in text.lower() or "登录" in text:
                                elem.click()
                                return True
                except Exception:
                    continue

            # 备用：点击最后一个可见的按钮
            buttons = self.driver.find_elements(By.CSS_SELECTOR, "[role='button']")
            for btn in reversed(buttons):
                if btn.is_displayed() and btn.is_enabled():
                    btn.click()
                    return True

            logger.warning("未找到登录按钮")
            return False

        except Exception as e:
            logger.error(f"点击登录按钮时出错: {e}")
            return False

    def _get_conversations(self) -> list:
        """
        获取当前对话列表

        Returns:
            [(标题, url_id)] 列表
        """
        conversations = []
        try:
            # 等待页面完全加载


            # 获取页面源代码，使用更精确的选择器
            # 对话链接：class="_546d736" 且包含 href="/a/chat/s/"
            conversation_links = self.driver.find_elements(
                By.CSS_SELECTOR,
                "a[href*='/a/chat/s/']"
            )

            if conversation_links:
                for link in conversation_links:
                    try:
                        # 获取对话标题（在 class="c08e6e93" 的 div 中）
                        title_elem = link.find_element(By.CSS_SELECTOR, "div.c08e6e93")
                        title = title_elem.text.strip()
                        # 提取URL中的对话ID
                        href = link.get_attribute('href')
                        url_id = href.split('/')[-1] if href else ''

                        # 如果 url_id 提取失败，使用标题作为备用 ID
                        if not url_id:
                            url_id = title

                        if title and len(title) > 0:
                            conversations.append((title, url_id))
                            # 更新标题映射
                            self.conversation_titles[url_id] = title
                    except Exception:
                        # 如果找不到标题元素，跳过
                        continue
            else:
                # 备用方案：从页面文本中提取
                body_text = self.driver.find_element(By.TAG_NAME, "body").text

                if body_text:
                    # 按行分割
                    lines = body_text.split('\n')

                    # 过滤出有效的对话标题
                    exclude_words = [
                        '发送', '登录', '密码', '验证码', 'Terms', 'Privacy',
                        'New chat', 'Start chatting', 'Instant', 'Expert',
                        'Vision', 'DeepThink', 'Search', 'AI-generated',
                        'for reference only', 'Continue', 'Contact us',
                        'Today', 'Yesterday', '7 Days', '30 Days',
                        '14 Days', '21 Days', 'Last 7 days', 'Last 30 days'
                    ]

                    # 过滤年份开头的内容（如 "2026-07", "2026-06"）
                    import re
                    year_pattern = re.compile(r'^\d{4}[-/]\d{2}')

                    for line in lines:
                        line = line.strip()
                        # 过滤条件
                        if not line:
                            continue
                        if len(line) < 2 or len(line) > 100:
                            continue
                        if any(word in line for word in exclude_words):
                            continue
                        # 排除明显的非对话内容
                        if line.startswith('@') or line.startswith('#'):
                            continue
                        if 'http' in line.lower():
                            continue
                        # 排除年份标签
                        if year_pattern.match(line):
                            continue

                        conversations.append((line, line))  # 备用方案使用标题作为ID

            return conversations

        except Exception as e:
            logger.warning(f"获取对话列表时出错: {e}")
            return conversations

    def _click_conversation(self, title: str) -> bool:
        """
        点击指定对话

        Args:
            title: 对话标题

        Returns:
            点击是否成功
        """
        try:
            # 等待页面稳定
            

            # 查找所有可点击元素
            clickables = self.driver.find_elements(By.CSS_SELECTOR, '[role="button"], button, a, [class*="item"], li')

            for elem in clickables:
                try:
                    elem_text = elem.text.strip()
                    if title in elem_text or elem_text == title:
                        elem.click()
                        logger.info(f"已点击对话: {title}")
                        # 等待页面加载
                        
                        return True
                except (NoSuchElementException, StaleElementReferenceException):
                    continue

            logger.warning(f"未找到对话: {title}")
            return False

        except Exception as e:
            logger.error(f"点击对话时出错: {e}")
            return False

    def _get_latest_message(self) -> Optional[str]:
        """
        获取当前对话最后一条 @ 命令

        通过 textContent 遍历 DOM 取完整命令，不受 CSS 截断影响。
        限定搜索范围为当前对话的消息容器，按 DOM 顺序取最后一条以 @ 开头的消息。

        Returns:
            以 @ 开头的命令消息；返回空字符串表示已确认该对话不含 @ 命令；
            返回 None 表示发生异常需重试
        """
        try:
            # 等待页面加载，确保消息内容已完全渲染
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            import time
            time.sleep(0.5)

            message = self.driver.execute_script("""
                // 查找当前对话的消息区域（主内容区，排除侧边栏）
                var mainContent = document.querySelector('main') ||
                                  document.querySelector('[role="main"]') ||
                                  document.querySelector('.main') ||
                                  document.body;

                // 策略1：遍历用户消息气泡容器，从后往前找以 @ 开头的消息
                var msgContainers = mainContent.querySelectorAll(
                    '[class*="user-message"], [class*="userMessage"], [class*="message-user"],' +
                    '[class*="assistant-message"], [class*="assistantMessage"], [class*="chat-item"],' +
                    '[class*="bubble"], [class*="msg-"], [data-testid]'
                );
                for (var i = msgContainers.length - 1; i >= 0; i--) {
                    var el = msgContainers[i];
                    var text = el.textContent.trim();
                    if (text.startsWith('@')) {
                        var afterAt = text.slice(1).trim();
                        // 过滤：真正的 bash 命令不含中文解释性描述
                        var hasChineseExplain = /(?:帮我|请|需要|可以|怎么|如何|为什么|怎样|介绍|说明|解释|显示|列出|查看|运行|执行|打开|创建|新建|生成|输出|返回|显示|使用|调用|方法|格式|写法|示例|例子)/.test(afterAt);
                        if (!hasChineseExplain && afterAt.length > 0 && afterAt.length < 200) {
                            return text;
                        }
                    }
                }

                // 策略2：TreeWalker 遍历所有文本节点
                var walker = document.createTreeWalker(
                    mainContent,
                    NodeFilter.SHOW_TEXT,
                    null,
                    false
                );
                var node;
                var lastMatch = null;
                while ((node = walker.nextNode())) {
                    var text = node.textContent;
                    if (text && text.trim().startsWith('@') && text.trim().length > 1) {
                        var trimmed = text.trim();
                        var afterAt = trimmed.slice(1).trim();
                        // 排除对话中间的说明性引用：
                        // 1. @后紧跟中文解释词（帮我/请/方法/格式等）
                        // 2. @后紧跟中文字符（如 '@cd 到某目录'）
                        if (afterAt.length < 200 &&
                            !/^(?:帮我|请|需要|可以|怎么|如何|为什么|怎样|介绍|说明|解释|显示|列出|查看|运行|执行|打开|创建|新建|生成|输出|返回|显示|使用|调用|方法|格式|写法|示例|例子)/.test(afterAt) &&
                            !/^[\\u4e00-\\u9fa5]/.test(afterAt)) {
                            lastMatch = trimmed;
                        }
                    }
                }

                return lastMatch || null;
            """)

            if message:
                message = ' '.join(message.split())
                logger.info(f"获取到命令消息（长度: {len(message)}）")
                return message

            # 未取到 @ 文本：确认该对话不是命令对话
            return ""

        except Exception as e:
            logger.warning(f"获取消息时出错: {e}")
            return None

    def _execute_bash_command(self, command: str) -> tuple:
        """
        执行 bash 命令

        Args:
            command: 要执行的命令

        Returns:
            (stdout, stderr, returncode) 元组
        """
        logger.info(f"执行命令: {command}")
        try:
            # 使用 bash -c 执行，确保参数正确传递
            result = subprocess.run(
                ['bash', '-c', command],
                capture_output=True,
                text=True,
                timeout=60  # 60秒超时
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            logger.error(f"命令执行超时: {command}")
            return "", "命令执行超时", 1
        except Exception as e:
            logger.error(f"命令执行出错: {e}")
            return "", str(e), 1

    def _send_response(self, response_text: str) -> bool:
        """
        发送回复消息 - 使用多策略确保发送成功

        Args:
            response_text: 回复内容

        Returns:
            发送是否成功
        """
        try:
            import time
            from selenium.webdriver.common.action_chains import ActionChains

            # 记录发送前的URL，用于检测页面跳转
            url_before = self.driver.current_url
            logger.info(f"发送前URL: {url_before}")

            # 等待输入框加载并可见
            input_box = WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "textarea[name='search']"))
            )
            logger.info("找到输入框: textarea[name='search']")

            # 使用send_keys设置文本，确保Vue响应式系统正确更新按钮状态
            # 重要：不能使用JS直接设置textarea.value，否则按钮会保持disabled状态
            # 重要：不能一次性send_keys包含换行符(\n)的多行文本，
            # 因为\n会被页面当作Enter键处理，导致第一行被立即单独发送成一条消息，
            # 后续内容丢失换行挤成另一条。正确做法：逐行输入，行与行之间
            # 用 Shift+Enter 组合键插入换行（不触发发送），最后统一按Enter发送，
            # 保证多行命令结果只产生一条带换行的回复。
            response_text = response_text.replace('\r\n', '\n').replace('\r', '\n')
            lines = response_text.split('\n')
            for i, line in enumerate(lines):
                if line:
                    input_box.send_keys(line)
                # 除最后一行外，每行末尾插入换行（Shift+Enter，不触发发送）
                if i < len(lines) - 1:
                    ActionChains(self.driver) \
                        .key_down(Keys.SHIFT) \
                        .send_keys(Keys.ENTER) \
                        .key_up(Keys.SHIFT) \
                        .perform()
            logger.info(f"文本已设置（共 {len(lines)} 行）: {repr(response_text[:30])}...")

            time.sleep(0.5)

            # 多策略发送消息
            sent = False

            # 策略1: 使用键盘Enter发送（首选，最直接）
            if not sent:
                try:
                    logger.info("策略1: 使用键盘Enter发送")
                    actions = ActionChains(self.driver)
                    actions.click(input_box)
                    actions.send_keys(Keys.ENTER)
                    actions.perform()
                    # 等待页面更新
                    time.sleep(2)
                    # 验证发送成功
                    if self._verify_send_success(response_text, url_before):
                        sent = True
                        logger.info("策略1成功")
                except Exception as e:
                    logger.error(f"策略1失败: {e}")

            # 策略2: 使用JavaScript触发keydown事件（备用）
            if not sent:
                try:
                    logger.info("策略2: 使用JavaScript触发Enter事件")
                    result = self.driver.execute_script("""
                        const textarea = document.querySelector('textarea[name="search"]');
                        if (textarea) {
                            textarea.dispatchEvent(new KeyboardEvent('keydown', {
                                key: 'Enter',
                                code: 'Enter',
                                keyCode: 13,
                                bubbles: true
                            }));
                            return 'triggered_enter_event';
                        }
                        return 'not found';
                    """)
                    logger.info(f"策略2 JS结果: {result}")
                    time.sleep(2)
                    if self._verify_send_success(response_text, url_before):
                        sent = True
                        logger.info("策略2成功")
                except Exception as e:
                    logger.error(f"策略2失败: {e}")

            if sent:
                logger.info("已发送回复")
                return True
            else:
                logger.error("所有发送策略均失败")
                return False

        except Exception as e:
            logger.error(f"发送回复时出错: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def _verify_send_success(self, expected_text, url_before=None, timeout=5.0):
        """验证消息是否真正发送成功

        验证条件（必须同时满足）：
        1. 输入框已清空
        2. 消息文本出现在页面中（或URL已跳转到新对话）

        注意：仅检查输入框清空不够，因为点击disabled按钮也会清空输入框

        Args:
            expected_text: 期望发送的文本
            url_before: 发送前的URL（用于检测跳转）
            timeout: 最大等待时间（秒），默认为5秒

        Returns:
            验证是否成功
        """
        import time
        start_time = time.time()
        check_interval = 0.3

        while time.time() - start_time < timeout:
            try:
                # 检查输入框是否为空
                current_input = self.driver.find_element(By.CSS_SELECTOR, "textarea[name='search']")
                current_value = current_input.get_attribute('value')
                input_empty = not current_value or current_value.strip() == ''

                # 检查URL是否变化（新建对话）
                url_changed = False
                if url_before:
                    current_url = self.driver.current_url
                    url_changed = (url_before != current_url and '/a/chat/s/' in current_url)

                # 检查文本是否出现在页面中
                # 注意：多行消息在页面渲染后，空白（换行/空格）格式可能与原文不同
                # （如段落间空行），因此先去除所有空白字符再做包含性比较
                body_text = self.driver.find_element(By.TAG_NAME, "body").text
                text_in_page = ''.join(expected_text.split()) in ''.join(body_text.split())

                # 验证成功条件：输入框清空 AND (文本在页面中 OR URL已变化)
                if input_empty and (text_in_page or url_changed):
                    logger.info("验证通过: 消息已发送成功")
                    return True

            except Exception as e:
                pass
            time.sleep(check_interval)

        logger.warning(f"验证失败: 在{timeout}秒内未检测到发送成功的证据")
        return False

    def run(self):
        """
        运行监控主循环（持续刷新模式）
        """
        logger.info("开始 DeepSeek 监控...")

        # 登录
        if not self.login():
            logger.error("登录失败，退出程序")
            return

        logger.info("监控已启动，持续刷新页面检查新对话...")

        reconnect_count = 0
        max_reconnect = 5

        try:
            while True:
                try:
                    # 刷新页面获取最新对话列表
                    logger.info("刷新页面...")
                    self.driver.refresh()

                    # 获取当前对话列表
                    current_conversations = self._get_conversations()

                    if self.is_first_run:
                        # 首次运行：缓存所有现有对话，不处理
                        logger.info(f"首次运行，缓存 {len(current_conversations)} 个现有对话")
                        self.last_conversations = set(url_id for _, url_id in current_conversations)
                        self.processed_conversations = set(url_id for _, url_id in current_conversations)
                        self.is_first_run = False
                    else:
                        # 后续运行：只处理新增的对话（基于URL ID）
                        current_url_ids = set(url_id for _, url_id in current_conversations)
                        new_url_ids = current_url_ids - self.last_conversations - self.processed_conversations

                        if new_url_ids:
                            # 找到新对话的标题
                            new_conversations = [(title, url_id) for title, url_id in current_conversations if url_id in new_url_ids]
                            logger.info(f"发现 {len(new_conversations)} 个新对话")

                            for conv_title, conv_url_id in new_conversations[:3]:  # 限制处理最多3个新对话
                                # 点击新对话
                                if self._click_conversation(conv_title):
                                    # 获取最新消息
                                    message = self._get_latest_message()

                                    if message and message.startswith("@"):
                                        # 提取命令
                                        command = message[1:].strip()  # 去掉 @ 符号
                                        logger.info(f"检测到 @ 命令: {command}")

                                        # 执行命令
                                        stdout, stderr, returncode = self._execute_bash_command(command)
                                        logger.info(f"命令执行完成，返回码: {returncode}")

                                        # 构造回复内容（不带前缀，保留换行）
                                        # 命令执行完成但没有任何输出时，统一回复 no output
                                        stdout_text = (stdout or "").strip()
                                        stderr_text = (stderr or "").strip()

                                        if returncode == 0:
                                            # 执行成功：优先回复 stdout；
                                            # stdout 为空时回退到 stderr（部分命令把信息输出到 stderr）；
                                            # 两者都为空则回复 no output
                                            if stdout_text:
                                                response = stdout_text
                                            elif stderr_text:
                                                response = stderr_text
                                            else:
                                                response = "no output"
                                        else:
                                            # 执行失败：回复 stderr；
                                            # 无错误输出时回复“执行失败: no output”，保留失败状态说明
                                            response = f"执行失败: {stderr_text if stderr_text else 'no output'}"
                                        logger.info(f"执行结果预览: {response[:100]}{'...' if len(response) > 100 else ''}")

                                        # 发送回复
                                        send_result = self._send_response(response)
                                        logger.info(f"发送回复完成: {'成功' if send_result else '失败'}")

                                        if send_result:
                                            # 等待2秒，确保回复已提交
                                            import time
                                            time.sleep(2)

                                        logger.info(f"已处理并回复对话: {conv_title}")
                                    elif message is None:
                                        # 获取消息时发生异常，不标记为已处理，留到下一轮重试
                                        logger.warning(f"对话 '{conv_title}' 获取消息异常，本轮跳过")
                                        continue
                                    else:
                                        # 返回空字符串表示已确认该对话不含 @ 命令
                                        logger.info(f"对话 '{conv_title}' 不含 @ 命令，跳过")

                                    # 处理完标记为已处理，避免重复检查（使用URL ID）
                                    self.processed_conversations.add(conv_url_id)
                                    logger.info(f"已标记对话为已处理: {conv_title} (ID: {conv_url_id})")
                        else:
                            logger.info("未检测到新对话")

                    # 更新上一秒的对话列表（存储URL ID）
                    current_url_ids = set(url_id for _, url_id in current_conversations)
                    self.last_conversations = current_url_ids
                    reconnect_count = 0  # 重置重连计数

                except Exception as e:
                    # 处理浏览器会话失效等错误
                    error_msg = str(e)
                    if "invalid session id" in error_msg or "session deleted" in error_msg or "session not created" in error_msg:
                        logger.warning(f"浏览器会话失效，尝试重新登录... ({reconnect_count + 1}/{max_reconnect})")
                        reconnect_count += 1
                        if reconnect_count >= max_reconnect:
                            logger.error("重连次数过多，退出程序")
                            break
                        try:
                            if self.driver:
                                try:
                                    self.driver.quit()
                                except:
                                    pass
                            # 清理残留进程
                            self._kill_stale_processes()
                            
                            if self.login():
                                logger.info("重新登录成功")
                                reconnect_count = 0
                        except Exception as reconnect_err:
                            logger.error(f"重新登录失败: {reconnect_err}")
                    else:
                        logger.warning(f"监控过程中出错: {e}")

                # 短暂等待后继续
                

        except KeyboardInterrupt:
            logger.info("收到中断信号，正在关闭...")
        except Exception as e:
            logger.error(f"监控过程中发生错误: {e}")
        finally:
            self.shutdown()

    def shutdown(self):
        """关闭浏览器并清理资源"""
        if self.driver:
            logger.info("正在关闭浏览器...")
            self.driver.quit()
            logger.info("浏览器已关闭")


if __name__ == "__main__":
    monitor = DeepSeekMonitor()
    monitor.run()
