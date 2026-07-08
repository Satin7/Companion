# 问题 & 目标跟踪

> 使用中发现的问题与后续开发目标，分类记录，最后统一处理。

---

## 🐛 待修复问题

- [ ] **聊天对象头像支持更换** — 目前联系人头像仅用纯色圆形代替，需要支持用户自定义更换头像图片。
- [ ] **聊天列表预览文字显示最后一条消息** — 当前 `ChatListActivity` 中联系人的 `preview` 是写死的固定文本，应该动态显示该联系人的最后一条聊天记录。
- [x] **主动消息没有触发** — 根因：`DeepSeekClient.execute()` 直接返回原始 JSON。已修复。
- [x] **AI 回复包含多余信息** — 已添加 `parseContent()` 提取 `choices[0].message.content`。
- [x] **主动消息与回复重叠** — 根因：用户消息后 `ENGAGEMENT_DROP` 仍触发。已通过 InteractionState (PRESENT/ABSENT) + 欲望系统修复：PRESENT 模式下 desire < 0.4 完全抑制主动消息，用户互动满足欲望。
- [ ] **主动消息偶发截断** — LLM 生成主动消息时偶尔会被截断，可能是 `maxTokens` 设置偏小或 API 提前终止，待排查。
- [ ] **发消息频率过高** — PRESENT 模式下仍过于频繁触发。已收紧 PRESENT 下决策逻辑（desire<0.4 完全抑制），需继续观察和调参。

---

## 🎯 后续开发目标

- [ ] **去掉正式版 `[主动关心]` 前缀** — 测试标记，正式版去掉。
- [ ] **注意力节律轮询** — 替代固定间隔为双频叠加 + 随机浮动模型。设计已完成，待实现（见 plan）。
- [ ] **Companion 长期记忆** — 基于对话历史提取和更新用户关键记忆。web-shell 已有基础实现，待深化。
- [x] **InteractionState PRESENT/ABSENT** — 已实现，支持手动开关切换。
- [x] **欲望系统 (Desire System)** — EmotionEngine 感受层已实现欲望水平 + 积累 + 满足。
- [x] **用户消息驱动源** — LifeEngine 环境侧已加入关键词分析（needCare/intensity）。
