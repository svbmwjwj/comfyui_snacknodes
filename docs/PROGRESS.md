# 开发记录与测试计划

最后更新：2026-11-01 · 分支：`claude/stoic-fermat-wano83`（尚未合并到 main）

## 已完成

1. **兼容性检查**：对照最新的 ComfyUI 后端和前端检查了旧节点，结论是旧节点能正常加载，但有几个功能 bug。
2. **下架旧节点**（提交 `eeed202`）：删除 Image Info、Image Scaler、Text Box、Text Processor 四个节点，README 里给出了对应的官方替代节点。
3. **新增 Save to Cloud Drive 节点**（提交 `cdbe497`，节点 ID 为 `SnackSaveToCloudDrive`，显示名不加图标）：
   - 支持 Google Drive（设备码授权，`drive.file` 权限，断点续传）
   - 支持阿里云盘（开放平台扫码授权，或用 `--refresh-token` 导入，分片上传）
   - 可选 Cryptomator 端到端加密（vault format 8）：可以新建保险库，也可以解锁已有保险库
   - 授权、建库、查看状态、退出登录都通过 `auth.py` 完成；凭据保存在 `~/.config/comfyui_snacknodes/cloud_drive.json`（权限 600）
   - 版本号改为 2.0.0

## 已做过的需求决策

- （2026-11-01 补充）`remote_folder` 支持日期变量（`%date:yyyy-MM%` 等），可以按日期自动归档
- （2026-11-01 补充）加密默认关闭。创建保险库时用户自己选择：输入密码，或自动生成密码。都会警告"密码是恢复文件的唯一方式"；自动生成的密码要输入最后一组确认已保存。不做恢复密钥
- （2026-11-01 补充）Google Drive 内置一个由项目方发布为正式版的公共 OAuth 客户端，用户只需运行 `auth.py google_drive` 并输入验证码；文件存在用户自己的 Drive、占用用户自己的空间。用户仍可通过参数或环境变量使用自己的客户端。项目方已在网页上把客户端 ID 和 secret 填入 `cloud_drive/google_drive.py`（提交 `b9ed3e8`）；同意屏幕已发布为正式版，首页和隐私政策都指向本仓库

- 只面向个人用户，不接入云厂商的对象存储（如 S3、GCS）
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

- **（2026-11-01 决定）先不发布，等阿里云盘也做好、测好后一起发布。** 在此之前不要合并到 main：合并后 `publish_action.yml` 会自动发布。发布时再决定两个发布流程保留哪一个

- **隐私政策链接**：Google 同意屏幕里的链接现在指向 `blob/claude/stoic-fermat-wano83/PRIVACY.md`，合并后要改成 `blob/main/PRIVACY.md`，否则删除分支后链接会失效

- 合并到 main 后，`publish_action.yml` 会自动把 2.0.0 发布到 Comfy Registry，发布后旧节点会消失
- `publish_action.yml` 和 `publish_node.yml` 是两个重复的发布流程，建议只保留一个
- 要从 Registry 真正下架或弃用旧版本，需要在 registry.comfy.org 的发布者后台手动操作

## 后续可能要做的

- 做一个 Comfy Cloud 同步工具：在节点外部运行，通过 Comfy Cloud API v2（`GET /api/v2/assets/{id}/content`）下载生成结果，再上传到网盘或保险库。注意结果有 `expires_at` 过期时间
- iCloud（非官方接口，国际账号）
- 夸克网盘（基于 Cookie 的非官方接口；也可以先通过 OpenList + WebDAV 使用）
- 腾讯网盘（等它开放接口或 MCP）
