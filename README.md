# TikTok Shop 海外开放平台 · 商品发布最小 demo

自研签名 + 授权客户端，不依赖官方 SDK，覆盖：注册开发者 → 建 Custom App → 换 token → 取 shop_cipher → 类目属性 → 传图 → 创建商品。

## 验证状态

| 项 | 状态 | 依据 |
|---|---|---|
| token 端点 `auth.tiktok-shops.com/api/v2/token/get` | ✅ 真实可达 | 实测返回 `36004004 invalid auth code`，链路通 |
| API 端点 `open-api.tiktokglobalshop.com` | ✅ 真实可达 | 实测能正确解析 `app_key` query 参数 |
| HMAC-SHA256 签名计算 | ✅ 交叉验证 | 与 .NET 独立实现逐字节比对一致 |
| string-to-sign 构造规则 | ✅ 双重来源 | 参照可工作的第三方客户端转写，且与官方 `Sign your API request` 章节一致 |
| 授权域名 / `service_id` / token 字段 | ✅ 官方文档核对 | Developer Guide → Authorization overview |
| **端到端签名被服务端接受** | ⚠️ **未验证** | 需真实 `app_key`；假 key 在 app_key 校验就被拒 |
| **create 完整 payload 字段** | ⚠️ **未验证** | 必填项随站点/类目变，代码只给骨架 |

## 接入流程（官方文档口径）

### 阶段一：拿到 app_key / app_secret

**前置门槛（这几条卡住最多人，先自查）**
- 卖家账号已通过 **KYB/KYC** 审核
- 卖家账号**已分配 Account Manager (AM)** —— AM 不能自己申请，平台按站点/类目/GMV/店铺表现指派，没有就走 Seller Center 帮助中心提工单申请 AM 资格评审
- 必须用**卖家 owner 主账号**，子账号不行
- 验证邮箱要和**注册店铺时用的邮箱一致**
- 一个卖家账号只能绑一个 Partner Center 账号
- ⚠️ **卖家开发者必须过合规安全审核 + App 功能审核**，表单要用英文如实填写。**连续三次被拒会直接封号**
- ⏱️ 美区/英区合规审核官方口径是 **3 周以上**，提前排期

**操作步骤**
1. 注册账号：美区 `partner.us.tiktokshop.com/account/sign-up`，其他 `partner.tiktokshop.com/account/sign-up`
2. 业务指引里选 **For TikTok Shop Seller** → Start Business
3. 目标市场/业务类目都选 **TikTok Shop Seller**
4. 用卖家账号验证并绑定
5. **App & Service → Create app & service** → 选 **Custom App**（不上架应用商店，只给自己店用）
6. 打开 **Enable API** 开关，填 **Redirect URL**（接收 `code` 的回跳地址），Webhook URL 可选
7. 点 Create → App 详情页即可看到 **App key / App secret / service_id**
8. 需要先在 **Access scope** 里勾选商品相关权限，否则 `granted_scopes` 会是空的
9. App 建好不能删，只能 deactivate，且 deactivate 后不能重新上线 —— 名字和配置想清楚再建

### 阶段二：授权换 token

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
copy .env.example .env     # 填 APP_KEY / APP_SECRET / SERVICE_ID / REGION
```

```bash
# 1. 生成授权链接（更省事的是直接在 App 详情页复制）
.venv/Scripts/python.exe demo_publish.py auth-url

# 2. 店铺管理员打开链接点同意 → 回跳 URL 上的 code → 换 token
.venv/Scripts/python.exe demo_publish.py token --code <code>

# 3. 取 shop_cipher（token 响应里没有这个字段）
.venv/Scripts/python.exe demo_publish.py cipher

# 4. 验证签名真的被接受：这一步通了就说明鉴权全链路 OK
.venv/Scripts/python.exe demo_publish.py shops
```

### 阶段三：发布商品

```bash
.venv/Scripts/python.exe demo_publish.py categories --parent 0
.venv/Scripts/python.exe demo_publish.py attrs --category-id <叶子类目ID>
.venv/Scripts/python.exe demo_publish.py create --category-id <ID> \
  --image ..\img_ec\output\xxx\candidate_1.png \
  --title "Shiba Inu Surfing T-Shirt" --price 9.99
# 默认 dry-run，核对 payload 后加 --yes 才真正提交
```

### 测试环境

官方有 **Development Shop**（前身叫 Sandbox），可以模拟卖家流程不动真实店铺数据；另有 **API Testing Tool** 可直接在 Partner Center 里发请求看参数。建议先在 Development Shop 上把 `create` 跑通再碰生产店。

签名自检（无网络依赖）：`.venv/Scripts/python.exe test_signature.py`

## 关键实现要点

- **授权域名分市场、用 `service_id` 不用 `app_key`**：
  - 美区 `https://services.us.tiktokshop.com/open/authorize?service_id={sid}`
  - 其他 `https://services.tiktokshop.com/open/authorize?service_id={sid}`
  - token 端点全市场共用 `auth.tiktok-shops.com`
- **`grant_type=authorized_code` 是官方刻意拼错的写法**，不要"修正"成标准 OAuth 的 `authorization_code`，否则请求失败
- **`auth_code` 30 分钟过期且只能用一次**；用户拒绝时回跳是 `code=null&error=auth_denied`
- **`access_token` 默认 7 天有效**，走请求头 `x-tts-access-token`，不是 query 参数
- **`shop_cipher` 不在 token 响应里**，要调 `/authorization/202309/shops` 取；refresh 响应里也没有，代码已做合并保护
- 签名步骤：除 `sign`/`access_token` 外的 query 按 key 字典序排 → 拼 `{key}{value}` → **path 放最前** → 非 GET 且非 multipart 时**原始 body 放最后** → 前后各包一层 `app_secret` → 以 `app_secret` 为密钥 HMAC-SHA256，hex 输出
- **签名用的 body 必须和实发字节完全一致**：`json.dumps` 一次，签名和发送复用同一 bytes。中文转义或空格格式不同都会导致 `105xxx`
- `shop_cipher` 在 `images/upload`、`files/upload`、`compliance`、`authorization`、`seller` 接口**不允许携带**，代码按路径前缀排除
- refresh 会下发**新的 refresh_token**，必须一起覆盖保存
- 图片不能给外链，先 `images/upload` 换平台内部 media id
- Custom App **只能授权绑定 1 个店**（自己的店）
- 已有卖家账号的人**不能再注册 ISV**，只能走卖家开发者
- API 版本默认 `202309`

## 你必须自己确认的两件事

1. **创建商品的完整字段**。`create` 只组装了 title / description / category_id / main_images / price / package_weight / sku_infos 骨架，必填属性列在 `_TODO_missing_attributes` 里提示你补。SKU、包裹尺寸、区域价格、GPSR/责任人合规字段要按 `attrs` 实际返回和官方文档填。
2. **美区可用性**。2025 年 TikTok US 业务重组后接口范围有变动，以你后台实际能申请到的权限包为准。

## 支持渠道

- 美区问题：`partner.us.tiktokshop.com/ticket/center`
- 非美区：`partner.tiktokshop.com/ticket/center`
- 文档站每页右上角有「下载 Markdown」按钮，比复制网页方便

## 文件

- `tts_client.py` — 客户端（授权、签名、商品接口）
- `demo_publish.py` — CLI，跑通整条链路
- `test_signature.py` — 签名自检
- `.env` / `tokens.json` — 含密钥，已在 `.gitignore`，勿提交
