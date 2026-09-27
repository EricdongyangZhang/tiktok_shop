# -*- coding: utf-8 -*-
"""TikTok Shop 海外开放平台最小客户端：授权换 token + 请求签名。

签名算法与端点路径参照可正常工作的第三方客户端实现核对过（见 README）。
access_token 走请求头 x-tts-access-token，不是 query 参数。
"""
import hashlib
import hmac
import json
import time

import requests

AUTH_HOST = "https://auth.tiktok-shops.com"          # token 端点，所有市场共用
API_HOST = "https://open-api.tiktokglobalshop.com"
API_VERSION = "202309"

# 卖家授权页域名按市场区分，且用的是 service_id 而不是 app_key
SERVICES_HOST = {
    "US": "https://services.us.tiktokshop.com",
    "ROW": "https://services.tiktokshop.com",
}

# 这些接口不允许携带 shop_cipher
NO_CIPHER_PREFIXES = (
    "/product/%s/files/upload",
    "/product/%s/images/upload",
    "/product/%s/compliance",
    "/product/%s/global_products",
    "/authorization/%s/",
    "/seller/%s/",
)


class TikTokShopError(Exception):
    def __init__(self, message, code=None, request_id=None):
        super().__init__(message)
        self.code = code
        self.request_id = request_id

    def __str__(self):
        parts = [super().__str__()]
        if self.code is not None:
            parts.append(f"code={self.code}")
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        return " | ".join(parts)


class TikTokShopClient:
    def __init__(self, app_key: str, app_secret: str, access_token: str = "",
                 shop_cipher: str = "", service_id: str = "", region: str = "ROW",
                 version: str = API_VERSION, timeout: int = 60):
        self.app_key = app_key
        self.app_secret = app_secret
        self.access_token = access_token
        self.shop_cipher = shop_cipher
        self.service_id = service_id
        self.region = region
        self.version = version
        self.timeout = timeout
        self.http = requests.Session()

    # ---------- 第一步：授权换 token ----------

    def auth_url(self, state: str = "img_ec") -> str:
        """店铺管理员账号打开此链接点「同意授权」，回调拿到 code。

        注意：卖家授权用 service_id + 分市场域名，不是 app_key。
        最省事的做法是直接在 Partner Center 的 App 详情页复制授权链接。
        """
        if not self.service_id:
            raise TikTokShopError("缺少 service_id（在 Partner Center App 详情页，与 app_key 同页）")
        host = SERVICES_HOST["US"] if self.region.upper() == "US" else SERVICES_HOST["ROW"]
        return f"{host}/open/authorize?service_id={self.service_id}&state={state}"

    def exchange_code(self, auth_code: str) -> dict:
        """用 auth_code 换 access_token / refresh_token。auth_code 30 分钟过期且只能用一次。"""
        return self._token_call("/api/v2/token/get", {"auth_code": auth_code,
                                                     "grant_type": "authorized_code"})

    def refresh(self, refresh_token: str) -> dict:
        """刷新时服务端会下发新的 refresh_token，必须一起持久化（会轮换）。"""
        return self._token_call("/api/v2/token/refresh", {"refresh_token": refresh_token,
                                                          "grant_type": "refresh_token"})

    def _token_call(self, path: str, extra: dict) -> dict:
        params = {"app_key": self.app_key, "app_secret": self.app_secret, **extra}
        resp = self.http.get(AUTH_HOST + path, params=params, timeout=self.timeout)
        body = self._json(resp)
        if body.get("code") != 0:
            raise TikTokShopError(body.get("message") or "token 请求失败", body.get("code"))
        data = body["data"]
        # token 响应里没有 shop_cipher，它要另外调 authorization/shops 取
        self.access_token = data.get("access_token", self.access_token)
        return data

    # ---------- 签名 ----------

    def _sign(self, path: str, query: dict, body_text: str, method: str) -> str:
        # 1. 取除 sign / access_token 外的 query 参数，按 key 字典序排序
        params = {k: v for k, v in query.items()
                  if k not in ("sign", "access_token", "x-tts-access-token")
                  and not isinstance(v, (list, dict))}
        # 2. 拼成 {key}{value}
        concat = "".join(f"{k}{params[k]}" for k in sorted(params))
        # 3. path 放最前面
        digest = path + concat
        # 4. 非 GET 且非 multipart 时，原始 body 放最后（必须与实发字节完全一致）
        if method != "GET" and body_text is not None:
            digest += body_text
        # 5. 前后各包一层 app_secret
        digest = self.app_secret + digest + self.app_secret
        # 6. 以 app_secret 为密钥做 HMAC-SHA256
        return hmac.new(self.app_secret.encode(), digest.encode(), hashlib.sha256).hexdigest()

    def _allows_cipher(self, path: str) -> bool:
        return not any(path.startswith(p % self.version) for p in NO_CIPHER_PREFIXES)

    # ---------- 通用请求 ----------

    def get(self, action: str, category: str = "product", **query):
        return self.request("GET", f"/{category}/{self.version}/{action}", query=query)

    def post(self, action: str, body=None, category: str = "product", **query):
        return self.request("POST", f"/{category}/{self.version}/{action}", body=body, query=query)

    def request(self, method: str, path: str, query: dict | None = None,
                body=None, multipart: list | None = None) -> dict:
        query = dict(query or {})
        query["app_key"] = self.app_key
        query["timestamp"] = int(time.time())
        if self.shop_cipher and self._allows_cipher(path):
            query.setdefault("shop_cipher", self.shop_cipher)

        headers = {}
        body_text = None
        if multipart is not None:
            # multipart 不参与签名，也不设 content-type（交给 requests 生成 boundary）
            data = None
        else:
            if body is not None:
                body_text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
                data = body_text.encode("utf-8")
                headers["Content-Type"] = "application/json; charset=UTF-8"
            else:
                data = None
                headers["Content-Type"] = "application/json; charset=UTF-8"

        query["sign"] = self._sign(path, query, body_text if multipart is None else None, method)
        if self.access_token:
            headers["x-tts-access-token"] = self.access_token

        resp = self.http.request(method, API_HOST + path, params=query, data=data,
                                 files=multipart, headers=headers, timeout=self.timeout)
        payload = self._json(resp)
        # 业务码在 200 响应里也可能非 0，必须查
        if payload.get("code", 0) != 0:
            raise TikTokShopError(payload.get("message") or "请求失败",
                                  payload.get("code"), payload.get("request_id"))
        return payload.get("data", payload)

    @staticmethod
    def _json(resp) -> dict:
        try:
            return resp.json()
        except ValueError:
            raise TikTokShopError(f"响应非 JSON (HTTP {resp.status_code}): {resp.text[:300]}")

    # ---------- 商品链路常用调用 ----------

    def get_categories(self, **query) -> dict:
        return self.get("categories", **query)

    def get_attributes(self, category_id: str | int, **query) -> dict:
        return self.get(f"categories/{category_id}/attributes", **query)

    def get_category_rules(self, category_id: str | int, **query) -> dict:
        return self.get(f"categories/{category_id}/rules", **query)

    def recommend_category(self, title: str, description: str = "", images=None) -> dict:
        return self.post("categories/recommend",
                         body={"product_title": title, "description": description,
                               "images": images or []})

    def upload_image(self, local_path: str, use_case: str = "MAIN_IMAGE") -> dict:
        with open(local_path, "rb") as f:
            return self.request("POST", f"/product/{self.version}/images/upload",
                                multipart=[("data", ("image", f.read(), "image/png")),
                                           ("use_case", (None, use_case))])

    def create_product(self, payload: dict) -> dict:
        return self.post("products", body=payload)

    def search_products(self, body: dict | None = None, **query) -> dict:
        return self.post("products/search", body=body or {}, **query)

    def activate_products(self, product_ids: list[str]) -> dict:
        return self.post("products/activate", body={"product_ids": product_ids})

    def deactivate_products(self, product_ids: list[str]) -> dict:
        return self.post("products/deactivate", body={"product_ids": product_ids})

    def get_authorized_shops(self) -> dict:
        return self.get("shops", category="authorization")

    def resolve_shop_cipher(self, shop_name: str = "") -> str:
        """从已授权店铺列表里取 cipher 并缓存到实例。Custom App 通常只有一个店。"""
        data = self.get_authorized_shops()
        shops = data.get("shops") or data.get("data") or []
        if not shops:
            raise TikTokShopError(f"授权店铺列表为空：{data}")
        if shop_name:
            shops = [s for s in shops if shop_name in (s.get("name") or s.get("seller_name") or "")] or shops
        shop = shops[0]
        self.shop_cipher = shop.get("cipher") or shop.get("shop_cipher") or ""
        if not self.shop_cipher:
            raise TikTokShopError(f"该店铺条目里没有 cipher 字段：{shop}")
        return self.shop_cipher
