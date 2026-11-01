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

- 只面向个人用户，不接入云厂商的对象存储（如 S3、GCS）
- 先做阿里云盘和 Google Drive，因为它们有官方接口
- 夸克网盘和 iCloud 只能走非官方接口，暂缓。iCloud 是美区账号（以后可能换德区），都在国际服务器上，技术上可行
- 腾讯网盘还在内测，暂未发现公开接口，暂缓
- 网络问题由用户自己解决，工具遵循 `HTTPS_PROXY`
- 主要使用场景是 AutoDL。Comfy Cloud 不允许安装自定义节点，所以这个节点在 Comfy Cloud 上跑不了

## 已验证

- 35 个自动化测试全部通过（`pytest`），`ruff check .` 无报错
- 用 Cryptomator 官方 Java 库 `cryptofs` 做了双向互通测试：本工具写的保险库，官方能逐字节正确解密；官方建的保险库，本工具能解锁并继续写入。这项测试已加入 CI
- 阿里云盘的上传类接口，已对照 OpenList 的 `aliyundrive_open` 驱动源码核对过

## 还没验证（待测试）

| 项目 | 阻碍 | 需要准备什么 |
|---|---|---|
| Google Drive 真实授权和上传 | 无，当前环境能连上 Google | 一个测试用的 OAuth 客户端（类型选"电视和受限输入设备"，同意屏幕设为"正式版"），提供 client ID 和 secret |
| 阿里云盘真实授权和上传 | 环境网络策略拦截了相关域名 | 在环境设置里放行 `openapi.alipan.com`、`*.aliyundrive.net`、`*.alipan.com`；准备开放平台应用的 client_id 和 secret |
| 阿里云盘扫码授权接口 | 官方文档（语雀）在当前环境打不开，OpenList 源码里也没有这个接口 | 实测时验证；失败就改用 `--refresh-token` |
| 用 Cryptomator App 打开 Google Drive 上的保险库 | 需要真机 | 在手机上安装 Cryptomator，添加 Google Drive |
| 在真实 ComfyUI 中加载节点、执行工作流 | 权限策略拦截了"安装并运行外部 ComfyUI 代码" | 二选一：授权在当前环境安装 ComfyUI；或在 AutoDL 上 clone 这个分支，把启动日志发过来 |

## 测试前的环境配置（在云环境设置里完成，不要把密钥贴进聊天）

在会话标题栏的云环境菜单 → 编辑（Edit）中设置：

- 环境变量：`SNACK_GDRIVE_CLIENT_ID`、`SNACK_GDRIVE_CLIENT_SECRET`
- 阿里云盘（可选）：环境变量 `SNACK_ALIYUNDRIVE_CLIENT_ID`、`SNACK_ALIYUNDRIVE_CLIENT_SECRET`，并在网络访问里放行 `openapi.alipan.com`、`*.aliyundrive.net`、`*.alipan.com`

改完后要开一个新会话才会生效。新会话里先读本文件，然后从"测试步骤"开始。

## 测试步骤（准备好后照做）

1. **Google Drive**：运行 `python auth.py google_drive --client-id … --client-secret …`，在手机上输入验证码
   - 普通上传：上传一张图片和一个视频，检查返回的分享链接
   - 加密上传：运行 `auth.py vault-create google_drive --path ComfyUI-Vault-Test`，用节点逻辑上传，再用手机 Cryptomator 打开核对
   - 测完：删除测试用的 OAuth 客户端，执行 `auth.py logout google_drive`
2. **阿里云盘**：放行域名之后，按同样的流程测一遍，另外测一次 `vault-unlock` 解锁已有保险库
3. **ComfyUI 实机**：确认节点能出现在节点列表里，并跑通一次"生成图片 → 上传"

## 合并前注意

- 合并到 main 后，`publish_action.yml` 会自动把 2.0.0 发布到 Comfy Registry，发布后旧节点会消失
- `publish_action.yml` 和 `publish_node.yml` 是两个重复的发布流程，建议只保留一个
- 要从 Registry 真正下架或弃用旧版本，需要在 registry.comfy.org 的发布者后台手动操作

## 后续可能要做的

- 做一个 Comfy Cloud 同步工具：在节点外部运行，通过 Comfy Cloud API v2（`GET /api/v2/assets/{id}/content`）下载生成结果，再上传到网盘或保险库。注意结果有 `expires_at` 过期时间
- iCloud（非官方接口，国际账号）
- 夸克网盘（基于 Cookie 的非官方接口）
- 腾讯网盘（等它开放接口或 MCP）
