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
import time
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
    level=logging.DEBUG,
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
        self.last_conversations: set = set()  # 上一秒的对话集合
        self.processed_conversations: set = set()  # 已处理过的对话集合
        self.is_first_run: bool = True  # 是否首次运行
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
            logger.debug(f"使用浏览器数据目录: {self.profile_dir}")

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
            self.driver = self._setup_driver()
            logger.info("正在打开 DeepSeek 登录页面...")
            self.driver.get(LOGIN_URL)

            # 等待页面加载
            time.sleep(3)

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
            logger.debug("等待登录表单加载...")
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "input"))
            )

            # 如果是密码登录，先点击"密码登录"按钮
            if login_type == "password":
                logger.debug("检测到密码登录模式，正在点击密码登录按钮...")
                self._click_password_login()

            # 获取所有输入框
            inputs = self.driver.find_elements(By.TAG_NAME, "input")
            logger.debug(f"找到 {len(inputs)} 个输入框")

            # 填写手机号
            if len(inputs) >= 1:
                logger.debug("正在输入手机号...")
                inputs[0].clear()
                inputs[0].send_keys(phone)

            # 根据登录方式填写密码或验证码
            if login_type == "password":
                password = self.config.get("password", "")
                if len(inputs) >= 2:
                    logger.debug("正在输入密码...")
                    inputs[1].clear()
                    inputs[1].send_keys(password)
            else:
                code = self.config.get("code", "")
                if len(inputs) >= 2:
                    logger.debug("正在输入验证码...")
                    inputs[1].clear()
                    inputs[1].send_keys(code)

            # 查找并点击登录按钮
            logger.debug("正在点击登录按钮...")
            self._click_login_button()

            # 等待登录完成
            logger.debug("等待登录完成...")
            WebDriverWait(self.driver, 30).until(
                lambda d: "sign_in" not in d.current_url.lower()
            )

            # 额外等待页面加载
            time.sleep(3)

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
                            logger.debug("已点击密码登录按钮")
                            time.sleep(1)
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
                                time.sleep(1)
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
                                logger.debug(f"已点击登录按钮: {text}")
                                return True
                except Exception:
                    continue

            # 备用：点击最后一个可见的按钮
            buttons = self.driver.find_elements(By.CSS_SELECTOR, "[role='button']")
            for btn in reversed(buttons):
                if btn.is_displayed() and btn.is_enabled():
                    btn.click()
                    logger.debug("已点击最后一个可用按钮")
                    return True

            logger.warning("未找到登录按钮")
            return False

        except Exception as e:
            logger.error(f"点击登录按钮时出错: {e}")
            return False

    def _get_conversations(self) -> set:
        """
        获取当前对话列表

        Returns:
            对话标题集合
        """
        conversations = set()
        try:
            # 等待页面完全加载
            time.sleep(2)

            # 获取页面文本内容
            body_text = self.driver.find_element(By.TAG_NAME, "body").text

            if not body_text:
                logger.warning("页面文本为空")
                return conversations

            # 按行分割
            lines = body_text.split('\n')

            # 过滤出有效的对话标题
            exclude_words = ['发送', '登录', '密码', '验证码', 'Terms', 'Privacy',
                           'New chat', 'Start chatting', 'Instant', 'Expert',
                           'Vision', 'DeepThink', 'Search', 'AI-generated',
                           'for reference only', 'Continue', 'Contact us']

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

                conversations.add(line)

            logger.debug(f"从页面提取到 {len(conversations)} 个对话标题")
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
            time.sleep(1)

            # 查找所有可点击元素
            clickables = self.driver.find_elements(By.CSS_SELECTOR, '[role="button"], button, a, [class*="item"], li')

            for elem in clickables:
                try:
                    elem_text = elem.text.strip()
                    if title in elem_text or elem_text == title:
                        elem.click()
                        logger.info(f"已点击对话: {title}")
                        # 等待页面加载
                        time.sleep(2)
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
        获取最后一条用户消息

        Returns:
            消息文本，如果找不到则返回 None
        """
        try:
            # 等待页面加载
            time.sleep(1)

            # 获取页面所有文本
            body_text = self.driver.find_element(By.TAG_NAME, "body").text

            # 尝试查找消息元素
            messages = self.driver.find_elements(By.CSS_SELECTOR, '[class*="message"], [class*="bubble"], [class*="text"]')

            if messages:
                # 从后往前找第一条用户消息
                for msg in reversed(messages):
                    try:
                        text = msg.text.strip()
                        if text and len(text) > 0:
                            logger.debug(f"找到消息: {text[:50]}...")
                            return text
                    except Exception:
                        continue

            # 如果没有找到结构化元素，从页面文本中提取
            if body_text:
                lines = body_text.split('\n')
                for line in reversed(lines):
                    line = line.strip()
                    if line and len(line) > 0:
                        return line

            logger.debug("未找到消息")
            return None

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
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60  # 60秒超时
            )
            logger.debug(f"命令执行完成，返回码: {result.returncode}")
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            logger.error(f"命令执行超时: {command}")
            return "", "命令执行超时", 1
        except Exception as e:
            logger.error(f"命令执行出错: {e}")
            return "", str(e), 1

    def _send_response(self, response_text: str) -> bool:
        """
        发送回复消息

        Args:
            response_text: 回复内容

        Returns:
            发送是否成功
        """
        try:
            # 等待输入框加载
            input_box = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "textarea"))
            )

            # 清空并输入回复内容
            input_box.clear()
            input_box.send_keys(response_text)

            # 发送消息（模拟回车）
            input_box.send_keys(Keys.ENTER)

            logger.info("已发送回复")
            return True

        except Exception as e:
            logger.error(f"发送回复时出错: {e}")
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
                    logger.debug("刷新页面...")
                    self.driver.refresh()
                    time.sleep(3)  # 等待页面加载

                    # 获取当前对话列表
                    current_conversations = self._get_conversations()

                    if self.is_first_run:
                        # 首次运行：缓存所有现有对话，不处理
                        logger.info(f"首次运行，缓存 {len(current_conversations)} 个现有对话")
                        self.last_conversations = current_conversations.copy()
                        self.processed_conversations = current_conversations.copy()
                        self.is_first_run = False
                    else:
                        # 后续运行：只处理新增的对话
                        new_conversations = current_conversations - self.last_conversations - self.processed_conversations

                        if new_conversations:
                            logger.info(f"发现 {len(new_conversations)} 个新对话: {new_conversations}")

                            for conv_title in list(new_conversations)[:3]:  # 限制处理最多3个新对话
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

                                        # 构造回复内容
                                        if returncode == 0:
                                            response = f"✅ 命令执行成功\n\n```\n{stdout}\n```"
                                        else:
                                            response = f"❌ 命令执行失败\n\n错误: {stderr if stderr else '未知错误'}"

                                        # 发送回复
                                        self._send_response(response)
                                        logger.info(f"已处理并回复对话: {conv_title}")
                                    else:
                                        logger.debug(f"对话 '{conv_title}' 的消息不以 @ 开头，跳过")

                                    # 处理完立即标记为已处理，避免重复检查
                                    self.processed_conversations.add(conv_title)
                        else:
                            logger.debug("未检测到新对话")

                    # 更新上一秒的对话列表
                    self.last_conversations = current_conversations.copy()
                    reconnect_count = 0  # 重置重连计数

                except Exception as e:
                    # 处理浏览器会话失效等错误
                    error_msg = str(e)
                    if "invalid session id" in error_msg or "session deleted" in error_msg:
                        logger.warning(f"浏览器会话失效，尝试重新登录... ({reconnect_count + 1}/{max_reconnect})")
                        reconnect_count += 1
                        if reconnect_count >= max_reconnect:
                            logger.error("重连次数过多，退出程序")
                            break
                        try:
                            self.driver.quit()
                            time.sleep(2)
                            if self.login():
                                logger.info("重新登录成功")
                                reconnect_count = 0
                        except Exception as reconnect_err:
                            logger.error(f"重新登录失败: {reconnect_err}")
                    else:
                        logger.warning(f"监控过程中出错: {e}")

                # 短暂等待后继续
                time.sleep(1)

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
