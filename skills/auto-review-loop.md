# Auto Review Loop (电商评价自动生成)

## Goal
根据运营提供的“产品 ID"或“卖点素材”，自动生成 15-30 字真实评价 + 5 张买家秀图片，并推送到钉钉群。

## Workflow

### 1. 数据准备 (Data Preparation)

检查用户输入：

**情况 A：用户只给了"产品 ID" (全自动模式)**
1. 调用 `browser_goto("https://item.taobao.com/item.htm?id={ID}")` 打开商品页。
2. 调用 `browser_exec` 运行以下 Python 代码提取数据：
   ```python
   # 简单的数据提取逻辑 (需根据实际电商页面结构调整)
   # 返回 JSON: {"selling_points": "...", "image_url": "http://...", "title": "..."}
   ```
3. 获取返回的 JSON 数据。

**情况 B：用户直接给了“卖点文字”和“参考图片”**
1. 直接从对话中提取卖点文字和图片链接/路径。

### 2. 执行生成 (Execution)

一旦获得了 `{selling_points}` 和 `{image_url}`：

1. 调用项目中的 Python 工具：
   ```bash
   python tools/dingtalk_reviewer.py "{product_id}" "{selling_points}" "{image_url}"
   ```
   *(注：该脚本会自动调用大模型生成 5 条文案 + 5 张图，并推送到钉钉)*

### 3. 反馈结果 (Feedback)

*   **成功**：回复用户“评价已生成并推送到钉钉群”。
*   **失败**：如果浏览器抓取失败，提示用户“无法打开商品页，请手动提供卖点文字”。

## Notes
*   确保环境变量 `DASHSCOPE_API_KEY` 和 `DINGTALK_WEBHOOK` 已配置。
*   如果用户要求修改评价风格（如：更夸张一点），修改传给 Python 脚本的 prompt 即可。
