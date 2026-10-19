# 可复现发布门禁与平台矩阵

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将a1的既有有限候选验证固定为仓库维护工具与平台矩阵，完成定向测试、实际离线执行和本地提交。

**Architecture:** 维护脚本读取固定制品、测试选择与平台声明；从sdist取测试，独立venv离线安装锁定依赖并验证已安装wheel，不引入SDK入口。已验收a1制品及其证据不可覆盖。

**Tech Stack:** Python3.11–3.13标准库、pytest、现有Linux ARM64镜像／Docker。

**Spec:** 用户本轮指令与[Alpha范围](../../releases/0.1.0a1.md)。

## Global Constraints

- 不改src、版本、运行依赖、Schema、身份算法或执行权威；不扩展新功能。
- 函数指纹专项与S2不执行、不标完成，原失败／门槛保留。
- 制品显式指定并核对SHA、版本和输入；不从dist通配选择，不覆盖已有输出目录。
- 默认范围为既有311项基础、16项恢复、两条starter；本机门禁执行与远端CI、模型／服务质量分开。
- Linux ARM64仍2CPU／2GiB无额外swap串行；macOS ARM64/Python3.12实测；AMD64只列待验证，Windows不选。
- 最后单次跳过钩子本地提交，不改持久配置，不推送、上传或建公开Tag。

## Review Focus

- 错误／缺失制品、平台不匹配、依赖漂移和用例变化必须失败，不能靠计数巧合放行。
- 任何失败／错误／skip或JUnit缺失都不返回passed；已有证据不被覆盖。
- 测试只来自固定sdist；安装无checkout／editable泄漏，环境不继承模型密钥／服务地址。
- 维护者可先下载带哈希的依赖wheelhouse；门禁本身只离线安装、不访问模型或真实业务服务。
- 平台声明只是允许执行的范围；只有实际报告才赋予验收结果，不虚报AMD64／远端CI。

### Task 1: 固定输入与失败门槛

- [x] 新增tools/release_gate_manifest.json与依赖锁；保存既有制品及node身份摘要。
- [x] 先写tests/test_release_gate.py，观察错误制品／平台、集合漂移、JUnit失败／skip、输出保护等有效RED。
- [x] 实现tools/release_gate.py：计划查询、制品检查、隔离安装、固定集合执行、starter和完整状态报告；没有发布操作。

### Task 2: 定向与实际门禁

- [x] 单测GREEN，保留RED／GREEN与安装输入。
- [x] 现有a1包执行macOS3.12和Linux3.11→3.12→3.13离线门禁；后者限资源并记录实际退出与峰值。
- [x] 一次独立只读整批复核，必要修复仅限门禁可靠性，不扩SDK。

### Task 3: 文档与提交

- [x] 新增docs/release-gate.md说明精确命令、依赖准备、平台矩阵、失败语义和证据边界；同步发布／当前状态入口。
- [x] 验收记录与SHA清单单独保存，不改原a1制品；Ruff／格式／空白检查通过。
- [x] 单次跳过钩子本地提交并核对工作区／钩子配置，无推送或公开发布。
