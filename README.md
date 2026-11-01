# SnackNodes 🍿

**Save to Cloud Drive**：把 ComfyUI 生成的图片、视频或文件直接上传到你自己的 **Google Drive** 或任意 **WebDAV** 网盘/服务器（坚果云、Nextcloud、群晖等 NAS、OpenList/AList……）。可选**端到端加密**，加密格式与 [Cryptomator](https://cryptomator.org) 保险库完全兼容，网盘服务商看不到文件内容和文件名。

适合在 AutoDL 等租卡平台、或任何远程 GPU 服务器上运行 ComfyUI 的个人用户。

## 功能

- 接收 `images`、`video`，或 output 目录中已有文件的路径（`file_paths`，一行一个）
- 可选在本地保留一份副本，也可以只用临时目录
- 远程文件夹可以自己设置，不存在时会自动创建；支持日期变量，例如 `ComfyUI/%date:yyyy-MM%` 会自动按月归档（详见下文）
- 输出上传结果：Google Drive 返回分享链接；其他网盘和加密文件返回 `provider:路径`
- 不会覆盖网盘上已有的文件：WebDAV 和保险库里同名文件会自动加 `_1`、`_2` 后缀
- 凭据和密钥**不会写进工作流**，分享工作流不会泄露账号
- 分片上传，网络错误或限流时自动重试；Google Drive 支持断点续传
- 网络代理：遵循标准的 `HTTPS_PROXY` 环境变量，网络问题需要用户自行解决

## 节点界面

节点名「保存到网盘」（英文界面为 Save to Cloud Drive），界面语言跟随 ComfyUI 的语言设置；搜索时中英文名称都能搜到。悬停在每一项上可以看到说明，节点说明（右键 → 节点信息，或右侧面板）里有完整用法。

| 项目 | 默认值 | 说明 |
|---|---|---|
| 图像 / 视频（输入） | — | 连上要上传的图片和/或视频 |
| 额外上传文件（输入） | — | 可选：连一个文本节点，列出 output 目录里已有的文件，一行一个 |
| 网盘 | Google Drive | Google Drive / WebDAV / Aliyun Drive |
| 网盘目录 | `ComfyUI/%date:yyyy-MM-dd%` | 按日期自动分文件夹，可改 |
| 加密 | 关 | 开启后用 Cryptomator 保险库格式端到端加密 |
| 预览 | 开 | 运行后在节点上显示图片；不需要可以关掉 |
| 保留本地副本 | 开 | 关掉则只放在临时目录 |
| 文件名前缀（高级） | `ComfyUI` | 本地副本的文件名，可带子目录 |
| 失败时停止（高级） | 开 | 关掉后上传失败不会中断工作流，而是让「成功」输出 false |

**输出**：「上传结果」（每个文件一行：分享链接或 `网盘:路径`）和「成功」（布尔值，全部上传成功为 true），可以接到其他节点做自动化，例如失败时走另一条分支。

**上传过程中**：节点上显示进度条和当前文件，例如 `2/3 · video.mp4 · 12.0/15.2 MB`。**完成后**：显示「✅ 已上传 N 个文件」和每个文件的位置（加密的带 🔒）；失败时显示「❌ 上传失败」和原因。

在 Nodes 2.0 界面中，高级选项默认折叠，点节点底部的「显示高级输入」展开。

## 安装

放进 `ComfyUI/custom_nodes/comfyui_snacknodes`，然后安装依赖：

```bash
pip install -r custom_nodes/comfyui_snacknodes/requirements.txt
```

依赖只有 `requests` 和 `cryptography`。

## 一次性授权

以下命令都在**运行 ComfyUI 的那台机器**上执行（比如 AutoDL 的终端），在 ComfyUI 根目录下运行。

### Google Drive

运行下面的命令，按提示在手机或电脑上打开网址、输入验证码，再用你自己的 Google 账号登录并同意授权即可：

```bash
python custom_nodes/comfyui_snacknodes/auth.py google_drive
```

- 文件上传到**你自己的 Google Drive**，占用你自己的空间。本项目内置的 OAuth 客户端只用来标识这个应用，本身访问不了任何人的 Drive。
- 只申请 `drive.file` 权限：本工具**只能看到它自己创建的文件和文件夹**，读不到你 Drive 里的其他任何内容。详见[隐私政策](PRIVACY.md)。

<details>
<summary>进阶：使用你自己的 OAuth 客户端</summary>

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)，新建项目并启用 **Google Drive API**。
2. 配置 OAuth 同意屏幕：用户类型选"外部"，发布状态改为 **"正式版（In production）"**。`drive.file` 是非敏感权限，发布不需要经过 Google 审核。如果停留在"测试"状态，未加入测试用户的账号会被拒绝（提示"尚未完成 Google 验证流程"），而且 refresh token 每 7 天就会失效。
3. 在"凭据"页面创建 OAuth 客户端 ID，应用类型选 **"电视和受限输入设备"（TVs and Limited Input devices）**。
4. 运行 `auth.py google_drive --client-id 你的ID --client-secret 你的Secret`，或者设置环境变量 `SNACK_GDRIVE_CLIENT_ID` / `SNACK_GDRIVE_CLIENT_SECRET`。

</details>

### WebDAV（坚果云、Nextcloud、NAS、OpenList……）

```bash
python custom_nodes/comfyui_snacknodes/auth.py webdav --url https://dav.jianguoyun.com/dav/ --username 你的账号
```

按提示输入密码。工具会先连一次服务器，确认地址和密码正确后才保存。

| 服务 | 地址 | 密码 |
|---|---|---|
| 坚果云 | `https://dav.jianguoyun.com/dav/` | 在 账户信息 → 安全选项 → 第三方应用管理 里生成的**应用密码**，不是登录密码 |
| Nextcloud / ownCloud | `https://你的域名/remote.php/dav/files/用户名/` | 建议在 设置 → 安全 里生成应用密码 |
| 群晖 / 威联通等 NAS | 在 NAS 上开启 WebDAV 服务后的地址 | NAS 账号密码 |
| OpenList / AList | `https://你的域名/dav/` | OpenList 用户密码。可借它把阿里云盘、夸克、115 等挂载出来再上传 |

- 尽量使用 `https://`。用 `http://` 连接非本机地址时，密码会明文传输，工具会给出警告。
- 坚果云免费版有 WebDAV 请求次数限制（每 30 分钟约 600 次），大批量上传时可能会被限流，工具会自动重试。

### 阿里云盘（仅限已有开放平台应用的开发者）

> 阿里云盘开放平台自 2025 年 7 月 1 日起**暂停个人开发者申请**。只有已经注册过开放平台应用的开发者才能用这种方式；其他用户请用 OpenList 挂载阿里云盘，再按上面的 WebDAV 方式连接。

```bash
python custom_nodes/comfyui_snacknodes/auth.py aliyundrive --client-id 你的ID --client-secret 你的Secret
```

运行后打开输出的二维码链接，用阿里云盘 App 扫码确认。如果扫码授权失败，可以加上 `--refresh-token 你的token`，直接导入一个已有的 refresh token。

默认上传到"资源库"。如果想传到"备份盘"，在凭据文件的 `aliyundrive` 项中加上 `"drive": "backup"`。

### 查看状态和退出登录

```bash
python custom_nodes/comfyui_snacknodes/auth.py status
```

```bash
python custom_nodes/comfyui_snacknodes/auth.py logout google_drive
```

凭据保存在 `~/.config/comfyui_snacknodes/cloud_drive.json`，文件权限为 600。可以用 `SNACKNODES_CONFIG_DIR` 环境变量修改位置。
也可以不用凭据文件，改用环境变量：`SNACK_GDRIVE_CLIENT_ID` / `SNACK_GDRIVE_CLIENT_SECRET` / `SNACK_GDRIVE_REFRESH_TOKEN`；WebDAV 对应 `SNACK_WEBDAV_URL` / `SNACK_WEBDAV_USERNAME` / `SNACK_WEBDAV_PASSWORD`；阿里云盘对应 `SNACK_ALIYUNDRIVE_*`。

## 远程文件夹与日期变量

节点的 `remote_folder` 填网盘上的目录，可以有多层，例如 `ComfyUI/portraits`；开启加密时，它是保险库内部的路径。`remote_folder` 和 `filename_prefix` 都支持以下变量（按服务器本地时间）：

| 写法 | 示例结果 |
|---|---|
| `%date:yyyy-MM-dd%` | `2026-11-01`（可用 `yyyy` `yy` `MM` `dd` `hh` `mm` `ss` 自由组合） |
| `%year%` `%month%` `%day%` `%hour%` `%minute%` `%second%` | `2026` `11` `01` … |

例如 `ComfyUI/%date:yyyy-MM%/%date:dd%` 会按月建文件夹，月份下面再按日期分子文件夹。本地副本的位置由 `filename_prefix` 决定（写法和官方 Save Image 节点相同，如 `子目录/前缀`）。

## 端到端加密（Cryptomator 保险库）

在节点上把 `encryption` 设为 **Cryptomator vault** 后，文件会**先在本机加密，再上传**：

- **文件内容**：AES-256-GCM，每 32 KiB 一个分块，每块都有完整性校验，被篡改或损坏会被发现
- **文件名和文件夹名**：AES-SIV 加密，网盘上只能看到 `d/XX/YYYY…/xxxx.c9r` 这样的乱码
- **密码**：经过 scrypt 派生密钥，用来包裹主密钥

这就是 Cryptomator 的保险库格式（vault format 8），所以你可以用 **Cryptomator 官方客户端（桌面端、iOS、Android）** 直接打开、浏览和解密，不依赖本工具。
兼容性已经用 Cryptomator 官方的 Java 库 `cryptofs` 双向验证过，CI 每次都会重跑这项测试：本工具写的保险库，官方能逐字节正确解密；官方创建的保险库，本工具也能解锁并继续写入。

加密**默认关闭**，需要先创建保险库，再在节点上打开。

### 创建或解锁保险库

```bash
python custom_nodes/comfyui_snacknodes/auth.py vault-create google_drive --path ComfyUI-Vault
```

创建时可以选择：

- **[1] 自己输入密码**（至少 8 位，需要输入两次）
- **[2] 自动生成强密码**：例如 `k7mpq-x3wfa-…`，共 6 组，约 148 位强度，不含 0/O、1/l 这类容易混淆的字符。生成后需要你输入最后一组来确认已保存，确认后才会创建保险库

也可以直接加 `--generate-password` 或 `--own-password` 跳过选择。

如果 WebDAV（或阿里云盘）上已经有一个用 Cryptomator App 创建的保险库，用这个命令解锁，之后节点会往里面继续写入：

```bash
python custom_nodes/comfyui_snacknodes/auth.py vault-unlock webdav --path 我的保险库
```

> ⚠️ **密码是恢复文件的唯一方式。** 没有找回、重置或恢复密钥，请立即存进密码管理器。本工具不保存密码，只在本机保存解锁后的密钥。

### 用 Cryptomator 打开

| 网盘 | 打开方式 |
|---|---|
| Google Drive | Cryptomator iOS/Android 版直接添加 Google Drive；或者在桌面端用 Google Drive 客户端同步到本地后，用 Cryptomator 桌面版打开 |
| WebDAV | Cryptomator 各平台都原生支持 WebDAV：添加 WebDAV，填同样的地址、账号和密码即可直接打开 |
| 阿里云盘 | Cryptomator 没有内置阿里云盘。可以把保险库文件夹下载到本地后用桌面版打开；或者用 OpenList/AList 把阿里云盘挂载成 WebDAV，再在 Cryptomator 里添加 WebDAV |

### 限制与注意事项

- **Google Drive 只能使用本工具创建的保险库。** 因为 `drive.file` 权限看不到其他应用创建的文件。WebDAV 和阿里云盘没有这个限制。
- **在 Google Drive 上，需要上传的文件夹请让节点自己创建。** 如果你先在 Cryptomator App 里建了同名文件夹，本工具看不到它，会再建一个同名的，导致保险库里出现两个重名文件夹。
- **加密不会隐藏这些信息**：文件数量、大致大小、修改时间，以及目录层级的大致形状。
- **服务器本身没有被加密**：保险库密钥保存在 GPU 服务器上。能登录这台服务器的人都能拿到密钥，生成的原图也是以明文形式先写到服务器上的。用完可以执行 `auth.py logout`；如果不想在服务器上保留原图，可以关闭 `keep_local_copy`。

## 已下架的旧节点

旧节点已被 ComfyUI 官方节点取代。打开旧工作流时如果提示缺少节点，请按下表替换：

| 旧节点 | 官方替代 |
|---|---|
| Text Box 🍿 (`TextBox`) | **Text (Multiline)** (`PrimitiveStringMultiline`) |
| Image Info 🍿 (`ImageInfo`) | **Get Image Size** (`GetImageSize`) |
| Text Processor 🍿 (`TextProcessor`) | **Concatenate Text** (`StringConcatenate`)、**Replace Text** (`StringReplace`)、**Preview Any** (`PreviewAny`) |
| Image Scaler 🍿 (`ImageScaler`) | **Scale Image to Total Pixels** (`ImageScaleToTotalPixels`，用 `resolution_steps` 对齐尺寸倍数)、**Resize And Pad Image** (`ResizeAndPadImage`)、**Resize Image/Mask** (`ResizeImageMaskNode`) |

## 开发

```bash
pip install -r requirements.txt numpy pillow pytest ruff
```

```bash
ruff check . && pytest
```

装有 Java 21+ 和 Maven 时，测试会额外运行与 Cryptomator 官方 `cryptofs` 库的互通性测试。

## 致谢

- [Cryptomator](https://github.com/cryptomator)：保险库格式与 `cryptofs` 参考实现
- [ComfyUI-Custom-Scripts](https://github.com/pythongosssss/ComfyUI-Custom-Scripts)（pythongosssss）：早期文本节点的灵感来源
