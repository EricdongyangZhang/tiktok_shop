# -*- coding: utf-8 -*-
"""TikTok Shop 商品发布最小 demo。

用法（按顺序跑通）：
  python demo_publish.py auth-url
  python demo_publish.py token --code <回调里的 code>
  python demo_publish.py cipher
  python demo_publish.py shops
  python demo_publish.py categories --parent 0
  python demo_publish.py attrs --category-id <叶子类目ID>
  python demo_publish.py create --category-id <ID> --image <本地png> --title "..." --price 9.99
  加 --yes 才会真正调用创建接口，否则只打印将要提交的 payload。
"""
import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from tts_client import TikTokShopClient, TikTokShopError

BASE = Path(__file__).resolve().parent
TOKEN_FILE = BASE / "tokens.json"


def make_client() -> TikTokShopClient:
    load_dotenv(BASE / ".env")
    app_key = os.getenv("TTS_APP_KEY", "").strip()
    app_secret = os.getenv("TTS_APP_SECRET", "").strip()
    if not app_key or not app_secret:
        sys.exit("缺少 TTS_APP_KEY / TTS_APP_SECRET，请先复制 .env.example 为 .env 并填写")

    saved = json.loads(TOKEN_FILE.read_text(encoding="utf-8")) if TOKEN_FILE.exists() else {}
    return TikTokShopClient(app_key, app_secret,
                            access_token=saved.get("access_token", ""),
                            shop_cipher=os.getenv("TTS_SHOP_CIPHER", "").strip()
                            or saved.get("shop_cipher", ""),
                            service_id=os.getenv("TTS_SERVICE_ID", "").strip(),
                            region=os.getenv("TTS_REGION", "ROW").strip())


def save_tokens(data: dict) -> None:
    TOKEN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {TOKEN_FILE.name}（含密钥，已加入 .gitignore，勿提交）")


def cmd_auth_url(_):
    c = make_client()
    print("方式 A（推荐）：直接在 Partner Center 的 App 详情页复制授权链接。\n")
    print("方式 B：按文档规则拼出来的链接（店铺管理员账号打开并点「同意授权」）：\n")
    print(c.auth_url())
    print("\n授权后跳转到 Redirect URL，带上 ?code=xxx&state=xxx。")
    print("注意 code 30 分钟内有效且只能用一次；用户拒绝时 code=null&error=auth_denied。")


def cmd_token(a):
    c = make_client()
    data = c.exchange_code(a.code)
    save_tokens(data)
    print("access_token :", (data.get("access_token") or "")[:12] + "...")
    print("seller_name  :", data.get("seller_name"))
    print("region       :", data.get("seller_base_region"), "| user_type:", data.get("user_type"), "(0=卖家)")
    print("有效期       : access", data.get("access_token_expire_in"), "/ refresh", data.get("refresh_token_expire_in"))
    print("已授权 scope :", ", ".join(data.get("granted_scopes") or []) or "(空 —— 去 App 页确认 scope 已勾选)")
    print("\n下一步跑 cipher 取 shop_cipher（token 响应里没有这个字段）")


def cmd_cipher(_):
    c = make_client()
    print(json.dumps(c.get_authorized_shops(), ensure_ascii=False, indent=2))
    cipher = c.resolve_shop_cipher()
    saved = json.loads(TOKEN_FILE.read_text(encoding="utf-8")) if TOKEN_FILE.exists() else {}
    saved["shop_cipher"] = cipher
    save_tokens(saved)
    print("shop_cipher:", cipher)


def cmd_refresh(_):
    c = make_client()
    saved = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    data = c.refresh(saved["refresh_token"])
    # refresh 响应里没有 shop_cipher，要把已存的合并回去，否则被覆盖丢字段
    data.setdefault("shop_cipher", saved.get("shop_cipher", ""))
    save_tokens(data)
    print("刷新成功，新 refresh_token 已覆盖保存")


def cmd_shops(_):
    print(json.dumps(make_client().get_authorized_shops(), ensure_ascii=False, indent=2))


def cmd_categories(a):
    q = {"category_version": a.category_version}
    if a.parent:
        q["parent_category_id"] = a.parent
    print(json.dumps(make_client().get_categories(**q), ensure_ascii=False, indent=2))


def cmd_attrs(a):
    c = make_client()
    attrs = c.get_attributes(a.category_id, category_version=a.category_version)
    print(json.dumps(attrs, ensure_ascii=False, indent=2))
    required = [x for x in (attrs.get("data") or []) if x.get("required")]
    print(f"\n>>> 该类目必填属性 {len(required)} 个，创建商品时必须全部覆盖")


def cmd_upload(a):
    print(json.dumps(make_client().upload_image(a.image), ensure_ascii=False, indent=2))


def cmd_create(a):
    c = make_client()

    # 1. 先拿类目属性，缺必填项服务端一定拒
    attrs = c.get_attributes(a.category_id, category_version=a.category_version)
    required = [x["name"] for x in (attrs.get("data") or []) if x.get("required")]
    print("必填属性:", required or "(接口未返回，请人工核对)")

    # 2. 主图必须先上传换成平台内部 media id，不能直接给外链
    image_id = a.image_id
    if not image_id and a.image:
        up = c.upload_image(a.image)
        image_id = (up.get("data") or {}).get("id") or up.get("id")
        print("图片上传成功, media id:", image_id)
    if not image_id:
        sys.exit("缺少主图：用 --image 本地路径 或 --image-id 已上传的 id")

    # 3. 组装 payload 骨架；SKU/包裹/合规字段按你站点和类目实际要求补
    payload = {
        "title": a.title,
        "description": a.description or a.title,
        "category_id": int(a.category_id),
        "type": "PHYSICAL",
        "main_images": [image_id],
        "price": a.price,
        "package_weight": a.weight,
        "sku_infos": [
            {
                "id": "sku-1",
                "price": a.price,
                "inventory_type": "DROPSHIPPING",
                "sales_channel_infos": [{"region": a.region, "price": a.price}],
            }
        ],
    }
    if required:
        payload["_TODO_missing_attributes"] = required

    print("\n将要提交的 payload:\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if not a.yes:
        print("\n[dry-run] 未真正创建。核对无误后加 --yes 提交。")
        return
    print("\n提交中...")
    print(json.dumps(c.create_product(payload), ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(description="TikTok Shop 发布 demo")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("auth-url").set_defaults(func=cmd_auth_url)
    s = sub.add_parser("token"); s.add_argument("--code", required=True); s.set_defaults(func=cmd_token)
    sub.add_parser("cipher").set_defaults(func=cmd_cipher)
    sub.add_parser("refresh").set_defaults(func=cmd_refresh)
    sub.add_parser("shops").set_defaults(func=cmd_shops)

    s = sub.add_parser("categories")
    s.add_argument("--parent", default=""); s.add_argument("--category-version", default="v1")
    s.set_defaults(func=cmd_categories)

    s = sub.add_parser("attrs")
    s.add_argument("--category-id", required=True); s.add_argument("--category-version", default="v1")
    s.set_defaults(func=cmd_attrs)

    s = sub.add_parser("upload"); s.add_argument("--image", required=True); s.set_defaults(func=cmd_upload)

    s = sub.add_parser("create")
    s.add_argument("--category-id", required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--description", default="")
    s.add_argument("--image", default="")
    s.add_argument("--image-id", default="")
    s.add_argument("--price", type=float, required=True)
    s.add_argument("--weight", type=float, default=0.3)
    s.add_argument("--region", default="US")
    s.add_argument("--category-version", default="v1")
    s.add_argument("--yes", action="store_true", help="真正调用创建接口")
    s.set_defaults(func=cmd_create)

    a = p.parse_args()
    try:
        a.func(a)
    except TikTokShopError as e:
        print(f"\n[接口报错] {e}", file=sys.stderr)
        print("排查顺序：1) app_key/app_secret 是否有效 2) token 是否过期（跑 refresh）"
              "3) 签名是否用了与实发字节完全一致的 body（105xxx/36009xxx）", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
