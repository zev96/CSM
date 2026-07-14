from csm_core.monitor.geo.models import GeoAnswer, Citation
from csm_core.monitor.geo.extract import extract


class FakeClient:
    def __init__(self, payload: str):
        self._payload = payload
        self.last_user = ""

    def complete(self, *, system: str, user: str, temperature=None) -> str:
        self.last_user = user
        return self._payload


def test_extract_parses_llm_json():
    payload = '''{"mentioned": true, "target_rank": 2, "sentiment": "pos",
      "recommended": [{"name":"比亚迪","position":1},{"name":"小鹏","position":2}],
      "summary": "小鹏智驾被正面推荐"}'''
    ans = GeoAnswer(platform="tongyi", keyword="新能SUV",
                    answer_text="推荐比亚迪、小鹏……",
                    citations=[Citation(url="https://zhuanlan.zhihu.com/p/1", title="知乎文")])
    ext = extract(ans, brand="小鹏", aliases=["XPeng"], client=FakeClient(payload))
    assert ext.mentioned is True
    assert ext.target_rank == 2
    assert ext.recommended[1].is_target is True          # 「小鹏」被标 target
    assert ext.recommended[0].is_target is False
    # 信源来自 answer，分类已补
    assert ext.citations[0].domain == "zhihu.com"
    assert ext.citations[0].source_type == "知乎"


def test_extract_bad_json_falls_back():
    ans = GeoAnswer(platform="kimi", keyword="k", answer_text="小鹏不错")
    ext = extract(ans, brand="小鹏", aliases=[], client=FakeClient("这不是JSON"))
    assert ext.target_rank == -1
    assert ext.summary.startswith("[抽取失败")
    assert ext.mentioned is True  # heuristic: 小鹏 appears in text


def test_extract_retry_succeeds_on_second_attempt():
    """First call returns bad JSON, the strict-retry call returns good JSON -> parsed, not degraded."""
    payloads = ["not json at all",
                '{"mentioned": true, "target_rank": 1, "sentiment": "pos", "recommended": [], "summary": "ok"}']
    class TwoShot:
        def __init__(self): self.calls = 0
        def complete(self, *, system, user, temperature=None):
            p = payloads[self.calls]; self.calls += 1; return p
    c = TwoShot()
    ans = GeoAnswer(platform="tongyi", keyword="k", answer_text="小鹏不错")
    ext = extract(ans, brand="小鹏", aliases=[], client=c)
    assert c.calls == 2
    assert ext.target_rank == 1
    assert not ext.summary.startswith("[抽取失败")


def test_extract_llm_exception_degrades():
    """An LLM call that raises (network/timeout) degrades to the heuristic, not a crash."""
    class Boom:
        def complete(self, *, system, user, temperature=None):
            raise RuntimeError("network down")
    ans = GeoAnswer(platform="tongyi", keyword="k", answer_text="小鹏不错")
    ext = extract(ans, brand="小鹏", aliases=[], client=Boom())
    assert ext.target_rank == -1
    assert ext.mentioned is True            # heuristic: 小鹏 appears in text
    assert ext.summary.startswith("[抽取失败")


def test_extract_downgrades_hallucinated_first_push():
    """回归:LLM 自相矛盾——判 mentioned=true/rank=1(首推),但正文没出现品牌、
    recommended 也没有目标(summary 甚至写「未提及」)。以正文为准撤销幻觉正例。
    对应线上 bug:腾讯元宝显示「首推 #1」但回答根本没提到目标品牌。"""
    payload = ('{"mentioned": true, "target_rank": 1, "sentiment": "pos",'
               '"recommended": [{"name":"空气堡P4","position":1},'
               '{"name":"米家空气净化器","position":2}],'
               '"summary": "回答中未提及目标品牌希喂。"}')
    ans = GeoAnswer(platform="yuanbao", keyword="宠物空气净化器哪款好",
                    answer_text="推荐空气堡P4、米家空气净化器，除味能力都很强……")
    ext = extract(ans, brand="希喂", aliases=[], client=FakeClient(payload))
    assert ext.mentioned is False        # 正文无品牌 + recommended 无目标 → 撤销
    assert ext.target_rank == -1         # 未提及不可能有顺位
    assert ext.sentiment == "na"         # 未提及 → 情感一并归零（不残留「口碑正面」）


def test_extract_keeps_mention_when_brand_in_text():
    """保守:只要品牌名真的出现在正文,即便 recommended 为空也保留 LLM 的判定,
    不做过度下调(避免制造假阴性)。"""
    payload = ('{"mentioned": true, "target_rank": 1, "sentiment": "pos",'
               '"recommended": [], "summary": "希喂被首推"}')
    ans = GeoAnswer(platform="yuanbao", keyword="k",
                    answer_text="综合来看，希喂是很多人的首选……")
    ext = extract(ans, brand="希喂", aliases=[], client=FakeClient(payload))
    assert ext.mentioned is True
    assert ext.target_rank == 1


def test_extract_upgrades_mention_when_alias_in_text():
    """回归:LLM 只认中文主名、不知别名,把「只以别名(CEWEY)出现」的目标判成未提及;
    但别名字面出现在正文 → 上调为提及,顺位取 recommended 里目标条目的位次。
    对应线上 bug:品牌希喂 别名 CEWEY,回答写「CEWEY DS18」被误判未提及、还被当竞品。"""
    payload = ('{"mentioned": false, "target_rank": -1, "sentiment": "pos",'
               '"recommended": [{"name":"CEWEY DS18","position":1},'
               '{"name":"戴森 V12","position":2}],'
               '"summary": "回答中未提及目标品牌希喂"}')
    ans = GeoAnswer(platform="tongyi", keyword="无线吸尘器推荐",
                    answer_text="综合性价比看，CEWEY DS18 是首选，其次是戴森 V12……")
    ext = extract(ans, brand="希喂", aliases=["CEWEY"], client=FakeClient(payload))
    assert ext.mentioned is True          # 别名 CEWEY 字面出现 → 提及
    assert ext.target_rank == 1           # 顺位取 recommended 里 is_target 条目位次
    assert ext.sentiment == "pos"         # 提及了,情感不归零
    # CEWEY DS18 被标为目标(is_target)→ 前端 deriveCompetitors 不会把它当竞品
    assert any(r.is_target and r.name == "CEWEY DS18" for r in ext.recommended)
    assert not any(r.is_target and r.name == "戴森 V12" for r in ext.recommended)


def test_extract_alias_fed_to_llm_prompt():
    """别名应写进给 LLM 的 user prompt（消除别名盲区的治本部分）。"""
    client = FakeClient('{"mentioned": true, "target_rank": 1, "recommended": [], "summary": "x"}')
    ans = GeoAnswer(platform="tongyi", keyword="k", answer_text="CEWEY DS18 不错")
    extract(ans, brand="希喂", aliases=["CEWEY"], client=client)
    assert "CEWEY" in client.last_user and "别名" in client.last_user


def test_extract_no_upgrade_when_only_prose_substring_not_recommended():
    """上调要「正文命中 + LLM 把目标列进 recommended」双证据。仅正文子串命中（品牌名
    恰是常用词「完美」混在描述里）、但 recommended 里没有目标条目 → 不上调，避免哑子串
    盖过 LLM 正确的「未提及」判定。"""
    payload = ('{"mentioned": false, "target_rank": -1, "sentiment": "na",'
               '"recommended": [{"name":"戴森","position":1},{"name":"小米","position":2}],'
               '"summary": "未提及"}')
    ans = GeoAnswer(platform="tongyi", keyword="k",
                    answer_text="这几款吸力都很完美，推荐戴森、小米……")
    ext = extract(ans, brand="完美", aliases=[], client=FakeClient(payload))
    assert ext.mentioned is False
    assert ext.target_rank == -1


def test_extract_keeps_mention_when_target_in_recommended():
    """安全网:正文没有品牌字面串,但 LLM 已把目标列进 recommended(is_target)
    → 保留提及(结构化证据),不下调。"""
    payload = ('{"mentioned": true, "target_rank": 1, "sentiment": "pos",'
               '"recommended": [{"name":"希喂","position":1}],'
               '"summary": "首推希喂"}')
    ans = GeoAnswer(platform="yuanbao", keyword="k",
                    answer_text="综合来看这几个牌子除味都不错。")
    ext = extract(ans, brand="希喂", aliases=[], client=FakeClient(payload))
    assert ext.mentioned is True
    assert ext.target_rank == 1


def test_extract_dedupes_recommended_and_renumbers():
    """确定性兜底:LLM 半合规(同品牌列了多条 / 写法不一 / 位次不连续)时,后端也要把
    recommended 收敛成「一品牌一条 + 位次连续」,否则竞品榜会裂成重复行。"""
    payload = ('{"mentioned": true, "target_rank": 9, "sentiment": "pos",'
               '"recommended": [{"name":"戴森 V12","position":3},'
               '{"name":"戴森V12","position":1},'          # 同一条,只差空格 → 合并,取最优位次 1
               '{"name":"希亦 V800","position":5},'
               '{"name":"希喂 DS18","position":9}],'        # 目标
               '"summary": "x"}')
    ans = GeoAnswer(platform="tongyi", keyword="k",
                    answer_text="推荐 戴森V12、希亦 V800，希喂 DS18 也不错")
    ext = extract(ans, brand="希喂", aliases=["CEWEY"], client=FakeClient(payload))
    names = [(r.name, r.position, r.is_target) for r in ext.recommended]
    assert len(ext.recommended) == 3                 # 戴森两条合并成一条
    assert names[0][1] == 1 and names[1][1] == 2 and names[2][1] == 3   # 位次连续重编号
    assert [n for n, _, _ in names][0].replace(" ", "") == "戴森V12"     # 保留最优位次那条
    # 目标顺位取去重后 recommended 里 is_target 条目的 position（不是 LLM 自由字段的 9）
    tgt = next(r for r in ext.recommended if r.is_target)
    assert ext.target_rank == tgt.position == 3


def test_extract_empty_answer_short_circuits():
    ans = GeoAnswer(platform="kimi", keyword="k", answer_text="", status="empty")
    called = {"n": 0}

    class Counting(FakeClient):
        def complete(self, **kw):
            called["n"] += 1
            return "{}"

    ext = extract(ans, brand="小鹏", aliases=[], client=Counting("{}"))
    assert ext.mentioned is False
    assert called["n"] == 0           # 空答案不调 LLM
