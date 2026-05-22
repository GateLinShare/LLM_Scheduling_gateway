---
name: changelog
description: 生成本轮修改的结构化 JSON 变更日志，用于 AI 上下文交接与快速回顾
---

你正在为本轮代码修改生成结构化变更日志。该日志帮助其他 AI 快速了解实现了什么、为什么实现、怎么实现的——跨会话快速恢复上下文。

## 步骤

1. **收集变更**：运行 `git diff` 查看未提交的变更，`git diff --cached` 查看已暂存的变更。同时回顾对话上下文中每项变更的意图。

2. **归类功能与修复**：将变更分为：
   - **features**：新增的功能能力（每项分配唯一 ID，如 F1、F2...）
   - **bugfixes**：实现过程中修复的缺陷（每项分配唯一 ID，如 B1、B2...）

3. **逐项记录**：
   - `title`：简短名称
   - `description`：做了什么、为什么做
   - `files`：对每个修改的文件，列出具体的代码变更要点（不是逐行 diff，而是总结关键逻辑变更）

4. **记录配置变更**：如果 runtime_config、环境变量或数据库 schema 有变更，记录精确的键值对。

5. **记录关键概念**：记录仅从代码中不易理解的领域知识——时间边界、计算公式、优先级体系等。

6. **写入 JSON 文件**，路径为 `docs/changelog_YYYY-MM-DD_<主题>.json`，使用以下结构：

```json
{
  "version": "1.0",
  "date": "YYYY-MM-DD",
  "author": "Claude Code",
  "summary": "一句话中文摘要",
  "features": [
    {
      "id": "F1",
      "title": "功能名称",
      "description": "做了什么以及为什么",
      "files": [
        {
          "path": "相对路径/to/file",
          "changes": ["具体变更1", "具体变更2"]
        }
      ]
    }
  ],
  "bugfixes": [
    {
      "id": "B1",
      "title": "缺陷名称",
      "description": "什么问题以及如何修复",
      "file": "相对路径/to/file",
      "fix": "修复方式说明"
    }
  ],
  "config_changes": {
    "文件路径": { "键": "值" }
  },
  "key_concepts": {
    "概念名": "解释说明"
  }
}
```

## 规则

- 文件名格式：`changelog_YYYY-MM-DD_<主题缩写>.json`
- 描述使用中文
- `files[].changes` 写**具体逻辑摘要**，不要逐行粘贴 diff
- 描述中要包含"为什么做"，不只是"做了什么"
- 跨层变更要完整记录：如果一个功能涉及后端+前端+配置，三项都要记录
- 实现过程中发现的 bug 单独记录到 `bugfixes` 中
- `key_concepts` 记录对 AI 来说不明显的领域知识——时间边界、计算公式、优先级规则等
- 保持 JSON 格式合法、结构清晰，JSON 内不要包含 markdown 代码围栏
