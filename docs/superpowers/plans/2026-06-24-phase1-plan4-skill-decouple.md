# Phase 1 — Plan 4：Skill 解耦（人设 / 去AI味 + `role` 字段）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把巨型 `家电科普博主.md`（人设 + 去AI味 + 硬编码 CEWEY DS18 品牌事实三合一）拆成可复用的「人设」「去AI味」两块 + 一个去品牌的合并 skill，并给 skill 加 `role` 元数据字段——品牌事实改由 Plan 1-3 的记忆注入提供。

**Architecture:** 纯后端 + 内容工程。`skills_service.Skill` 加 `role`（frontmatter 解析，缺省 `persona`，向后兼容 loader 既有的「字段缺失优雅降级」）。合并 skill = **原地改写** `家电科普博主.md` 保留 id（`default_skill_id: 家电科普博主` 的模板零迁移、自动继承去品牌内容），同时另出独立 `家电科普人设.md`(persona) / `去AI味.md`(humanize) 供 Phase 2 skill 链用。内容守卫测试钉死「3 个 skill body 不含任何品牌事实 token + role 正确」。前端 role 暴露与素材库 UI 留 Plan 5。

**Tech Stack:** Python 3.11+ / pydantic / `python-frontmatter` / pytest / Markdown 内容编辑。

参考 spec：[Phase 1 设计稿 §5](../specs/2026-06-23-phase1-brand-model-memory-design.md)；总计划表 [Plan 4 行](2026-06-23-phase1-brand-memory.md)。

---

## 关键设计决定（执行前已与用户确认 2026-06-24）

1. **合并策略 = 原地改写保留 id**：`examples/skills/家电科普博主.md` 原地改写成「人设 + 去AI味」去品牌合并 skill，**id 不变**。`default_skill_id: 家电科普博主` 的模板引用**零迁移**、自动继承去品牌内容——**不需要任何模板迁移脚本**（spec §5 列的迁移脚本被本策略消解）。另出独立 `家电科普人设.md`(persona) 与 `去AI味.md`(humanize) 供 Phase 2 skill 链。**本检出已有 `templates/导购·吸尘器·三品-r2j7.json` 用 `"default_skill_id": "家电科普博主"`（第 6 行）——id 不变 = 它零改动仍解析（B1 第 4 个测试钉死）。**
2. **Plan 4 = 纯后端 + 内容**：`role` 字段走 model/service/routes/API；**前端 `SkillEditView` 暴露 role + 素材库 tab 全留 Plan 5**（与 Plan 3「纯后端，UI 留 Plan 5」一致）。skill 以 `.md` 形式在团队盘作者维护，role 直接写 frontmatter 即可，前端非必需。
3. **品牌事实从所有 skill 删除**：`家电科普博主.md` 466-816 行的 CEWEY DS18 参数/认证/话术/痛点/框架全删（现由 Plan 1-3 注入）。其余 3 个 example skill 本就无品牌事实，**不动**。
4. **去品牌 ⇒ 必须配合 `brand_memory.inject=ON`**：去品牌后 skill body 不再带 facts，CEWEY 事实**只能**靠 Plan 3 注入（默认 OFF）。故**应用到真实盘时必须同时开 `brand_memory.inject`**，否则成稿丢失型号事实。本 PR **只改版本控制的 example 种子**，不碰用户真实盘 → 真实行为在用户跑 gated runbook（拷新 skill + 开 inject）前不变，无意外回归。
5. **`role` 默认 `persona`，update 省略 role 时保留原值**：旧 skill 无 `role` 视为 `persona`。**关键**：现有前端 PATCH 不发 role，若 update 把缺省当 persona 会把 humanize skill 误降级——故 `update_skill(role=None)` 必须**读现值保留**，不回退。
6. **真实盘 `D:\家电组共享\DATA\skills` 应用 = gated runbook**（备份 + 拷 3 个 .md + 开 inject），**不在本 PR 执行**，待用户放行（同 Plan 2 vault 回填边界）。

---

## File Structure

- **Modify** `sidecar/csm_sidecar/services/skills_service.py` — `Skill` 加 `role`；`list_skills`/`get_skill` 解析 frontmatter `role`（缺省 `persona`）；`to_dict` 含 `role`；`_write_skill` 写 `role`；`create_skill(role="persona")`；`update_skill(role=None→保留现值)`。
- **Modify** `sidecar/csm_sidecar/routes/skills.py` — `SkillPayload.role: str = "persona"`；`SkillUpdatePayload.role: str | None = None`；透传。
- **Modify** `examples/skills/家电科普博主.md` — 原地改写：去品牌合并 skill（人设 + 去AI味），加 frontmatter `role: persona`。
- **Create** `examples/skills/家电科普人设.md` — persona（人设 + 风格/结构/禁区约束，去品牌）。
- **Create** `examples/skills/去AI味.md` — humanize（24 模式 + 灵魂注入 + 检查清单 + 质量评分，去品牌通用）。
- **Test (Modify)** `sidecar/tests/test_skills_routes.py` — role 解析/默认/round-trip/preserve。
- **Test (Create)** `sidecar/tests/test_skill_decoupling.py` — 内容守卫：3 个 skill body 无品牌 token + role 正确 + 可解析非空。
- **Doc** 本计划「真实盘应用」节 = gated runbook（不执行）。

---

# Unit A：后端 `role` 字段

> 一个内聚的后端改动：model + loader + writer + create/update + routes。先做（Unit B 的内容守卫测试依赖 `get_skill().role`）。

### Task A1: `Skill.role` 解析（model + loader）

**Files:**
- Modify: `sidecar/csm_sidecar/services/skills_service.py`
- Test: `sidecar/tests/test_skills_routes.py`（追加）

- [ ] **Step 1: 写失败测试**（追加到 `test_skills_routes.py` 末尾）

```python
def test_skill_role_defaults_persona_when_absent(tmp_path):
    (tmp_path / "x.md").write_text("# 无 frontmatter\n本体", encoding="utf-8")
    sk = skills_service.get_skill(tmp_path, "x")
    assert sk is not None
    assert sk.role == "persona"
    assert sk.to_dict()["role"] == "persona"


def test_skill_role_parsed_from_frontmatter(tmp_path):
    (tmp_path / "y.md").write_text(
        "---\nname: 去AI味\nrole: humanize\n---\n本体", encoding="utf-8")
    sk = skills_service.get_skill(tmp_path, "y")
    assert sk is not None
    assert sk.role == "humanize"
    assert sk.to_dict()["role"] == "humanize"
```

> 注：`test_skills_routes.py` 顶部已 `from csm_sidecar.services import skills_service`（沿用既有 import；若缺则补）。

- [ ] **Step 2: 跑测试确认失败**

Run（**注意 PYTHONPATH**，见文末「测试调用」）：`pytest sidecar/tests/test_skills_routes.py::test_skill_role_defaults_persona_when_absent -v`
Expected: FAIL — `AttributeError: 'Skill' object has no attribute 'role'`

- [ ] **Step 3: 写实现**

`skills_service.py` —— `Skill` dataclass 加字段（放在 `tone` 之后、`path` 之前以匹配现序）：
```python
@dataclass
class Skill:
    id: str           # filename stem
    name: str         # frontmatter.name or id
    desc: str         # frontmatter.desc or ""
    tone: str         # frontmatter.tone or ""
    role: str         # frontmatter.role or "persona"（人设 persona / 去AI味 humanize）
    path: Path
    body: str         # markdown body without frontmatter
```
`to_dict` 加 `"role": self.role,`（在 `"tone"` 后、`"uses"` 前）：
```python
        d: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "desc": self.desc,
            "tone": self.tone,
            "role": self.role,
            "uses": 0,  # field exists in prototype mock data; sidecar returns 0 (砍 per A2)
        }
```
`list_skills` 与 `get_skill` 两处 `Skill(...)` 构造各加一行（缺省 `persona`）：
```python
            role=str(fm.get("role") or "persona"),
```
（`list_skills` 里在 `tone=...` 之后、`path=...` 之前；`get_skill` 同样位置。）

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest sidecar/tests/test_skills_routes.py -k role -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add sidecar/csm_sidecar/services/skills_service.py sidecar/tests/test_skills_routes.py
git commit -m "feat(skills): Skill.role 字段（frontmatter 解析，缺省 persona）"
```

---

### Task A2: 写入 + create/update 保留 role

**Files:**
- Modify: `sidecar/csm_sidecar/services/skills_service.py`
- Test: `sidecar/tests/test_skills_routes.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_create_skill_persists_role(tmp_path):
    skills_service.create_skill(
        tmp_path, "hz", name="去AI味", desc="", tone="", role="humanize", body="正文")
    assert skills_service.get_skill(tmp_path, "hz").role == "humanize"


def test_update_skill_preserves_role_when_omitted(tmp_path):
    skills_service.create_skill(
        tmp_path, "hz", name="去AI味", desc="", tone="", role="humanize", body="正文")
    # 模拟现有前端 PATCH：不带 role
    skills_service.update_skill(
        tmp_path, "hz", name="去AI味2", desc="d", tone="", body="新正文")
    sk = skills_service.get_skill(tmp_path, "hz")
    assert sk.role == "humanize"      # 关键：保留，不回退 persona
    assert sk.name == "去AI味2" and sk.body.strip() == "新正文"


def test_update_skill_changes_role_when_given(tmp_path):
    skills_service.create_skill(
        tmp_path, "p", name="人设", desc="", tone="", role="humanize", body="x")
    skills_service.update_skill(
        tmp_path, "p", name="人设", desc="", tone="", body="x", role="persona")
    assert skills_service.get_skill(tmp_path, "p").role == "persona"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest sidecar/tests/test_skills_routes.py::test_create_skill_persists_role -v`
Expected: FAIL — `TypeError: create_skill() got an unexpected keyword argument 'role'`

- [ ] **Step 3: 写实现**

`_write_skill` 加 `role` 参数并写入 frontmatter：
```python
def _write_skill(
    skill_dir: Path,
    skill_id: str,
    name: str,
    desc: str,
    tone: str,
    role: str,
    body: str,
) -> Path:
    skill_dir.mkdir(parents=True, exist_ok=True)
    md = skill_dir / f"{skill_id}.md"
    post = frontmatter.Post(
        body or "",
        **{
            "name": name or skill_id,
            "desc": desc or "",
            "tone": tone or "",
            "role": role or "persona",
        },
    )
    md.write_bytes(frontmatter.dumps(post).encode("utf-8"))
    return md
```
`create_skill` 加 `role: str = "persona"` 关键字参数，转传 `_write_skill`：
```python
def create_skill(
    skill_dir: Path | None,
    skill_id: str,
    *,
    name: str,
    desc: str,
    tone: str,
    body: str,
    role: str = "persona",
) -> Skill:
    if not skill_dir:
        raise ValueError("skill_dir is not configured")
    md = skill_dir / f"{skill_id}.md"
    if md.exists():
        raise FileExistsError(f"skill id already exists: {skill_id}")
    _write_skill(skill_dir, skill_id, name, desc, tone, role, body)
    skill = get_skill(skill_dir, skill_id)
    assert skill is not None
    return skill
```
`update_skill` 加 `role: str | None = None`，**None 时读现值保留**：
```python
def update_skill(
    skill_dir: Path | None,
    skill_id: str,
    *,
    name: str,
    desc: str,
    tone: str,
    body: str,
    role: str | None = None,
) -> Skill:
    if not skill_dir:
        raise ValueError("skill_dir is not configured")
    md = skill_dir / f"{skill_id}.md"
    if not md.exists():
        raise FileNotFoundError(f"skill not found: {skill_id}")
    if role is None:                        # 前端未传 role → 保留现值，不回退
        current = get_skill(skill_dir, skill_id)
        role = current.role if current else "persona"
    _write_skill(skill_dir, skill_id, name, desc, tone, role, body)
    skill = get_skill(skill_dir, skill_id)
    assert skill is not None
    return skill
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest sidecar/tests/test_skills_routes.py -v`
Expected: PASS（含既有路由测试——确认无回归）

- [ ] **Step 5: 提交**

```bash
git add sidecar/csm_sidecar/services/skills_service.py sidecar/tests/test_skills_routes.py
git commit -m "feat(skills): create/update 透传 role + update 省略时保留现值"
```

---

### Task A3: routes 透传 role

**Files:**
- Modify: `sidecar/csm_sidecar/routes/skills.py`
- Test: `sidecar/tests/test_skills_routes.py`（追加，用既有 client fixture）

- [ ] **Step 1: 写失败测试**（参照文件内既有路由测试的 client fixture 用法；下例假定 fixture 名 `client` 且其 skill_dir 已配置——**实现者先读文件确认 fixture 名与配置方式，照搬**）

```python
def test_route_create_and_get_round_trips_role(client):
    r = client.post("/api/skills", json={
        "id": "去AI味", "name": "去AI味", "role": "humanize", "body": "正文"})
    assert r.status_code == 201
    assert r.json()["role"] == "humanize"
    g = client.get("/api/skills/去AI味")
    assert g.json()["role"] == "humanize"


def test_route_patch_without_role_preserves(client):
    client.post("/api/skills", json={
        "id": "hz2", "name": "去AI味", "role": "humanize", "body": "a"})
    r = client.patch("/api/skills/hz2", json={"name": "去AI味", "body": "b"})
    assert r.status_code == 200
    assert r.json()["role"] == "humanize"   # PATCH 不带 role → 保留
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest sidecar/tests/test_skills_routes.py::test_route_create_and_get_round_trips_role -v`
Expected: FAIL — 返回的 dict 无 `role` 键 / 或 `SkillPayload` 拒绝 `role` 字段（视 pydantic extra 配置）

- [ ] **Step 3: 写实现**

`routes/skills.py` —— payload 加字段：
```python
class SkillPayload(BaseModel):
    id: str
    name: str
    desc: str = ""
    tone: str = ""
    role: str = "persona"
    body: str = ""


class SkillUpdatePayload(BaseModel):
    name: str
    desc: str = ""
    tone: str = ""
    role: str | None = None
    body: str = ""
```
`create_skill` 路由调用加 `role=payload.role,`；`update_skill` 路由调用加 `role=payload.role,`（None 由 service 保留）。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest sidecar/tests/test_skills_routes.py -v`
Expected: PASS（全部）

- [ ] **Step 5: 提交**

```bash
git add sidecar/csm_sidecar/routes/skills.py sidecar/tests/test_skills_routes.py
git commit -m "feat(skills): routes 透传 role（POST 默认 persona / PATCH None 保留）"
```

---

# Unit B：Skill 内容拆解（去品牌）

> 内容工程。源文件 = `examples/skills/家电科普博主.md`（824 行）。先写内容守卫测试（TDD 契约），再据章节清单授权 3 个文件。**依赖 Unit A 的 `role` 字段。**

### Task B1: 内容守卫测试（先红）

**Files:**
- Test (Create): `sidecar/tests/test_skill_decoupling.py`

- [ ] **Step 1: 写失败测试**

```python
"""内容守卫：拆解后的 3 个 skill 必须去品牌 + role 正确。

钉死 Plan 4 的核心契约——品牌事实已从 skill 移除（改由 Plan 1-3 注入），
并验证 role 元数据。读真实 example 种子文件（即交付物本身）。
"""
from pathlib import Path

from csm_sidecar.services import skills_service

# 任一 token 出现 = 品牌事实泄漏（应来自记忆注入，不应硬编码进 skill）
BRAND_FACT_TOKENS = [
    "CEWEY", "希喂", "DS18", "220AW", "12万转", "35kPa", "35000Pa",
    "1700L", "555nm", "22项黑科技", "Quad-Stage", "Dual-HEPA", "DS 2.0",
]
DECOUPLED = {
    "家电科普博主": "persona",   # 原地改写=合并 skill
    "家电科普人设": "persona",
    "去AI味": "humanize",
}


def _skills_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        cand = parent / "examples" / "skills"
        if cand.is_dir():
            return cand
    raise RuntimeError("找不到 examples/skills")


def test_decoupled_skills_exist_and_nonempty():
    d = _skills_dir()
    for sid in DECOUPLED:
        sk = skills_service.get_skill(d, sid)
        assert sk is not None, f"{sid} 缺失"
        assert sk.body.strip(), f"{sid} body 为空"


def test_decoupled_skills_have_no_brand_facts():
    d = _skills_dir()
    for sid in DECOUPLED:
        sk = skills_service.get_skill(d, sid)
        for tok in BRAND_FACT_TOKENS:
            assert tok not in sk.body, f"{sid} 仍含品牌事实 token: {tok!r}"


def test_decoupled_skill_roles():
    d = _skills_dir()
    for sid, role in DECOUPLED.items():
        assert skills_service.get_skill(d, sid).role == role, f"{sid} role 应为 {role}"


def test_inrepo_template_default_skill_still_resolves():
    """零迁移保证：default_skill_id: 家电科普博主 的模板 id 未变，仍解析到 skill。"""
    import json
    import pytest
    d = _skills_dir()
    tpl = d.parent.parent / "templates" / "导购·吸尘器·三品-r2j7.json"
    if not tpl.exists():
        pytest.skip("模板不在本检出")
    sid = json.loads(tpl.read_text(encoding="utf-8")).get("default_skill_id")
    assert sid == "家电科普博主"
    assert skills_service.get_skill(d, sid) is not None, f"模板引用 {sid} 断链"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest sidecar/tests/test_skill_decoupling.py -v`
Expected: FAIL — `家电科普人设`/`去AI味` 尚不存在（None）；`家电科普博主` 仍含品牌 token 且无 role frontmatter。

- [ ] **Step 3: 不写实现**（守卫测试先红，内容在 B2-B4 补齐）
- [ ] **Step 4: 提交测试**

```bash
git add sidecar/tests/test_skill_decoupling.py
git commit -m "test(skills): 拆解内容守卫（去品牌 + role），先红"
```

---

### Task B2: 创建 `去AI味.md`（humanize）

**Files:**
- Create: `examples/skills/去AI味.md`

通用「去除 AI 写作痕迹」内容，**与任何产品无关**。从源文件 `家电科普博主.md` 抽下列章节（**逐字搬运**，仅把开头 persona 句改成产品无关的通用引子）：

- 通用引子（改写源 L6-13 的处理步骤，去掉「知乎家电博主」，改为：「收到需要去AI味处理的文本时：1.识别AI模式 2.重写问题片段 3.保留含义 4.维持语调 5.注入灵魂」）
- `## 核心规则速查`（源 L14-23）
- `## 个性与灵魂`（源 L37-67，含「缺乏灵魂的迹象 / 如何增加语调 / 改写前后示例」）
- `## 内容模式` 1-6（源 L68-152）
- `## 语言和语法模式` 7-12（源 L154-229）
- `## 风格模式` 13-18（源 L231-311）
- `## 交流模式` 19-21（源 L313-353）
- `## 填充词和回避` 22-24（源 L355-391）
- `## 快速检查清单`（源 L394-404）
- `## 处理流程`（源 L407-418）
- `## 质量评分`（源 L429-444）
- `## 完整示例`（源 L448-464，**通用 AI 味软件更新示例**——非 CEWEY）
- `## 输出`（源 L821-823）

frontmatter：
```yaml
---
name: 去AI味
desc: 去除 AI 写作痕迹（24 模式 + 灵魂注入 + 质量评分），与产品无关可复用
tone: neutral
role: humanize
---
```

- [ ] **Step 1: 写文件**（按上述章节清单 + frontmatter；保留源文的 H2 标题与示例文字）
- [ ] **Step 2: 校验解析 + 去品牌**

Run: `pytest sidecar/tests/test_skill_decoupling.py -v`
Expected: `去AI味` 相关断言转绿（exist/role/no-brand）；`家电科普人设` 仍红（未建）。

- [ ] **Step 3: 提交**

```bash
git add examples/skills/去AI味.md
git commit -m "feat(skills): 拆出 去AI味.md（humanize，24 模式通用去品牌）"
```

---

### Task B3: 创建 `家电科普人设.md`（persona）

**Files:**
- Create: `examples/skills/家电科普人设.md`

家电博主**人设 + 风格/结构/禁区约束**，去品牌。组成：

- persona 引子（源 L1-4：「你是一位知乎家电博主，精通无线吸尘器家电知识和营销软文写作。收到毛坯文后进行**润色改写**（不是重写/扩写/删减），使文字更自然、更有人味。」——已足够通用，照搬）
- `## 风格约束`（源 L25-29：段落密度 / 数字保留 / 品牌型号**原样保留**）
- `## 结构约束`（源 L31-35：保留所有 H2 及顺序 / 段尾可加小结钩子但不新增 H2 / 不新增虚构场景评论数据）
- `## 写作禁区`（**从源 L784-806 去品牌提炼**，逐条保留通用项、**删品牌特定项**）：
  - 保留：不直接出现「广告/推广/赞助/软文」；不编造不存在的认证或检测机构；不用绝对化用语（最/第一/100%/根治/永不衰减/零缺陷）；不点名攻击具体竞品，用「行业/市面上/很多品牌」泛指；禁止引流话术（点击下方链接/关注账号/抽奖/免费领）；禁止 emoji；禁止破折号、双引号；不添加毛坯文里没有的产品信息。
  - **删除**（品牌特定，违背去品牌）：「品牌名统一使用 CEWEY/希喂、型号统一 DS18」；「口语风不堆砌 DS 2.0/Quad-Stage 等专有名词」；「所有参数必须来自本技能包信息库」（事实改由注入提供）。
- `## 输出`（源 L821-823）

frontmatter：
```yaml
---
name: 家电科普人设
desc: 知乎家电博主人设 + 风格/结构/禁区约束（去品牌，事实由记忆注入提供）
tone: rational
role: persona
---
```

- [ ] **Step 1: 写文件**
- [ ] **Step 2: 校验**

Run: `pytest sidecar/tests/test_skill_decoupling.py -v`
Expected: `去AI味` + `家电科普人设` 转绿；`家电科普博主` 仍红（尚未改写）。

- [ ] **Step 3: 提交**

```bash
git add examples/skills/家电科普人设.md
git commit -m "feat(skills): 拆出 家电科普人设.md（persona，去品牌禁区约束）"
```

---

### Task B4: 原地改写 `家电科普博主.md`（合并 skill，保留 id）

**Files:**
- Modify: `examples/skills/家电科普博主.md`

改写成**人设 + 去AI味合并、去品牌**——= `家电科普人设` 的 persona 章节 + `去AI味` 的 humanize 章节（去重引子/输出），**整段删除源 L466-816 的 CEWEY DS18 品牌事实 dump 与 L809-816 品牌特定注意事项**。组成顺序：

- frontmatter（**新增**）：
  ```yaml
  ---
  name: 家电科普博主（人设+去AI味）
  desc: 家电博主人设 + 去AI味 合并 skill；品牌事实由记忆注入提供（Plan 1-3）
  tone: rational
  role: persona
  ---
  ```
- persona 引子（源 L1-4）
- `## 风格约束` + `## 结构约束`（源 L25-35）
- `## 核心规则速查`（源 L14-23）
- `## 个性与灵魂`（源 L37-67）
- 24 模式（源 L68-391）
- `## 快速检查清单`（源 L394-404）
- `## 处理流程`（源 L407-418）
- `## 质量评分`（源 L429-444）
- `## 完整示例`（源 L448-464，通用示例）
- `## 写作禁区`（B3 同款去品牌版）
- `## 输出`（源 L821-823）

> **不得保留**任何品牌 token（守卫测试钉死）。这是 `default_skill_id: 家电科普博主` 模板的落点——内容质量靠「persona + 去AI味」+ 运行时注入的型号事实。

- [ ] **Step 1: 改写文件**
- [ ] **Step 2: 跑内容守卫 + skill 路由全绿**

Run: `pytest sidecar/tests/test_skill_decoupling.py sidecar/tests/test_skills_routes.py -v`
Expected: PASS（3 个 skill 全部 exist/role/no-brand；A 单元路由无回归）

- [ ] **Step 3: 提交**

```bash
git add examples/skills/家电科普博主.md
git commit -m "refactor(skills): 家电科普博主 原地改写为去品牌合并 skill（保留 id，删 CEWEY 事实）"
```

---

### Task B5: 整包回归 + 既有 skill 不退化

**Files:** 无新增（验证步）

- [ ] **Step 1: 全 skill 相关测试**

Run: `pytest sidecar/tests/test_skills_routes.py sidecar/tests/test_skill_decoupling.py -v`
Expected: PASS

- [ ] **Step 2: 确认其余 3 个 example skill 未被动**

Run: `git status --porcelain examples/skills/`
Expected: 仅 `家电科普博主.md`(M) / `家电科普人设.md`(??) / `去AI味.md`(??)；`知乎科普人设.md`/`知乎软文博主.md`/`百家公众号博主.md` **不在列**。

- [ ] **Step 3: 抽查既有 generate 装配未被破坏**

Run: `pytest sidecar/tests/ -k "skill or generate" -q`
Expected: PASS（`get_skill().body` 流入 `user_skill_prompt` 的路径不受影响；`role` 是附加字段）

---

## 真实盘应用（gated runbook — 不在本 PR 执行，待用户放行）

> 同 Plan 2 vault 回填：本 PR 只改版本控制的 `examples/skills/` 种子。用户真实盘 `D:\家电组共享\DATA\skills`（`cfg.skill_dir`）的应用是**团队盘改动**，从重、需放行。

1. **先整盘备份** `D:\家电组共享\DATA\skills` 到 vault 外目录。
2. 把 3 个更新后的种子拷过去覆盖/新增：`家电科普博主.md`（覆盖）、`家电科普人设.md`（新增）、`去AI味.md`（新增）。
3. **同时在「设置」开 `brand_memory.inject`**（否则去品牌 skill 不再带 facts、且若 `factcheck` 也开则去 inject 的成稿会缺事实）——决定 4 的硬依赖。
4. 抽 1-2 个 `default_skill_id: 家电科普博主` 的模板生成验证：CEWEY 事实经注入出现、去AI味仍生效、参数无编造（接 Plan 3 factcheck 门禁）。
5. 模板 `default_skill_id` **无需改**（id 未变）。

---

## 门禁 / 验收对照（spec §9.6）

| spec §9 验收 | 本 Plan 对应 | 证据 |
|---|---|---|
| 6. `家电科普博主.md` 拆分 + 迁移后 CEWEY 文章不退化、去AI味仍生效 | B4 原地改写（保留 id 零迁移）+ B2 去AI味独立 | 内容守卫绿 + gated runbook 步 4 A/B |
| §5 产出三 skill（人设/去AI味/合并） | B2/B3/B4 | `test_decoupled_skills_exist` |
| §5 品牌事实从所有 skill 删除 | B2/B3/B4 去品牌 | `test_decoupled_skills_have_no_brand_facts` |
| §5/§7 `role` 字段（旧无 role 视为 persona） | A1-A3 | `test_skill_role_*` |
| §5 迁移：模板 default_skill_id 不断链 | 原地改写保留 id（零迁移） | `git status` 确认 id 文件名未变 |

---

## Self-Review（对照 spec §5/§7 + 已确认决定）

- **Spec 覆盖**：§5 三 skill→B2/B3/B4；§5 去品牌→守卫测试；§5/§7 role→A1-A3；§5 迁移不断链→原地改写保留 id（消解迁移脚本）；§7「SkillEditView role」→**明确留 Plan 5**（决定 2）；真实盘→gated runbook。✅
- **占位符扫描**：无 TBD；后端步含完整代码；内容步给「章节清单 + 源行号 + frontmatter + 守卫断言」作为完整契约（prose 不逐字贴入计划，由守卫测试钉死）。✅
- **类型一致性**：`Skill.role` 在 A1 定义，A2 `_write_skill`/`create`/`update`、A3 routes、B 守卫 `get_skill().role` 一致引用；`create_skill(role="persona")` 默认 vs `update_skill(role=None→保留)` 语义在 A2 测试与 A3 路由测试一致验证。✅
- **回归边界**：role 为附加字段，`user_skill_prompt` 注入路径不变；前端不动（PATCH 不带 role 由 service 保留）；其余 3 个 example skill 不动（B5 git status 守）。✅

---

## 测试调用（关键——sidecar import 路径）

worktree 跑 sidecar 测试必须设 PYTHONPATH，否则 `csm_sidecar` 解析到主仓 `D:\CSM\sidecar`（editable 装）。单行：

```
cd D:\CSM\.claude\worktrees\phase1-plan4; $env:PYTHONPATH="D:\CSM\.claude\worktrees\phase1-plan4;D:\CSM\.claude\worktrees\phase1-plan4\sidecar"; D:/CSM/.venv/Scripts/python.exe -m pytest <args>
```
