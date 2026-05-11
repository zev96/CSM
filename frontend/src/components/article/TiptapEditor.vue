<script setup lang="ts">
/**
 * Markdown-friendly rich text editor wrapping Tiptap.
 *
 * Why Tiptap over textarea (B3 polish item):
 *  - Headings preserve their visual hierarchy in-place instead of showing
 *    raw ``# Foo`` markers — the user reads what they'll publish.
 *  - Future hooks for inline decorations (Skill highlight, dedup hits)
 *    require ProseMirror's decoration API; textarea is a dead-end for that.
 *  - Built-in undo/redo stack survives v-model swaps.
 *
 * Two-way data flow: ``modelValue`` is plain text (markdown-ish). On
 * mount we feed it through a tiny mdToHTML pass; on edit we feed back
 * via htmlToMd. Both are *deliberately* lossy — Tiptap's full markdown
 * round-trip needs a heavier extension (@tiptap/extension-markdown is a
 * paid extra). For our use the article is mostly headings + paragraphs +
 * bold, which converts cleanly.
 *
 * Read-only mode is for the draft tab (毛坯文 from compose_draft).
 */
import { onBeforeUnmount, shallowRef, watch } from "vue";
import { Editor, EditorContent } from "@tiptap/vue-3";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import CharacterCount from "@tiptap/extension-character-count";

const props = withDefaults(
  defineProps<{
    modelValue: string;
    placeholder?: string;
    readonly?: boolean;
    minHeight?: number;
  }>(),
  { minHeight: 440 },
);

const emit = defineEmits<{
  (e: "update:modelValue", v: string): void;
  (e: "characterCount", n: number): void;
}>();

const editor = shallowRef<Editor | null>(null);
// True while we're applying an external value change — prevents the
// Tiptap onUpdate handler from echoing it back as a model update.
let suppressEcho = false;

function mdToHtml(md: string): string {
  if (!md) return "";
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];
  let para: string[] = [];
  const flushPara = () => {
    if (para.length) {
      out.push(`<p>${para.join("<br/>")}</p>`);
      para = [];
    }
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (line === "") {
      flushPara();
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      flushPara();
      const level = h[1].length;
      out.push(`<h${level}>${escapeHtml(h[2])}</h${level}>`);
      continue;
    }
    para.push(escapeHtml(line).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>"));
  }
  flushPara();
  return out.join("\n");
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function htmlToMd(html: string): string {
  if (!html) return "";
  // Walk the parsed DOM. Lossy: keeps headings, paragraphs, bold, line breaks.
  const tpl = document.createElement("template");
  tpl.innerHTML = html;
  const out: string[] = [];
  function visit(node: Node, ctx: { inHeading: number }): string {
    if (node.nodeType === Node.TEXT_NODE) {
      return node.textContent ?? "";
    }
    if (!(node instanceof HTMLElement)) return "";
    const tag = node.tagName.toLowerCase();
    if (/^h[1-6]$/.test(tag)) {
      const level = Number(tag[1]);
      const text = childText(node, { inHeading: level });
      out.push(`${"#".repeat(level)} ${text.trim()}`);
      return "";
    }
    if (tag === "p") {
      const text = childText(node, ctx);
      out.push(text.trim());
      return "";
    }
    if (tag === "br") return "\n";
    if (tag === "strong" || tag === "b") return `**${childText(node, ctx)}**`;
    if (tag === "em" || tag === "i") return `*${childText(node, ctx)}*`;
    return childText(node, ctx);
  }
  function childText(n: Node, ctx: { inHeading: number }): string {
    let s = "";
    n.childNodes.forEach((c) => {
      s += visit(c, ctx);
    });
    return s;
  }
  tpl.content.childNodes.forEach((c) => {
    visit(c, { inHeading: 0 });
  });
  return out.join("\n\n").replace(/\n{3,}/g, "\n\n").trim();
}

function init() {
  editor.value = new Editor({
    content: mdToHtml(props.modelValue),
    editable: !props.readonly,
    extensions: [
      StarterKit.configure({
        // We render headings ourselves; keep the others default.
        codeBlock: false,
        blockquote: false,
        horizontalRule: false,
      }),
      Placeholder.configure({
        placeholder: props.placeholder ?? "起飞后这里会显示成稿。可直接编辑。",
        emptyNodeClass: "is-editor-empty",
      }),
      CharacterCount.configure({}),
    ],
    onUpdate({ editor: ed }) {
      if (suppressEcho) return;
      const md = htmlToMd(ed.getHTML());
      emit("update:modelValue", md);
      emit("characterCount", ed.storage.characterCount.characters());
    },
  });
  emit(
    "characterCount",
    editor.value!.storage.characterCount.characters(),
  );
}

watch(
  () => props.modelValue,
  (v) => {
    if (!editor.value) return;
    const current = htmlToMd(editor.value.getHTML());
    if (current === v) return;
    suppressEcho = true;
    editor.value.commands.setContent(mdToHtml(v), false);
    suppressEcho = false;
  },
);
watch(
  () => props.readonly,
  (r) => editor.value?.setEditable(!r),
);

onBeforeUnmount(() => editor.value?.destroy());

// Init on first render — happens after the script setup body runs.
init();
</script>

<template>
  <EditorContent
    :editor="editor ?? undefined"
    class="tiptap-host font-serif-cn"
    :class="{ 'is-readonly': readonly }"
    :style="{ minHeight: `${minHeight}px` }"
  />
</template>

<style scoped>
.tiptap-host {
  font-size: 14px;
  line-height: 1.7;
  color: var(--ink);
  /*
    Flex-fill so when the host is placed inside a `flex-1 min-h-0`
    parent (e.g. the V1 white editor card on Article view), the inner
    ProseMirror absorbs the full available height — clicking anywhere
    inside the card focuses the editor instead of dumping the cursor
    in a tiny strip at the top.
  */
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
}
.tiptap-host :deep(.ProseMirror) {
  outline: none;
  min-height: inherit;
  padding: 4px 0;
  flex: 1 1 auto;
}
.tiptap-host :deep(.ProseMirror p) {
  margin: 0 0 1em 0;
}
.tiptap-host :deep(.ProseMirror h1),
.tiptap-host :deep(.ProseMirror h2),
.tiptap-host :deep(.ProseMirror h3) {
  font-family: "Plus Jakarta Sans", "Noto Sans SC", sans-serif;
  letter-spacing: -0.02em;
  font-weight: 700;
  margin: 1.4em 0 0.6em 0;
  line-height: 1.25;
}
.tiptap-host :deep(.ProseMirror h1) {
  font-size: 22px;
}
.tiptap-host :deep(.ProseMirror h2) {
  font-size: 18px;
}
.tiptap-host :deep(.ProseMirror h3) {
  font-size: 15.5px;
}
.tiptap-host :deep(.ProseMirror strong) {
  color: var(--primary-deep);
}
.tiptap-host :deep(.ProseMirror ul),
.tiptap-host :deep(.ProseMirror ol) {
  padding-left: 1.5em;
  margin: 0 0 1em 0;
}
/* Placeholder styling — only shows when editor is empty. */
.tiptap-host :deep(.ProseMirror .is-editor-empty:first-child::before) {
  content: attr(data-placeholder);
  color: var(--ink-3);
  float: left;
  height: 0;
  pointer-events: none;
}
.is-readonly :deep(.ProseMirror) {
  background: var(--card-2);
  padding: 12px;
  border-radius: var(--radius-inner);
  border: 1px solid var(--line);
}
</style>
