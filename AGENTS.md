# AGENTS.md

## 项目: 视频压缩浏览器 (Android)

一个 Android 浏览器 App，通过检测网页中的视频元素并用 Android MediaCodec API 转码（20fps）来节省流量。压缩后的视频跳转至 ExoPlayer 播放。

## 架构

```
android/
├── build.gradle.kts              — 项目级 Gradle 配置 (AGP 8.2.2, Kotlin 1.9.22)
├── settings.gradle.kts           — 项目设置 (Maven Central, Google)
├── gradle.properties
├── gradle/wrapper/
│   └── gradle-wrapper.properties — Gradle 8.5
└── app/
    ├── build.gradle.kts          — 模块依赖 (OkHttp, Media3, WebKit, 无外部 FFmpeg)
    └── src/main/
        ├── AndroidManifest.xml
        ├── java/com/videobrowser/
        │   ├── MainActivity.kt           — 浏览器主界面 (WebView)
        │   ├── VideoPlayerActivity.kt    — 视频播放器 (ExoPlayer) + 压缩统计
        │   └── VideoCompressor.kt        — 下载 + MediaCodec 转码 20fps + 缓存
        └── res/
            ├── layout/
            │   ├── activity_main.xml     — 浏览器 UI (工具栏、地址栏、状态栏)
            │   └── activity_player.xml   — 播放器 UI (ExoPlayerView, 统计面板)
            ├── drawable/                 — 矢量图标 + URL 栏背景
            └── values/                   — 字符串、颜色、主题
```

## 核心流程

1. **WebView 浏览** — 用户正常上网
2. **视频检测** — 页面加载完成后注入 JS，查找 `<video>` 和 `<source>` 元素
3. **弹窗提示** — 检测到视频后显示横幅，点击可选择要压缩的视频
4. **下载+转码** — 用 OkHttp 下载原视频，通过 `MediaCodec` 解码 → 选择性丢帧 → 编码至 20fps
5. **播放** — 跳转至 ExoPlayer 显示压缩前后大小对比和节省百分比

## 转码方案 (MediaCodec)

- 使用 Android 内置 `MediaCodec` API，**无需外部 FFmpeg**
- 流程: 下载 → `MediaExtractor` 读取 → `MediaCodec` 解码 → 选择性渲染到编码器 Surface → 20fps H.264 输出 → `MediaMuxer` 写入
- 帧率控制: 根据 PTS 时间戳判断是否保留当前帧，跳过多余帧以降至 20fps
- 音频: v1 暂不处理（无声）

## 开发者命令 (Android Studio)

```bash
cd android/
# 在 Android Studio 中 Sync Project with Gradle Files → Run ('▶')
```

## 前置依赖

- Android Studio Hedgehog (2023.1.1+) 或更新版本
- Android SDK 35 (compileSdk)
- **无外部 FFmpeg 依赖**，使用系统 MediaCodec API（API 16+ 内置）

## 关键文件说明

| 文件 | 职责 |
|------|------|
| `MainActivity.kt` | 浏览器 Chrome：WebView、地址栏、前进/后退/刷新、视频检测 JS 注入 |
| `VideoCompressor.kt` | OkHttp 下载 → `MediaCodec` 解码/编码 → 缓存到 `cache/video_cache/` |
| `VideoPlayerActivity.kt` | ExoPlayer 播放 + 原始大小/压缩后大小/节省百分比展示 |

## 视频 URL 检测方式

1. **直接导航**: `shouldOverrideUrlLoading` 拦截 `.mp4/.webm/.m3u8` 等直接视频链接
2. **页面检测**: 注入 JS 扫描 `<video src>` 和 `<source src>`（`onPageFinished` 时执行）

## 已知限制

- **不支持 JS 动态加载的流媒体**（如 YouTube 的 MSE/EME）—— 视频 URL 不在 DOM 中
- **HLS/DASH 仅拦截根 URL**，不重写分片
- **DRM 受保护视频** 无法处理
- 转码需要设备 CPU/GPU，低端机型大文件可能耗时较长
- **v1 无声**: 音频轨道不转码（仅视频降帧）
- MediaCodec 编码质量取决于设备硬件编码器
