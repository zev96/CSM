"""geo_query adapter —— 批量关键词 × 多 AI 平台 fan-out 卡位监控。

fetch() 对 keywords × platforms 做笛卡尔积，逐 cell：provider 采集 →
LLM 抽取 → 信源分类 → 累积 GeoCell。cell 级错误隔离（单 cell 失败记
status 继续）。结束后聚合四大 KPI 写 MonitorResult.metric，明细落
geo_cells/geo_citations。复用 baidu 的 progress_cb / maybe_cancel /
resume_from 约定。

**持久化约定**：fetch() 像 baidu_keyword 一样**只返回** MonitorResult，
由 monitor_loop._run_one 调 save_result 持久化一次。adapter 自己**不**调
save_result —— 否则会与 loop 双写 monitor_results（一行被 geo_cells 引用、
一行带 alert 标志成孤儿，共享 checked_at 时下钻/latest 取行不确定）。
geo 明细则用 adapter 盖的同一个 ``checked_at`` 关联（record_run），不靠
monitor_results.id 外键。

全失败保护：若所有 cell 都失败，返回 status="failed"（而非 ok+rank=-1），
避免 notify 误报"排名跌出 Top-N"。

签名约定对齐 baidu_keyword.fetch —— progress_cb / cancel_token /
resume_from 都是 keyword-only（``*`` 之后），与 monitor_loop 的分发方式
一致。
"""
from __future__ import annotations
import hashlib
import logging
import random
import threading
import time
from datetime import datetime
from typing import Any, Callable

from ..base import MonitorTask, MonitorResult, maybe_cancel, is_cancelled
from ..geo.models import GeoCell
from ..geo.providers.base import get_provider
from ..geo.extract import extract, build_extract_client
from ..geo.fail_reason import classify_fail_reason
from ..geo import metrics
from ..geo import runner as geo_runner
from ..geo import storage as geo_storage
from ..rate_limit import configure_concurrency

logger = logging.getLogger(__name__)


def _sleep_jitter(tok, lo: float, hi: float, *, _rand=random.uniform) -> None:
    """答后「思考间隔」:睡 U(lo,hi) 秒,可被 cancel_token 立即打断(Stop 不等满)。
    hi<=0 视作禁用。用 Event.wait(timeout):命中 Stop 返回 True → maybe_cancel 抛取消。"""
    if hi <= 0:
        return
    delay = _rand(min(lo, hi), max(lo, hi))
    if tok is not None:
        if tok.wait(delay):                 # 期间被 set → 立即抛取消,别再问下一个关键词
            maybe_cancel(tok)
    else:
        time.sleep(delay)


def _shuffled_keywords(keywords: list, task_id: int, checked_day) -> list:
    """确定性洗牌:种子 = sha256(task_id:UTC日期)。同日复现同序(当日断点续跑 resume_from
    索引仍有效),跨日变序防固定顺序指纹。用 sha256 而非 hash(str)——后者被 PYTHONHASHSEED
    随机化,跨进程/续跑会变序、破断点。"""
    key = f"{task_id}:{checked_day.isoformat()}".encode()
    seed = int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
    out = list(keywords)
    random.Random(seed).shuffle(out)
    return out


class GeoQueryAdapter:
    platform = "geo_query"

    def fetch(
        self,
        task: MonitorTask,
        *,
        progress_cb: "Callable[[int, int], None] | None" = None,
        cancel_token: "threading.Event | None" = None,
        resume_from: int = 0,
    ) -> MonitorResult:
        cfg = task.config or {}
        brand = str(cfg.get("brand", "")).strip()
        aliases = list(cfg.get("brand_aliases", []) or [])
        keywords = [k for k in (cfg.get("keywords") or []) if str(k).strip()]
        platforms = list(cfg.get("platforms") or [])
        web_search = bool(cfg.get("web_search", True))
        # 抽取/分析模型固定默认 DeepSeek（前端不再给选项）；测试可在 config 显式传 mock。
        extract_provider = str(cfg.get("extract_provider") or "deepseek")

        if not brand or not keywords or not platforms:
            return MonitorResult(task_id=task.id or 0, checked_at=datetime.utcnow(),
                                 status="failed", rank=-1,
                                 error_message="geo_query 配置缺 brand/keywords/platforms")

        # 关键词顺序洗牌(防固定顺序指纹);确定性种子保当日断点续跑 resume_from 仍有效。
        keywords = _shuffled_keywords(keywords, task.id or 0, datetime.utcnow().date())
        cells_plan = [(kw, plat) for kw in keywords for plat in platforms]
        total = len(cells_plan)

        # 抽取 client 建一次（失败 → 整体失败，因为每个 cell 都要用）
        try:
            client = build_extract_client(extract_provider)
        except Exception as e:
            return MonitorResult(task_id=task.id or 0, checked_at=datetime.utcnow(),
                                 status="failed", rank=-1, error_message=f"抽取 client: {e}")

        # Clamp resume_from to valid range so callers don't need to guard.
        resume_from = max(0, min(int(resume_from), total))

        # 双车道并发调度(API 并发 + RPA 按平台并发)。cell 级隔离与串行版一致:
        # _run_cell 内部把非取消异常兜成 error cell,取消异常上抛由 runner 传导。
        def _int_cfg(key: str, default: int, hi: int) -> int:
            try:
                v = int(cfg.get(key, default) or default)
            except (TypeError, ValueError):
                v = default
            return max(1, min(v, hi))
        api_pool_size = _int_cfg("geo_api_pool_size", 5, 16)
        rpa_conc = _int_cfg("geo_rpa_platform_concurrency", 3, 8)
        consec_skip = _int_cfg("geo_consecutive_fail_skip", 3, 999)
        rpa_retry = _int_cfg("geo_rpa_retry", 1, 5)

        def _int_cfg0(key: str, default: int, hi: int) -> int:   # 允许 0(禁用),下限不夹到 1
            try:
                v = int(cfg.get(key, default))
            except (TypeError, ValueError):
                v = default
            return max(0, min(v, hi))
        jitter_min = _int_cfg0("geo_rpa_jitter_min", 15, 600)
        jitter_max = _int_cfg0("geo_rpa_jitter_max", 45, 600)

        # 预计算每个平台的车道(mode)。get_provider 可能抛(未知/废弃平台 key、
        # provider 模块 import 失败)——逐平台兜住,把失败平台并入 API 车道,让
        # _run_cell 执行时再次 get_provider 抛错并隔离成 error cell(恢复串行版的
        # cell 级隔离:一个坏平台不拖垮整轮),顺带每平台只构造一次 provider。
        mode_map: "dict[str, str]" = {}
        for _p in dict.fromkeys(plat for _, plat in cells_plan):
            try:
                mode_map[_p] = get_provider(_p).mode
            except Exception:
                logger.warning("[geo] 平台 %s 无法构造(未知/模块缺失),归入 API 车道由 _run_cell 兜错", _p)
                mode_map[_p] = "api"

        def _cell(kw: str, plat: str) -> GeoCell:
            return self._run_cell(kw, plat, brand, aliases, web_search, client,
                                  cancel_token=cancel_token)

        maybe_cancel(cancel_token)               # 开跑前先检一次取消(等价串行版首个 maybe_cancel)
        tail = cells_plan[resume_from:]
        cells: list[GeoCell] = geo_runner.run_cells_dual_lane(
            tail, _cell,
            mode_of=lambda p: mode_map.get(p, "api"),
            api_pool_size=api_pool_size,
            rpa_platform_concurrency=rpa_conc,
            progress_cb=progress_cb,
            initial_done=resume_from,
            cancel_token=cancel_token,
            rpa_batch=lambda plat, kws, t: self._rpa_batch(
                plat, kws, t, web_search=web_search, brand=brand, aliases=aliases,
                client=client, consec_skip=consec_skip, rpa_retry=rpa_retry,
                jitter_min=jitter_min, jitter_max=jitter_max),
        )

        # C1 修复:runner 返回后复查取消。API cell 的同步 httpx POST 只在
        # provider.query() 起始处调过一次 maybe_cancel —— 若用户在该 cell 已
        # 发出请求、尚未返回时点 Stop,POST 会照常跑完并记 ok,token 置位这件事
        # 就被在飞请求"吞掉"。这里补一次复查,把「运行期间被取消」正确抛成取消,
        # 而不是悄悄按 status="ok" 持久化(甚至误发告警)。
        maybe_cancel(cancel_token)

        agg = metrics.aggregate(cells)
        # I2：把"够不到平台"和"曝光低"区分开 —— error_cells 让仪表盘知道
        # 是采集失败还是真没提及（现由 metrics._block 算出：total-ok_total，
        # cell 只会是 ok/error/blocked，无 empty，等价旧的 error+blocked 计数）。
        # I3：续抓标记，让 UI 知道这次只跑了断点之后。
        agg["partial_resume"] = resume_from > 0
        # 三类告警：与上次运行比较（上次 = 当前还没存，latest_result 即上一跑）。
        from ..geo.alerts import evaluate_geo_alerts
        from .. import storage as _storage
        prev = _storage.latest_result(task.id) if task.id else None
        prev_metric = prev.metric if prev else None
        agg["alerts"] = evaluate_geo_alerts(agg, prev_metric)
        rank = metrics.representative_rank(cells)

        # checked_at 算一次，同时盖在 MonitorResult 和这批 cell 上 —— 这是
        # geo 表与本次运行的关联键（不靠 monitor_results.id 外键）。
        checked_at = datetime.utcnow()

        # I1：全失败 → status=failed，避免误报"排名跌出 Top-N"告警。
        # （notify.should_alert 在 status != "ok" 时直接 return False —— 已核实。）
        # 即便整体失败也照样 record_run 这批 cell，数据不丢。
        ok_cells = sum(1 for c in cells if c.status == "ok")
        if cells and ok_cells == 0:
            first_err = next(
                (c.raw.get("error") for c in cells if c.status in ("error", "blocked")),
                "全部平台采集失败",
            )
            result = MonitorResult(
                task_id=task.id or 0, checked_at=checked_at,
                status="failed", rank=-1, metric=agg,
                error_message=f"geo_query 全部 cell 失败：{first_err}",
            )
        else:
            result = MonitorResult(
                task_id=task.id or 0, checked_at=checked_at,
                status="ok", rank=rank, metric=agg,
            )

        # 明细落 geo_cells/geo_citations，用同一个 checked_at 关联。
        # adapter 不再 save_result —— monitor_loop._run_one 持久化 result（一次）。
        geo_storage.record_run(task.id or 0, checked_at, cells)
        return result

    def _run_cell(
        self,
        keyword: str,
        platform: str,
        brand: str,
        aliases: list[str],
        web_search: bool,
        client: Any,
        cancel_token: "threading.Event | None" = None,
    ) -> GeoCell:
        try:
            provider = get_provider(platform)
            answer = provider.query(keyword, web_search=web_search, cancel_token=cancel_token)
            if answer.status in ("error", "blocked"):
                return GeoCell(platform=platform, keyword=keyword, status=answer.status,
                               answer_text="",
                               fail_reason=classify_fail_reason(status=answer.status, error=answer.error),
                               raw={"error": answer.error})
            ext = extract(answer, brand=brand, aliases=aliases, client=client)
            return GeoCell(
                platform=platform, keyword=keyword,
                mentioned=ext.mentioned, rank=ext.target_rank, sentiment=ext.sentiment,
                answer_text=answer.answer_text, status="ok", raw=answer.raw,
                citations=ext.citations, recommended=ext.recommended, summary=ext.summary)
        except Exception as e:                       # cell 级隔离
            if is_cancelled(e):                      # 用户 Stop：上抛给 loop 干净处理
                raise                                # 不记 error cell、不打噪声 traceback
            # logger.exception 抓 traceback（漏检 debug 用）；raw 存 repr(e)
            # 保留异常类型（不止 message），下钻时能区分 TimeoutError vs ValueError。
            logger.exception("[geo] cell 失败 kw=%s plat=%s", keyword, platform)
            return GeoCell(platform=platform, keyword=keyword, status="error",
                           fail_reason=classify_fail_reason(status="error", error=repr(e)),
                           raw={"error": repr(e)})

    def _run_cell_on_session(self, query_one, keyword, platform, brand, aliases, client) -> GeoCell:
        """在已开好的 RPA session 上跑单关键词:query_one → extract → cell(逐 cell 隔离,同 _run_cell)。"""
        try:
            answer = query_one(keyword)
            if answer.status in ("error", "blocked"):
                return GeoCell(platform=platform, keyword=keyword, status=answer.status,
                               answer_text="",
                               fail_reason=classify_fail_reason(status=answer.status, error=answer.error),
                               raw={"error": answer.error})
            ext = extract(answer, brand=brand, aliases=aliases, client=client)
            return GeoCell(platform=platform, keyword=keyword,
                           mentioned=ext.mentioned, rank=ext.target_rank, sentiment=ext.sentiment,
                           answer_text=answer.answer_text, status="ok", raw=answer.raw,
                           citations=ext.citations, recommended=ext.recommended, summary=ext.summary)
        except Exception as e:
            if is_cancelled(e):
                raise
            logger.exception("[geo] rpa cell 失败 kw=%s plat=%s", keyword, platform)
            return GeoCell(platform=platform, keyword=keyword, status="error",
                           fail_reason=classify_fail_reason(status="error", error=repr(e)),
                           raw={"error": repr(e)})

    def _rpa_batch(self, plat, plat_keywords, tok, *, web_search, brand, aliases,
                   client, consec_skip, rpa_retry=1, jitter_min=0, jitter_max=0):
        """每平台开一次 session,循环关键词逐 cell yield(浏览器跨关键词复用)。

        登录 gate(§4.3):首关键词返回 blocked = 平台没登录 → 余下关键词全出合成
        blocked cell(不再问,省 goto/等流)。
        连败短路(§4.3):连续 consec_skip 个关键词 status∈{error,blocked} → 余下
        全出合成 cell,携带最后一个失败的 fail_reason。
        合成 cell(§4.5:被跳平台不缺席)status=blocked、携带触发失败的 fail_reason、
        raw.synthetic=True;记 error_cells、不进 KPI 分母、不触发假「跌出」告警。

        契约:必对每个关键词各 yield 一个 (local_idx, cell);provider 构造 / session
        开启(__enter__)/收尾(__exit__)失败 → 该平台每关键词各出一个 error cell(隔离)。
        """
        def _synthetic(start_li, reason, detail):
            for li in range(start_li, len(plat_keywords)):
                yield li, GeoCell(platform=plat, keyword=plat_keywords[li], status="blocked",
                                  fail_reason=reason, raw={"error": detail, "synthetic": True})

        try:
            provider = get_provider(plat)
            session_cm = provider.session(web_search=web_search, cancel_token=tok, retry=rpa_retry)
        except Exception as e:                       # 构造失败:全隔离成 error
            reason = classify_fail_reason(status="error", error=repr(e))
            for li, kw in enumerate(plat_keywords):
                yield li, GeoCell(platform=plat, keyword=kw, status="error",
                                  fail_reason=reason, raw={"error": repr(e)})
            return

        produced = 0
        consec = 0
        try:
            with session_cm as query_one:
                for li, kw in enumerate(plat_keywords):
                    maybe_cancel(tok)
                    cell = self._run_cell_on_session(query_one, kw, plat, brand, aliases, client)
                    produced = li + 1
                    yield li, cell
                    failed = cell.status in ("error", "blocked")
                    # 登录 gate:首关键词就 blocked = 平台没登录,别再问剩下的。
                    if li == 0 and cell.status == "blocked":
                        for li2, syn in _synthetic(li + 1, cell.fail_reason or "not_logged_in",
                                                   f"{plat} 首关键词未登录,跳过剩余关键词"):
                            produced = li2 + 1
                            yield li2, syn
                        return
                    is_interrupt = cell.fail_reason == "interrupted"
                    if failed and not is_interrupt:
                        consec += 1
                    elif not failed:
                        consec = 0
                    # 中断(睡眠唤醒):consec 不变 —— 机器睡眠与平台健康无关,不喂短路计数。
                    if failed and not is_interrupt and consec >= consec_skip:
                        for li2, syn in _synthetic(li + 1, cell.fail_reason or "unknown",
                                                   f"{plat} 连续 {consec} 个关键词失败,短路跳过剩余"):
                            produced = li2 + 1
                            yield li2, syn
                        return
                    # 答后 jitter:仅成功答案(ok/empty)+ 非该平台末个关键词;失败/合成不 jitter(加速短路/收尾)。
                    if cell.status in ("ok", "empty") and li < len(plat_keywords) - 1:
                        _sleep_jitter(tok, jitter_min, jitter_max)
        except Exception as e:                       # session __enter__/__exit__ 失败或中途非隔离异常
            if is_cancelled(e):
                raise
            logger.exception("[geo] rpa session 中断 plat=%s", plat)
            reason = classify_fail_reason(status="error", error=repr(e))
            for li in range(produced, len(plat_keywords)):
                yield li, GeoCell(platform=plat, keyword=plat_keywords[li], status="error",
                                  fail_reason=reason, raw={"error": f"session 中断: {e!r}"})


ADAPTER = GeoQueryAdapter()


# geo RPA 会开有头 Chrome：把 geo_query 并发设为 1，避免两次运行抢同一
# geo_<platform> 持久档 / 同时弹多窗。monitor_loop 用 slot(task.type) 取槽，
# 故必须在「取槽前」配置好——模块级（导入时）配置最稳，不走 baidu 的 in-fetch 懒配。
configure_concurrency("geo_query", 1)
