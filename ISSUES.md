# 问题 & 目标跟踪

> 使用中发现的问题与后续开发目标，分类记录，最后统一处理。

---

## 🐛 待修复问题

- [ ] **聊天对象头像支持更换** — 目前联系人头像仅用纯色圆形代替，需要支持用户自定义更换头像图片。
- [ ] **聊天列表预览文字显示最后一条消息** — 当前 `ChatListActivity` 中联系人的 `preview` 是写死的固定文本，应该动态显示该联系人的最后一条聊天记录。
- [x] **主动消息没有触发** — 根因：`DeepSeekClient.execute()` 直接返回原始 JSON，`TriggerDecision.fromJson()` 找不到 `shouldSpeak` 字段永远返回 `noAction()`。已在 v0.2.0 修复。
- [x] **AI 回复包含多余信息** — 根因：同上，`DeepSeekClient` 漏掉了 JSON 解析步骤，返回了完整响应体。已添加 `parseContent()` 提取 `choices[0].message.content`。

---

## 🎯 后续开发目标

- [ ] **未读消息气泡提示** — 聊天列表每个联系人显示未读消息数量角标。

- [ ] **注意力节律轮询** — 将定时轮询改为模拟人类注意力自然节律的模型，基于 ultradian rhythm（~90分钟周期）、注意力衰减曲线（beta/theta 脑波转换）、以及"偶然想起"的随机性，设计更自然的主动触达时机。参考：BRAC（Basic Rest-Activity Cycle）、Pomodoro 25分钟注意力窗口、Zeigarnik 效应。
