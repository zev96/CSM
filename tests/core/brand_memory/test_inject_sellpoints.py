"""B1.4：render_brand_facts 按卖点维度优先（命中排前 + 标【主打】，不丢其余）。

直接构造 ModelScope/BrandModelMemory（scripts 含多维度），最贴近被测逻辑。
"""
from csm_core.brand_memory.inject import render_brand_facts, ModelScope
from csm_core.brand_memory.model import BrandModelMemory


def _scope() -> ModelScope:
    mem = BrandModelMemory(
        brand="CEWEY", model="DS18", category="吸尘器", role="主推",
        scripts={
            "动力系统": ["220AW强劲吸力"],
            "防缠绕技术": ["防缠绕刷头不卡毛"],
            "续航时间": ["续航60分钟"],
        },
    )
    return ModelScope(brand="CEWEY", model="CEWEYDS18", role="主推", memory=mem)


def test_sellpoint_dim_goes_first_and_marked():
    facts = render_brand_facts([_scope()], sellpoints=["防缠绕技术"])
    # 命中维度排在其余维度之前
    assert facts.index("防缠绕技术") < facts.index("动力系统")
    assert facts.index("防缠绕技术") < facts.index("续航时间")
    # 命中维度标【主打】，未命中不标
    assert "【主打】防缠绕技术" in facts
    assert "【主打】动力系统" not in facts


def test_other_dims_not_dropped():
    facts = render_brand_facts([_scope()], sellpoints=["防缠绕技术"])
    # 其余维度仍在（不丢）
    assert "动力系统" in facts and "220AW强劲吸力" in facts
    assert "续航时间" in facts and "续航60分钟" in facts


def test_no_sellpoints_unchanged():
    """sellpoints=[]（默认）→ 行为同今天（顺序不变、无【主打】）。"""
    facts_default = render_brand_facts([_scope()])
    facts_empty = render_brand_facts([_scope()], sellpoints=[])
    assert facts_default == facts_empty
    assert "【主打】" not in facts_default
    # 维度按 scripts 原始插入顺序（动力系统在最前）
    assert facts_default.index("动力系统") < facts_default.index("防缠绕技术")
    assert facts_default.index("防缠绕技术") < facts_default.index("续航时间")
