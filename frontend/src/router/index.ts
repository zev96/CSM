import { createRouter, createWebHashHistory } from "vue-router";

// Hash mode chosen because Tauri serves the SPA from the file:// scheme —
// HTML5 history mode breaks deep links inside the bundled app.

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", redirect: "/home" },
    {
      path: "/home",
      name: "home",
      component: () => import("@/views/HomeView.vue"),
      meta: { label: "工作台" },
    },
    {
      path: "/article",
      name: "article",
      component: () => import("@/views/ArticleView.vue"),
      meta: { label: "创作区" },
    },
    {
      path: "/batch",
      name: "batch",
      component: () => import("@/views/BatchView.vue"),
      meta: { label: "批量生成" },
    },
    {
      path: "/monitor",
      name: "monitor",
      component: () => import("@/views/MonitorView.vue"),
      meta: { label: "监测中心" },
    },
    {
      // 数据中心 —— 从原 MonitorView 的 "report" tab 抽出来的独立 view，
      // LeftNav 单独项；内部仍沿用 RetentionPage / ZhihuRankingPage /
      // BaiduSEOAnalytics 三个 history sub-page，结构跟旧 tab 一致。
      path: "/data-center",
      name: "data-center",
      component: () => import("@/views/DataCenterView.vue"),
      meta: { label: "数据中心" },
    },
    {
      path: "/mining",
      name: "mining",
      component: () => import("@/views/MiningView.vue"),
      meta: { label: "引流" },
    },
    {
      path: "/templates",
      name: "templates",
      component: () => import("@/views/TemplatesView.vue"),
      meta: { label: "模板库" },
    },
    {
      path: "/materials",
      name: "materials",
      component: () => import("@/views/MaterialsView.vue"),
      meta: { label: "素材库" },
    },
    {
      path: "/xhs",
      name: "xhs",
      component: () => import("@/views/XhsEditorView.vue"),
      meta: { label: "小红书" },
    },
    {
      // 结构模板编辑/新建独立页 —— 用户要求 ⋯ → 编辑 / 卡片点击都走 router
      // 而不是原先的 inBuilder modal-takeover 模式。`:id = "new"` = 新建。
      path: "/templates/edit/:id",
      name: "template-edit",
      component: () => import("@/views/TemplateEditView.vue"),
      meta: { label: "编辑模板" },
    },
    {
      // 风格 Skill 编辑/新建独立页 —— 跟结构模板同模式，原 SkillEditModal
      // 改成独立 view（用户要求"和模板库一样的，有单独页面的设计"）。
      path: "/templates/skills/edit/:id",
      name: "skill-edit",
      component: () => import("@/views/SkillEditView.vue"),
      meta: { label: "编辑 Skill" },
    },
    {
      // 最近文档历史页 —— 从 HomeView 的「更多」按钮进入。比首页那张
      // 卡片更完整：所有 7 天内的文档 + 单独的导出位置查看 + 清除记录。
      path: "/recent-history",
      name: "recent-history",
      component: () => import("@/views/RecentHistoryView.vue"),
      meta: { label: "最近文档" },
    },
    {
      path: "/settings",
      name: "settings",
      component: () => import("@/views/SettingsView.vue"),
      meta: { label: "设置" },
    },
    {
      path: "/states",
      name: "states",
      component: () => import("@/views/StatesView.vue"),
      meta: { label: "状态预览" },
    },
  ],
});

export default router;
