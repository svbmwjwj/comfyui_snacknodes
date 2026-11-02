# 开发记录与测试计划

最后更新：2026-11-02 · **2.1.0 开发中：R2、节点内连接网盘** · **2.0.0 已发布到 Comfy Registry；项目主页上线，Google 品牌已验证**

## 已完成

0. **发布 2.0.0（2026-11-01）**：[PR #1](https://github.com/svbmwjwj/comfyui_snacknodes/pull/1) 合并到 main（合并提交 `5039246`），`publish_action.yml` 自动运行并成功上传到 Comfy Registry（此前 Registry 为 v1.0.1）。PR 上 `validate`（node-diff）失败：它加载 main 上的旧代码时缺少 torch；即使能加载，也只会报告 4 个旧节点被删除，属于有意的不兼容改动，PR 上已留言说明

1. **兼容性检查**：对照最新的 ComfyUI 后端和前端检查了旧节点，结论是旧节点能正常加载，但有几个功能 bug。
2. **下架旧节点**（提交 `eeed202`）：删除 Image Info、Image Scaler、Text Box、Text Processor 四个节点，README 里给出了对应的官方替代节点。
3. **新增 Save to Cloud Drive 节点**（提交 `cdbe497`，节点 ID 为 `SnackSaveToCloudDrive`，显示名不加图标）：
   - 支持 Google Drive（设备码授权，`drive.file` 权限，断点续传）
   - 支持阿里云盘（开放平台扫码授权，或用 `--refresh-token` 导入，分片上传）
   - 可选 Cryptomator 端到端加密（vault format 8）：可以新建保险库，也可以解锁已有保险库
   - 授权、建库、查看状态、退出登录都通过 `auth.py` 完成；凭据保存在 `~/.config/comfyui_snacknodes/cloud_drive.json`（权限 600）
   - 版本号改为 2.0.0

4. **2.1.0：S3 / Cloudflare R2 + README 重排（2026-11-02）**：
   - 新增 `cloud_drive/s3.py`：自己实现 AWS SigV4 签名（不引入 boto3），路径风格地址；`S3`（通用：AWS、B2、MinIO、Wasabi）和 `R2`（只需账户 ID，region `auto`）两个下拉选项
   - R2 默认 `limit_gb = 10`：每次运行先 ListObjectsV2 统计存储桶大小，超出就拒绝上传（错误码 `storage_limit`，中英文提示）；`--limit-gb 0` 关闭
   - 文件夹用 `prefix/` 空对象表示（和 AWS 控制台、rclone 一致），因此 Cryptomator 保险库可以放在 R2/S3 上；>64 MB 分片上传（16 MB 一片），失败时 AbortMultipartUpload
   - 可选 `--public-url`（r2.dev 或自定义域名），节点输出可直接打开的链接
   - 验证：签名与 AWS 文档测试向量及 botocore 输出逐字节一致；用 moto S3 服务端跑通上传、改名、12 MB 分片、上限、保险库读写。**尚未在真实 R2 账户上实测**
   - README 改为：居中标题 + 徽章、功能两栏、存储对比表、三步快速开始；各存储的授权步骤和加密细节折叠到 `<details>`
   - 用户已在本地用真实 R2 账户测试通过（2026-11-02）
5. **在节点上连接网盘（2026-11-02）**：用户反馈终端配置太麻烦。现在选好网盘后，节点上直接出现连接面板（`web/js/drive_setup.js`，DOM 小部件，`serialize: false` 不进工作流）：
   - R2 只要粘贴三项：存储桶「设置 → S3 API」地址（含账户 ID 和桶名，`parse_r2_url` 解析，支持 .eu/.fedramp 管辖区）、访问密钥 ID、机密；可选容量上限
   - WebDAV：地址、用户名、密码；Google Drive：一个「连接」按钮，节点上显示网址和验证码，后台线程等待授权，前端每 3 秒刷新
   - 后端 `cloud_drive/connect.py`（逻辑，可测试）+ `nodes/routes.py`（ComfyUI 的 aiohttp 路由 `/snacknodes/drive/...`）。凭据写入同一个凭据文件；状态接口只返回非机密信息（桶名、地址、用户名）
   - 已连接时显示「✓ 已连接」+ 概况，可「修改」「断开」（断开同时删除该网盘的保险库密钥）
   - 安全取舍：能打开 ComfyUI 网页的人就能改连接信息（但读不到密钥）；这和能直接运行任意工作流的权限相当
   - 保险库（加密）仍需在终端用 `auth.py vault-create` 创建
6. **只在节点里显示实测过的网盘**：下拉框只有 Google Drive、WebDAV、Cloudflare R2（`NODE_PROVIDERS`）。通用 S3 和阿里云盘代码保留，`auth.py` 仍可用，README 移到「实验性支持（待实测）」。注意：2.0.0 的工作流里如果选了 Aliyun Drive，打开后需要重新选择网盘
7. **显示名**：`DisplayName` 改为 `SnackNodes`。Registry 节点 ID `comfyui_snacknodes` 发布后不可修改（官方文档：name "Immutable after creation"；最佳实践是名称里不带 ComfyUI，但只是建议），所以 ID 不变

8. **用户本地实测反馈（2026-11-02，ComfyUI 0.43.2，前端 1.57.4，macOS，`comfy launch`，路径 `/Users/yuono/Developer/comfyui`）**：
   - 之前的 404：旧 ComfyUI 进程占着 8188 端口，新进程没起来。已加启动日志 `SnackNodes: drive setup routes ready` 和 404 时的中文提示（提交 `a0165b5`）。关掉旧进程后，R2 显示「✓ 已连接」，后端正常
   - **用户不满意的地方 1：连接面板的样式**。现在是 HTML 面板（`web/js/drive_setup.js`，DOM 小部件），而且节点被撑得很高、按钮被截断。用户要的是：选了某个网盘后，**直接在「网盘」下拉框下面展开几行原生控件**，样子和「网盘目录」那一行一样
   - **用户不满意的地方 2：节点上方的标签仍显示 `comfyui_snacknodes`**。查了前端源码（`getNodeSource` / `shortenNodeName`）：这个标签取自插件**文件夹名**（`custom_nodes/<文件夹>`），只会去掉大小写完全匹配的 `ComfyUI-`/`ComfyUI_`/`Comfy-`/`Comfy_` 前缀；`pyproject.toml` 的 `DisplayName` 只影响 Registry 和 Manager 的列表。从 Registry 安装时文件夹名就是节点 ID `comfyui_snacknodes`（不可改），所以**我们改不了这个标签**。用户自己可以在设置里关掉节点来源标签。如果一定要改，只能换一个新的 Registry ID（之前讨论过的代价：老用户收不到更新）。**这一点要先跟用户确认怎么处理**

### 下一步：把连接面板改成原生控件（新对话从这里开始）

已确认的前端行为（读的是 `comfyui_frontend_package` 1.57 的打包代码）：
- `serialiseWidgetValues` 会跳过 `widget.serialize === false` 的控件，并且同时保存 `widgets_values_named`（按名字）；生成 API prompt 时跳过 `options.serialize === false`。所以在「网盘」下面插入不保存的控件，不会打乱其他控件的值
- 但 `addCustomWidget` 推入后会按位置尝试恢复值：新加的控件要**立刻**设 `serialize = false` 并重置 value
- 前端源码里插入控件到中间位置是用 `node.widgets.splice(...)`，有的地方随后调用 `syncNodeWidgetOrder(node)`；需要在经典界面和 Nodes 2.0（Vue）界面都验证插入后能正常显示和刷新
- 前端支持原生的 `COMFY_DYNAMICCOMBO`（选项切换时展开子输入），但子输入是正常输入，**值会存进工作流**，密钥会泄露，所以不能直接用；凭据控件必须是前端自己加、`serialize: false` 的

计划：
1. 去掉 HTML 面板（DOM 小部件），改为在 provider 控件后面插入原生控件（`node.addWidget` 后 splice 到 provider 后面）：
   - R2：文本控件「S3 API 地址」「访问密钥 ID」「机密访问密钥」「容量上限（GB）」+ 按钮「连接」；提示放到控件 tooltip
   - WebDAV：「WebDAV 地址」「用户名」「密码」+「连接」
   - Google Drive：按钮「连接 Google Drive」；授权中显示按钮「打开 https://www.google.com/device」和「验证码 XXXX-XXXX（点击复制）」，每 3 秒刷新状态
   - 已连接：一行按钮「✓ 已连接：存储桶 xxx，上限 10 GB」，加「修改连接」「断开连接」
   - 出错用 ComfyUI 的 toast（`app.extensionManager.toast.add`），节点上留一行简短状态
   - 连接成功后清空密码/机密控件（原生文本控件不会遮盖密码，只在输入时可见）
2. 后端 `cloud_drive/connect.py`、`nodes/routes.py` 不用改
3. 测试：沙箱不允许运行外部下载的 ComfyUI，只能请用户在本地测（经典界面 + Nodes 2.0），步骤：节点目录 `git pull` → 停掉旧 ComfyUI（`lsof -ti tcp:8188 | xargs kill`）→ `comfy launch` → 浏览器 `Cmd+Shift+R`

## 已做过的需求决策

- （2026-11-01 补充）`remote_folder` 支持日期变量（`%date:yyyy-MM%` 等），可以按日期自动归档
- （2026-11-01 补充）加密默认关闭。创建保险库时用户自己选择：输入密码，或自动生成密码。都会警告"密码是恢复文件的唯一方式"；自动生成的密码要输入最后一组确认已保存。不做恢复密钥
- （2026-11-01 补充）Google Drive 内置一个由项目方发布为正式版的公共 OAuth 客户端，用户只需运行 `auth.py google_drive` 并输入验证码；文件存在用户自己的 Drive、占用用户自己的空间。用户仍可通过参数或环境变量使用自己的客户端。项目方已在网页上把客户端 ID 和 secret 填入 `cloud_drive/google_drive.py`（提交 `b9ed3e8`）；同意屏幕已发布为正式版，首页和隐私政策都指向本仓库

- ~~只面向个人用户，不接入云厂商的对象存储（如 S3、GCS）~~ → （2026-11-02 改为）接入 S3 兼容存储，并单独提供 Cloudflare R2 选项，用它每月 10 GB 免费存储、出口流量免费的额度
- 先做阿里云盘和 Google Drive，因为它们有官方接口
- （2026-11-01）**阿里云盘开放平台自 2025-07-01 起暂停个人开发者申请**（只接企业，需发邮件对接）。现有代码保留，只给已有开放平台应用的老开发者用；README 引导其他用户通过 OpenList 挂载后走 WebDAV
- （2026-11-01）**百度网盘开放平台同样已下线个人认证和个人创建应用**（已创建的个人应用不受影响，新申请只接企业认证），暂不接入。来源：贴吧官方回复、第三方接入指南；官方文档域名在本环境打不开，未能直接核对
- （2026-11-01）**新增通用 WebDAV**：一次覆盖坚果云、Nextcloud、NAS、OpenList（可中转阿里云盘、夸克、115 等）。Cryptomator 各端都原生支持 WebDAV，可以直接打开保险库
- （2026-11-01）发布计划：Google Drive 和 WebDAV 做好、测好后一起发布
- 夸克网盘和 iCloud 只能走非官方接口，暂缓。iCloud 是美区账号（以后可能换德区），都在国际服务器上，技术上可行
- 腾讯网盘还在内测，暂未发现公开接口，暂缓
- 网络问题由用户自己解决，工具遵循 `HTTPS_PROXY`
- 主要使用场景是 AutoDL。Comfy Cloud 不允许安装自定义节点，所以这个节点在 Comfy Cloud 上跑不了

## 已验证

- 79 个自动化测试全部通过（`pytest`，含 cryptofs 互通测试和 WebDAV 单元测试），`ruff check .` 无报错
- 用 Cryptomator 官方 Java 库 `cryptofs` 做了双向互通测试：本工具写的保险库，官方能逐字节正确解密；官方建的保险库，本工具能解锁并继续写入。这项测试已加入 CI
- 阿里云盘的上传类接口，已对照 OpenList 的 `aliyundrive_open` 驱动源码核对过
- **ComfyUI 实机测试通过（2026-11-01）**：在云端临时环境里装了最新版 ComfyUI（提交 `6d35280`，2026-10-31；前端 1.57.6；CPU 模式）。节点加载无报错，显示名、分类、下拉选项都正确；通过 API 和网页"运行"按钮分别执行了"Empty Image → Save to Cloud Drive（WebDAV）"，状态 success，图片按日期变量传到了 WebDAV，本地副本按 `filename_prefix` 存进 `output/snack/`，节点下方显示预览图。截图流程见 Playwright 脚本（未入库）
  - 发现：节点返回的上传结果文字（`ui.text`）在新前端里不会显示 → 已用前端扩展解决（见下）
- **节点界面改版（2026-11-01，按用户要求）**：
  - 中英双语：`locales/zh` 和 `locales/en` 的 nodeDefs.json，跟随 ComfyUI 语言设置切换节点名、参数名、悬停提示、节点说明；开关显示「开 on / 关 off」。测试会检查两种语言都覆盖了所有参数
  - 节点说明（DESCRIPTION）写清一次性设置命令和用法示例；网盘目录默认 `ComfyUI/%date:yyyy-MM-dd%`
  - 新增「预览」开关（默认开）
  - 布局：网盘 → 网盘目录 → 加密 → 预览 为常用项；文件名前缀、保留本地副本、额外上传文件 标为 advanced（Nodes 2.0 界面中折叠；经典画布不支持折叠，仍会显示）；额外上传文件 从大文本框改为输入接口
  - 上传结果：`web/js/save_to_cloud_drive.js` 在节点上显示「✅ 已上传 N 个文件」和每个文件的位置（加密的带 🔒），不写入工作流
  - 修复：节点带 VIDEO 输入，Nodes 2.0 界面会把图片预览当视频播放 →设 `previewMediaType = "image"`；节点默认宽度 480，避免英文下目录被截断
  - 已在 ComfyUI 最新版的经典画布和 Nodes 2.0 两种界面、中英文两种语言下截图核对
- **界面第二轮（2026-11-01，按用户反馈）**：
  - 名称不再中英混排，各语言只显示自己的（中文「保存到网盘」）；ComfyUI 搜索本身支持中英文检索。开关去掉自定义文字，用前端自带样式（Nodes 2.0 为拨动开关，经典画布为 true/false，与官方节点一致）
  - 「加密」从下拉框（none / Cryptomator vault，选项值无法翻译）改为开关 `encrypt`
  - 「保留本地副本」移出高级选项（Nodes 2.0 的「显示高级输入」按钮在预览图下方，容易漏看）；高级只留 文件名前缀、失败时停止
  - 进度：`comfy.utils.ProgressBar` 按所有文件的总字节数推进，`send_progress_text` 在节点上显示 `2/3 · 文件名 · 12.0/15.2 MB`（与语言无关）。各网盘的 upload_file 都支持 progress 回调（Google 按 8 MiB 分块、WebDAV 按读取字节、阿里云盘按分片、加密按密文比例）
  - 新增布尔输出「成功」和高级选项「失败时停止」（默认开）：关掉后上传失败不中断工作流，成功 = false，节点上显示 ❌ 和原因
  - 实测：60 MB 文件上传时节点显示进度文字、任务面板显示节点进度；制造失败（目标路径是文件）时工作流继续、节点显示 ❌
- **错误提示翻译（2026-11-01）**：`cloud_drive/errors.py` 按 HTTP 状态码、响应内容和异常类型把失败归为 12 类（未授权、密码错误、无权限、目录冲突、找不到、空间不足、文件过大、限流、服务器错误、网络、未建保险库、本地文件），每类有中英文的原因和解决办法；原始技术信息保留在下方
  - `CloudDriveError` 新增 `status`、`body`、`network` 字段，重试用尽后保留最后的状态码，或标记为网络错误；WebDAV 的 403 不再误判为授权问题
  - 「失败时停止」开启时：抛出的错误按 ComfyUI 界面语言（读 `user/default/comfy.settings.json` 的 `Comfy.Locale`；读不到时中英文都给）；新版前端的「作业失败」提示一闪即逝，所以前端扩展还会监听 `execution_error`，把同样的说明写到节点上
  - 实测：目录冲突（关闭失败时停止）中英文界面各一次；断开网盘服务制造网络错误（开启失败时停止），节点上显示中文原因和解决办法
- **WebDAV 实测通过（2026-11-01）**，测了 4 种服务端实现，每种都跑同一套流程（脚本流程：连接测试 → 明文上传两次 → 新建保险库并加密上传 → 解锁官方 cryptofs 建的保险库并继续写入；保险库都通过 WebDAV 下载回来，交给官方 `cryptofs` 校验 SHA-256）：

  | 服务端 | 代表的真实场景 | 结果 |
  |---|---|---|
  | WsgiDAV 4.4（Python） | 通用 | ✅ |
  | Nextcloud（Docker 官方镜像，sabre/dav，使用应用密码） | Nextcloud / ownCloud | ✅ |
  | Apache 2.4 mod_dav | 群晖等 NAS 自带的 WebDAV、自建服务器 | ✅ |
  | rclone serve webdav（Go `x/net/webdav`） | OpenList / AList（同一套 Go WebDAV 库） | ✅ |

  - 每种都验证了：密码错误时有友好提示；中文、空格目录和日期变量正常；同名文件自动改为 `_1`、不覆盖；内容逐字节一致；两个方向的保险库互通
  - 1 GB 文件流式上传（rclone）：7.6 秒，进程内存峰值 27 MB，内容一致
  - 实测中发现并修复了一个 bug：**密码含中文等非 Latin-1 字符时程序崩溃**（requests 默认按 latin-1 编码 Basic 认证），现在统一按 UTF-8 发送
  - 没测到的：坚果云本身（没有账号）。坚果云的已知限制是免费版有请求频率上限，工具会自动重试
- **Google Drive 实测通过（2026-11-01）**：
  - 设备码授权成功。首次授权报"尚未完成 Google 验证流程"（403 access_denied），原因是同意屏幕处于"测试中"，且账号不在测试用户名单里；把账号加为测试用户（或发布为正式版）后就能通过，代码不用改
  - 普通上传：通过节点上传 1 张 PNG（804 B，带 prompt 元数据）和 1 个 MP4（15.2 MB，按 8 MiB 分块，共 2 块，走断点续传），都返回了分享链接；下载回来逐字节一致，md5 与 Drive 记录的相同，MIME 类型正确，目录 `ComfyUI-Test/plain` 自动创建
  - 再次上传到同一目录：沿用已有文件夹，不会重复建；同名文件会多出一份（Drive 允许重名，这是预期行为）
  - **内置客户端从零开始测试**：去掉环境变量，使用空的凭据目录，直接运行 `auth.py google_drive`（不带任何参数），一次授权通过，没有再出现"尚未完成 Google 验证流程"。之后的普通上传（`ComfyUI-Test/%date:yyyy-MM%` 展开为 `2026-11`）、按交互流程创建保险库（选择自动生成密码，并输入最后一组确认）、加密上传（`ComfyUI/%date:yyyy-MM-dd%`）都通过，官方 `cryptofs` 解密后的 SHA-256 与原文件一致
  - 加密上传：`vault-create` 在 Drive 上建了 `ComfyUI-Vault-Test`，通过节点上传到 `ComfyUI/enc-test`；把整个保险库下载到本地后，用官方 `cryptofs` 解密，目录结构和两个文件的 SHA-256 都与原文件一致

## 还没验证（待测试）

| 项目 | 阻碍 | 需要准备什么 |
|---|---|---|
| 坚果云真实上传（可选，没有账号可跳过） | 环境网络策略需放行 `dav.jianguoyun.com` | 坚果云账号和应用密码（设到环境变量 `SNACK_WEBDAV_URL`、`SNACK_WEBDAV_USERNAME`、`SNACK_WEBDAV_PASSWORD`）；之后用手机 Cryptomator 添加 WebDAV 打开保险库 |
| 阿里云盘真实授权和上传（降级为可选） | 环境网络策略拦截了相关域名 | 在环境设置里放行 `openapi.alipan.com`、`*.aliyundrive.net`、`*.alipan.com`；准备开放平台应用的 client_id 和 secret |
| 阿里云盘扫码授权接口 | 官方文档（语雀）在当前环境打不开，OpenList 源码里也没有这个接口 | 实测时验证；失败就改用 `--refresh-token` |
| 用 Cryptomator App 打开 Google Drive 上的保险库 | 需要真机 | 在手机上安装 Cryptomator，添加 Google Drive |

## 测试前的环境配置（在云环境设置里完成，不要把密钥贴进聊天）

在会话标题栏的云环境菜单 → 编辑（Edit）中设置：

- 环境变量：`SNACK_GDRIVE_CLIENT_ID`、`SNACK_GDRIVE_CLIENT_SECRET`
- 阿里云盘（可选）：环境变量 `SNACK_ALIYUNDRIVE_CLIENT_ID`、`SNACK_ALIYUNDRIVE_CLIENT_SECRET`，并在网络访问里放行 `openapi.alipan.com`、`*.aliyundrive.net`、`*.alipan.com`

改完后要开一个新会话才会生效。新会话里先读本文件，然后从"测试步骤"开始。

## 测试步骤（准备好后照做）

1. **Google Drive**：✅ 已完成（见"已验证"）。还剩两项：用手机 Cryptomator 打开 `ComfyUI-Vault-Test` 核对；测完后删除测试用的 OAuth 客户端，并执行 `auth.py logout google_drive`
2. **WebDAV**：4 种服务端都已测通（见"已验证"）。如果以后有坚果云账号：放行 `dav.jianguoyun.com` 并配好环境变量后，用真实坚果云再测一遍，并用手机 Cryptomator（添加 WebDAV）打开保险库
3. **阿里云盘**（可选，需要已有开放平台应用）：放行域名之后，按同样的流程测一遍
4. **ComfyUI 实机**：✅ 已完成（见"已验证"）。如有条件，在 AutoDL 上用真实模型和 GPU 再跑一次

## 合并前注意

- **发布方式（2026-11-01 决定）**：只保留官方推荐的 `publish_action.yml`（Comfy-Org/publish-node-action 的示例），已删除 `publish_node.yml`。规则：main 分支上 `pyproject.toml` 有改动就发布其中的版本号；不改版本号不会发新版。发布失败时可在 Actions 页面手动 Run workflow 重发
- **版本号**：Registry 上当前是 v1.0.1（用户确认，2026-11-01）；本次发布用 2.0.0（删除旧节点属于不兼容改动）
- **发布密钥**：仓库只跑过一次发布流程（2026-05-05，失败），很可能缺少 `REGISTRY_ACCESS_TOKEN`。配置方法：在 registry.comfy.org 的发布者 svbmwjwj 页面创建 API Key，再到 GitHub 仓库 Settings → Secrets and variables → Actions → New repository secret，名称填 `REGISTRY_ACCESS_TOKEN`

- ~~合并即发布~~（已完成）：Google Drive、WebDAV 和界面都已测完（阿里云盘因开放平台不再接受个人开发者，改为可选）。合并到 main 就会自动发布 2.0.0，合并前确认 `REGISTRY_ACCESS_TOKEN` 已配好。
- **隐私政策链接**：Google 同意屏幕里的链接现在指向 `blob/claude/stoic-fermat-wano83/PRIVACY.md`，合并后要改成 `blob/main/PRIVACY.md`，否则删除分支后链接会失效

- **项目主页与 Google 品牌验证（2026-11-01 完成）**：Google 修改品牌信息时要求品牌验证，`github.com` 无法证明归属，于是改用项目方自己的域名。主页 `https://snacknodes.linksluckytime.com/`，隐私政策 `https://snacknodes.linksluckytime.com/privacy.html`，由 GitHub Pages 托管 `docs/` 目录（`main` / `/docs`，`docs/CNAME`）。域名 `linksluckytime.com` 已在 Search Console 验证；**Google OAuth 品牌已验证并发布**，用户授权时会看到应用名称「ComfyUI SnackNodes」
  - DNS 里的 TXT 记录（`google-site-verification=...`）和 CNAME（`snacknodes` → `svbmwjwj.github.io`）要一直保留，删掉会导致验证失效或主页打不开
  - 名称约定：Registry 节点 ID 和 GitHub 仓库名固定为 `comfyui_snacknodes`；Google 应用名称 `ComfyUI SnackNodes`，主页标题与之一致（品牌验证会核对）；品牌名 SnackNodes
  - 开发分支 `claude/stoic-fermat-wano83` 已不再被任何外部链接引用，可以删除
- 要从 Registry 真正下架或弃用旧版本，需要在 registry.comfy.org 的发布者后台手动操作

## 后续可能要做的

- ~~**下次发版时一起改**~~（2.1.0 已改为 `SnackNodes`）：`pyproject.toml` 的 `DisplayName`（Registry 页面显示的名字）从 `comfyui_snacknodes` 改为 `SnackNodes` 或 `ComfyUI SnackNodes`；节点 ID `name = "comfyui_snacknodes"` 不变。单独改 `pyproject.toml` 会在合并时触发发布，所以和版本号（如 2.0.1）一起改
- **修复 `validate`（node-diff）检查**：它不安装依赖就加载 base 分支的 `__init__.py`，目前因顶层导入 numpy/PIL/requests/cryptography 而必定失败。办法是把这些依赖改为按需导入（已在 PR #2 留言说明）

- 做一个 Comfy Cloud 同步工具：在节点外部运行，通过 Comfy Cloud API v2（`GET /api/v2/assets/{id}/content`）下载生成结果，再上传到网盘或保险库。注意结果有 `expires_at` 过期时间
- iCloud（非官方接口，国际账号）
- 夸克网盘（基于 Cookie 的非官方接口；也可以先通过 OpenList + WebDAV 使用）
- 腾讯网盘（等它开放接口或 MCP）
