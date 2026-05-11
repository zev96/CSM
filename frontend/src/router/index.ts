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
      path: "/templates",
      name: "templates",
      component: () => import("@/views/TemplatesView.vue"),
      meta: { label: "模板库" },
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
