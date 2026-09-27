# -*- coding: utf-8 -*-
"""签名算法自检：断言 string-to-sign 结构，并用独立实现交叉验证 HMAC 结果。

跑法： python test_signature.py
"""
import hashlib
import hmac

from tts_client import TikTokShopClient

SECRET = "test_secret"


def expected_hmac(string_to_sign: str) -> str:
    return hmac.new(SECRET.encode(), string_to_sign.encode(), hashlib.sha256).hexdigest()


def test_get_signature():
    c = TikTokShopClient("ak123", SECRET)
    query = {"app_key": "ak123", "timestamp": "1700000000", "shop_cipher": "sc"}
    path = "/product/202309/categories"

    # 期望串 = path + 按 key 排序拼接的 {key}{value}，前后包 app_secret
    body = "app_keyak123shop_ciphersc" + "timestamp1700000000"
    want = expected_hmac(SECRET + path + body + SECRET)
    got = c._sign(path, query, None, "GET")
    assert got == want, f"GET 签名不符\n want={want}\n got ={got}"
    assert len(got) == 64
    print("PASS GET 签名")


def test_sign_excludes_sign_and_token():
    c = TikTokShopClient("ak123", SECRET)
    base = {"app_key": "ak123", "timestamp": "1700000000"}
    s1 = c._sign("/p", dict(base), None, "GET")
    s2 = c._sign("/p", {**base, "sign": "junk", "access_token": "tok",
                        "x-tts-access-token": "tok"}, None, "GET")
    assert s1 == s2, "sign/access_token 必须被排除在签名之外"
    print("PASS 排除字段")


def test_post_includes_body():
    c = TikTokShopClient("ak123", SECRET)
    query = {"app_key": "ak123", "timestamp": "1700000000"}
    body = '{"title":"abc"}'
    want = expected_hmac(SECRET + "/product/202309/products"
                         + "app_keyak123timestamp1700000000" + body + SECRET)
    assert c._sign("/product/202309/products", query, body, "POST") == want
    # GET 即使带 body 文本也不应拼进去
    assert c._sign("/product/202309/products", query, body, "GET") != want
    print("PASS POST 拼 body / GET 不拼")


def test_multipart_skips_body_and_cipher():
    c = TikTokShopClient("ak123", SECRET, shop_cipher="sc")
    assert not c._allows_cipher("/product/202309/images/upload"), "图片上传不应带 shop_cipher"
    assert not c._allows_cipher("/product/202309/files/upload")
    assert c._allows_cipher("/product/202309/products"), "普通商品接口应带 shop_cipher"
    assert not c._allows_cipher("/authorization/202309/shops")
    print("PASS shop_cipher 适用范围")


def test_body_must_match_exactly():
    """签名用的 body 文本必须和实际发出的字节一致，否则 105xxx 签名错误。"""
    import json
    c = TikTokShopClient("ak123", SECRET)
    query = {"app_key": "ak123", "timestamp": "1700000000"}
    payload = {"title": "柴犬T恤", "price": 9.99}
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    signed = c._sign("/product/202309/products", query, body, "POST")
    # 换个序列化方式（带空格/转义中文）就应该对不上 —— 证明必须复用同一字符串
    other = json.dumps(payload)
    assert signed != c._sign("/product/202309/products", query, other, "POST")
    print("PASS body 序列化必须一致")


if __name__ == "__main__":
    test_get_signature()
    test_sign_excludes_sign_and_token()
    test_post_includes_body()
    test_multipart_skips_body_and_cipher()
    test_body_must_match_exactly()
    print("\n全部签名自检通过")
