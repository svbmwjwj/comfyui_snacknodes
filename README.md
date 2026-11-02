<div align="center">

<img src="web/icon.png" width="96" alt="SnackNodes">

# SnackNodes 🍿

**把 ComfyUI 生成的图片和视频，直接存进你自己的网盘**

Google Drive · Cloudflare R2 · WebDAV ｜ 可选 Cryptomator 端到端加密

[![Comfy Registry](https://img.shields.io/badge/Comfy_Registry-comfyui__snacknodes-blue)](https://registry.comfy.org/publishers/svbmwjwj/nodes/comfyui_snacknodes)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-green.svg)](LICENSE)

[项目主页](https://snacknodes.linksluckytime.com) · [隐私政策](https://snacknodes.linksluckytime.com/privacy.html) · [问题反馈](https://github.com/svbmwjwj/comfyui_snacknodes/issues)

</div>

---

在 AutoDL 等租卡平台或任何远程 GPU 服务器上跑 ComfyUI？关机前不用再手动打包下载了：加一个 **保存到网盘**（Save to Cloud Drive）节点，出图即上传。

<table>
<tr>
<td width="50%" valign="top">

**📤 上传**
- 图片、视频，或 output 目录里已有的任意文件
- 网盘目录自动创建，支持按日期归档
- 分片上传，断网、限流自动重试
- 同名文件不覆盖，自动改名 `_1`、`_2`
- 节点上实时显示进度条

</td>
<td width="50%" valign="top">

**🔐 安全**
- 账号凭据只存在服务器上，**不进工作流**，分享工作流不泄密
- 可选**端到端加密**，与 [Cryptomator](https://cryptomator.org) 保险库格式完全兼容
- 失败时给出看得懂的原因和解决办法（中 / 英）
- 只依赖 `requests` 和 `cryptography`

</td>
</tr>
</table>

## 📦 支持的存储

| 存储 | 适合谁 | 免费空间 | 连接时需要填 |
|---|---|---|---|
| **Google Drive** | 有 Google 账号的人 | 15 GB | 不用填，点「连接」后登录 |
| **Cloudflare R2** ⭐ | 想要一个稳定、免费、无流量费的仓库 | **10 GB**，下载不收费 | S3 API 地址、密钥 ID、机密 |
| **WebDAV** | 坚果云、Nextcloud、群晖等 NAS、OpenList/AList | 看服务商 | 地址、用户名、密码 |

> 通用 S3（AWS、B2、MinIO……）和阿里云盘的代码已经写好，但**还没用真实账号测试**，所以暂时不在节点里显示，见[实验性支持](#-实验性支持待实测)。

> 💡 **不知道选哪个？** 国内网络选 **坚果云（WebDAV）**；能访问海外选 **Cloudflare R2**，10 GB 免费、下载不收流量费，本工具还会帮你守住 10 GB 上限，不会产生费用。

## 🚀 快速开始

**① 安装**：在 ComfyUI Manager 里搜索 `comfyui_snacknodes` 安装；或者手动安装：

```bash
cd ComfyUI/custom_nodes && git clone https://github.com/svbmwjwj/comfyui_snacknodes
```

```bash
pip install -r comfyui_snacknodes/requirements.txt
```

**② 添加节点并连接网盘**：添加 **保存到网盘** 节点（搜索「网盘」「上传」「upload」都能找到），在「网盘」里选一个。还没连接过的话，节点上会直接出现要填的项目，填好点「连接」即可，**不用开终端**。

**③ 运行**：连上图像或视频，运行工作流，文件就会传到网盘。


## 🔑 连接网盘

在节点上选好网盘后，节点会自动显示这个网盘需要的信息：

- **已连接**：显示 `✓ 已连接` 和概况（比如存储桶名和容量上限），可以「修改」或「断开」
- **还没连接**：显示要填的项目，填完点「连接」。工具会先试连一次，确认无误才保存

连接信息保存在**运行 ComfyUI 的那台机器**上（`~/.config/comfyui_snacknodes/cloud_drive.json`，权限 600），**不会写进工作流**；保存后密码和密钥也不会再显示到网页上。

习惯用终端也可以：每个网盘下面都给了对应的 `auth.py` 命令（在 ComfyUI 根目录执行），效果相同。展开查看各网盘的说明：

<details>
<summary><b>Google Drive</b>：点「连接」，打开网址、输入验证码即可</summary>

在节点上点 **连接 Google Drive**，节点会显示一个网址和验证码。用手机或电脑打开网址、输入验证码，用你自己的 Google 账号登录并同意授权，节点会自动变成「已连接」。

终端方式：

```bash
python custom_nodes/comfyui_snacknodes/auth.py google_drive
```

- 文件上传到**你自己的 Google Drive**，占用你自己的空间。内置的 OAuth 客户端只用来标识这个应用，本身访问不了任何人的 Drive。
- 只申请 `drive.file` 权限：本工具**只能看到它自己创建的文件和文件夹**，读不到你 Drive 里的其他内容。详见[隐私政策](PRIVACY.md)。

**进阶：使用你自己的 OAuth 客户端**

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)，新建项目并启用 **Google Drive API**。
2. 配置 OAuth 同意屏幕：用户类型选「外部」，发布状态改为**「正式版（In production）」**。`drive.file` 是非敏感权限，发布不需要 Google 审核。停留在「测试」状态的话，未加入测试用户的账号会被拒绝，而且 refresh token 每 7 天失效。
3. 在「凭据」页面创建 OAuth 客户端 ID，应用类型选 **「电视和受限输入设备」**。
4. 运行 `auth.py google_drive --client-id 你的ID --client-secret 你的Secret`，或设置环境变量 `SNACK_GDRIVE_CLIENT_ID` / `SNACK_GDRIVE_CLIENT_SECRET`。

</details>

<details>
<summary><b>Cloudflare R2</b>：免费 10 GB，下载不收流量费 ⭐</summary>

R2 是 Cloudflare 的对象存储，**每月免费 10 GB 存储、100 万次写操作、1000 万次读操作，下载流量永久免费**。本工具默认把用量限制在 10 GB 以内，超出前会拒绝上传并提示你清理，**不会产生费用**。

**1. 开通 R2 并建存储桶**

1. 注册并登录 [Cloudflare 控制台](https://dash.cloudflare.com/)，左侧菜单进入 **R2 对象存储**。
2. 首次使用需要点「开通」并绑定一张信用卡或 PayPal（Cloudflare 的要求；不超过免费额度不会扣款）。
3. 点 **创建存储桶**，起个名字（例如 `comfyui`），位置默认即可。

**2. 创建 API 令牌**

1. 在 R2 概览页点 **管理 API 令牌** → **创建 API 令牌**（选「账户 API 令牌」或「用户 API 令牌」都可以）。
2. 权限选 **对象读和写（Object Read & Write）**，范围选 **仅应用于特定存储桶** → 刚才的桶。
3. 创建后页面会显示 **访问密钥 ID（Access Key ID）** 和 **机密访问密钥（Secret Access Key）**。机密只显示一次，先复制下来。
4. 回到存储桶，打开 **设置**，复制 **S3 API** 地址，形如 `https://<账户ID>.r2.cloudflarestorage.com/comfyui`。它已经包含了账户 ID 和桶名。

**3. 在节点上连接**

网盘选 **Cloudflare R2**，把三样东西粘贴进去：

| 节点上的项目 | 填什么 |
|---|---|
| S3 API 地址 | 第 4 步复制的地址 |
| 访问密钥 ID | 第 3 步的 Access Key ID |
| 机密访问密钥 | 第 3 步的 Secret Access Key |
| 容量上限（可选） | 默认 10 GB（免费额度）。设为 `0` 关闭检查，超出免费额度的部分会按量计费 |

点「连接」后，工具会先列一次存储桶，确认密钥正确才保存，并显示当前用量。

终端方式（效果相同，另外支持 `--public-url`：存储桶开启了公开访问时填 r2.dev 或自定义域名，节点会输出能直接打开的链接）：

```bash
python custom_nodes/comfyui_snacknodes/auth.py r2 --url https://<账户ID>.r2.cloudflarestorage.com/comfyui --access-key-id 访问密钥ID
```

**说明**

- 上限按**这个存储桶**的实际大小计算；免费额度是整个账户共用的，如果你还有别的桶，请相应调小容量上限。
- 每次运行节点会列一次存储桶来统计用量（每 1000 个文件算 1 次写操作），远低于每月 100 万次的免费额度。
- 单个文件超过 64 MB 自动分片上传，失败时会清理未完成的分片，不会留下占空间的垃圾。
- 想在网页上管理文件？直接在 Cloudflare 控制台的存储桶页面浏览、下载、删除即可。

</details>

<details>
<summary><b>WebDAV</b>：坚果云、Nextcloud、NAS、OpenList……</summary>

在节点上填 **WebDAV 地址、用户名、密码**，点「连接」。各服务的地址和密码见下表。

终端方式：

```bash
python custom_nodes/comfyui_snacknodes/auth.py webdav --url https://dav.jianguoyun.com/dav/ --username 你的账号
```

按提示输入密码。工具会先连一次服务器，确认地址和密码正确后才保存（节点上连接时也一样）。

| 服务 | 地址 | 密码 |
|---|---|---|
| 坚果云 | `https://dav.jianguoyun.com/dav/` | 账户信息 → 安全选项 → 第三方应用管理 里生成的**应用密码**，不是登录密码 |
| Nextcloud / ownCloud | `https://你的域名/remote.php/dav/files/用户名/` | 建议在 设置 → 安全 里生成应用密码 |
| 群晖 / 威联通等 NAS | 在 NAS 上开启 WebDAV 服务后的地址 | NAS 账号密码 |
| OpenList / AList | `https://你的域名/dav/` | OpenList 用户密码。可借它挂载阿里云盘、夸克、115 等再上传 |

- 尽量使用 `https://`。用 `http://` 连接非本机地址时密码会明文传输，工具会给出警告。
- 坚果云免费版有 WebDAV 请求次数限制（每 30 分钟约 600 次），大批量上传可能被限流，工具会自动重试。

</details>

<details>
<summary><b>查看状态、退出登录、环境变量</b></summary>

```bash
python custom_nodes/comfyui_snacknodes/auth.py status
```

```bash
python custom_nodes/comfyui_snacknodes/auth.py logout r2
```

（在节点上点「断开」效果相同。）

凭据保存在 `~/.config/comfyui_snacknodes/cloud_drive.json`（权限 600），可用 `SNACKNODES_CONFIG_DIR` 修改位置。

也可以不用凭据文件，改用环境变量（适合 Docker、云平台的密钥管理）：

| 存储 | 环境变量 |
|---|---|
| Google Drive | `SNACK_GDRIVE_CLIENT_ID` `SNACK_GDRIVE_CLIENT_SECRET` `SNACK_GDRIVE_REFRESH_TOKEN` |
| Cloudflare R2 | `SNACK_R2_ACCOUNT_ID` `SNACK_R2_BUCKET` `SNACK_R2_ACCESS_KEY_ID` `SNACK_R2_SECRET_ACCESS_KEY`，可选 `SNACK_R2_PUBLIC_URL` `SNACK_R2_LIMIT_GB` |
| S3 | `SNACK_S3_ENDPOINT` `SNACK_S3_REGION` `SNACK_S3_BUCKET` `SNACK_S3_ACCESS_KEY_ID` `SNACK_S3_SECRET_ACCESS_KEY`，可选 `SNACK_S3_PUBLIC_URL` `SNACK_S3_LIMIT_GB` |
| WebDAV | `SNACK_WEBDAV_URL` `SNACK_WEBDAV_USERNAME` `SNACK_WEBDAV_PASSWORD` |
| 阿里云盘 | `SNACK_ALIYUNDRIVE_*` |

网络代理遵循标准的 `HTTPS_PROXY` 环境变量。

</details>

## 🧪 实验性支持（待实测）

下面两种存储的代码和自动化测试都已完成，但**还没用真实账号测试过**，所以暂时不在节点的「网盘」下拉框里显示，只能用终端命令配置和测试。实测通过后会放进节点。欢迎有账号的朋友试用并[反馈](https://github.com/svbmwjwj/comfyui_snacknodes/issues)。

<details>
<summary><b>S3 兼容存储</b>：AWS S3、Backblaze B2、MinIO、Wasabi……</summary>

```bash
python custom_nodes/comfyui_snacknodes/auth.py s3 --endpoint https://s3.us-east-1.amazonaws.com --region us-east-1 --bucket 存储桶 --access-key-id 密钥ID
```

按提示输入 Secret Access Key。和 R2 一样支持 `--public-url` 和 `--limit-gb`（S3 默认不限制）。

| 服务 | Endpoint | Region |
|---|---|---|
| AWS S3 | `https://s3.<region>.amazonaws.com` | 存储桶所在区域，如 `us-east-1` |
| Backblaze B2 | `https://s3.<region>.backblazeb2.com` | 如 `us-west-004` |
| Wasabi | `https://s3.<region>.wasabisys.com` | 如 `us-east-1` |
| MinIO（自建） | 你的 MinIO 地址，如 `https://minio.example.com` | `us-east-1` |

使用路径风格地址（`endpoint/bucket/key`），各家都支持。密钥需要对该存储桶有列出、读取、写入权限。

</details>

<details>
<summary><b>阿里云盘</b>：仅限已有开放平台应用的开发者</summary>

> 阿里云盘开放平台自 2025 年 7 月 1 日起**暂停个人开发者申请**。其他用户请用 OpenList 挂载阿里云盘，再按 WebDAV 方式连接。

```bash
python custom_nodes/comfyui_snacknodes/auth.py aliyundrive --client-id 你的ID --client-secret 你的Secret
```

打开输出的二维码链接，用阿里云盘 App 扫码确认。扫码失败时可以加 `--refresh-token 你的token` 直接导入。

默认上传到「资源库」；想传到「备份盘」，在凭据文件的 `aliyundrive` 项中加上 `"drive": "backup"`。

</details>

## 🧩 节点说明

节点名 **保存到网盘**（英文界面为 Save to Cloud Drive），界面语言跟随 ComfyUI 设置。悬停在每一项上有说明；右键 → 节点信息里有完整用法。

| 项目 | 默认值 | 说明 |
|---|---|---|
| 图像 / 视频 | — | 要上传的图片和/或视频 |
| 网盘 | Google Drive | 上传到哪个存储。没连接过的网盘，选中后下拉框下面会出现几行连接设置 |
| 网盘目录 | `ComfyUI/%date:yyyy-MM-dd%` | 按日期自动分文件夹，见[日期变量](#-网盘目录与日期变量) |
| 加密 | 关 | 用 Cryptomator 保险库格式端到端加密，见[加密](#-端到端加密) |
| 预览 | 开 | 运行后在节点上显示图片 |
| 保留本地副本 | 开 | 关掉则只放在临时目录 |
| 文件名前缀 *(高级)* | `ComfyUI` | 本地副本的文件名，可带子目录 |
| 失败时停止 *(高级)* | 开 | 关掉后上传失败不中断工作流，而是让「成功」输出 false |
| 额外上传文件 *(高级输入)* | — | 连一个文本节点，列出 output 目录里已有的文件，一行一个 |

**输出**

- **上传结果**：每个文件一行。Google Drive 和设置了 `--public-url` 的 R2/S3 返回可打开的链接，其他返回 `网盘:路径`
- **成功**：全部上传成功为 true，可以用来做分支判断

**运行时**，节点上会显示：

- 上传中：进度条和当前文件，例如 `2/3 · video.mp4 · 12.0/15.2 MB`
- 完成：`✅ 已上传 N 个文件` 和每个文件的位置（加密的带 🔒）
- 失败：`❌ 上传失败`、看得懂的原因和解决办法，最后附原始技术信息。能识别授权失效、密码或密钥错误、没有写入权限、目录冲突、找不到位置、空间不足、超过 R2 免费额度上限、文件过大、限流、服务器出错、网络问题、未建保险库、本地文件不存在等情况

> 在 Nodes 2.0 界面中，高级选项默认折叠，点节点底部的「显示高级输入」展开。

## 📅 网盘目录与日期变量

「网盘目录」可以有多层，例如 `ComfyUI/portraits`；开启加密时它是保险库内部的路径。「网盘目录」和「文件名前缀」都支持以下变量（服务器本地时间）：

| 写法 | 结果示例 |
|---|---|
| `%date:yyyy-MM-dd%` | `2026-11-01`（可用 `yyyy` `yy` `MM` `dd` `hh` `mm` `ss` 自由组合） |
| `%year%` `%month%` `%day%` `%hour%` `%minute%` `%second%` | `2026` `11` `01` … |

例如 `ComfyUI/%date:yyyy-MM%/%date:dd%` 会按月建文件夹，月份下再按日分子文件夹。

## 🔒 端到端加密

把节点上的「加密」打开后，文件会**先在本机加密，再上传**，网盘服务商看不到文件内容和文件名：

| 加密对象 | 方式 |
|---|---|
| 文件内容 | AES-256-GCM，每 32 KiB 一块，每块都有完整性校验 |
| 文件名、文件夹名 | AES-SIV，网盘上只能看到 `d/XX/YYYY…/xxxx.c9r` 这样的乱码 |
| 密码 | scrypt 派生密钥，用来包裹主密钥 |

这就是 Cryptomator 的保险库格式（vault format 8），可以用 **Cryptomator 官方客户端**直接打开，不依赖本工具。兼容性已用 Cryptomator 官方 Java 库 `cryptofs` 双向验证，CI 每次都会重跑。

**第一步：创建保险库**（每个网盘一次，目前需要在终端里执行）

```bash
python custom_nodes/comfyui_snacknodes/auth.py vault-create r2 --path ComfyUI-Vault
```

可以选择 **自己输入密码**（至少 8 位），或 **自动生成强密码**（6 组共约 148 位强度，不含 0/O、1/l 这类易混字符，需输入最后一组确认已保存）。也可以加 `--own-password` / `--generate-password` 跳过选择。

已经有用 Cryptomator App 创建的保险库（WebDAV、R2/S3、阿里云盘）？用 `vault-unlock` 解锁后，节点会往里面继续写入：

```bash
python custom_nodes/comfyui_snacknodes/auth.py vault-unlock webdav --path 我的保险库
```

> ⚠️ **密码是恢复文件的唯一方式。** 没有找回、重置或恢复密钥，请立即存进密码管理器。本工具不保存密码，只在本机保存解锁后的密钥。

**第二步：在节点上打开「加密」**，之后上传的文件都会进入保险库。

<details>
<summary><b>如何用 Cryptomator 打开</b></summary>

| 存储 | 打开方式 |
|---|---|
| Google Drive | Cryptomator iOS/Android 版直接添加 Google Drive；或在桌面端用 Google Drive 客户端同步到本地后，用 Cryptomator 桌面版打开 |
| Cloudflare R2 / S3 | Cryptomator iOS/Android 版直接添加 S3（R2 填 Endpoint `https://<账户ID>.r2.cloudflarestorage.com`、Region `auto`）；桌面端可用 rclone、Cyberduck/Mountain Duck 挂载后用 Cryptomator 打开 |
| WebDAV | Cryptomator 各平台都原生支持：添加 WebDAV，填同样的地址、账号和密码 |
| 阿里云盘 | 把保险库文件夹下载到本地后用桌面版打开；或用 OpenList 挂载成 WebDAV 再添加 |

</details>

<details>
<summary><b>限制与注意事项</b></summary>

- **Google Drive 只能使用本工具创建的保险库**，因为 `drive.file` 权限看不到其他应用创建的文件。其他存储没有这个限制。
- **在 Google Drive 上，需要上传的文件夹请让节点自己创建。** 如果先在 Cryptomator App 里建了同名文件夹，本工具看不到它，会再建一个，导致保险库里出现两个重名文件夹。
- **加密不会隐藏**：文件数量、大致大小、修改时间，以及目录层级的大致形状。
- **服务器本身没有被加密**：保险库密钥保存在 GPU 服务器上，能登录这台服务器的人都能拿到；生成的原图也是先以明文写到服务器上的。用完可以执行 `auth.py logout`；不想在服务器上保留原图可以关闭「保留本地副本」。

</details>

## ♻️ 已下架的旧节点

<details>
<summary>旧版的 4 个工具节点已被 ComfyUI 官方节点取代，打开旧工作流提示缺少节点时按此表替换</summary>

| 旧节点 | 官方替代 |
|---|---|
| Text Box 🍿 (`TextBox`) | **Text (Multiline)** (`PrimitiveStringMultiline`) |
| Image Info 🍿 (`ImageInfo`) | **Get Image Size** (`GetImageSize`) |
| Text Processor 🍿 (`TextProcessor`) | **Concatenate Text** (`StringConcatenate`)、**Replace Text** (`StringReplace`)、**Preview Any** (`PreviewAny`) |
| Image Scaler 🍿 (`ImageScaler`) | **Scale Image to Total Pixels** (`ImageScaleToTotalPixels`，用 `resolution_steps` 对齐尺寸倍数)、**Resize And Pad Image** (`ResizeAndPadImage`)、**Resize Image/Mask** (`ResizeImageMaskNode`) |

</details>

## 🛠️ 开发

```bash
pip install -r requirements.txt numpy pillow pytest ruff
```

```bash
ruff check . && pytest
```

装有 Java 21+ 和 Maven 时，测试会额外运行与 Cryptomator 官方 `cryptofs` 库的互通性测试。S3 签名（AWS Signature V4）用 AWS 官方文档的测试向量校验。

## 🙏 致谢

- [Cryptomator](https://github.com/cryptomator)：保险库格式与 `cryptofs` 参考实现
- [ComfyUI-Custom-Scripts](https://github.com/pythongosssss/ComfyUI-Custom-Scripts)（pythongosssss）：早期文本节点的灵感来源

<div align="center"><sub>GPL-3.0 · Made with 🍿 for ComfyUI users</sub></div>
