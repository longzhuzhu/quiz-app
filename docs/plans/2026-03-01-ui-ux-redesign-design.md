# CIPT 备考应用 UI/UX 重设计方案

日期: 2026-03-01
状态: 已确认

## 目标

将备考应用从基础功能型界面升级为清新现代、沉浸式的学习体验。提升移动端适配、交互反馈、视觉一致性。

## 设计风格

清新现代风，类似 Duolingo / Quizlet 的愉快学习体验。明亮配色、大圆角卡片、微动效。

## 配色方案

- 主色: indigo-500 / indigo-600
- 辅助: sky-400 / emerald-400
- 背景: slate-50（浅色）/ slate-900（深色）
- 卡片: white / slate-800
- 成功: emerald-500 / emerald-50
- 错误: rose-500 / rose-50
- 警告: amber-500 / amber-50

## 技术方案

方案 A：基于现有 Tailwind CSS 4 + HeadlessUI + Heroicons 全面增强，不引入新依赖。

## 模块一：设计系统 & 基础架构

### Design Tokens

在 `style.css` 中通过 Tailwind CSS 4 的 `@theme` 定义全局 tokens（颜色、圆角、阴影）。所有颜色通过 CSS 变量定义，`dark:` 下自动切换。

### Dark Mode

- `class` 策略，在 `<html>` 标签上切换 `dark` class
- 用户偏好存入 localStorage，默认跟随系统 `prefers-color-scheme`
- NavBar 上放太阳/月亮图标切换按钮

### 新增基础组件（6 个）

| 组件 | 用途 |
|------|------|
| `BaseModal` | 基于 HeadlessUI Dialog，替换所有内联模态框 |
| `BaseButton` | 统一按钮：primary / secondary / danger / ghost，sm/md/lg |
| `ToastNotification` | 右上角滑入通知，替换所有 alert() |
| `ConfirmDialog` | 基于 BaseModal，替换所有 confirm() |
| `SkeletonLoader` | 骨架屏：text / card / list 三种形状 |
| `MobileNav` | 移动端底部 Tab Bar |

### 图标统一

所有内联 SVG 替换为 `@heroicons/vue` 组件。

## 模块二：导航 & 整体布局

### 桌面端导航栏

- 左侧品牌标识（带图标），中部主导航链接（当前页底部指示条），右侧管理员下拉菜单（HeadlessUI Menu）+ 深色模式切换 + 用户下拉菜单
- 背景: `bg-white/80 backdrop-blur-md` 毛玻璃效果 + `sticky top-0`

### 移动端底部 Tab Bar

- 固定底部 5 个入口：首页、错题、历史、单词、更多
- 当前项 indigo 高亮 + 微上浮
- "更多"收纳管理功能和设置
- `md:hidden`，桌面端隐藏

### 页面容器

- 最大宽度从 `max-w-5xl` 调整为 `max-w-6xl`
- 页面切换 `transition` 过渡

## 模块三：首页

### 统计仪表盘

- 4 列统计卡片（题库数、总题目、正确率、待攻克错题）
- 响应式 `grid-cols-2 md:grid-cols-4`
- 卡片: `rounded-xl bg-white shadow-sm`，顶部颜色条纹装饰
- 数字 `text-3xl font-bold`，标签 `text-sm text-gray-500`

### 题库列表卡片

- 每个题库增加进度条展示学习进度
- 按钮带图标，hover 微放大
- 增加题目数量选择快捷入口
- `hover:shadow-md transition-shadow`

## 模块四：答题页（核心体验）

### 布局

- 保留左右分栏（桌面端侧边导航 + 右侧答题区）
- 移动端底部题号导航条保留并优化
- 顶部信息栏：题库名 + 进度百分比 + 渐变色进度条

### 答题交互增强

- 选项卡片化：选中时 `ring-2 ring-indigo-500 bg-indigo-50` + 左侧选中标记
- 正确答案绿色渐变闪烁 + 轻微弹跳；错误答案震动效果
- 进度条渐变色 `from-indigo-500 to-sky-400`
- 移动端左右滑动切换题目
- 侧边栏 `sticky` 固定

### 答题反馈区

- 正确：绿色渐变边框 + 绿色背景图标
- 错误：红色渐变边框 + 选择标红、正确选项标绿
- 翻译和解析区域手风琴折叠动效

## 模块五：学习反馈页面

### 答题结果页

- 正确率圆环计数动画（0% 渐增到实际值）
- 高分（≥80%）撒花效果，低分鼓励文案
- 新增"再来一次"按钮
- 错误题目可展开查看答案和解析

### 错题本

- 顶部掌握率进度条
- 卡片式布局（每张错题独立卡片）替代手风琴
- 标记掌握时卡片滑出消失动效
- 筛选改为 HeadlessUI Menu 下拉菜单

### 答题历史

- 每条记录增加正确率小圆环图标
- 悬停微放大卡片
- 清空历史使用 ConfirmDialog

## 模块六：登录/注册 + 管理页面

### 登录/注册

- 全屏渐变背景 `bg-gradient-to-br from-indigo-50 via-white to-sky-50`
- 品牌标识 + 副标题
- 卡片 `rounded-2xl` + 柔和阴影
- 密码显示/隐藏切换
- 输入框焦点光晕效果

### 管理页面

- 模态框全部替换为 BaseModal（HeadlessUI Dialog）
- 按钮统一使用 BaseButton
- 题目管理桌面端表格布局，移动端卡片列表
- 批量翻译进度展示优化
- 管理入口合并到导航栏下拉菜单
