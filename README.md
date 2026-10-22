# 家庭广播

基于 [mdj2812/home-intercom](https://github.com/mdj2812/home-intercom) 的 Home Assistant 自定义集成，包含本地中文界面与文字播报扩展。本包版本对应集成清单 2.2.5；不是原作者的官方发行包。

## 功能

- 浏览器按住说话，向指定房间或全部房间广播。
- 房间、音箱、音量和提示音管理。
- 小爱音箱文字播报与预设文本按钮。
- 支持配套 ESP32 广播按键；硬件与固件需另行准备。

## 手动安装

1. 解压下载包，将 `custom_components/home_intercom` 整个文件夹复制到 Home Assistant 的 `/config/custom_components/` 下。
2. 重启 Home Assistant。
3. 在“设置 → 设备与服务 → 添加集成”中搜索“家庭广播”；未显示时可搜索 Home Intercom。
4. 打开 `https://你的HA地址/home-intercom`，进入设置添加自己的房间与音箱。
5. 可按 `examples/dashboard.yaml` 创建侧边栏仪表盘。路径 `/home-intercom` 使用连字符。

升级前请备份原集成目录。覆盖文件并重启，不要删除 `.storage` 中的配置。

## HACS

将发布本包的 GitHub 仓库作为 HACS 自定义仓库添加，类别选择“集成”，下载后重启。目标仓库 `https://github.com/HASSAAS/home-intercom` 须包含本包的 `custom_components/home_intercom` 与 `hacs.json`。

## 使用条件

- 语音录音需要 HTTPS 或浏览器允许的安全上下文，以及麦克风授权。
- 音箱需要已接入 Home Assistant，并能访问 HA 生成的音频地址。
- 小爱文字播报依赖 `xiaomi_miot.intelligent_speaker` 服务；其他音箱可使用语音广播，文字播报不保证支持。
- 房间、音箱实体和账户信息由每位使用者在自己的 HA 中配置。

## 发布范围与验证

本包只包含集成源代码、内置资源和通用仪表盘示例，不包含个人配置、访问令牌、录音、设备数据库或 Python 缓存。发布前进行清单及压缩包完整性检查；尚未在全新 HA 实例完成安装测试。

## 来源与许可

保留原项目 MIT 许可，详见 `LICENSE`。按钮固件同步源为 `HASSAAS/home-intercom` 的最新 Release。需额外上传 `intercom-button-*.bin`（可附同名 `.sig`）；集成 ZIP 不能用于按钮 OTA。集成清单中的原作者与上游问题地址保持原样；本地扩展的问题应提交到本包的发布仓库。
