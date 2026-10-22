export type Locale = "zh" | "en";
export const locales: Locale[] = ["zh", "en"];
export const brand = {
  name: "Relf-Agent",
  fullName: "Reliable and Extensible Lifecycle Framework for Intelligent Agents",
  meaning: {
    zh: "可靠、可扩展的智能体全生命周期框架。",
    en: "A reliable, extensible lifecycle framework for intelligent agents.",
  },
  tagline: {
    zh: "灵活构建智能体，可靠运行智能应用。",
    en: "Build intelligent agents. Run them reliably.",
  },
} as const;
export { repository, repositoryUrl, repositoryInfo } from './repository.mjs';
export const guideSlugs = [
  "overview",
  "installation",
  "quickstart",
  "app-tutorial",
  "concepts",
  "models-tools",
  "sessions-memory",
  "user-input",
  "workflows",
  "integrations",
  "operations",
  "recovery",
  "api-reference",
  "testing",
] as const;
export const guideNames: Record<Locale, string[]> = {
  zh: [
    "能力总览",
    "安装与环境",
    "快速开始",
    "连续应用教程",
    "核心概念",
    "模型与工具",
    "会话、记忆与 RAG",
    "持久用户输入",
    "工作流与多 Agent",
    "集成与扩展",
    "运行与部署",
    "审批与恢复",
    "API 与 CLI 参考",
    "测试与评估",
  ],
  en: [
    "Capabilities overview",
    "Installation",
    "Quickstart",
    "Application tutorial",
    "Core concepts",
    "Models & tools",
    "Sessions, memory & RAG",
    "Durable user input",
    "Workflows & teams",
    "Integrations & extensions",
    "Runtime & deployment",
    "Approval & recovery",
    "API & CLI reference",
    "Testing & evaluation",
  ],
};
export type GuideSlug = (typeof guideSlugs)[number];
export const guideGroups: {
  title: Record<Locale, string>;
  slugs: GuideSlug[];
}[] = [
  {
    title: { zh: "开始使用", en: "Start here" },
    slugs: ["overview", "installation", "quickstart", "app-tutorial", "concepts"],
  },
  {
    title: { zh: "构建能力", en: "Build capabilities" },
    slugs: ["models-tools", "sessions-memory", "user-input", "workflows", "integrations"],
  },
  {
    title: { zh: "运行与维护", en: "Operate & maintain" },
    slugs: ["operations", "recovery"],
  },
  {
    title: { zh: "查询与验证", en: "Reference & verification" },
    slugs: ["api-reference", "testing"],
  },
];
export const featuredGuideSlugs: GuideSlug[] = [
  "overview",
  "quickstart",
  "models-tools",
  "sessions-memory",
  "workflows",
  "operations",
];
export const guideDescriptions: Record<Locale, Record<GuideSlug, string>> = {
  zh: {
    overview: "按业务目标选择能力，了解默认起点与可选组件。",
    installation: "源码安装、Python 环境与可选依赖。",
    quickstart: "从安装到审批恢复，完成第一个离线任务。",
    "app-tutorial": "围绕一个工单，逐步加入模型、会话、知识、记忆与编排。",
    concepts: "理解 Run、Action、Session 与执行权威。",
    "models-tools": "选择模型协议，注册自己的 Python 工具。",
    "sessions-memory": "组织多轮对话、长期事实与可追溯的知识检索。",
    "user-input": "持久保存问题，回复原任务，并在重启后继续。",
    workflows: "组合静态图、有界并行、Plan 与 Team。",
    integrations: "连接 MCP、HTTP、CLI、Workspace 与 Skills。",
    operations: "选择执行后端，管理版本、额度与资源生命周期。",
    recovery: "处理审批、重启、未知效果与常见故障。",
    "api-reference": "查询常用 SDK、CLI、返回值和错误处理契约。",
    testing: "运行离线应用测试、协议兼容检查与有界任务评估。",
  },
  en: {
    overview:
      "Choose capabilities by task, with clear defaults and optional components.",
    installation:
      "Source installation, Python setup and optional dependencies.",
    quickstart:
      "Complete an offline task from installation through approval and recovery.",
    "app-tutorial": "Add models, conversations, knowledge, facts and workflows to one ticket app.",
    concepts: "Understand runs, actions, sessions and execution authority.",
    "models-tools": "Choose a model protocol and register your Python tools.",
    "sessions-memory":
      "Organize conversations, lasting facts and traceable knowledge retrieval.",
    "user-input": "Persist questions, reply to the original task and continue after restart.",
    workflows: "Compose static graphs, bounded parallelism, plans and teams.",
    integrations: "Connect MCP, HTTP, CLI, workspaces and skills.",
    operations:
      "Choose a backend. Manage versions, limits and resource ownership.",
    recovery:
      "Handle approvals, restarts, uncertain effects and common failures.",
    "api-reference": "Look up common SDK and CLI calls, return values and error contracts.",
    testing: "Run offline application tests, protocol checks and bounded task evaluations.",
  },
};
export function localeHref(path: string, target: Locale): string {
  return /^\/(zh|en)(\/|$)/.test(path)
    ? path.replace(/^\/(zh|en)(?=\/|$)/, `/${target}`)
    : `/${target}/`;
}
export function siteMetadata(
  site: string | undefined,
  path: string,
): { indexable: boolean; canonical?: string; origin?: string } {
  if (!site?.trim()) return { indexable: false };
  const url = new URL(site);
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.pathname !== "/" ||
    url.search ||
    url.hash ||
    url.username ||
    url.password
  ) {
    throw new Error(
      "PUBLIC_SITE_URL must be an HTTP(S) origin without a path, credentials, query or fragment.",
    );
  }
  return {
    indexable: true,
    canonical: new URL(path, url.origin).href,
    origin: url.origin,
  };
}
