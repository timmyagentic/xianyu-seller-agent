import time
import os
import re
import sys
import json
from http.cookies import SimpleCookie

import requests
from loguru import logger
from utils.xianyu_utils import generate_sign
from services.delivery.orders import is_session_expired_ret, is_token_expired_ret, parse_order_detail_response
from services.listing.relist import map_relist_failure_reason, parse_relist_api_response


class XianyuApis:
    parse_order_detail_response = staticmethod(parse_order_detail_response)
    is_token_expired_ret = staticmethod(is_token_expired_ret)
    is_session_expired_ret = staticmethod(is_session_expired_ret)
    parse_relist_api_response = staticmethod(parse_relist_api_response)
    map_relist_failure_reason = staticmethod(map_relist_failure_reason)

    def __init__(self):
        self.url = 'https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.pc.login.token/1.0/'
        self.session = requests.Session()
        self.session.headers.update({
            'accept': 'application/json',
            'accept-language': 'zh-CN,zh;q=0.9',
            'cache-control': 'no-cache',
            'origin': 'https://www.goofish.com',
            'pragma': 'no-cache',
            'priority': 'u=1, i',
            'referer': 'https://www.goofish.com/',
            'sec-ch-ua': '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
        })
        
    def clear_duplicate_cookies(self):
        """清理重复的cookies"""
        self._replace_session_cookies(self._cookie_dict())
        self.update_env_cookies()

    def _cookie_dict(self) -> dict[str, str]:
        cookies: dict[str, str] = {}
        for cookie in list(self.session.cookies):
            if cookie.name and cookie.value is not None:
                cookies[cookie.name] = cookie.value
        return cookies

    def _cookie_value(self, name: str) -> str:
        return self._cookie_dict().get(name, "")

    def get_cookie_string(self) -> str:
        return '; '.join([f"{name}={value}" for name, value in self._cookie_dict().items()])

    def _replace_session_cookies(self, cookies: dict[str, str]) -> None:
        new_jar = requests.cookies.RequestsCookieJar()
        for name, value in cookies.items():
            new_jar.set(name, value)
        self.session.cookies = new_jar

    def _merge_response_cookies(self, response) -> list[str]:
        new_cookies: dict[str, str] = {}
        for cookie in getattr(response, "cookies", []) or []:
            if getattr(cookie, "name", None) and getattr(cookie, "value", None) is not None:
                new_cookies[cookie.name] = cookie.value

        header_values: list[str] = []
        headers = getattr(response, "headers", {}) or {}
        raw_headers = getattr(getattr(response, "raw", None), "headers", None)
        if hasattr(raw_headers, "get_all"):
            header_values.extend(raw_headers.get_all("Set-Cookie") or [])
            header_values.extend(raw_headers.get_all("set-cookie") or [])
        if hasattr(headers, "get"):
            for header_name in ("Set-Cookie", "set-cookie"):
                header_value = headers.get(header_name)
                if header_value:
                    header_values.append(header_value)

        for header_value in header_values:
            parsed = SimpleCookie()
            try:
                parsed.load(header_value)
            except Exception:
                continue
            for name, morsel in parsed.items():
                if name and morsel.value is not None:
                    new_cookies[name] = morsel.value

        if not new_cookies:
            return []

        merged = self._cookie_dict()
        merged.update(new_cookies)
        self._replace_session_cookies(merged)
        self.update_env_cookies()
        return list(new_cookies)
        
    def update_env_cookies(self):
        """更新.env文件中的COOKIES_STR"""
        try:
            cookie_str = self.get_cookie_string()
            
            # 读取.env文件
            env_path = os.path.join(os.getcwd(), '.env')
            if not os.path.exists(env_path):
                logger.warning(".env文件不存在，无法更新COOKIES_STR")
                return
                
            with open(env_path, 'r', encoding='utf-8') as f:
                env_content = f.read()
                
            # 使用正则表达式替换COOKIES_STR的值
            if 'COOKIES_STR=' in env_content:
                new_env_content = re.sub(
                    r'COOKIES_STR=.*', 
                    f'COOKIES_STR={cookie_str}',
                    env_content
                )
                
                # 写回.env文件
                with open(env_path, 'w', encoding='utf-8') as f:
                    f.write(new_env_content)
                    
                logger.debug("已更新.env文件中的COOKIES_STR")
            else:
                logger.warning(".env文件中未找到COOKIES_STR配置项")
        except Exception as e:
            logger.warning(f"更新.env文件失败: {str(e)}")

    def renew_login_cookies(self) -> dict:
        """Use the login-user mtop API to proactively refresh mtop cookies."""
        data_val = '{}'
        token = self._cookie_value('_m_h5_tk').split('_')[0]
        if not token:
            logger.warning("Cookie缺少_m_h5_tk，无法执行登录态续期")
            return {
                "status": "token_empty",
                "message": "令牌为空，需要重新登录",
                "updated_cookie_names": [],
            }

        timestamp = str(int(time.time() * 1000))
        params = {
            'jsv': '2.7.2',
            'appKey': '34839810',
            't': timestamp,
            'sign': generate_sign(timestamp, token, data_val),
            'v': '1.0',
            'type': 'originaljson',
            'accountSite': 'xianyu',
            'dataType': 'json',
            'timeout': '20000',
            'api': 'mtop.taobao.idlemessage.pc.loginuser.get',
            'sessionOption': 'AutoLoginOnly',
            'spm_cnt': 'a21ybx.im.0.0',
        }
        headers = {
            'accept': 'application/json',
            'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'cache-control': 'no-cache',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://www.goofish.com',
            'pragma': 'no-cache',
            'referer': 'https://www.goofish.com/',
            'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
            'cookie': self.get_cookie_string().replace('\n', '').replace('\r', ''),
        }

        try:
            response = self.session.post(
                'https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.pc.loginuser.get/1.0/',
                params=params,
                data={'data': data_val},
                headers=headers,
            )
            res_json = response.json()
            updated_cookies = self._merge_response_cookies(response)
            ret = res_json.get('ret', []) if isinstance(res_json, dict) else []

            if any('SUCCESS' in item for item in ret):
                status = "cookie_updated" if updated_cookies else "success"
                message = "登录状态正常，Cookie已更新" if updated_cookies else "登录状态正常"
                logger.info(message)
                return {
                    "status": status,
                    "message": message,
                    "updated_cookie_names": updated_cookies,
                }

            if is_token_expired_ret(ret):
                if updated_cookies:
                    logger.info(f"令牌已通过Set-Cookie刷新 {len(updated_cookies)} 个Cookie字段")
                    return {
                        "status": "token_refreshed",
                        "message": "令牌已刷新",
                        "updated_cookie_names": updated_cookies,
                    }
                logger.warning("令牌过期但未获取到新Cookie")
                return {
                    "status": "failed",
                    "message": "令牌过期但未获取到新Cookie",
                    "updated_cookie_names": [],
                }

            if is_session_expired_ret(ret):
                logger.warning("Session过期，需要人工重新登录")
                return {
                    "status": "session_expired",
                    "message": "Session过期，需要重新登录",
                    "updated_cookie_names": updated_cookies,
                }

            ret_str = str(ret)
            if "TOKEN_EMPTY" in ret_str or "令牌为空" in ret_str:
                logger.warning("Cookie令牌为空，需要人工重新登录")
                return {
                    "status": "token_empty",
                    "message": "令牌为空，需要重新登录",
                    "updated_cookie_names": updated_cookies,
                }

            return {
                "status": "failed",
                "message": ret[0] if ret else "登录态续期失败",
                "updated_cookie_names": updated_cookies,
            }
        except Exception as e:
            logger.warning(f"登录态续期请求异常: {e}")
            return {
                "status": "failed",
                "message": f"请求异常: {e}",
                "updated_cookie_names": [],
            }
        
    def hasLogin(self, retry_count=0):
        """调用hasLogin.do接口进行登录状态检查"""
        if retry_count >= 2:
            logger.error("Login检查失败，重试次数过多")
            return False
            
        try:
            url = 'https://passport.goofish.com/newlogin/hasLogin.do'
            params = {
                'appName': 'xianyu',
                'fromSite': '77'
            }
            data = {
                'hid': self._cookie_value('unb'),
                'ltl': 'true',
                'appName': 'xianyu',
                'appEntrance': 'web',
                '_csrf_token': self._cookie_value('XSRF-TOKEN'),
                'umidToken': '',
                'hsiz': self._cookie_value('cookie2'),
                'bizParams': 'taobaoBizLoginFrom=web',
                'mainPage': 'false',
                'isMobile': 'false',
                'lang': 'zh_CN',
                'returnUrl': '',
                'fromSite': '77',
                'isIframe': 'true',
                'documentReferer': 'https://www.goofish.com/',
                'defaultView': 'hasLogin',
                'umidTag': 'SERVER',
                'deviceId': self._cookie_value('cna')
            }
            
            response = self.session.post(url, params=params, data=data)
            res_json = response.json()
            self._merge_response_cookies(response)
            
            if res_json.get('content', {}).get('success'):
                logger.debug("Login成功")
                # 清理和更新cookies
                self.clear_duplicate_cookies()
                return True
            else:
                logger.warning(f"Login失败: {res_json}")
                time.sleep(0.5)
                return self.hasLogin(retry_count + 1)
                
        except Exception as e:
            logger.error(f"Login请求异常: {str(e)}")
            time.sleep(0.5)
            return self.hasLogin(retry_count + 1)

    def get_token(self, device_id, retry_count=0):
        if retry_count >= 2:  # 最多重试3次
            logger.warning("获取token失败，尝试重新登陆")
            # 尝试通过hasLogin重新登录
            if self.hasLogin():
                logger.info("重新登录成功，重新尝试获取token")
                return self.get_token(device_id, 0)  # 重置重试次数
            else:
                logger.error("重新登录失败，Cookie已失效")
                logger.error("🔴 程序即将退出，请更新.env文件中的COOKIES_STR后重新启动")
                sys.exit(1)  # 直接退出程序

        params = {
            'jsv': '2.7.2',
            'appKey': '34839810',
            't': str(int(time.time()) * 1000),
            'sign': '',
            'v': '1.0',
            'type': 'originaljson',
            'accountSite': 'xianyu',
            'dataType': 'json',
            'timeout': '20000',
            'api': 'mtop.taobao.idlemessage.pc.login.token',
            'sessionOption': 'AutoLoginOnly',
            'spm_cnt': 'a21ybx.im.0.0',
            "spm_pre": "a21ybx.item.want.1.14ad3da6ALVq3n",
            "log_id": "14ad3da6ALVq3n"
        }
        data_val = '{"appKey":"444e9908a51d1cb236a27862abc769c9","deviceId":"' + device_id + '"}'
        data = {
            'data': data_val,
        }
        headers = {
            "Host": "h5api.m.goofish.com",
            "sec-ch-ua-platform": "\"Windows\"",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
            "accept": "application/json",
            "sec-ch-ua": "\"Chromium\";v=\"146\", \"Not-A.Brand\";v=\"24\", \"Google Chrome\";v=\"146\"",
            "content-type": "application/x-www-form-urlencoded",
            "sec-ch-ua-mobile": "?0",
            "origin": "https://www.goofish.com",
            "sec-fetch-site": "same-site",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "referer": "https://www.goofish.com/",
            "accept-language": "en,zh-CN;q=0.9,zh;q=0.8,zh-TW;q=0.7,ja;q=0.6",
            "priority": "u=1, i"
        }
        # 简单获取token，信任cookies已清理干净
        token = self._cookie_value('_m_h5_tk').split('_')[0]
        
        sign = generate_sign(params['t'], token, data_val)
        params['sign'] = sign
        
        try:
            response = self.session.post('https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.pc.login.token/1.0/', headers=headers, params=params, data=data)
            res_json = response.json()
            updated_cookies = self._merge_response_cookies(response)
            
            if isinstance(res_json, dict):
                ret_value = res_json.get('ret', [])
                # 检查ret是否包含成功信息
                if not any('SUCCESS::调用成功' in ret for ret in ret_value):
                    # 检测风控/限流错误
                    error_msg = str(ret_value)
                    if 'RGV587_ERROR' in error_msg or '被挤爆啦' in error_msg:
                        logger.error(f"❌ 触发风控: {ret_value}")
                        logger.error("🔴 系统目前无法自动解决，请进入闲鱼网页版-点击消息-过滑块-复制最新的Cookie")
                        
                        # 获取用户输入的新Cookie
                        print("\n" + "="*50)
                        new_cookie_str = input("请输入新的Cookie字符串 (复制浏览器中的完整cookie，直接回车则退出程序): ").strip()
                        print("="*50 + "\n")
                        
                        if new_cookie_str:
                            try:
                                # 解析cookie字符串并更新session
                                from http.cookies import SimpleCookie
                                cookie = SimpleCookie()
                                cookie.load(new_cookie_str)
                                
                                # 清空旧cookie并设置新cookie
                                self.session.cookies.clear()
                                for key, morsel in cookie.items():
                                    self.session.cookies.set(key, morsel.value, domain='.goofish.com')
                                
                                logger.success("✅ Cookie已更新，正在尝试重连...")
                                # 同步更新到.env文件
                                self.update_env_cookies()
                                
                                # 立即重试
                                return self.get_token(device_id, 0)
                            except Exception as e:
                                logger.error(f"Cookie解析失败: {e}")
                                sys.exit(1)
                        else:
                            logger.info("用户取消输入，程序退出")
                            sys.exit(1)

                    logger.warning(f"Token API调用失败，错误信息: {ret_value}")
                    if updated_cookies:
                        logger.debug(f"检测到Set-Cookie，已更新 {len(updated_cookies)} 个cookie字段")
                    time.sleep(0.5)
                    return self.get_token(device_id, retry_count + 1)
                else:
                    logger.info("Token获取成功")
                    return res_json
            else:
                logger.error(f"Token API返回格式异常: {res_json}")
                return self.get_token(device_id, retry_count + 1)
                
        except Exception as e:
            logger.error(f"Token API请求异常: {str(e)}")
            time.sleep(0.5)
            return self.get_token(device_id, retry_count + 1)

    def get_item_info(self, item_id, retry_count=0):
        """获取商品信息，自动处理token失效的情况"""
        if retry_count >= 3:  # 最多重试3次
            logger.error("获取商品信息失败，重试次数过多")
            return {"error": "获取商品信息失败，重试次数过多"}
            
        params = {
            'jsv': '2.7.2',
            'appKey': '34839810',
            't': str(int(time.time()) * 1000),
            'sign': '',
            'v': '1.0',
            'type': 'originaljson',
            'accountSite': 'xianyu',
            'dataType': 'json',
            'timeout': '20000',
            'api': 'mtop.taobao.idle.pc.detail',
            'sessionOption': 'AutoLoginOnly',
            'spm_cnt': 'a21ybx.im.0.0',
        }
        
        data_val = '{"itemId":"' + item_id + '"}'
        data = {
            'data': data_val,
        }
        
        # 简单获取token，信任cookies已清理干净
        token = self._cookie_value('_m_h5_tk').split('_')[0]
        
        sign = generate_sign(params['t'], token, data_val)
        params['sign'] = sign
        
        try:
            response = self.session.post(
                'https://h5api.m.goofish.com/h5/mtop.taobao.idle.pc.detail/1.0/', 
                params=params, 
                data=data
            )
            
            res_json = response.json()
            updated_cookies = self._merge_response_cookies(response)
            # 检查返回状态
            if isinstance(res_json, dict):
                ret_value = res_json.get('ret', [])
                # 检查ret是否包含成功信息
                if not any('SUCCESS::调用成功' in ret for ret in ret_value):
                    logger.warning(f"商品信息API调用失败，错误信息: {ret_value}")
                    if updated_cookies:
                        logger.debug(f"检测到Set-Cookie，已更新 {len(updated_cookies)} 个cookie字段")
                    time.sleep(0.5)
                    return self.get_item_info(item_id, retry_count + 1)
                else:
                    logger.debug(f"商品信息获取成功: {item_id}")
                    return res_json
            else:
                logger.error(f"商品信息API返回格式异常: {res_json}")
                return self.get_item_info(item_id, retry_count + 1)
                
        except Exception as e:
            logger.error(f"商品信息API请求异常: {str(e)}")
            time.sleep(0.5)
            return self.get_item_info(item_id, retry_count + 1)

    def get_order_detail(self, order_id, retry_count=0):
        """获取订单详情，供自动发货补全购买数量和规格信息。"""
        if retry_count >= 3:
            logger.error("获取订单详情失败，重试次数过多")
            return {"error": "获取订单详情失败，重试次数过多"}

        timestamp = str(int(time.time()) * 1000)
        data_val = json.dumps({"tid": str(order_id)}, separators=(",", ":"))
        token = self._cookie_value('_m_h5_tk').split('_')[0]
        sign = generate_sign(timestamp, token, data_val)
        params = {
            'jsv': '2.7.2',
            'appKey': '34839810',
            't': timestamp,
            'sign': sign,
            'v': '1.0',
            'type': 'originaljson',
            'accountSite': 'xianyu',
            'dataType': 'json',
            'timeout': '20000',
            'api': 'mtop.idle.web.trade.order.detail',
            'sessionOption': 'AutoLoginOnly',
            'spm_cnt': 'a21ybx.order-detail.0.0',
        }
        data = {'data': data_val}
        headers = {
            'accept': 'application/json',
            'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://www.goofish.com',
            'referer': 'https://www.goofish.com/',
        }

        try:
            response = self.session.post(
                'https://h5api.m.goofish.com/h5/mtop.idle.web.trade.order.detail/1.0/',
                params=params,
                data=data,
                headers=headers,
            )
            res_json = response.json()
            updated_cookies = self._merge_response_cookies(response)
            if isinstance(res_json, dict):
                ret_value = res_json.get('ret', [])
                if not any('SUCCESS' in ret for ret in ret_value):
                    logger.warning(f"订单详情API调用失败，错误信息: {ret_value}")
                    if updated_cookies:
                        logger.debug(f"检测到Set-Cookie，已更新 {len(updated_cookies)} 个cookie字段")
                    time.sleep(0.5)
                    return self.get_order_detail(order_id, retry_count + 1)
                logger.debug(f"订单详情获取成功: {order_id}")
                return res_json

            logger.error(f"订单详情API返回格式异常: {res_json}")
            return self.get_order_detail(order_id, retry_count + 1)
        except Exception as e:
            logger.error(f"订单详情API请求异常: {str(e)}")
            time.sleep(0.5)
            return self.get_order_detail(order_id, retry_count + 1)
