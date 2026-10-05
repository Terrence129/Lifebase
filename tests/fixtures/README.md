# Test Fixtures

**只放合成的、脱敏的测试数据。**

红线（见 AGENTS.md）：
- 禁止放入任何真实个人数据（聊天记录、照片、位置、交易……）。
- 合成数据示例：手工构造的小型 conversations.json、随机 GPS 点、占位图片。
- 任何新 collector 的测试都必须能靠 fixtures 跑通，不依赖真实导出。
