# dev15 消息交接与 A2A

MessageBus/Inbox/Outbox 是交接边界，不拥有 Run 状态。默认 InMemoryMessageBus；真实 RedisStreamsBus 用消费组/PEL/显式 claim/ack，消息包含稳定 message_id、非秘密路由和有限 JSON。publish 去重冲突可识别；ack 仅在应用权威返回结果后执行。Redis 不自动保证恰好一次业务操作，也不自动提供 Local 多 Coordinator。

SQLiteOutbox/Inbox 提供独立耐久交接参考实现；记录、待投递、已投递和消费回执保留稳定身份。重复交接交给 Engine command_id 去重，消费侧保存结果后 ack；已接受但未确认的命令重投递仍返回原回执。控制分发支持 submit/approve/cancel/reconcile，明确 wakeup 与执行推进的职责。

A2A 固定0.3 JSON-RPC polling 子集（message/send、tasks/get、tasks/cancel），ASGI 服务发布 Agent Card，不宣称 SSE/push/gRPC/企业认证。请求身份经宿主认证绑定，不信任模型提供的 Scope。Task 对应真实 Run，稳定 messageId 对应提交去重，结果与 pending 映射清晰；完成 Task 不复活。失败和协议错误脱敏。

A2AClient 支持借用/owned HTTP 客户端、固定卡片能力/版本、有限超时与响应；不隐藏提交重试。A2AToolSource 接入既有受管理 ToolSource/ToolPolicy，使远程 Agent 调用仍有明确效果、审批和幂等身份。网络超时留下未知调用，原请求身份可查；远端回执不伪装成当地业务效果恰好一次。

验收包含真实 Redis 组消费/claim/replay，Outbox 接收后进程退出，重复 command/冲突及消费后 ack；真实或 ASGI HTTP A2A 的发现/send/get/cancel、重复 messageId、错误 Task/auth/响应，以及 ToolSource 审批/效果链路。Linux/macOS、本地可信配置预览；生产 Broker 配置/ACL/多租户认证另验收。
