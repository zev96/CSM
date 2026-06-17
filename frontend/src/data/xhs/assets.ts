/**
 * 小红书起步素材的类型化加载层（设计稿 §3.3）。
 *
 * resolveJsonModule 会把 JSON 推断成很宽的字面量类型，这里用 `as` 收成业务
 * 接口，让所有面板组件/store 只从这一个文件导入、拿到稳定的类型。素材内容
 * 的合法性由 __tests__/assets.spec.ts 校验。
 */
import templatesRaw from "./templates.json";
import emojiRaw from "./emoji.json";
import titlesRaw from "./titles.json";
import copyRaw from "./copy.json";
import topicsRaw from "./topics.json";
import decorationsRaw from "./decorations.json";

export interface XhsTemplate {
  id: string;
  category: string;
  name: string;
  title: string;
  body: string;
  topics: string[];
}

export interface EmojiGroup {
  key: string;
  name: string;
  emojis: string[];
}
export interface XhsCode {
  code: string;
  label: string;
}
export interface EmojiLibrary {
  curatedGroups: EmojiGroup[];
  unicodeGroups: EmojiGroup[];
  xhsCodes: XhsCode[];
}

/** 标题分类 / 文案分组 / 装饰分组：统一「key + name + items(字符串数组)」。 */
export interface ItemGroup {
  key: string;
  name: string;
  items: string[];
}
/** 话题分组：tags 而非 items（元素不含前导 #）。 */
export interface TopicGroup {
  key: string;
  name: string;
  tags: string[];
}

export const TEMPLATES = templatesRaw as XhsTemplate[];
export const EMOJI = emojiRaw as EmojiLibrary;
export const TITLE_CATEGORIES = (titlesRaw as { categories: ItemGroup[] }).categories;
export const COPY_GROUPS = (copyRaw as { groups: ItemGroup[] }).groups;
export const TOPIC_GROUPS = (topicsRaw as { groups: TopicGroup[] }).groups;
export const DECORATION_GROUPS = (decorationsRaw as { groups: ItemGroup[] }).groups;

/**
 * 模板分类（按出现顺序去重）。注意这里是 `string[]`，与其它 `{key,name}[]`
 * 分组导出形状不同 —— 模板分类没有独立 key，分类名本身即 key 即显示名，
 * 故 TemplatePanel 用 `c => ({ key: c, name: c })` 适配 CategoryTabs。
 */
export const TEMPLATE_CATEGORIES: string[] = [...new Set(TEMPLATES.map((t) => t.category))];

