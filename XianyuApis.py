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

    def get_published_items_page(self, page_number=1, page_size=20, myid=None, retry_count=0):
        """获取当前账号已发布/在售商品列表的一页。"""
        if retry_count >= 3:
            logger.error("获取已发布商品失败，重试次数过多")
            return {"success": False, "message": "获取已发布商品失败，重试次数过多"}

        timestamp = str(int(time.time()) * 1000)
        data_payload = {
            "needGroupInfo": False,
            "pageNumber": int(page_number),
            "pageSize": int(page_size),
            "groupName": "在售",
            "groupId": "58877261",
            "defaultGroup": True,
            "userId": str(myid or self._cookie_value("unb")),
        }
        data_val = json.dumps(data_payload, separators=(",", ":"), ensure_ascii=False)
        token = self._cookie_value("_m_h5_tk").split("_")[0]
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
            'api': 'mtop.idle.web.xyh.item.list',
            'sessionOption': 'AutoLoginOnly',
            'spm_cnt': 'a21ybx.im.0.0',
            'spm_pre': 'a21ybx.collection.menu.1.272b5141NafCNK',
        }
        headers = {
            'accept': 'application/json',
            'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://www.goofish.com',
            'referer': 'https://www.goofish.com/',
            'cookie': self.get_cookie_string(),
        }

        try:
            response = self.session.post(
                'https://h5api.m.goofish.com/h5/mtop.idle.web.xyh.item.list/1.0/',
                params=params,
                data={'data': data_val},
                headers=headers,
            )
            res_json = response.json()
            updated_cookies = self._merge_response_cookies(response)
            if not isinstance(res_json, dict):
                return {"success": False, "message": f"商品列表API返回格式异常: {res_json}"}

            ret = res_json.get("ret", [])
            if not any("SUCCESS" in str(item) for item in ret):
                if is_token_expired_ret(ret):
                    if updated_cookies:
                        logger.debug(f"已发布商品列表检测到Set-Cookie，已更新 {len(updated_cookies)} 个cookie字段")
                    time.sleep(0.5)
                    return self.get_published_items_page(page_number, page_size, myid, retry_count + 1)
                message = ret[0] if ret else "获取已发布商品失败"
                logger.warning(f"已发布商品列表API调用失败: {message}")
                return {"success": False, "message": message, "ret": ret}

            card_list = res_json.get("data", {}).get("cardList", [])
            items = []
            for card in card_list:
                card_data = card.get("cardData", {}) if isinstance(card, dict) else {}
                if not card_data:
                    continue
                price_info = card_data.get("priceInfo", {}) or {}
                items.append(
                    {
                        "id": str(card_data.get("id", "")),
                        "title": card_data.get("title", ""),
                        "price": price_info.get("price", ""),
                        "price_text": f"{price_info.get('preText', '')}{price_info.get('price', '')}",
                        "category_id": card_data.get("categoryId", ""),
                        "auction_type": card_data.get("auctionType", ""),
                        "item_status": card_data.get("itemStatus", 0),
                        "detail_url": card_data.get("detailUrl", ""),
                        "pic_info": card_data.get("picInfo", {}),
                        "detail_params": card_data.get("detailParams", {}),
                        "track_params": card_data.get("trackParams", {}),
                        "item_label_data": card_data.get("itemLabelDataVO", {}),
                        "card_type": card.get("cardType", 0),
                    }
                )

            return {
                "success": True,
                "message": f"获取到第 {page_number} 页商品，共 {len(items)} 件",
                "page_number": int(page_number),
                "page_size": int(page_size),
                "current_count": len(items),
                "items": items,
                "raw_data": res_json.get("data", {}),
            }
        except Exception as e:
            logger.error(f"已发布商品列表API请求异常: {str(e)}")
            time.sleep(0.5)
            return self.get_published_items_page(page_number, page_size, myid, retry_count + 1)

    def get_all_published_items(self, *, page_size=20, max_pages=None, myid=None):
        """自动翻页获取当前账号所有已发布/在售商品。"""
        all_items = []
        page_number = 1
        fetched_pages = 0
        while True:
            if max_pages is not None and page_number > int(max_pages):
                break

            result = self.get_published_items_page(
                page_number=page_number,
                page_size=page_size,
                myid=myid,
            )
            if not result.get("success"):
                result.setdefault("items", all_items)
                result.setdefault("total_count", len(all_items))
                result.setdefault("total_pages", fetched_pages)
                result.setdefault("page_size", page_size)
                return result

            items = result.get("items", [])
            if not items:
                break

            all_items.extend(items)
            fetched_pages = page_number
            if len(items) < int(page_size):
                break
            page_number += 1

        return {
            "success": True,
            "message": f"获取到 {len(all_items)} 个已发布商品",
            "items": all_items,
            "total_count": len(all_items),
            "total_pages": fetched_pages,
            "page_size": int(page_size),
        }

    def get_item_status(self, item_id, *, page_size=20, max_pages=None, myid=None):
        """Refresh one item's current platform status from the seller account.

        The published-item list is the safest first source because it proves the
        item is currently visible in the seller's in-sale group. If the item is
        absent from that list, fall back to the item detail endpoint so stale
        local snapshots cannot keep reporting `active`.
        """
        item_id = str(item_id).strip()
        if not item_id:
            return {"success": False, "message": "item_id is required"}

        published_result = self.get_all_published_items(
            page_size=page_size,
            max_pages=max_pages,
            myid=myid,
        )
        if not published_result.get("success"):
            return published_result

        for item in published_result.get("items") or []:
            candidate_id = str(item.get("item_id") or item.get("itemId") or item.get("id") or "")
            if candidate_id == item_id:
                live_item = dict(item)
                live_item["item_id"] = item_id
                live_item["itemId"] = item_id
                live_item["status"] = "active"
                live_item["status_source"] = "published_list"
                live_item["platform_status"] = item.get("item_status", item.get("itemStatus", item.get("status", 0)))
                live_item["platform_status_text"] = item.get("item_status_text", item.get("itemStatusStr", "在售"))
                live_item["can_relist"] = False
                return {
                    "success": True,
                    "item": live_item,
                    "message": "商品在当前账号在售列表中",
                }

        detail_result = self.get_item_info(item_id)
        if isinstance(detail_result, dict) and detail_result.get("data"):
            item_detail = self._extract_item_detail(detail_result)
            if item_detail:
                live_item = self._normalize_detail_item_status(item_id, item_detail)
                return {
                    "success": True,
                    "item": live_item,
                    "message": "商品不在在售列表中，已使用详情接口刷新状态",
                }

        return {
            "success": True,
            "item": {
                "item_id": item_id,
                "itemId": item_id,
                "id": item_id,
                "status": "inactive",
                "status_source": "published_list_absent",
                "platform_status": "",
                "platform_status_text": "not_in_published_list",
                "can_relist": True,
            },
            "message": "商品不在当前账号在售列表中",
        }

    def relist_item(self, item_id, *, stock=None, retry_count=0):
        """Call a configured seller mtop relist API without hardcoding a guessed endpoint."""
        relist_api = os.getenv("XIANYU_RELIST_API") or os.getenv("XIANXY_RELIST_API")
        if not relist_api:
            return {
                "ret": ["FAIL::relist_api_not_configured"],
                "data": {"msg": "relist API is not configured"},
            }
        if retry_count >= 2:
            return {
                "ret": ["FAIL::relist_api_retry_exhausted"],
                "data": {"msg": "relist API retry exhausted"},
            }

        item_id = str(item_id).strip()
        payload: dict[str, object] = {"itemId": item_id}
        if stock is not None:
            payload["stock"] = int(stock)
        data_val = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        timestamp = str(int(time.time() * 1000))
        token = self._cookie_value("_m_h5_tk").split("_")[0]
        params = {
            "jsv": "2.7.2",
            "appKey": "34839810",
            "t": timestamp,
            "sign": generate_sign(timestamp, token, data_val),
            "v": "1.0",
            "type": "originaljson",
            "accountSite": "xianyu",
            "dataType": "json",
            "timeout": "20000",
            "needLoginPC": "true",
            "showErrorToast": "true",
            "api": relist_api,
            "sessionOption": "AutoLoginOnly",
            "spm_cnt": "a21107h.42829799.0.0",
        }
        headers = {
            "accept": "application/json",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "cache-control": "no-cache",
            "content-type": "application/x-www-form-urlencoded",
            "idle_site_biz_code": "COMMONPRO",
            "idle_user_group_member_id": "",
            "origin": "https://seller.goofish.com",
            "pragma": "no-cache",
            "referer": "https://seller.goofish.com/?site=COMMONPRO",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/146.0.0.0 Safari/537.36"
            ),
            "cookie": self.get_cookie_string().replace("\n", "").replace("\r", ""),
        }
        try:
            response = self.session.post(
                f"https://h5api.m.goofish.com/h5/{relist_api}/1.0/",
                params=params,
                data={"data": data_val},
                headers=headers,
            )
            res_json = response.json()
            updated_cookies = self._merge_response_cookies(response)
            ret = res_json.get("ret", []) if isinstance(res_json, dict) else []
            if is_token_expired_ret(ret) and retry_count < 1:
                if updated_cookies:
                    logger.debug(f"重新上架API检测到Set-Cookie，已更新 {len(updated_cookies)} 个cookie字段")
                time.sleep(0.5)
                return self.relist_item(item_id, stock=stock, retry_count=retry_count + 1)
            return res_json
        except Exception as e:
            logger.warning(f"重新上架API请求异常: {e}")
            return {
                "ret": ["FAIL::relist_api_exception"],
                "data": {"msg": str(e)},
            }

    def _extract_item_detail(self, detail_result: dict) -> dict:
        data = detail_result.get("data", {}) if isinstance(detail_result, dict) else {}
        if not isinstance(data, dict):
            return {}
        for key in ("itemDO", "item", "itemInfo", "auctionDO"):
            value = data.get(key)
            if isinstance(value, dict):
                return value
        return data if any(key in data for key in ("title", "itemStatus", "status", "quantity")) else {}

    def _normalize_detail_item_status(self, item_id: str, item_detail: dict) -> dict:
        status_value = item_detail.get(
            "status",
            item_detail.get("item_status", item_detail.get("itemStatus", item_detail.get("auctionStatus", ""))),
        )
        status_label = item_detail.get(
            "status_text",
            item_detail.get("statusText", item_detail.get("itemStatusStr", item_detail.get("statusDesc", ""))),
        )
        status_text = self._map_platform_status(status_value, status_label)
        live_item = dict(item_detail)
        live_item["item_id"] = item_id
        live_item.setdefault("itemId", item_id)
        live_item.setdefault("id", item_id)
        live_item["status"] = status_text
        live_item["status_source"] = "item_detail"
        live_item["platform_status"] = status_value
        live_item["platform_status_text"] = status_label
        live_item["can_relist"] = status_text in {"inactive", "sold", "relistable"}
        return live_item

    def _map_platform_status(self, value, label: object = "") -> str:
        label_text = str(label or "").strip().lower()
        if any(word in label_text for word in ("卖掉", "已卖", "已售", "sold")):
            return "sold"
        if any(word in label_text for word in ("可重新上架", "重新上架", "可上架", "待上架", "relist")):
            return "relistable"
        if any(word in label_text for word in ("下架", "off_sale", "offline")):
            return "inactive"
        if any(word in label_text for word in ("在售", "已上架", "on_sale", "selling", "active")):
            return "active"
        if value is None or value == "":
            return "inactive"
        text = str(value).strip().lower()
        if text in {"0", "active", "online", "on_sale", "selling", "在售", "已上架"}:
            return "active"
        if text in {"sold", "sold_out", "已售出", "卖掉了"}:
            return "sold"
        if text in {"relistable", "可重新上架", "重新上架"}:
            return "relistable"
        if text in {"1", "2", "inactive", "offline", "off_sale", "down", "下架", "已下架"}:
            return "inactive"
        return text

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

    def confirm_delivery(self, order_id, item_id=None, retry_count=0):
        """在闲鱼订单侧执行无物流确认发货。"""
        if retry_count >= 5:
            logger.error("自动确认发货失败，重试次数过多")
            return {"success": False, "error": "自动确认发货失败，重试次数过多", "order_id": str(order_id)}

        timestamp = str(int(time.time()) * 1000)
        payload = {
            "orderId": str(order_id),
            "tradeText": "",
            "picList": [],
            "newUnconsign": True,
        }
        data_val = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
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
            'api': 'mtop.taobao.idle.logistic.consign.dummy',
            'sessionOption': 'AutoLoginOnly',
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
                'https://h5api.m.goofish.com/h5/mtop.taobao.idle.logistic.consign.dummy/1.0/',
                params=params,
                data=data,
                headers=headers,
            )
            res_json = response.json()
            updated_cookies = self._merge_response_cookies(response)
            ret_value = res_json.get('ret', []) if isinstance(res_json, dict) else []
            ret_msg = str(ret_value[0]) if ret_value else ""

            if ret_msg == 'SUCCESS::调用成功' or any('SUCCESS' in str(item) for item in ret_value):
                logger.info(f"自动确认发货成功: 订单={order_id}, 商品={item_id or ''}")
                return {
                    "success": True,
                    "order_id": str(order_id),
                    "item_id": str(item_id or ""),
                    "message": ret_msg or "SUCCESS::调用成功",
                    "ret": ret_value,
                }

            if 'ORDER_ALREADY_DELIVERY' in ret_msg or '已发货成功' in ret_msg or '已发货' in ret_msg:
                logger.info(f"订单已发货，无需重复确认: 订单={order_id}")
                return {
                    "success": True,
                    "already_delivered": True,
                    "order_id": str(order_id),
                    "item_id": str(item_id or ""),
                    "message": ret_msg,
                    "ret": ret_value,
                }

            if is_token_expired_ret(ret_value) or is_session_expired_ret(ret_value):
                if updated_cookies:
                    logger.debug(f"确认发货检测到Set-Cookie，已更新 {len(updated_cookies)} 个cookie字段")
                time.sleep(0.5)
                return self.confirm_delivery(order_id, item_id=item_id, retry_count=retry_count + 1)

            if any(keyword in ret_msg for keyword in ("RGV587_ERROR", "滑块", "验证码", "风控", "被挤爆")):
                return {
                    "success": False,
                    "order_id": str(order_id),
                    "item_id": str(item_id or ""),
                    "error": "risk_control",
                    "message": ret_msg,
                    "ret": ret_value,
                }

            logger.warning(f"自动确认发货失败: 订单={order_id}, ret={ret_value}")
            time.sleep(0.5)
            return self.confirm_delivery(order_id, item_id=item_id, retry_count=retry_count + 1)
        except Exception as e:
            logger.error(f"自动确认发货API请求异常: {str(e)}")
            time.sleep(0.5)
            return self.confirm_delivery(order_id, item_id=item_id, retry_count=retry_count + 1)
