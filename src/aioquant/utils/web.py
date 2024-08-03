# -*- coding:utf-8 -*-

"""
Web module.

Author: HuangTao
Date:   2018/08/26
Email:  huangtao@ifclover.com
"""

import json

import aiohttp
from urllib.parse import urlparse

from aioquant.utils import logger
from aioquant.configure import config
from aioquant.tasks import LoopRunTask, SingleTask
from aioquant.utils.decorator import async_method_locker


__all__ = ("Websocket", "AsyncHttpRequests", "WeiChat", "TelegramBot", "DingTalk")


class Websocket:
    """Websocket connection.

    Attributes:
        url: Websocket connection url.
        connected_callback: Asynchronous callback function will be called after connected to Websocket server successfully.
        process_callback: Asynchronous callback function will be called if any stream data receive from Websocket
            connection, this function only callback `text/json` message. e.g.
                async def process_callback(json_message): pass
        process_binary_callback: Asynchronous callback function will be called if any stream data receive from Websocket
            connection, this function only callback `binary` message. e.g.
                async def process_binary_callback(binary_message): pass
        check_conn_interval: Check Websocket connection interval time(seconds), default is 10s.
    """

    def __init__(self, url, connected_callback=None, process_callback=None, process_binary_callback=None,
                 check_conn_interval=10):
        """Initialize."""
        self._url = url
        self._connected_callback = connected_callback
        self._process_callback = process_callback
        self._process_binary_callback = process_binary_callback
        self._check_conn_interval = check_conn_interval
        self._ws = None  # Websocket connection object.

        LoopRunTask.register(self._check_connection, self._check_conn_interval)
        SingleTask.run(self._connect)

    @property
    def ws(self):
        return self._ws

    async def close(self):
        await self._ws.close()

    async def ping(self, message: bytes = b"") -> None:
        await self._ws.ping(message)

    async def pong(self, message: bytes = b"") -> None:
        await self._ws.pong(message)

    async def _connect(self) -> None:
        logger.info("url:", self._url, caller=self)
        proxy = config.proxy
        session = aiohttp.ClientSession()
        try:
            self._ws = await session.ws_connect(self._url, proxy=proxy)
        except aiohttp.ClientConnectorError:
            logger.error("connect to Websocket server error! url:", self._url, caller=self)
            return
        if self._connected_callback:
            SingleTask.run(self._connected_callback)
        SingleTask.run(self._receive)

    @async_method_locker("Websocket.reconnect.locker", False, 30)
    async def reconnect(self) -> None:
        """Re-connect to Websocket server."""
        logger.warn("reconnecting to Websocket server right now!", caller=self)
        await self.close()
        await self._connect()

    async def _receive(self):
        """Receive stream message from Websocket connection."""
        async for msg in self.ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                if self._process_callback:
                    try:
                        data = json.loads(msg.data)
                    except:
                        data = msg.data
                    SingleTask.run(self._process_callback, data)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                if self._process_binary_callback:
                    SingleTask.run(self._process_binary_callback, msg.data)
            elif msg.type == aiohttp.WSMsgType.CLOSED:
                logger.warn("receive event CLOSED:", msg, caller=self)
                SingleTask.run(self.reconnect)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.error("receive event ERROR:", msg, caller=self)
            else:
                logger.warn("unhandled msg:", msg, caller=self)

    async def _check_connection(self, *args, **kwargs) -> None:
        """Check Websocket connection, if connection closed, re-connect immediately."""
        if not self.ws:
            logger.warn("Websocket connection not connected yet!", caller=self)
            return
        if self.ws.closed:
            SingleTask.run(self.reconnect)

    async def send(self, data) -> bool:
        """ Send message to Websocket server.

        Args:
            data: Message content, must be dict or string.

        Returns:
            If send successfully, return True, otherwise return False.
        """
        if not self.ws:
            logger.warn("Websocket connection not connected yet!", caller=self)
            return False
        if isinstance(data, dict):
            await self.ws.send_json(data)
        elif isinstance(data, str):
            await self.ws.send_str(data)
        else:
            logger.error("send message failed:", data, caller=self)
            return False
        logger.debug("send message:", data, caller=self)
        return True


class AsyncHttpRequests(object):
    """ Asynchronous HTTP Request Client.
    """

    # Every domain name holds a connection session, for less system resource utilization and faster request speed.
    _SESSIONS = {}  # {"domain-name": session, ... }

    @classmethod
    async def fetch(cls, method, url, params=None, body=None, data=None, headers=None, timeout=30, **kwargs):
        """ Create a HTTP request.

        Args:
            method: HTTP request method. `GET` / `POST` / `PUT` / `DELETE`
            url: Request url.
            params: HTTP query params.
            body: HTTP request body, string or bytes format.
            data: HTTP request body, dict format.
            headers: HTTP request header.
            timeout: HTTP request timeout(seconds), default is 30s.

            kwargs:
                proxy: HTTP proxy.

        Return:
            code: HTTP response code.
            success: HTTP response data. If something wrong, this field is None.
            error: If something wrong, this field will holding a Error information, otherwise it's None.

        Raises:
            HTTP request exceptions or response data parse exceptions. All the exceptions will be captured and return
            Error information.
        """
        session = cls._get_session(url)
        if not kwargs.get("proxy"):
            kwargs["proxy"] = config.proxy  # If there is a `HTTP PROXY` Configuration in config file?
        try:
            if method == "GET":
                response = await session.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
            elif method == "POST":
                response = await session.post(url, params=params, data=body, json=data, headers=headers,
                                              timeout=timeout, **kwargs)
            elif method == "PUT":
                response = await session.put(url, params=params, data=body, json=data, headers=headers,
                                             timeout=timeout, **kwargs)
            elif method == "DELETE":
                response = await session.delete(url, params=params, data=body, json=data, headers=headers,
                                                timeout=timeout, **kwargs)
            else:
                error = "http method error!"
                return None, None, error
        except Exception as e:
            logger.error("method:", method, "url:", url, "headers:", headers, "params:", params, "body:", body,
                         "data:", data, "Error:", e, caller=cls)
            return None, None, e
        code = response.status
        if code not in (200, 201, 202, 203, 204, 205, 206):
            text = await response.text()
            logger.error("method:", method, "url:", url, "headers:", headers, "params:", params, "body:", body,
                         "data:", data, "code:", code, "result:", text, caller=cls)
            return code, None, text
        try:
            result = await response.json()
        except:
            result = await response.text()
            logger.debug("response data is not json format!", "method:", method, "url:", url, "headers:", headers,
                         "params:", params, "body:", body, "data:", data, "code:", code, "result:", result, caller=cls)
        logger.debug("method:", method, "url:", url, "headers:", headers, "params:", params, "body:", body,
                     "data:", data, "code:", code, "result:", json.dumps(result), caller=cls)
        return code, result, None

    @classmethod
    async def get(cls, url, params=None, body=None, data=None, headers=None, timeout=30, **kwargs):
        """ HTTP GET
        """
        result = await cls.fetch("GET", url, params, body, data, headers, timeout, **kwargs)
        return result

    @classmethod
    async def post(cls, url, params=None, body=None, data=None, headers=None, timeout=30, **kwargs):
        """ HTTP POST
        """
        result = await cls.fetch("POST", url, params, body, data, headers, timeout, **kwargs)
        return result

    @classmethod
    async def delete(cls, url, params=None, body=None, data=None, headers=None, timeout=30, **kwargs):
        """ HTTP DELETE
        """
        result = await cls.fetch("DELETE", url, params, body, data, headers, timeout, **kwargs)
        return result

    @classmethod
    async def put(cls, url, params=None, body=None, data=None, headers=None, timeout=30, **kwargs):
        """ HTTP PUT
        """
        result = await cls.fetch("PUT", url, params, body, data, headers, timeout, **kwargs)
        return result

    @classmethod
    def _get_session(cls, url):
        """ Get the connection session for url's domain, if no session, create a new.

        Args:
            url: HTTP request url.

        Returns:
            session: HTTP request session.
        """
        parsed_url = urlparse(url)
        key = parsed_url.netloc or parsed_url.hostname
        if key not in cls._SESSIONS:
            session = aiohttp.ClientSession()
            cls._SESSIONS[key] = session
        return cls._SESSIONS[key]

class DingTalk:
    """ DingTalk Bot API.
    """
    BASE_URL = "https://oapi.dingtalk.com/robot/send?access_token="

    @classmethod
    async def send_text_msg(cls, access_token:str, content:str, secret_key:str=None, phones: list=None, is_at_all:bool=False):
        """ Send text message.

        Args:
            access_token: DingTalk Access Token.
            content: Message content to be sent.
            phones: Phone numbers to be @.
            is_at_all: Is @ all members? default is False.
            secret_key: Secret key for generate signature.

        Returns:
            success: HTTP response data. If something wrong, this field is None.
            error: If something wrong, this field will holding a Error information, otherwise it's None.
        """
        body = {
            "msgtype": "text",
            "text": {
                "content": content
            }
        }
        if is_at_all:
            body["at"] = {"isAtAll": True}
        if phones:
            body['at'] = {'atMobiles': phones}
        url = cls.BASE_URL + access_token
        if secret_key:
            timestamp = tools.get_cur_timestamp_ms()
            secret_enc = bytes(secret_key.encode('utf-8'))
            string_to_sign_enc = "{}\n{}".format(timestamp, secret_key).encode("utf-8")
            hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
            sign = parse.quote_plus(base64.b64encode(hmac_code))
            url = cls.BASE_URL + access_token + '&timestamp=' + str(timestamp) + '&sign=' + str(sign)
        headers = {"Content-Type": "application/json"}
        await AsyncHttpRequests.post(url, data=body, headers=headers)

    @classmethod
    async def send_markdown_msg(cls, access_token, title, text, secret_key:str=None, phones=None, is_at_all=False):
        """ Send markdown message.

        Args:
            access_token: DingTalk Access Token.
            title: Message title.
            text: Message content to be sent.
            phones: Phone numbers to be @.
            is_at_all: Is @ all members? default is False.
        """
        body = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": text
            }
        }
        if is_at_all:
            body["at"] = {"isAtAll": True}
        if phones:
            assert isinstance(phones, list)
            body["at"] = {"atMobiles": phones}
        url = cls.BASE_URL + access_token
        if secret_key:
            timestamp = tools.get_cur_timestamp_ms()
            secret_enc = bytes(secret_key.encode('utf-8'))
            string_to_sign_enc = "{}\n{}".format(timestamp, secret_key).encode("utf-8")
            hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
            sign = parse.quote_plus(base64.b64encode(hmac_code))
            url = cls.BASE_URL + access_token + '&timestamp=' + timestamp + '&sign=' + sign
        headers = {"Content-Type": "application/json"}
        await AsyncHttpRequests.post(url, data=body, headers=headers)

class TelegramBot:
    """ Telegram Bot.
    """
    BASE_URL = "https://api.telegram.org"

    @classmethod
    async def send_text_msg(cls, token, chat_id, content):
        """ Send text message.

        Args:
            token: Telegram bot token.
            chat_id: Telegram chat id.
            content: The message string that you want to send.
        """
        url = "{base_url}/bot{token}/sendMessage?chat_id={chat_id}&text={content}".format(
            base_url=cls.BASE_URL,
            token=token,
            chat_id=chat_id,
            content=content
        )
        await AsyncHttpRequests.fetch("GET", url)

class WeiChat:
    """ WeiChat Bot API.
    """
    BASE_URL = "https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token="

    @classmethod
    @async_method_locker("WeiChat.send_text_msg.locker", True, 2)
    async def send_text_msg(cls, secret:str, content:str, corpid:str=None, agentid:str=None, phones: str=None, is_at_all:bool=True):
        """ Send text message.

        Args:
            secret: WeiChat Access Token.
            content: Message content to be sent.
            agentid: corpration agent.
            phones: Phone numbers to be @.
            is_at_all: Is @ all members? default is False.
            corpid: Secret key for generate signature.

        Returns:
            success: HTTP response data. If something wrong, this field is None.
            error: If something wrong, this field will holding a Error information, otherwise it's None.
        """
        body = {
            "msgtype": "text",
            "text": {
                "content": content
            },
            # "safe": "1"
        }
        if is_at_all:
            body["touser"] = "@all"
        if agentid:
            body["agentid"] = agentid
        if phones:
            body['touser'] = phones
        if secret:
            url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={ID}&corpsecret={SECRET}".format(ID=corpid, SECRET=secret)
            result = await AsyncHttpRequests.get(url)
            token = result[1]["access_token"]
            url = cls.BASE_URL + token
        await AsyncHttpRequests.post(url, data=body)
