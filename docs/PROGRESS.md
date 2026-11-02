# 开发记录与测试计划

最后更新：2026-11-02 · **2.1.0 开发中：R2、节点内连接网盘和设置保险库、后台上传；Registry ID 改为 `SnackNodes`** · **2.0.0 已发布到 Comfy Registry；项目主页上线，Google 品牌已验证**

## 已完成

0. **发布 2.0.0（2026-11-01）**：[PR #1](https://github.com/svbmwjwj/SnackNodes/pull/1) 合并到 main（合并提交 `5039246`），`publish_action.yml` 自动运行并成功上传到 Comfy Registry（此前 Registry 为 v1.0.1）。PR 上 `validate`（node-diff）失败：它加载 main 上的旧代码时缺少 torch；即使能加载，也只会报告 4 个旧节点被删除，属于有意的不兼容改动，PR 上已留言说明

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
   - **用户不满意的地方 2：节点上方的标签仍显示 `comfyui_snacknodes`**。查了前端源码（`getNodeSource` / `shortenNodeName`）：这个标签取自插件**文件夹名**（`custom_nodes/<文件夹>`），只会去掉大小写完全匹配的 `ComfyUI-`/`ComfyUI_`/`Comfy-`/`Comfy_` 前缀；`pyproject.toml` 的 `DisplayName` 只影响 Registry 和 Manager 的列表。从 Registry 安装时文件夹名就是节点 ID `comfyui_snacknodes`（不可改），所以**我们改不了这个标签**。用户自己可以在设置里关掉节点来源标签。如果一定要改，只能换一个新的 Registry ID（之前讨论过的代价：老用户收不到更新）。**已决定（2026-11-02）：换新 ID `SnackNodes`**（见第 11 条）。用户随后问「要不要改仓库名」：**不用**。1.57.4 的 `getNodeSource` 只看 `python_module` 里 `custom_nodes.` 后面那一段（即文件夹名），从 Registry 安装时文件夹名是节点 ID，和 GitHub 仓库名无关；改仓库名只会影响以后用 `git clone` 新装的人，已装的文件夹不会变

9. **连接面板改成原生控件（2026-11-02）**：`web/js/drive_setup.js` 重写，不再用 HTML 面板（DOM 小部件）。选好网盘后，「网盘」下拉框下面直接出现几行原生控件，样子和「网盘目录」那一行一样：
   - R2：文本控件「S3 API 地址」「访问密钥 ID」「机密访问密钥」「容量上限（GB）（可选）」+ 按钮「连接」；WebDAV：「WebDAV 地址」「用户名」「密码」+「连接」。字段、标签、默认值仍由后端 `FORMS` 提供，说明放在控件的悬停提示里
   - Google Drive：按钮「连接 Google Drive」；授权中显示三行按钮：「① 打开 https://www.google.com/device」（点击打开）、「② 输入验证码 XXXX-XXXX（点击复制）」、「③ 登录 Google 并允许访问…」，每 3 秒刷新一次
   - 已连接：「✓ 已连接：存储桶 xxx，上限 10 GB」（点击重新检查）、「修改连接」（Google 为「重新登录」）、「断开连接」（用 ComfyUI 自带的确认框）
   - 结果和错误用 ComfyUI 的 toast（`app.extensionManager.toast`）；Google 授权失败时节点上留一行「⚠ 原因」，点击再次显示详情
   - 控件名都以 `snack_` 开头，创建时就设 `serialize: false`（含 `options.serialize`），不进工作流、不进 API prompt；连接成功后整组控件被换掉，密码/机密不会留在页面上。非机密的输入（地址、用户名）在切换网盘或「修改连接」时保留
   - 已确认的前端行为（读的是 `comfyui_frontend_package` 1.57.4 的打包代码）：`node.widgets` 是被追踪的数组，`splice` 会触发 `syncWidgetOrder` → `replaceNodeWidgetOrder`，所以插到中间后 Nodes 2.0（Vue）界面的顺序也会更新；`addCustomWidget` 只给 `serialize !== false` 的控件按位置恢复值；控件只在异步请求状态之后才加，那时节点已按工作流配置完毕，不会打乱其他控件的值。按钮文字在两种界面都取 `widget.label`
   - 验证：用一个模拟节点在 Node.js 里跑了插入位置、切换网盘、连接后清空机密、修改连接保留草稿；`pytest` 100 个通过，`ruff` 无报错。**还没在真实 ComfyUI 里看过**（沙箱不允许运行外部下载的 ComfyUI）
   - 措辞同步：节点提示、README、错误提示里的「连接面板」改为「连接设置 / 下面出现的几行」

10. **按用户实测反馈（2026-11-02，经典界面截图：Google Drive 已连接，三行按钮显示正常）**：
   - **在节点上设置加密**：打开「加密」后，它下面出现原生控件：「保险库位置」（默认 `ComfyUI-Vault`）、「新建保险库（设置密码）…」「打开已有保险库（输入密码）…」；设置好后显示「🔒 保险库：位置（已就绪）」+「更换保险库」；网盘没连接时提示先连接。关掉「加密」这些行就消失
   - 密码在一个小的遮盖输入弹窗里输入（节点控件无法遮盖输入内容）。新建时可选「自己设置密码」（至少 8 位，输两次）或「自动生成强密码（推荐）」（与 auth.py 同一字母表，6 组×5 位，需要输入最后一组确认已保存），并有醒目的「密码是恢复文件的唯一方式」警告。密码只在创建/解锁时发给本机后端一次，用来派生密钥；不保存、不写进工作流、不写日志
   - 后端：`Connector.vault_status / vault_create / vault_unlock / vault_forget / vault_error`，路由 `GET /snacknodes/vault/{name}`、`POST .../create|unlock|forget`。错误有中英文说明：密码太短、密码错误、该位置已有保险库、该位置没有保险库（Google Drive 只能打开本工具创建的）、网盘未连接
   - **「预览」默认改为关闭**（节点定义、函数默认值、README、中英文说明都已改）
   - 节点说明、提示、README、「未设置保险库」错误提示都改为指向节点上的保险库设置；终端命令保留在 README 的折叠区
   - 前端代码重构：通用的 `Rows`（挂在某个控件下面的一组行），`DriveRows` 挂在「网盘」下，`VaultRows` 挂在「加密」下。已确认 Vue 界面改值也会调用控件的 callback，所以两种界面都能感知「加密」开关
   - 验证：`pytest` 103 个通过（新增保险库接口测试：未连接、密码太短、新建、重复新建、忘记、密码错误、位置不存在、重新解锁得到同一密钥、返回内容不含密码）；aiohttp 路由实测；用 Playwright 在真实浏览器里跑了模块（桩 app/api + 模拟节点）：开关加密、密码太短、生成密码确认最后一组、创建后显示就绪、解锁密码错误、关掉加密行消失，弹窗截图正常。**还没在真实 ComfyUI 里看过**

11. **节点 ID 改为 `SnackNodes`；节点说明缩短（2026-11-02）**：
   - 用户确认换新 ID，并选定 `SnackNodes`。验证（comfy.org 在本环境被网络策略拦截，改读 GitHub 上的源码）：
     - Registry 后端 `Comfy-Org/registry-backend` 的 `mapper/node.go` `IsValidNodeID`：允许 ASCII 大小写字母、数字、`_ - .`，不能以符号开头或结尾，1–100 字符；测试用例里有 `ValidNodeID` 这样的大小写混合 ID。创建时 ID 原样保存，另存一份小写的 `normalized_id`，所以大写会保留，重名按不区分大小写判断
     - 安装文件夹：ComfyUI-Manager `_cnr_install` 用 `custom_nodes/<node_id>`，comfy-cli `registry_install` 也是 `custom_nodes/<node_id>`，都不改大小写 → 标签显示 `SnackNodes`（`shortenNodeName` 不会去掉它）。用 comfy-cli 时如果用户输入小写 `snacknodes`，文件夹就是小写
     - **没能确认 `SnackNodes` 在 Registry 上没被占用**（API 打不开）。GitHub 代码搜索里没有别的仓库用这个名字。如果被占用，合并后发布那一步会失败，到时换名字即可。用户可以自己打开 https://registry.comfy.org/nodes/SnackNodes 看一眼
   - 改动：`pyproject.toml` `name = "SnackNodes"`（版本仍 2.1.0）；终端命令提示不再写死文件夹名，改为读实际安装目录（`cloud_drive/paths.py` 的 `AUTH_SCRIPT`），新老安装都正确；README / 主页的安装步骤改为搜索 `SnackNodes`、`comfy node install SnackNodes`、手动 `git clone ... SnackNodes`；README 加了「从 2.0.0 升级」：卸载 `comfyui_snacknodes` 再装 `SnackNodes`，不要同时装两个
   - **凭据目录保持 `~/.config/comfyui_snacknodes/` 不变**，换装后不用重新连接；节点类名 `SnackSaveToCloudDrive` 不变，旧工作流照常打开
   - **GitHub 仓库改名为 `SnackNodes`（用户决定，2026-11-02）**：仓库里的链接（`pyproject.toml` Repository/Icon、README、主页、隐私政策、连接说明的教程链接、Issue 模板、CI 名称）已全部改成 `svbmwjwj/SnackNodes`，手动安装改为 `git clone https://github.com/svbmwjwj/SnackNodes`。**需要用户在 GitHub 上操作改名**：仓库 Settings → General → Repository name。改名后 GitHub 会自动把旧地址（网页、git clone/pull、raw 链接）跳转到新地址；主页用的是自定义域名（`docs/CNAME`），不受影响，Google 品牌验证也不受影响。改名前新链接会 404，所以**要在合并到 main 之前改名**
     - 本地克隆可以继续用，也可以更新远程地址：`git remote set-url origin https://github.com/svbmwjwj/SnackNodes`
     - 注意：以后不要再新建一个叫 `comfyui_snacknodes` 的仓库，否则旧地址的跳转会失效
     - 当前云端会话的 GitHub 权限是按旧仓库名授予的，改名后新会话可能需要重新添加仓库
   - **节点说明（DESCRIPTION）缩短为一句话**：ComfyUI 鼠标悬停在节点标题上就会显示说明（不是只在节点信息里），原来的长用法太乱。细节都在各项的悬停提示里；「同名文件不覆盖」移到「网盘目录」的提示里
   - 合并后要做（在 registry.comfy.org 发布者后台手动）：确认新节点 `SnackNodes` 已发布；把旧节点 `comfyui_snacknodes` 的描述改成「已改名为 SnackNodes」或标记弃用

14. **按用户反馈调整布局（2026-11-02）**：
   - **上传入口挪到顶部操作栏**（用户选：官方接口）：`upload_panel.js` 不再注册侧边栏标签，改用扩展的 `actionBarButtons`（1.57 的 `ActionBarButtons` 组件，位置由 ComfyUI 决定）。按钮上的角标「还剩几个文件 · 总进度%」（失败显示「!」）：扩展对象在 1.57 里是 `markRaw`（不会响应式更新），所以按 `aria-label` 找到渲染出来的按钮，直接往里加一个小 `span`，每次事件和每 2 秒更新一次（按钮被重新渲染后会补回来）。点按钮弹出上传队列（固定定位在按钮下方，点外面或按 Esc 关闭），内容和之前的面板一样
   - **网盘配置全部挪到侧边栏**（用户选：节点只留下拉框和一行状态）：新的 `settings_panel.js` 注册侧边栏标签「SnackNodes」（`pi pi-cloud` 图标）。每个网盘一张卡片：状态、连接表单（密码/机密是遮盖输入框；输错时已填的内容保留在内存里，连接成功后清空）、Google 的网址和验证码（每 3 秒自动刷新）、修改/断开；卡片下方是该网盘的「🔒 加密保险库」：位置、新建/打开（沿用遮盖输入的密码弹窗）、更换。连接或保险库变化时发 `snacknodes:drives-changed`，所有节点的状态行跟着刷新
   - 节点（`drive_setup.js` 重写）：只在「网盘」下面留一行原生按钮作为状态，例如「✓ 已连接：存储桶 comfy，上限 10 GB · 🔒 保险库 ComfyUI-Vault」「⚠ 未连接 · 点此在侧边栏连接」「⚠ 已开加密但没有保险库，点此设置」；点它打开侧边栏并高亮对应网盘（`sidebarTab.toggleSidebarTab`）。「加密」下面不再有行
   - 公共代码放到 `web/js/snack_common.js`（语言、请求、保险库密码弹窗、打开侧边栏），ComfyUI 会把它当扩展文件加载，它自己不注册扩展
   - **默认值按用户截图**：「保留本地副本」默认改为**关**（其余本来就一致：加密关、预览关、等待上传完成关、失败时停止开）；它的说明改为「关：output 里不留文件；临时副本在上传完成后或 ComfyUI 重启时删除」
   - 节点提示、错误提示、README 都改为指向侧边栏 SnackNodes 面板和顶部「上传」按钮
   - **修复：用符号链接装在 custom_nodes 里时（用户本地就是这样：开发目录链接进 ComfyUI），终端命令提示显示的是开发目录名**。`paths.py` 不再 `resolve()`，用 ComfyUI 看到的链接名；加了测试
   - 验证：Playwright + 桩 app/api：节点状态行（未连接 → 连接 R2 → 已开加密没保险库 → 建好保险库）、点状态行打开侧边栏、遮盖输入、漏填时保留已填内容、自动生成密码建库、顶部按钮角标「1 · 25%」、弹窗打开和点外面关闭，截图核对（修了一个空占位显示成 "null" 的问题）；`pytest` 119 个通过。**还没在真实 ComfyUI 里看过**：顶部按钮的具体位置、角标样式、侧边栏图标需要用户确认

### 下一步：请用户在本地测（新对话从这里开始）

本地是用 git 装的话，文件夹名不会变（标签仍是 `comfyui_snacknodes`），这是正常的；标签要等合并发布后从 Registry 装 `SnackNodes` 才会变。

GitHub 仓库已改名为 `svbmwjwj/SnackNodes`：本地克隆先执行 `git remote set-url origin https://github.com/svbmwjwj/SnackNodes`（不改也能用，GitHub 会跳转）。

后台上传要测的：
- 连一个视频（或 file_paths 指向一个几百 MB 的文件），默认设置运行：工作流马上结束，节点上显示进度，完成后右上角提示
- 上传中途关掉 ComfyUI 再启动：日志提示继续，R2 / Google Drive 从断点接着传
- 断网几分钟：节点显示「⏸ 几点几分自动重试」，恢复后继续
- 终端执行 `python custom_nodes/<文件夹>/auth.py uploads --wait`，看到进度，全部完成后返回 0
- 打开「等待上传完成」：和以前一样，传完才继续，输出里有链接
- 关闭「保留本地副本」：上传完成后 output 和 `user/snacknodes_pending/` 里都不留文件
- 顶部「上传」按钮：位置、角标数字和进度、点开的上传队列（重试、取消、清除已完成）、浅色主题下是否看得清
- 左侧边栏「SnackNodes」：连接/修改/断开网盘、Google 授权、新建和打开保险库；节点状态行是否跟着变、点它能否打开侧边栏
- 新建节点：「保留本地副本」默认是关
- 符号链接的本地开发目录：把 custom_nodes 里的链接改名为 SnackNodes（`mv custom_nodes/<旧链接名> custom_nodes/SnackNodes`，只改链接，不动开发目录），标签变为 SnackNodes

步骤：节点目录 `git pull` → 停掉旧 ComfyUI（`lsof -ti tcp:8188 | xargs kill`）→ `comfy launch` → 浏览器 `Cmd+Shift+R`。经典界面和 Nodes 2.0 各看一遍：
1. 打开「加密」：下面出现保险库位置和两个按钮；点「新建保险库」→ 弹窗 → 选自动生成 → 存好密码 → 输入最后一组 → 创建，节点显示「🔒 保险库：ComfyUI-Vault（已就绪）」
2. 跑一次上传，用 Cryptomator App 打开保险库核对
3. 「更换保险库」→「打开已有保险库」→ 故意输错密码：弹窗里显示「保险库密码错误」
4. 新建节点：「预览」默认是关
5. 保存工作流、刷新再打开：其他控件的值不错位，JSON 里没有 `snack_` 开头的值，也没有密码
6. 之前的连接控件检查项（R2/WebDAV 填写、切换网盘、Google 授权）

12. **后台上传（2026-11-02，用户确认：默认后台、加「等待上传完成」开关默认关、要 `uploads --wait`、断点续传和 R2 并行分片一起做）**：
   - 原因：同步上传时大视频会让整个工作流队列停在这个节点。ComfyUI 的异步节点也一样要等返回，解决不了
   - `cloud_drive/uploads.py`：持久化队列（`~/.config/comfyui_snacknodes/uploads.json`，原子写入）+ 后台线程（一次一个任务）+ 心跳线程（有任务时每 5 秒写一次）。任务状态 queued / running / waiting（临时失败，30 秒、2 分钟、10 分钟后自动重试，最多 3 次；只对网络、服务器出错、限流）/ failed / done（保留最近 50 个）。重启时 running → queued。进度事件节流 0.5 秒，进度落盘节流 3 秒。`snapshot()` 给前端的数据不含本地路径和续传状态
   - 断点续传（provider 的 `upload_file(..., resume=dict)`，改动后调用 `save_resume()` 落盘）：
     - Google Drive：保存 resumable session URL，重试时先 `PUT bytes */size` 问已收到多少再接着传；会话失效（404/410）就新建
     - R2/S3：保存 UploadId、key 和已完成分片的 ETag，只补传缺的分片；保存的上传已不存在（404 NoSuchUpload）就从头开始一次。后台模式失败时不中止分片上传（R2 7 天后自动清理），取消任务时调用 `discard_resume` 中止
     - 加密：保存密文临时文件和选定的文件名，重试时发送同一份密文（重新加密每次结果都不同，没法续传）；传完删除
     - WebDAV：没有标准续传，从头传
   - R2/S3 分片并行：`PARALLEL_PARTS = 4`（内存约 4×16 MB），进度按各分片已发送字节汇总。等待模式也会用到
   - 节点：新选项「等待上传完成」（默认关）。后台模式下先检查设置（网盘已连接、开了加密就要有保险库），有问题照旧按「失败时停止」处理；然后入队立即返回：输出「上传结果」= 每个文件将要存放的位置，「成功」= 已入队。「保留本地副本」关闭时文件复制（优先硬链接）到 `ComfyUI/user/snacknodes_pending/<任务>/`，上传成功或取消后删除。「保留本地副本」的说明改为「关：上传完成后删除本地文件」
   - 启动：`__init__.py` 在 ComfyUI 里启动队列，`notify` 用 `PromptServer.instance.send_sync("snacknodes.upload", …)` 广播；日志会提示「还有 N 个文件没传完，继续」
   - 路由：`GET /snacknodes/uploads`、`POST /snacknodes/uploads/{id}/retry`、`POST /snacknodes/uploads/{id}/cancel`（运行中的任务不能取消，返回 409）
   - 前端（`web/js/save_to_cloud_drive.js`）：节点结果区显示「⏳ 已加入上传队列」→「⬆ 后台上传中 15% · 1/3 · a.mp4 · 120.0/800.0 MB」→「✅ 已上传」；临时失败显示「⏸ 几点几分自动重试」；失败显示 ❌ 原因 + 原生按钮「重试上传」「取消（删除为上传保留的文件）」；完成和失败弹 toast。刷新网页后（`afterConfigureGraph`）会把没完成的任务重新显示到对应节点上（按节点 id 匹配）
   - `auth.py uploads [--wait] [--timeout 秒]`：读队列文件；返回码 0 全部成功、1 有失败、2 还有没传完但 ComfyUI 没在运行（心跳超过 60 秒）、3 超时。AutoDL 用法：`python custom_nodes/SnackNodes/auth.py uploads --wait && shutdown`
   - 测试：新增 `tests/test_uploads.py`（重启后继续、临时失败自动重试/永久失败手动重试、取消时删除临时文件并中止分片、心跳判断、并行分片、S3 只补传缺的分片、保存的上传失效时从头开始、Google 复用会话、加密续传发送同一份密文、`uploads --wait` 各种返回码、命令行、真实后台线程）和节点后台模式测试；`FakeS3` 改为每次生成不同的 UploadId，并对不存在的 UploadId 返回 404。前端用桩 app/api 在 Node.js 里跑了 排队→上传中→失败（按钮）→重试→完成 的显示。**还没在真实 ComfyUI 里测**

13. **全局上传面板（2026-11-02，用户同意方案）**：`web/js/upload_panel.js`
   - 用 `app.extensionManager.registerSidebarTab` 加左侧边栏标签「上传」（`pi pi-cloud-upload` 图标，`type: "custom"`，每次打开调用 `render(el)`，关闭调用 `destroy`）
   - 图标角标 = 还没传完的文件数；没有进行中但有失败的显示「!」。1.57 的 `SidebarIcon` 用 computed 读 `iconBadge`，函数形式读不到我们的数据变化，所以改为直接修改侧边栏 store 里登记的 tab 对象的 `iconBadge`（它是响应式的）
   - 面板：顶部汇总「还剩 N 个文件 · 大小 · 速度 · 约多久」+「清除已完成」；后台没在运行时提示。每个任务一张卡片：网盘 / 目录（加密带 🔒）、状态（排队中 / 上传中 / 等待重试 / 失败 / 已完成）、进度条、文件数和字节数、速度和剩余时间（前端按最近 15 秒的进度事件估算）、正在传的文件、错误原因；失败的有「重试」「取消」，排队或等待重试的可以「取消」，完成的列出每个文件，可「打开」链接（Google Drive / 设了公开地址的 R2）或「复制」路径
   - 数据：`GET /snacknodes/uploads` + `snacknodes.upload` 事件；断线重连（`reconnected`）后重新拉取。新增 `POST /snacknodes/uploads/clear`（`UploadQueue.clear_finished`，只清列表，不动网盘上的文件）
   - 验证：Playwright + 桩 app/api 渲染了三种状态的任务并截图核对，角标、速度/剩余时间、重试和清除的请求都正确；新增 `clear_finished` 测试，`pytest` 118 个通过。**还没在真实 ComfyUI 里看过**（侧边栏的图标、角标、浅色主题下的颜色需要用户实测确认）

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

- 119 个自动化测试全部通过（`pytest`，含 cryptofs 互通测试和 WebDAV 单元测试），`ruff check .` 无报错
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
  - 名称约定：Registry 节点 ID 从 2.1.0 起为 `SnackNodes`（旧 ID `comfyui_snacknodes` 停在 2.0.0），GitHub 仓库名仍为 `comfyui_snacknodes`；Google 应用名称 `ComfyUI SnackNodes`，主页标题与之一致（品牌验证会核对）；品牌名 SnackNodes
  - 开发分支 `claude/stoic-fermat-wano83` 已不再被任何外部链接引用，可以删除
- 要从 Registry 真正下架或弃用旧版本，需要在 registry.comfy.org 的发布者后台手动操作

## 后续可能要做的

- ~~**下次发版时一起改**~~（2.1.0 已改为 `SnackNodes`）：`pyproject.toml` 的 `DisplayName`（Registry 页面显示的名字）从 `comfyui_snacknodes` 改为 `SnackNodes` 或 `ComfyUI SnackNodes`；节点 ID `name = "comfyui_snacknodes"` 不变。单独改 `pyproject.toml` 会在合并时触发发布，所以和版本号（如 2.0.1）一起改
- **修复 `validate`（node-diff）检查**：它不安装依赖就加载 base 分支的 `__init__.py`，目前因顶层导入 numpy/PIL/requests/cryptography 而必定失败。办法是把这些依赖改为按需导入（已在 PR #2 留言说明）

- 做一个 Comfy Cloud 同步工具：在节点外部运行，通过 Comfy Cloud API v2（`GET /api/v2/assets/{id}/content`）下载生成结果，再上传到网盘或保险库。注意结果有 `expires_at` 过期时间
- iCloud（非官方接口，国际账号）
- 夸克网盘（基于 Cookie 的非官方接口；也可以先通过 OpenList + WebDAV 使用）
- 腾讯网盘（等它开放接口或 MCP）
