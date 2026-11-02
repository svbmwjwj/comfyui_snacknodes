# Privacy Policy / 隐私政策

Last updated / 最后更新：2026-11-01

SnackNodes ("Save to Cloud Drive") is an open-source ComfyUI custom node. It runs entirely on the
machine where you run ComfyUI. The developers operate **no servers** and receive **no data** from you.

## What the app accesses

- **Google Drive, scope `drive.file` only.** The app can see and change only the files and folders it
  created itself. It cannot read, list or modify any other file in your Google Drive.
- It uses this access solely to create folders and upload the files you choose to save from ComfyUI
  (images, videos, other output files) into **your own** Google Drive, and, when you use encryption, to
  read the Cryptomator vault files it created there.
- Aliyun Drive (阿里云盘) is accessed the same way, only to upload the files you choose.

## Where data is stored

- OAuth tokens and, if you enable encryption, the unlocked vault keys are stored only on your machine,
  in `~/.config/comfyui_snacknodes/cloud_drive.json` (file mode 600). They are never written into
  workflows and never sent anywhere except to the cloud drive provider's official API.
- Your files go directly from your machine to your cloud drive. With encryption enabled they are
  encrypted on your machine before upload.
- Vault passwords are never stored.

## Sharing

No data is sold, shared with, or transferred to the developers or any third party. There is no
analytics, telemetry or advertising.

## Google API Services User Data Policy

The app's use and transfer of information received from Google APIs adheres to the
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
including the Limited Use requirements.

## Deleting your data / revoking access

- Run `python auth.py logout google_drive` to delete the stored tokens and vault keys from your machine.
- Revoke the app's access at any time at <https://myaccount.google.com/permissions>.
- Files the app uploaded stay in your Drive under your control; delete them like any other file.

## Contact

Open an issue at <https://github.com/svbmwjwj/SnackNodes/issues>.

---

## 中文摘要

- 本工具完全在你运行 ComfyUI 的机器上运行，开发者**没有任何服务器**，也**收不到你的任何数据**。
- Google Drive 只申请 `drive.file` 权限：只能看到和修改本工具自己创建的文件和文件夹，用途仅限把你选择保存的文件上传到**你自己的** Drive，以及读取它自己创建的加密保险库文件。
- 授权凭据和保险库密钥只保存在你本机的 `~/.config/comfyui_snacknodes/cloud_drive.json`（权限 600），不写入工作流；保险库密码不保存。
- 不出售、不共享数据，没有统计、遥测或广告。对 Google API 数据的使用遵守 Google API Services User Data Policy（包括 Limited Use 要求）。
- 撤销授权：在本机运行 `auth.py logout google_drive`，或在 <https://myaccount.google.com/permissions> 移除本应用。
