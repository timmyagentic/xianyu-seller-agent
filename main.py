import base64
import json
import asyncio
import inspect
import time
import os
import argparse
import websockets
from loguru import logger
from dotenv import load_dotenv, set_key
from pathlib import Path
from XianyuApis import XianyuApis
import sys
import random


from utils.xianyu_utils import generate_mid, generate_uuid, trans_cookies, generate_device_id, decrypt
from XianyuAgent import FALLBACK_REPLY, XianyuReplyBot
from context_manager import ChatContextManager
from services.delivery.orders import OrderDetail, OrderInfo
from services.delivery.service import DeliveryService
from services.delivery.store import DeliveryStore
from services.listing.fetch_items import sync_published_items
from services.listing.models import PublishRequest
from services.listing.playwright_publish import PlaywrightPublishExecutor
from services.listing.playwright_relist import PlaywrightRelistExecutor, default_relist_management_url
from services.listing.relist import RelistService, load_relist_request
from services.listing.store import ListingStore
from services.messages import MessageDeduplicator, MessageParser
from services.messages.facts import (
    asks_availability,
    asks_new_account,
    item_is_available_for_reply,
    item_mentions_discount,
    item_mentions_new_user,
    item_price_display,
    normalize_stock_quantity,
    reply_claims_discount,
    reply_claims_unavailable,
    stock_state,
)
from services.web_app import run_web_server
from xianyu_qr_login import QRLoginError, run_qr_login_cli


class XianyuLive:
    def __init__(self, cookies_str, reply_bot=None):
        self.xianyu = XianyuApis()
        self.base_url = 'wss://wss-goofish.dingtalk.com/'
        self.cookies_str = cookies_str
        self.cookies = trans_cookies(cookies_str)
        self.xianyu.session.cookies.update(self.cookies)  # 直接使用 session.cookies.update
        self.myid = self.cookies['unb']
        self.device_id = generate_device_id(self.myid)
        self.context_manager = ChatContextManager()
        self.reply_bot = reply_bot or XianyuReplyBot()
        self.auto_reply_enabled = os.getenv("AUTO_REPLY_ENABLED", "true").lower() == "true"
        
        # 心跳相关配置
        self.heartbeat_interval = int(os.getenv("HEARTBEAT_INTERVAL", "15"))  # 心跳间隔，默认15秒
        self.heartbeat_timeout = int(os.getenv("HEARTBEAT_TIMEOUT", "5"))     # 心跳超时，默认5秒
        self.last_heartbeat_time = 0
        self.last_heartbeat_response = 0
        self.heartbeat_task = None
        self.ws = None
        
        # Token刷新相关配置
        self.token_refresh_interval = int(os.getenv("TOKEN_REFRESH_INTERVAL", "3600"))  # Token刷新间隔，默认1小时
        self.token_retry_interval = int(os.getenv("TOKEN_RETRY_INTERVAL", "300"))       # Token重试间隔，默认5分钟
        self.last_token_refresh_time = 0
        self.current_token = None
        self.token_refresh_task = None
        self.connection_restart_flag = False  # 连接重启标志

        # Cookie续期配置，参考 xianyu-auto-reply 的登录态定时续期策略
        self.cookie_refresh_enabled = os.getenv("COOKIE_REFRESH_ENABLED", "true").lower() == "true"
        self.cookie_refresh_interval = max(60, int(os.getenv("COOKIE_REFRESH_INTERVAL", "600")))
        self.cookie_refresh_retry_interval = max(30, int(os.getenv("COOKIE_REFRESH_RETRY_INTERVAL", "300")))
        self.last_cookie_refresh_time = 0
        self.cookie_refresh_task = None
        
        # 人工接管相关配置
        self.manual_mode_conversations = set()  # 存储处于人工接管模式的会话ID
        self.manual_mode_timeout = int(os.getenv("MANUAL_MODE_TIMEOUT", "3600"))  # 人工接管超时时间，默认1小时
        self.manual_mode_timestamps = {}  # 记录进入人工模式的时间
        
        # 消息过期时间配置
        self.message_expire_time = int(os.getenv("MESSAGE_EXPIRE_TIME", "300000"))  # 消息过期时间，默认5分钟
        self.message_parser = MessageParser(
            myid=self.myid,
            decrypt_func=decrypt,
            message_expire_time_ms=self.message_expire_time,
        )
        self.message_deduplicator = MessageDeduplicator()
        db_path = os.getenv("DB_PATH", "data/chat_history.db")
        self.delivery_store = DeliveryStore(db_path=db_path)
        self.listing_store = ListingStore(db_path=db_path)
        self.delivery_service = DeliveryService(
            store=self.delivery_store,
            send_message=self.send_delivery_message,
            enabled=os.getenv("AUTO_DELIVERY_ENABLED", "false").lower() == "true",
            post_delivery_hook=self.handle_post_delivery_relist,
            confirm_delivery=self.confirm_platform_delivery,
            confirm_delivery_enabled=os.getenv("AUTO_CONFIRM_DELIVERY_ENABLED", "false").lower() == "true",
        )
        self.order_detail_provider = self.fetch_order_detail_for_delivery
        
        # 人工接管关键词，从环境变量读取
        self.toggle_keywords = os.getenv("TOGGLE_KEYWORDS", "。")
        
        # 模拟人工输入配置
        self.simulate_human_typing = os.getenv("SIMULATE_HUMAN_TYPING", "False").lower() == "true"

    def sync_runtime_cookies(self):
        """Sync the latest API-session cookies into WebSocket runtime headers."""
        cookie_string = self.xianyu.get_cookie_string()
        if cookie_string:
            self.cookies_str = cookie_string
            self.cookies = trans_cookies(cookie_string)
        return cookie_string

    def has_enabled_delivery_config(self, item_id: str) -> bool:
        store = getattr(self, "delivery_store", None)
        if store is None:
            delivery_service = getattr(self, "delivery_service", None)
            store = getattr(delivery_service, "store", None)
        if store is None:
            return False
        try:
            return store.get_enabled_config(str(item_id)) is not None
        except Exception as exc:
            logger.error(f"检查商品发货配置失败: item_id={item_id}, error={exc}")
            return False

    def has_enabled_auto_relist_config(self, item_id: str) -> bool:
        store = getattr(self, "listing_store", None)
        if store is None:
            return False
        try:
            return store.get_enabled_auto_relist_config(str(item_id)) is not None
        except Exception as exc:
            logger.error(f"检查商品自动上架配置失败: item_id={item_id}, error={exc}")
            return False

    def is_item_configured_for_automation(self, item_id: str) -> bool:
        """Only configured items are allowed to enter automatic workflows."""
        if not item_id:
            return False
        return self.has_enabled_delivery_config(item_id) or self.has_enabled_auto_relist_config(item_id)

    async def refresh_token(self):
        """刷新token"""
        try:
            logger.info("开始刷新token...")
            
            # 获取新token（如果Cookie失效，get_token会直接退出程序）
            token_result = self.xianyu.get_token(self.device_id)
            if 'data' in token_result and 'accessToken' in token_result['data']:
                new_token = token_result['data']['accessToken']
                self.current_token = new_token
                self.last_token_refresh_time = time.time()
                self.sync_runtime_cookies()
                logger.info("Token刷新成功")
                return new_token
            else:
                logger.error(f"Token刷新失败: {token_result}")
                return None
                
        except Exception as e:
            logger.error(f"Token刷新异常: {str(e)}")
            return None

    async def refresh_cookies(self):
        """Refresh login cookies through the mtop login-user API."""
        try:
            logger.info("开始执行登录态Cookie续期...")
            result = self.xianyu.renew_login_cookies()
            if inspect.isawaitable(result):
                result = await result

            status = result.get("status", "failed")
            message = result.get("message", "")
            if status in {"success", "cookie_updated", "token_refreshed"}:
                self.sync_runtime_cookies()
                self.last_cookie_refresh_time = time.time()
                logger.info(f"登录态Cookie续期完成: {status}, {message}")
                return True

            if status in {"session_expired", "token_empty"}:
                logger.warning(f"登录态Cookie续期需要人工处理: {message}")
            else:
                logger.warning(f"登录态Cookie续期失败: {message}")
            return False
        except Exception as e:
            logger.warning(f"登录态Cookie续期异常: {e}")
            return False

    async def cookie_refresh_loop(self):
        """Periodically renew cookies before the mtop token naturally expires."""
        if not self.cookie_refresh_enabled:
            logger.info("登录态Cookie续期已关闭")
            return

        while True:
            try:
                current_time = time.time()
                if current_time - self.last_cookie_refresh_time >= self.cookie_refresh_interval:
                    success = await self.refresh_cookies()
                    if not success:
                        await asyncio.sleep(self.cookie_refresh_retry_interval)
                        continue
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"登录态Cookie续期循环异常: {e}")
                await asyncio.sleep(self.cookie_refresh_retry_interval)

    async def token_refresh_loop(self):
        """Token刷新循环"""
        while True:
            try:
                current_time = time.time()
                
                # 检查是否需要刷新token
                if current_time - self.last_token_refresh_time >= self.token_refresh_interval:
                    logger.info("Token即将过期，准备刷新...")
                    
                    new_token = await self.refresh_token()
                    if new_token:
                        logger.info("Token刷新成功，准备重新建立连接...")
                        # 设置连接重启标志
                        self.connection_restart_flag = True
                        # 关闭当前WebSocket连接，触发重连
                        if self.ws:
                            await self.ws.close()
                        break
                    else:
                        logger.error("Token刷新失败，将在{}分钟后重试".format(self.token_retry_interval // 60))
                        await asyncio.sleep(self.token_retry_interval)  # 使用配置的重试间隔
                        continue
                
                # 每分钟检查一次
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Token刷新循环出错: {e}")
                await asyncio.sleep(60)

    async def send_msg(self, ws, cid, toid, text):
        text = {
            "contentType": 1,
            "text": {
                "text": text
            }
        }
        text_base64 = str(base64.b64encode(json.dumps(text).encode('utf-8')), 'utf-8')
        msg = {
            "lwp": "/r/MessageSend/sendByReceiverScope",
            "headers": {
                "mid": generate_mid()
            },
            "body": [
                {
                    "uuid": generate_uuid(),
                    "cid": f"{cid}@goofish",
                    "conversationType": 1,
                    "content": {
                        "contentType": 101,
                        "custom": {
                            "type": 1,
                            "data": text_base64
                        }
                    },
                    "redPointPolicy": 0,
                    "extension": {
                        "extJson": "{}"
                    },
                    "ctx": {
                        "appVersion": "1.0",
                        "platform": "web"
                    },
                    "mtags": {},
                    "msgReadStatusSetting": 1
                },
                {
                    "actualReceivers": [
                        f"{toid}@goofish",
                        f"{self.myid}@goofish"
                    ]
                }
            ]
        }
        await ws.send(json.dumps(msg))
        return True

    async def send_delivery_message(self, *, chat_id, buyer_id, content):
        """Send an auto-delivery message through the active WebSocket."""
        if not self.ws:
            raise RuntimeError("WebSocket is not connected")
        await self.send_msg(self.ws, chat_id, buyer_id, content)
        return True

    async def fetch_order_detail_for_delivery(self, order_id: str) -> OrderDetail:
        """Fetch order detail when the API method is available; otherwise use safe defaults."""
        get_order_detail = getattr(self.xianyu, "get_order_detail", None)
        if not get_order_detail:
            return OrderDetail()
        response = get_order_detail(order_id)
        if inspect.isawaitable(response):
            response = await response
        if isinstance(response, OrderDetail):
            return response
        if isinstance(response, dict):
            return self.xianyu.parse_order_detail_response(response)
        return OrderDetail()

    async def confirm_platform_delivery(self, order: OrderInfo):
        """Confirm no-logistics delivery on Xianyu after delivery content is sent."""
        confirm_delivery = getattr(self.xianyu, "confirm_delivery", None)
        if not confirm_delivery:
            return {"success": False, "error": "confirm_delivery_not_available"}
        result = confirm_delivery(order.order_id, item_id=order.item_id)
        if inspect.isawaitable(result):
            result = await result
        self.sync_runtime_cookies()
        return result

    async def init(self, ws):
        # 如果没有token或者token过期，获取新token
        if not self.current_token or (time.time() - self.last_token_refresh_time) >= self.token_refresh_interval:
            logger.info("获取初始token...")
            await self.refresh_token()
        
        if not self.current_token:
            logger.error("无法获取有效token，初始化失败")
            raise Exception("Token获取失败")
            
        msg = {
            "lwp": "/reg",
            "headers": {
                "cache-header": "app-key token ua wv",
                "app-key": "444e9908a51d1cb236a27862abc769c9",
                "token": self.current_token,
                "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 DingTalk(2.1.5) OS(Windows/10) Browser(Chrome/133.0.0.0) DingWeb/2.1.5 IMPaaS DingWeb/2.1.5",
                "dt": "j",
                "wv": "im:3,au:3,sy:6",
                "sync": "0,0;0;0;",
                "did": self.device_id,
                "mid": generate_mid()
            }
        }
        await ws.send(json.dumps(msg))
        # 等待一段时间，确保连接注册完成
        await asyncio.sleep(1)
        msg = {"lwp": "/r/SyncStatus/ackDiff", "headers": {"mid": "5701741704675979 0"}, "body": [
            {"pipeline": "sync", "tooLong2Tag": "PNM,1", "channel": "sync", "topic": "sync", "highPts": 0,
             "pts": int(time.time() * 1000) * 1000, "seq": 0, "timestamp": int(time.time() * 1000)}]}
        await ws.send(json.dumps(msg))
        logger.info('连接注册完成')

    def is_chat_message(self, message):
        """判断是否为用户聊天消息"""
        try:
            return (
                isinstance(message, dict) 
                and "1" in message 
                and isinstance(message["1"], dict)  # 确保是字典类型
                and "10" in message["1"]
                and isinstance(message["1"]["10"], dict)  # 确保是字典类型
                and "reminderContent" in message["1"]["10"]
            )
        except Exception:
            return False

    def is_sync_package(self, message_data):
        """判断是否为同步包消息"""
        try:
            return (
                isinstance(message_data, dict)
                and "body" in message_data
                and "syncPushPackage" in message_data["body"]
                and "data" in message_data["body"]["syncPushPackage"]
                and len(message_data["body"]["syncPushPackage"]["data"]) > 0
            )
        except Exception:
            return False

    def is_typing_status(self, message):
        """判断是否为用户正在输入状态消息"""
        try:
            return (
                isinstance(message, dict)
                and "1" in message
                and isinstance(message["1"], list)
                and len(message["1"]) > 0
                and isinstance(message["1"][0], dict)
                and "1" in message["1"][0]
                and isinstance(message["1"][0]["1"], str)
                and "@goofish" in message["1"][0]["1"]
            )
        except Exception:
            return False

    def is_system_message(self, message):
        """判断是否为系统消息"""
        try:
            return (
                isinstance(message, dict)
                and "3" in message
                and isinstance(message["3"], dict)
                and "needPush" in message["3"]
                and message["3"]["needPush"] == "false"
            )
        except Exception:
            return False
    
    def is_bracket_system_message(self, message):
        """检查是否为带中括号的系统消息"""
        try:
            if not message or not isinstance(message, str):
                return False
            
            clean_message = message.strip()
            # 检查是否以 [ 开头，以 ] 结尾
            if clean_message.startswith('[') and clean_message.endswith(']'):
                logger.debug(f"检测到系统消息: {clean_message}")
                return True
            return False
        except Exception as e:
            logger.error(f"检查系统消息失败: {e}")
            return False

    def check_toggle_keywords(self, message):
        """检查消息是否包含切换关键词"""
        message_stripped = message.strip()
        return message_stripped in self.toggle_keywords

    def is_manual_mode(self, chat_id):
        """检查特定会话是否处于人工接管模式"""
        if chat_id not in self.manual_mode_conversations:
            return False
        
        # 检查是否超时
        current_time = time.time()
        if chat_id in self.manual_mode_timestamps:
            if current_time - self.manual_mode_timestamps[chat_id] > self.manual_mode_timeout:
                # 超时，自动退出人工模式
                self.exit_manual_mode(chat_id)
                return False
        
        return True

    def enter_manual_mode(self, chat_id):
        """进入人工接管模式"""
        self.manual_mode_conversations.add(chat_id)
        self.manual_mode_timestamps[chat_id] = time.time()

    def exit_manual_mode(self, chat_id):
        """退出人工接管模式"""
        self.manual_mode_conversations.discard(chat_id)
        if chat_id in self.manual_mode_timestamps:
            del self.manual_mode_timestamps[chat_id]

    def toggle_manual_mode(self, chat_id):
        """切换人工接管模式"""
        if self.is_manual_mode(chat_id):
            self.exit_manual_mode(chat_id)
            return "auto"
        else:
            self.enter_manual_mode(chat_id)
            return "manual"
    
    def format_price(self, price):
        """
        处理逻辑：标准化价格（分转元）
        """
        try:
            return round(float(price) / 100, 2)
        except (ValueError, TypeError):
            # 遇到 None 或脏数据，默认返回 0
            return 0.0

    def availability_reply(self, item_id):
        delivery_enabled = self.has_enabled_delivery_config(item_id)
        delivery_service = getattr(self, "delivery_service", None)
        if delivery_enabled and getattr(delivery_service, "enabled", False):
            return "有的，拍下后自动发货"
        if delivery_enabled:
            return "有的，拍下后会发货"
        return "有的，直接拍就行"

    def build_fact_reply(self, user_msg, item_info, item_id):
        """Return deterministic replies for facts where LLM hallucination is high risk."""
        if asks_availability(user_msg):
            if item_is_available_for_reply(item_info):
                return self.availability_reply(item_id)
            return FALLBACK_REPLY

        if asks_new_account(user_msg):
            if item_mentions_new_user(item_info):
                if self.has_enabled_delivery_config(item_id):
                    delivery_text = self.availability_reply(item_id).replace("有的，", "")
                    return f"新号可以用，{delivery_text}"
                return "新号可以用，按页面提示领取"
            return FALLBACK_REPLY

        return None

    def guard_fact_reply(self, reply, item_info, item_id, intent=None):
        if reply_claims_unavailable(reply) and item_is_available_for_reply(item_info):
            logger.warning("拦截未被商品事实支持的缺货回复: item_id={}, reply={}", item_id, reply)
            return self.availability_reply(item_id)

        if intent != "price" and reply_claims_discount(reply) and not item_mentions_discount(item_info):
            logger.warning("拦截未被商品事实支持的优惠回复: item_id={}, reply={}", item_id, reply)
            return FALLBACK_REPLY

        return reply
    
    def build_item_description(self, item_info):
        """构建商品描述"""
        
        # 处理 SKU 列表
        clean_skus = []
        raw_sku_list = item_info.get('skuList', [])
        
        for sku in raw_sku_list:
            # 提取规格文本
            specs = [p['valueText'] for p in sku.get('propertyList', []) if p.get('valueText')]
            spec_text = " ".join(specs) if specs else "默认规格"
            
            clean_skus.append({
                "spec": spec_text,
                "price": self.format_price(sku.get('price', 0)),
                "stock": normalize_stock_quantity(sku.get('quantity')) if 'quantity' in sku else None
            })

        # 获取价格
        valid_prices = [s['price'] for s in clean_skus if s['price'] > 0]
        
        if valid_prices:
            min_price = min(valid_prices)
            max_price = max(valid_prices)
            if min_price == max_price:
                price_display = f"¥{min_price}"
            else:
                price_display = f"¥{min_price} - ¥{max_price}" # 价格区间
        else:
            # 如果没有SKU价格，回退使用商品主价格
            price_display = item_price_display(item_info)

        summary = {
            "title": item_info.get('title', ''),
            "desc": item_info.get('desc', ''),
            "price_range": price_display,
            "total_stock": normalize_stock_quantity(item_info.get('quantity')) if 'quantity' in item_info else None,
            "stock_state": stock_state(item_info),
            "status": item_info.get('status', ''),
            "platform_status_text": item_info.get('platform_status_text', ''),
            "sku_details": clean_skus
        }

        return json.dumps(summary, ensure_ascii=False)

    async def handle_message(self, message_data, websocket):
        """处理所有类型的消息"""
        try:

            try:
                message = message_data
                ack = {
                    "code": 200,
                    "headers": {
                        "mid": message["headers"]["mid"] if "mid" in message["headers"] else generate_mid(),
                        "sid": message["headers"]["sid"] if "sid" in message["headers"] else '',
                    }
                }
                if 'app-key' in message["headers"]:
                    ack["headers"]["app-key"] = message["headers"]["app-key"]
                if 'ua' in message["headers"]:
                    ack["headers"]["ua"] = message["headers"]["ua"]
                if 'dt' in message["headers"]:
                    ack["headers"]["dt"] = message["headers"]["dt"]
                await websocket.send(json.dumps(ack))
            except Exception as e:
                pass

            incoming_messages = self.message_parser.parse_message_data(message_data)
            if not incoming_messages:
                return

            for incoming in incoming_messages:
                if self.message_deduplicator.mark_seen(incoming.message_id):
                    logger.debug(f"消息已处理，跳过: {incoming.message_id}")
                    continue
                await self.handle_incoming_message(incoming, websocket)
            
        except Exception as e:
            logger.error(f"处理消息时发生错误: {str(e)}")
            logger.debug(f"原始消息: {message_data}")

    async def handle_incoming_message(self, incoming, websocket):
        if incoming.kind == "paid_order":
            await self.handle_paid_order_message(incoming, websocket)
            return

        if incoming.kind != "chat":
            logger.debug(f"非聊天消息，暂不触发自动回复: {incoming.kind}")
            return

        send_user_name = incoming.sender_name
        send_user_id = incoming.sender_id
        send_message = incoming.text
        item_id = incoming.item_id
        chat_id = incoming.chat_id
        message = incoming.raw

        if not item_id:
            logger.warning("无法获取商品ID")
            return
        if not self.is_item_configured_for_automation(item_id):
            logger.info(f"商品 {item_id} 未配置自动化，跳过自动回复")
            return

        # 检查是否为卖家（自己）发送的控制命令
        if incoming.is_from_self:
            logger.debug("检测到卖家消息，检查是否为控制命令")

            # 检查切换命令
            if self.check_toggle_keywords(send_message):
                mode = self.toggle_manual_mode(chat_id)
                if mode == "manual":
                    logger.info(f"🔴 已接管会话 {chat_id} (商品: {item_id})")
                else:
                    logger.info(f"🟢 已恢复会话 {chat_id} 的自动回复 (商品: {item_id})")
                return

            # 记录卖家人工回复
            self.context_manager.add_message_by_chat(chat_id, self.myid, item_id, "assistant", send_message)
            logger.info(f"卖家人工回复 (会话: {chat_id}, 商品: {item_id}): {send_message}")
            return

        logger.info(f"用户: {send_user_name} (ID: {send_user_id}), 商品: {item_id}, 会话: {chat_id}, 消息: {send_message}")

        if not self.auto_reply_enabled:
            logger.info(f"自动回复已关闭，跳过会话 {chat_id} 的普通聊天回复")
            return

        # 如果当前会话处于人工接管模式，不进行自动回复
        if self.is_manual_mode(chat_id):
            logger.info(f"🔴 会话 {chat_id} 处于人工接管模式，跳过自动回复")
            # 添加用户消息到上下文
            self.context_manager.add_message_by_chat(chat_id, send_user_id, item_id, "user", send_message)
            return
        # 检查是否为带中括号的系统消息
        if self.is_bracket_system_message(send_message):
            logger.info(f"检测到系统消息：'{send_message}'，跳过自动回复")
            return
        if self.is_system_message(message):
            logger.debug("系统消息，跳过处理")
            return
        # 从数据库中获取商品信息，如果不存在则从API获取并保存
        item_info = self.context_manager.get_item_info(item_id)
        if not item_info:
            logger.info(f"从API获取商品信息: {item_id}")
            api_result = self.xianyu.get_item_info(item_id)
            if 'data' in api_result and 'itemDO' in api_result['data']:
                item_info = api_result['data']['itemDO']
                # 保存商品信息到数据库
                self.context_manager.save_item_info(item_id, item_info)
            else:
                logger.warning(f"获取商品信息失败: {api_result}")
                return
        else:
            logger.info(f"从数据库获取商品信息: {item_id}")

        item_description = f"当前商品的信息如下：{self.build_item_description(item_info)}"

        # 获取完整的对话上下文
        context = self.context_manager.get_context_by_chat(chat_id)
        bot_reply = self.build_fact_reply(send_message, item_info, item_id)
        if bot_reply is not None:
            self.reply_bot.last_intent = "fact"
            logger.info(f"使用商品事实保护回复: {bot_reply}")
        else:
            # 生成回复
            bot_reply = self.reply_bot.generate_reply(
                send_message,
                item_description,
                context=context,
                item_id=item_id,
                chat_id=chat_id,
            )
            bot_reply = self.guard_fact_reply(
                bot_reply,
                item_info,
                item_id,
                intent=self.reply_bot.last_intent,
            )

        # 检查是否需要回复
        if bot_reply == "-":
            logger.info(f"[无需回复] 用户 {send_user_name} 的消息被识别为无需回复类型")
            return

        # 添加用户消息到上下文
        self.context_manager.add_message_by_chat(chat_id, send_user_id, item_id, "user", send_message)

        # 检查是否为价格意图，如果是则增加议价次数
        if self.reply_bot.last_intent == "price":
            self.context_manager.increment_bargain_count_by_chat(chat_id)
            bargain_count = self.context_manager.get_bargain_count_by_chat(chat_id)
            logger.info(f"用户 {send_user_name} 对商品 {item_id} 的议价次数: {bargain_count}")

        # 添加机器人回复到上下文
        self.context_manager.add_message_by_chat(chat_id, self.myid, item_id, "assistant", bot_reply)

        logger.info(f"机器人回复: {bot_reply}")

        # 模拟人工输入延迟
        if self.simulate_human_typing:
            # 基础延迟 0-1秒 + 每字 0.1-0.3秒
            base_delay = random.uniform(0, 1)
            typing_delay = len(bot_reply) * random.uniform(0.1, 0.3)
            total_delay = base_delay + typing_delay
            # 设置最大延迟上限，防止过长回复等待太久
            total_delay = min(total_delay, 10.0)

            logger.info(f"模拟人工输入，延迟发送 {total_delay:.2f} 秒...")
            await asyncio.sleep(total_delay)

        await self.send_msg(websocket, chat_id, send_user_id, bot_reply)
        await self.mark_message_read(websocket, chat_id, incoming.message_id)

    async def handle_paid_order_message(self, incoming, websocket):
        if not incoming.order_id:
            logger.warning("付款消息缺少订单号，跳过自动发货")
            return None
        if not incoming.item_id:
            logger.warning(f"订单 {incoming.order_id} 缺少商品ID，跳过自动发货")
            return None
        if not incoming.chat_id or not incoming.sender_id:
            logger.warning(f"订单 {incoming.order_id} 缺少会话或买家ID，跳过自动发货")
            return None
        if not self.has_enabled_delivery_config(incoming.item_id):
            logger.info(f"商品 {incoming.item_id} 未配置自动发货，跳过订单 {incoming.order_id}")
            return None

        detail = await self._load_order_detail_for_delivery(incoming.order_id)
        order = OrderInfo(
            order_id=incoming.order_id,
            item_id=incoming.item_id,
            buyer_id=incoming.sender_id,
            chat_id=incoming.chat_id,
            buyer_name=self._delivery_buyer_name(incoming.sender_name),
            item_title="",
            quantity=max(int(detail.quantity or 1), 1),
            spec_name=detail.spec_name,
            spec_value=detail.spec_value,
        )
        result = await self.delivery_service.deliver_order(order)
        logger.info(
            "自动发货处理结果: 订单={}, 商品={}, 会话={}, 状态={}",
            order.order_id,
            order.item_id,
            order.chat_id,
            result.status,
        )
        if result.status in {"sent", "already_sent", "sent_confirm_failed", "already_sent_confirm_failed"}:
            await self.mark_message_read(websocket, incoming.chat_id, incoming.message_id)
        return result

    async def handle_post_delivery_relist(self, order: OrderInfo, result):
        if getattr(result, "status", "") != "sent":
            logger.debug(
                "跳过发货后自动重新上架: 订单={}, 商品={}, 发货状态={}",
                order.order_id,
                order.item_id,
                getattr(result, "status", ""),
            )
            return
        if os.getenv("AUTO_RELIST_ENABLED", "false").lower() != "true":
            return

        config = self.listing_store.get_enabled_auto_relist_config(order.item_id)
        if not config:
            return

        allow_playwright = config.allow_playwright or os.getenv("AUTO_RELIST_ALLOW_PLAYWRIGHT", "false").lower() == "true"
        confirm_playwright = os.getenv("AUTO_RELIST_CONFIRM_PLAYWRIGHT", "false").lower() == "true"
        cookie_string = self.sync_runtime_cookies()
        relist_executor = _build_playwright_relist_executor(
            cookies_str=cookie_string,
            allow_playwright=allow_playwright and confirm_playwright,
            target_stock=config.target_stock,
        )
        playwright_required_reason = "auto_relist_confirmation_required" if allow_playwright and not confirm_playwright else ""
        service = RelistService(
            listing_store=self.listing_store,
            delivery_store=self.delivery_store,
            api_client=self.xianyu,
            allow_playwright=allow_playwright,
            relist_executor=relist_executor,
            playwright_required_reason=playwright_required_reason,
        )
        relist_result = await service.relist(
            {
                "item_id": order.item_id,
                "expected_title": config.expected_title or order.item_title,
                "target_stock": config.target_stock,
            }
        )
        logger.info(
            "发货后自动重新上架结果: 订单={}, 商品={}, 目标库存={}, 状态={}, 原因={}",
            order.order_id,
            order.item_id,
            config.target_stock,
            relist_result.status,
            relist_result.failed_reason,
        )

    async def _load_order_detail_for_delivery(self, order_id: str) -> OrderDetail:
        provider = getattr(self, "order_detail_provider", None)
        if not provider:
            return OrderDetail()
        detail = provider(order_id)
        if inspect.isawaitable(detail):
            detail = await detail
        if isinstance(detail, OrderDetail):
            return detail
        if isinstance(detail, dict):
            return self.xianyu.parse_order_detail_response(detail)
        return OrderDetail()

    def _delivery_buyer_name(self, sender_name: str) -> str:
        system_names = {"", "系统通知", "闲鱼系统", "买家已付款", "等待你发货"}
        return "" if sender_name in system_names else sender_name

    async def mark_message_read(self, websocket, chat_id: str, message_id: str | None):
        """Clear the conversation red point and mark the incoming message as read."""
        if not message_id:
            logger.debug(f"会话 {chat_id} 缺少 messageId，跳过已读同步")
            return

        cid = chat_id if chat_id.endswith("@goofish") else f"{chat_id}@goofish"
        clear_red_point = {
            "lwp": "/r/Conversation/clearRedPoint",
            "headers": {"mid": generate_mid()},
            "body": [[{"cid": cid, "messageId": message_id}]],
        }
        mark_read = {
            "lwp": "/r/MessageStatus/read",
            "headers": {"mid": generate_mid()},
            "body": [[message_id]],
        }
        try:
            await websocket.send(json.dumps(clear_red_point))
            await websocket.send(json.dumps(mark_read))
            logger.info(f"已同步会话已读状态: {chat_id}")
        except Exception as e:
            logger.warning(f"同步会话已读状态失败: {chat_id}, {e}")

    async def send_heartbeat(self, ws):
        """发送心跳包并等待响应"""
        try:
            heartbeat_mid = generate_mid()
            heartbeat_msg = {
                "lwp": "/!",
                "headers": {
                    "mid": heartbeat_mid
                }
            }
            await ws.send(json.dumps(heartbeat_msg))
            self.last_heartbeat_time = time.time()
            logger.debug("心跳包已发送")
            return heartbeat_mid
        except Exception as e:
            logger.error(f"发送心跳包失败: {e}")
            raise

    async def heartbeat_loop(self, ws):
        """心跳维护循环"""
        while True:
            try:
                current_time = time.time()
                
                # 检查是否需要发送心跳
                if current_time - self.last_heartbeat_time >= self.heartbeat_interval:
                    await self.send_heartbeat(ws)
                
                # 检查上次心跳响应时间，如果超时则认为连接已断开
                if (current_time - self.last_heartbeat_response) > (self.heartbeat_interval + self.heartbeat_timeout):
                    logger.warning("心跳响应超时，可能连接已断开")
                    break
                
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"心跳循环出错: {e}")
                break

    async def handle_heartbeat_response(self, message_data):
        """处理心跳响应"""
        try:
            if (
                isinstance(message_data, dict)
                and "headers" in message_data
                and "mid" in message_data["headers"]
                and "code" in message_data
                and message_data["code"] == 200
            ):
                self.last_heartbeat_response = time.time()
                logger.debug("收到心跳响应")
                return True
        except Exception as e:
            logger.error(f"处理心跳响应出错: {e}")
        return False

    async def main(self):
        while True:
            try:
                # 重置连接重启标志
                self.connection_restart_flag = False
                
                headers = {
                    "Cookie": self.cookies_str,
                    "Host": "wss-goofish.dingtalk.com",
                    "Connection": "Upgrade",
                    "Pragma": "no-cache",
                    "Cache-Control": "no-cache",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                    "Origin": "https://www.goofish.com",
                    "Accept-Encoding": "gzip, deflate, br, zstd",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                }

                async with websockets.connect(self.base_url, extra_headers=headers) as websocket:
                    self.ws = websocket
                    await self.init(websocket)
                    
                    # 初始化心跳时间
                    self.last_heartbeat_time = time.time()
                    self.last_heartbeat_response = time.time()
                    
                    # 启动心跳任务
                    self.heartbeat_task = asyncio.create_task(self.heartbeat_loop(websocket))
                    
                    # 启动token刷新任务
                    self.token_refresh_task = asyncio.create_task(self.token_refresh_loop())

                    if self.cookie_refresh_enabled:
                        self.cookie_refresh_task = asyncio.create_task(self.cookie_refresh_loop())
                    
                    async for message in websocket:
                        try:
                            # 检查是否需要重启连接
                            if self.connection_restart_flag:
                                logger.info("检测到连接重启标志，准备重新建立连接...")
                                break
                                
                            message_data = json.loads(message)
                            
                            # 处理心跳响应
                            if await self.handle_heartbeat_response(message_data):
                                continue
                            
                            # 发送通用ACK响应
                            if "headers" in message_data and "mid" in message_data["headers"]:
                                ack = {
                                    "code": 200,
                                    "headers": {
                                        "mid": message_data["headers"]["mid"],
                                        "sid": message_data["headers"].get("sid", "")
                                    }
                                }
                                # 复制其他可能的header字段
                                for key in ["app-key", "ua", "dt"]:
                                    if key in message_data["headers"]:
                                        ack["headers"][key] = message_data["headers"][key]
                                await websocket.send(json.dumps(ack))
                            
                            # 处理其他消息
                            await self.handle_message(message_data, websocket)
                                
                        except json.JSONDecodeError:
                            logger.error("消息解析失败")
                        except Exception:
                            logger.exception("处理消息时发生错误")

            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket连接已关闭")
                
            except Exception as e:
                logger.error(f"连接发生错误: {e}")
                
            finally:
                # 清理任务
                if self.heartbeat_task:
                    self.heartbeat_task.cancel()
                    try:
                        await self.heartbeat_task
                    except asyncio.CancelledError:
                        pass
                        
                if self.token_refresh_task:
                    self.token_refresh_task.cancel()
                    try:
                        await self.token_refresh_task
                    except asyncio.CancelledError:
                        pass

                if self.cookie_refresh_task:
                    self.cookie_refresh_task.cancel()
                    try:
                        await self.cookie_refresh_task
                    except asyncio.CancelledError:
                        pass
                
                # 如果是主动重启，立即重连；否则等待5秒
                if self.connection_restart_flag:
                    logger.info("主动重启连接，立即重连...")
                else:
                    logger.info("等待5秒后重连...")
                    await asyncio.sleep(5)



def check_and_complete_env():
    """检查并补全关键环境变量"""
    # 定义关键变量及其默认无效值（占位符）
    critical_vars = {
        "API_KEY": "默认使用 ModelScope OpenAI 兼容接口，请填写 ModelScope Token",
        "COOKIES_STR": "your_cookies_here"
    }
    
    env_path = ".env"
    updated = False
    
    for key, placeholder in critical_vars.items():
        curr_val = os.getenv(key)
        
        # 如果变量未设置，或者值等于占位符
        if not curr_val or curr_val == placeholder:
            logger.warning(f"配置项 [{key}] 未设置或为默认值，请输入")
            while True:
                prompt = f"请输入 {key}: "
                if key == "COOKIES_STR":
                    prompt = "请输入 COOKIES_STR，或直接回车使用扫码登录: "
                val = input(prompt).strip()
                if key == "COOKIES_STR" and not val:
                    try:
                        val = run_qr_login_cli()
                    except QRLoginError as e:
                        logger.error(f"扫码登录失败: {e}")
                        continue
                if val:
                    # 更新当前环境
                    os.environ[key] = val
                    
                    # 尝试持久化到 .env
                    try:
                        # 如果没有.env文件，先创建
                        if not os.path.exists(env_path):
                            with open(env_path, 'w', encoding='utf-8') as f:
                                pass # Create empty file
                        
                        set_key(env_path, key, val)
                        updated = True
                    except Exception as e:
                        logger.warning(f"无法自动写入.env文件，请手动保存: {e}")
                    break
                else:
                    print(f"{key} 不能为空，请重新输入")
    
    if updated:
        logger.info("新的配置已保存/更新至 .env 文件中")


def run_qr_login_command():
    """独立执行扫码登录并保存COOKIES_STR。"""
    cookies_str = run_qr_login_cli()
    os.environ["COOKIES_STR"] = cookies_str
    env_path = ".env"
    if not os.path.exists(env_path):
        with open(env_path, 'w', encoding='utf-8') as f:
            pass
    set_key(env_path, "COOKIES_STR", cookies_str)
    logger.info("扫码登录 Cookie 已保存至 .env")


def _build_xianyu_api_from_env():
    cookies_str = os.getenv("COOKIES_STR", "")
    if not cookies_str:
        return None
    api = XianyuApis()
    api.session.cookies.update(trans_cookies(cookies_str))
    return api


def _build_playwright_relist_executor(*, cookies_str: str, allow_playwright: bool, target_stock: int | None = None):
    if not allow_playwright or not cookies_str:
        return None
    screenshot_dir = os.getenv("AUTO_RELIST_SCREENSHOT_DIR", "data/relist-screenshots")
    headless = os.getenv("AUTO_RELIST_PLAYWRIGHT_HEADLESS", os.getenv("PLAYWRIGHT_HEADLESS", "true")).lower() != "false"
    management_url = os.getenv("AUTO_RELIST_MANAGEMENT_URL", "").strip()
    return PlaywrightRelistExecutor(
        cookies_str=cookies_str,
        headless=headless,
        screenshot_dir=screenshot_dir,
        management_url=management_url or default_relist_management_url(target_stock),
    )


def _build_playwright_publish_executor(*, cookies_str: str, allow_playwright: bool):
    if not allow_playwright or not cookies_str:
        return None
    screenshot_dir = os.getenv("AUTO_PUBLISH_SCREENSHOT_DIR", "data/publish-screenshots")
    headless = os.getenv("AUTO_PUBLISH_PLAYWRIGHT_HEADLESS", os.getenv("PLAYWRIGHT_HEADLESS", "true")).lower() != "false"
    publish_url = os.getenv("AUTO_PUBLISH_URL", "").strip()
    kwargs = {}
    if publish_url:
        kwargs["publish_url"] = publish_url
    return PlaywrightPublishExecutor(
        cookies_str=cookies_str,
        headless=headless,
        screenshot_dir=screenshot_dir,
        **kwargs,
    )


def _public_item_status_payload(item: dict) -> dict:
    keys = (
        "item_id",
        "itemId",
        "id",
        "title",
        "status",
        "status_source",
        "platform_status",
        "platform_status_text",
        "can_relist",
        "detail_url",
        "detailUrl",
        "item_url",
        "itemUrl",
    )
    payload = {key: item[key] for key in keys if key in item}
    item_id = payload.get("item_id") or payload.get("itemId") or payload.get("id")
    if item_id:
        payload["item_id"] = str(item_id)
        payload.pop("itemId", None)
        payload.pop("id", None)
    item_url = payload.get("item_url") or payload.get("itemUrl") or payload.get("detail_url") or payload.get("detailUrl")
    if item_url:
        payload["item_url"] = str(item_url)
    payload.pop("itemUrl", None)
    payload.pop("detailUrl", None)
    payload.pop("detail_url", None)
    return payload


def build_cli_parser():
    parser = argparse.ArgumentParser(prog="python main.py")
    subparsers = parser.add_subparsers(dest="command")

    web_parser = subparsers.add_parser("web", help="启动本地管理页面")
    web_parser.add_argument("--host", default=os.getenv("WEB_HOST", "127.0.0.1"))
    web_parser.add_argument("--port", type=int, default=int(os.getenv("WEB_PORT", "8765")))
    web_parser.add_argument("--db-path", default=os.getenv("DB_PATH", "data/chat_history.db"))

    delivery_parser = subparsers.add_parser("delivery", help="管理本地自动发货配置")
    delivery_parser.add_argument("--db-path", default=os.getenv("DB_PATH", "data/chat_history.db"))
    delivery_subparsers = delivery_parser.add_subparsers(dest="delivery_command", required=True)

    add_parser = delivery_subparsers.add_parser("add", help="新增发货配置")
    add_parser.add_argument("--item-id", required=True)
    add_parser.add_argument("--type", required=True, choices=["text", "data", "api"], dest="delivery_type")
    add_parser.add_argument("--content", default="")
    add_parser.add_argument("--name", default="")
    add_parser.add_argument("--disabled", action="store_true")

    list_parser = delivery_subparsers.add_parser("list", help="列出发货配置")
    list_parser.add_argument("--item-id")

    inventory_parser = delivery_subparsers.add_parser("inventory", help="管理一次性发货库存")
    inventory_subparsers = inventory_parser.add_subparsers(dest="inventory_command", required=True)

    inventory_add_parser = inventory_subparsers.add_parser("add", help="新增一次性库存内容")
    inventory_add_parser.add_argument("--config-id", type=int, required=True)
    inventory_add_parser.add_argument("--content", action="append", default=[])
    inventory_add_parser.add_argument("--content-file")

    inventory_list_parser = inventory_subparsers.add_parser("list", help="列出一次性库存状态")
    inventory_list_parser.add_argument("--config-id", type=int, required=True)
    inventory_list_parser.add_argument("--status")
    inventory_list_parser.add_argument("--show-content", action="store_true")

    listing_parser = subparsers.add_parser("listing", help="管理已有商品重新上架任务")
    listing_parser.add_argument("--db-path", default=os.getenv("DB_PATH", "data/chat_history.db"))
    listing_subparsers = listing_parser.add_subparsers(dest="listing_command", required=True)

    relist_parser = listing_subparsers.add_parser("relist", help="对已发布过的商品创建重新上架任务")
    relist_parser.add_argument("config_path", nargs="?")
    relist_parser.add_argument("--item-id")
    relist_parser.add_argument("--expected-title", default="")
    relist_parser.add_argument("--delivery-type", choices=["text", "data", "api"])
    relist_parser.add_argument("--delivery-content", default="")
    relist_parser.add_argument("--delivery-name", default="")
    relist_parser.add_argument("--stock", type=int, dest="target_stock")
    relist_parser.add_argument("--allow-playwright", action="store_true")
    relist_parser.add_argument("--confirm-real-relist", action="store_true")

    publish_parser = listing_subparsers.add_parser("publish", help="通过卖家发布页发布新商品")
    publish_parser.add_argument("config_path", nargs="?")
    publish_parser.add_argument("--title")
    publish_parser.add_argument("--description", default="")
    publish_parser.add_argument("--description-file")
    publish_parser.add_argument("--price")
    publish_parser.add_argument("--stock", type=int, default=1)
    publish_parser.add_argument("--image", action="append", default=[])
    publish_parser.add_argument("--confirm-real-publish", action="store_true")

    content_version_parser = listing_subparsers.add_parser("content-version", help="管理本地商品信息版本")
    content_version_subparsers = content_version_parser.add_subparsers(dest="content_version_command", required=True)

    content_version_add_parser = content_version_subparsers.add_parser("add", help="保存商品信息版本到本地 SQLite")
    content_version_add_parser.add_argument("--item-id", required=True)
    content_version_add_parser.add_argument("--label", default="", dest="version_label")
    content_version_add_parser.add_argument("--title", default="")
    content_version_add_parser.add_argument("--description", default="")
    content_version_add_parser.add_argument("--description-file")
    content_version_add_parser.add_argument("--price", default="")
    content_version_add_parser.add_argument("--stock", type=int)
    content_version_add_parser.add_argument("--notes", default="")
    content_version_add_parser.add_argument("--source", default="manual")

    content_version_list_parser = content_version_subparsers.add_parser("list", help="列出本地商品信息版本")
    content_version_list_parser.add_argument("--item-id")
    content_version_list_parser.add_argument("--limit", type=int, default=20)

    preflight_parser = listing_subparsers.add_parser("relist-preflight", help="只读预检授权浏览器是否能定位重新上架入口")
    preflight_parser.add_argument("--item-id", required=True)
    preflight_parser.add_argument("--expected-title", default="")
    preflight_parser.add_argument("--stock", type=int, dest="target_stock")
    preflight_parser.add_argument("--page-size", type=int, default=20)
    preflight_parser.add_argument("--max-pages", type=int)
    preflight_parser.add_argument("--myid")

    auto_relist_parser = listing_subparsers.add_parser("auto-relist", help="管理发货成功后的自动重新上架配置")
    auto_relist_subparsers = auto_relist_parser.add_subparsers(dest="auto_relist_command", required=True)

    auto_relist_set_parser = auto_relist_subparsers.add_parser("set", help="设置商品发货后自动重新上架")
    auto_relist_set_parser.add_argument("--item-id", required=True)
    auto_relist_set_parser.add_argument("--stock", type=int, required=True, dest="target_stock")
    auto_relist_set_parser.add_argument("--expected-title", default="")
    auto_relist_set_parser.add_argument("--disabled", action="store_true")
    auto_relist_set_parser.add_argument("--allow-playwright", action="store_true")

    auto_relist_list_parser = auto_relist_subparsers.add_parser("list", help="列出发货后自动重新上架配置")
    auto_relist_list_parser.add_argument("--item-id")

    status_parser = listing_subparsers.add_parser("status", help="列出最近的重新上架任务")
    status_parser.add_argument("--limit", type=int, default=20)

    fetch_items_parser = listing_subparsers.add_parser("fetch-items", help="从闲鱼获取当前账号所有已发布商品")
    fetch_items_parser.add_argument("--page-size", type=int, default=20)
    fetch_items_parser.add_argument("--max-pages", type=int)
    fetch_items_parser.add_argument("--myid")

    item_status_parser = listing_subparsers.add_parser("item-status", help="刷新并查看单个商品的真实平台状态")
    item_status_parser.add_argument("--item-id", required=True)
    item_status_parser.add_argument("--page-size", type=int, default=20)
    item_status_parser.add_argument("--max-pages", type=int)
    item_status_parser.add_argument("--myid")

    return parser


def run_cli(argv=None):
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    if args.command == "web":
        run_web_server(host=args.host, port=args.port, db_path=args.db_path)
        return 0

    if args.command == "delivery":
        store = DeliveryStore(db_path=args.db_path)
        if args.delivery_command == "add":
            config_id = store.add_config(
                item_id=args.item_id,
                name=args.name or args.item_id,
                delivery_type=args.delivery_type,
                content=args.content,
                enabled=not args.disabled,
            )
            print(json.dumps({"id": config_id, "item_id": args.item_id}, ensure_ascii=False))
            return 0
        if args.delivery_command == "list":
            configs = store.list_configs(item_id=args.item_id)
            payload = [
                {
                    "id": config.id,
                    "item_id": config.item_id,
                    "name": config.name,
                    "type": config.delivery_type,
                    "enabled": config.enabled,
                }
                for config in configs
            ]
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.delivery_command == "inventory":
            if args.inventory_command == "add":
                contents = list(args.content or [])
                if args.content_file:
                    lines = Path(args.content_file).read_text(encoding="utf-8").splitlines()
                    contents.extend(line.strip() for line in lines if line.strip())
                if not contents:
                    parser.error("delivery inventory add requires --content or --content-file")
                row_ids = store.add_inventory(args.config_id, contents)
                print(json.dumps({"config_id": args.config_id, "added": len(row_ids)}, ensure_ascii=False))
                return 0

            if args.inventory_command == "list":
                rows = store.list_inventory(args.config_id, status=args.status)
                payload = []
                for row in rows:
                    item = {
                        "id": row.id,
                        "config_id": row.config_id,
                        "status": row.status,
                        "reserved_order_no": row.reserved_order_no,
                        "reservation_line_no": row.reservation_line_no,
                        "sent_at": row.sent_at,
                        "failed_reason": row.failed_reason,
                    }
                    if args.show_content:
                        item["content"] = row.content
                    payload.append(item)
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return 0

    if args.command == "listing":
        listing_store = ListingStore(db_path=args.db_path)
        delivery_store = DeliveryStore(db_path=args.db_path)
        if args.listing_command == "relist":
            if args.config_path:
                request = load_relist_request(args.config_path)
            else:
                if not args.item_id:
                    parser.error("listing relist requires --item-id or a config path")
                payload = {
                    "item_id": args.item_id,
                    "expected_title": args.expected_title,
                }
                if args.target_stock is not None:
                    payload["target_stock"] = args.target_stock
                if args.delivery_type:
                    payload["delivery"] = {
                        "type": args.delivery_type,
                        "content": args.delivery_content,
                        "name": args.delivery_name or args.item_id,
                    }
                request = load_relist_request(payload)

            api_client = _build_xianyu_api_from_env()
            confirm_real_relist = bool(getattr(args, "confirm_real_relist", False))
            relist_executor = _build_playwright_relist_executor(
                cookies_str=os.getenv("COOKIES_STR", ""),
                allow_playwright=args.allow_playwright and confirm_real_relist,
                target_stock=request.target_stock,
            )
            playwright_required_reason = (
                "real_relist_confirmation_required"
                if args.allow_playwright and not confirm_real_relist
                else ""
            )
            service = RelistService(
                listing_store=listing_store,
                delivery_store=delivery_store,
                api_client=api_client,
                allow_playwright=args.allow_playwright,
                relist_executor=relist_executor,
                playwright_required_reason=playwright_required_reason,
            )
            result = asyncio.run(service.relist(request))
            print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
            return 0

        if args.listing_command == "publish":
            if args.config_path:
                data = json.loads(Path(args.config_path).read_text(encoding="utf-8"))
                title = str(data.get("title") or "")
                description = str(data.get("description") or "")
                price = str(data.get("price") or "")
                stock = int(data.get("stock") or 1)
                images = tuple(str(image) for image in data.get("images", []) if str(image).strip())
            else:
                if not args.title:
                    parser.error("listing publish requires --title or a config path")
                description = args.description
                if args.description_file:
                    description = Path(args.description_file).read_text(encoding="utf-8")
                title = args.title
                price = args.price or ""
                stock = args.stock
                images = tuple(args.image or [])
            if stock < 1:
                parser.error("listing publish --stock must be greater than 0")

            request = PublishRequest(
                title=title,
                description=description,
                price=price,
                stock=stock,
                images=images,
            )
            executor = _build_playwright_publish_executor(
                cookies_str=os.getenv("COOKIES_STR", ""),
                allow_playwright=bool(getattr(args, "confirm_real_publish", False)),
            )
            if not executor:
                print(
                    json.dumps(
                        {
                            "success": False,
                            "failed_reason": "real_publish_confirmation_required",
                            "message": "listing publish requires --confirm-real-publish and COOKIES_STR",
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 1
            result = asyncio.run(executor.publish(request))
            if result.success and result.item_id:
                listing_store.save_item_snapshot(
                    {
                        "item_id": result.item_id,
                        "itemId": result.item_id,
                        "id": result.item_id,
                        "title": request.title,
                        "status": "active",
                        "item_url": result.item_url,
                        "itemUrl": result.item_url,
                        "status_source": "publish_result",
                        "stock": request.stock,
                    }
                )
            print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
            return 0 if result.success else 1

        if args.listing_command == "content-version":
            if args.content_version_command == "add":
                if args.stock is not None and args.stock < 1:
                    parser.error("listing content-version add --stock must be greater than 0")
                description = args.description
                if args.description_file:
                    description = Path(args.description_file).read_text(encoding="utf-8")
                try:
                    version_id = listing_store.record_content_version(
                        item_id=args.item_id,
                        title=args.title,
                        description=description,
                        price=args.price,
                        stock=args.stock,
                        version_label=args.version_label,
                        notes=args.notes,
                        source=args.source,
                    )
                except ValueError as exc:
                    parser.error(str(exc))
                print(json.dumps({"version_id": version_id, "item_id": args.item_id}, ensure_ascii=False, indent=2))
                return 0

            if args.content_version_command == "list":
                if args.limit < 1:
                    parser.error("listing content-version list --limit must be greater than 0")
                versions = listing_store.list_content_versions(item_id=args.item_id, limit=args.limit)
                payload = [version.__dict__ for version in versions]
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return 0

        if args.listing_command == "auto-relist":
            if args.auto_relist_command == "set":
                if args.target_stock < 1:
                    parser.error("listing auto-relist set --stock must be greater than 0")
                config_id = listing_store.upsert_auto_relist_config(
                    item_id=args.item_id,
                    target_stock=args.target_stock,
                    expected_title=args.expected_title,
                    enabled=not args.disabled,
                    allow_playwright=args.allow_playwright,
                )
                config = listing_store.list_auto_relist_configs(item_id=args.item_id)[0]
                payload = {
                    "id": config_id,
                    "item_id": config.item_id,
                    "target_stock": config.target_stock,
                    "expected_title": config.expected_title,
                    "enabled": config.enabled,
                    "allow_playwright": config.allow_playwright,
                }
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return 0

            if args.auto_relist_command == "list":
                configs = listing_store.list_auto_relist_configs(item_id=args.item_id)
                payload = [
                    {
                        "id": config.id,
                        "item_id": config.item_id,
                        "target_stock": config.target_stock,
                        "expected_title": config.expected_title,
                        "enabled": config.enabled,
                        "allow_playwright": config.allow_playwright,
                    }
                    for config in configs
                ]
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return 0

        if args.listing_command == "relist-preflight":
            if args.page_size < 1 or args.page_size > 100:
                parser.error("listing relist-preflight --page-size must be between 1 and 100")
            if args.max_pages is not None and args.max_pages < 1:
                parser.error("listing relist-preflight --max-pages must be greater than 0")
            if args.target_stock is not None and args.target_stock < 1:
                parser.error("listing relist-preflight --stock must be greater than 0")

            cookies_str = os.getenv("COOKIES_STR", "")
            if not cookies_str:
                print(json.dumps({"success": False, "message": "COOKIES_STR is required"}, ensure_ascii=False))
                return 1

            api = _build_xianyu_api_from_env()
            status_result = api.get_item_status(
                args.item_id,
                page_size=args.page_size,
                max_pages=args.max_pages,
                myid=args.myid,
            )
            if not status_result.get("success"):
                print(json.dumps(status_result, ensure_ascii=False, indent=2))
                return 1
            item = status_result.get("item") if isinstance(status_result.get("item"), dict) else {}
            if item:
                listing_store.save_item_snapshot(item)

            executor = _build_playwright_relist_executor(
                cookies_str=cookies_str,
                allow_playwright=True,
                target_stock=args.target_stock,
            )
            request = load_relist_request(
                {
                    "item_id": args.item_id,
                    "expected_title": args.expected_title,
                    "target_stock": args.target_stock,
                }
            )
            preview = asyncio.run(executor.preview(request))
            payload = {
                "success": bool(preview.get("success")),
                "item": _public_item_status_payload(item),
                "playwright": preview,
                "snapshot_saved": bool(item),
                "message": "preview only; no relist click executed",
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["success"] else 1

        if args.listing_command == "status":
            jobs = listing_store.list_jobs(limit=args.limit)
            payload = [job.__dict__ for job in jobs]
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        if args.listing_command == "item-status":
            if args.page_size < 1 or args.page_size > 100:
                parser.error("listing item-status --page-size must be between 1 and 100")
            if args.max_pages is not None and args.max_pages < 1:
                parser.error("listing item-status --max-pages must be greater than 0")

            api = _build_xianyu_api_from_env()
            if not api:
                print(json.dumps({"success": False, "message": "COOKIES_STR is required"}, ensure_ascii=False))
                return 1

            result = api.get_item_status(
                args.item_id,
                page_size=args.page_size,
                max_pages=args.max_pages,
                myid=args.myid,
            )
            if result.get("success") and isinstance(result.get("item"), dict):
                listing_store.save_item_snapshot(result["item"])
                result = {
                    **result,
                    "item": _public_item_status_payload(result["item"]),
                    "snapshot_saved": True,
                }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("success") else 1

        if args.listing_command == "fetch-items":
            if args.page_size < 1 or args.page_size > 100:
                parser.error("listing fetch-items --page-size must be between 1 and 100")
            if args.max_pages is not None and args.max_pages < 1:
                parser.error("listing fetch-items --max-pages must be greater than 0")

            cookies_str = os.getenv("COOKIES_STR", "")
            if not cookies_str:
                print(json.dumps({"success": False, "message": "COOKIES_STR is required"}, ensure_ascii=False))
                return 1

            api = XianyuApis()
            api.session.cookies.update(trans_cookies(cookies_str))
            result = sync_published_items(
                api=api,
                listing_store=listing_store,
                page_size=args.page_size,
                max_pages=args.max_pages,
                myid=args.myid,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("success") else 1

    parser.print_help()
    return 0


if __name__ == '__main__':
    # 加载环境变量
    if os.path.exists(".env"):
        load_dotenv()
        logger.info("已加载 .env 配置")
    
    if os.path.exists(".env.example"):
        load_dotenv(".env.example")  # 不会覆盖已存在的变量
        logger.info("已加载 .env.example 默认配置")
    
    # 配置日志级别
    log_level = os.getenv("LOG_LEVEL", "DEBUG").upper()
    logger.remove()  # 移除默认handler
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    logger.info(f"日志级别设置为: {log_level}")

    if "--qr-login" in sys.argv:
        try:
            run_qr_login_command()
            sys.exit(0)
        except QRLoginError as e:
            logger.error(f"扫码登录失败: {e}")
            sys.exit(1)

    if len(sys.argv) > 1 and sys.argv[1] in {"delivery", "listing", "web", "--help", "-h"}:
        sys.exit(run_cli(sys.argv[1:]))
    
    # 交互式检查并补全配置
    check_and_complete_env()
    
    cookies_str = os.getenv("COOKIES_STR")
    bot = XianyuReplyBot()
    xianyuLive = XianyuLive(cookies_str, reply_bot=bot)
    # 常驻进程
    asyncio.run(xianyuLive.main())
