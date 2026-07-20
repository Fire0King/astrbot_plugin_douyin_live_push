# astrbot_plugin_douyin_live_push 🎬

一个 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 插件，用于**监控抖音用户的视频更新和直播状态**，实时推送开播提醒与视频发布通知到指定会话。

基于 [DouYin_Spider](https://github.com/cv-cat/DouYin_Spider) 实现抖音数据抓取。

---

## ✨ 功能特性

- 📹 **视频监控** — 轮询检测订阅用户的抖音视频发布，有新作品时自动推送
- 🔴 **直播监控** — 检测直播间上下播状态，开播/下播时自动推送通知
- 👥 **@全体成员** — 支持开播或发视频时 @全体成员（需管理员权限）
- 🔄 **更新订阅** — 重复订阅同一用户可直接更新 @全体 标志
- 📋 **订阅管理** — 列表查看、取消订阅、全局管理查看
- 🔍 **用户查询** — 查看抖音用户信息（昵称、粉丝数等）

---

## 📦 安装

### 1. 克隆插件到 AstrBot

```bash
cd AstrBot/data/plugins
git clone https://github.com/Fire0King/astrbot_plugin_douyin_live_push.git
```

### 2. 克隆 DouYin_Spider 子模块

```bash
cd astrbot_plugin_douyin_live_push
git clone https://github.com/cv-cat/DouYin_Spider.git
```

### 3. 安装 Node.js 依赖（JS 签名引擎必需）

```bash
cd DouYin_Spider
npm install
cd ..
```

### 4. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

### 5. 配置 Cookie

在 AstrBot WebUI → 插件设置 → `astrbot_plugin_douyin_live_push` 中填写：

| 配置项 | 说明 |
|-------|------|
| `douyin_cookie` | 抖音网页版 Cookie（必需） |
| `douyin_live_cookie` | 直播间 Cookie（可选，不填则用上方） |
| `poll_interval` | 轮询间隔（秒），默认 60，最小 10 |
| `enable_live_monitor` | 是否开启直播监控，默认开启 |

#### 获取 Cookie

1. 用浏览器打开 [www.douyin.com](https://www.douyin.com) 并登录
2. 按 `F12` 打开开发者工具 → `Application` → `Cookies`
3. 全选所有 Cookie 并复制完整字符串
4. 粘贴到插件配置的 `douyin_cookie` 字段

### 6. 重载插件

在 WebUI 插件管理处点击「重载插件」。

---

## 📖 命令说明

### 用户命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `/dy_sub <URL/sec_uid> [选项]` | 订阅抖音用户视频更新 | `/dy_sub https://www.douyin.com/user/MS4wLjABAAAA...` |
| `/dy_sub video <URL/sec_uid> [选项]` | 仅订阅视频 | `/dy_sub video MS4wLjABAAAA...` |
| `/dy_sub live <直播间ID> [选项]` | 仅订阅直播 | `/dy_sub live 852953608964` |
| `/dy_unsub <ID> [video/live]` | 取消订阅 | `/dy_unsub MS4wLjABAAAA... video` |
| `/dy_list` | 列出当前会话订阅 | `/dy_list` |
| `/dy_info <URL/sec_uid>` | 查询抖音用户信息 | `/dy_info MS4wLjABAAAA...` |

### @全体 选项

| 选项 | 效果 | 权限 |
|------|------|------|
| `at_all` | 发视频**和**开播时 @全体成员 | 管理员 |
| `live_atall` | **仅**开播时 @全体成员 | 管理员 |
| _(不填)_ | 不 @全体成员 | — |

> **提示**：重复订阅同一用户可直接更新 @全体 标志，不会报"已存在"。

#### 示例

```bash
# 订阅用户，开启 @全体
/dy_sub https://www.douyin.com/user/MS4wLjABAAAA... at_all

# 订阅用户，仅开播 @全体
/dy_sub video MS4wLjABAAAA... live_atall

# 订阅直播间，开播 @全体
/dy_sub live 852953608964 live_atall

# 更新已有订阅（取消 @全体）
/dy_sub MS4wLjABAAAA...

# 查看用户信息
/dy_info MS4wLjABAAAA...
```

### 管理员命令

| 命令 | 说明 |
|------|------|
| `/dy_clear` | 清空当前会话所有订阅 |
| `/dy_global_list` | 查看所有会话的订阅 |
| `/dy_global_unsub <UMO> <UID>` | 删除指定会话指定用户的订阅 |
| `/dy_status` | 查看插件运行状态 |

---

## 🔧 项目结构

```
astrbot_plugin_douyin_live_push/
├── main.py                  # 插件入口 & 命令
├── metadata.yaml            # 插件元数据
├── _conf_schema.json        # 配置定义
├── requirements.txt         # Python 依赖
├── core/
│   ├── models.py            # 数据模型
│   ├── data_manager.py      # 数据持久化
│   └── utils.py             # 工具函数
├── services/
│   ├── listener.py          # 后台轮询监听
│   ├── subscription_service.py  # 订阅管理
│   └── renderer.py          # 消息渲染
└── DouYin_Spider/           # 抖音爬虫 SDK（单独克隆）
```

---

## 🚨 常见问题

### Q: 插件加载失败，提示 `Could not find an available JavaScript runtime`

**原因**：`DouYin_Spider` 依赖 Node.js 执行 JS 签名算法。

**解决**：
```bash
# 安装 Node.js
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# 安装 JS 依赖
cd AstrBot/data/plugins/astrbot_plugin_douyin_live_push/DouYin_Spider
npm install
```
---

## 📄 许可证

本项目基于 MIT 许可证开源。

## 🙏 致谢

- [AstrBot](https://github.com/AstrBotDevs/AstrBot) — 机器人框架
- [DouYin_Spider](https://github.com/cv-cat/DouYin_Spider) — 抖音爬虫 SDK
- [astrbot_plugin_bilibili](https://github.com/Soulter/astrbot_plugin_bilibili) — 参考实现的 B站推送插件


ai真的太好用了.jpg