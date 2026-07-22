# 变更日志

本项目所有可见变更都记录在这里。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

### Added

- **模板支持「结构版本」**：一个模板里可以放多套推荐区结构（版本1·口碑权威型 / 版本2·功能拆解型……），生成时随机抽中一套。每篇文章只抽一次签，主推和竞品消费的是同一个结果，**不可能出现主推用版本1、竞品用版本2**。块上标「所属版本」决定它在哪些版本里出现，不标 = 每个版本都出现。素材还没铺齐的版本可以先「禁用」，不进抽签池。保存模板时会做结构检查：跨版本引用（如测试框架跟随的主推块在该版本不可见）直接拦下不让存，漏标版本、某版本没有专属内容、竞品池前面没有主推等疑似问题给出警告。老模板不受任何影响——没有版本组时行为与之前逐字节一致。
- **十大排名榜单的产品卡片**：主推块和竞品池新增「小节」配置后进入卡片模式，输出「`### 层级标签 TOP1. 品牌 型号` + 若干加粗小节」的结构化卡片，替代旧的「推荐理由：一段话」形态。主推每个小节独立配目录与筛选（可以把「分维度硬核测评」拆成除醛/消毒/过敏原/体验四段，只有首段带标题）；竞品素材改为**每个竞品一张卡片笔记**（frontmatter 写品牌/型号/层级标签，正文用 `## 小节名` 分节，节内 ①②③ 放多份候选内容），生成时先筛出小节齐全的竞品再随机抽，每个点各自随机内容。同一竞品写多张卡时互为候选（随机用一张）。一张覆盖了多版本点的「超集卡」可以同时服务多个版本，不用每版本复制素材。支持同一榜单区放多个竞品池（TOP2-3 详细、TOP4-10 简略），排位连续编号且不会重复出同一款产品。
- **卡片正文保留关键数据加粗**：素材里写的 `**703.7 m³/h**` 这类标粗现在会原样出现在卡片正文里（此前解析器会无条件剥掉所有加粗）。仅卡片模式生效，其余素材路径行为不变。
- **AI 润色不再破坏榜单排版**：文章含卡片区时，润色环节会收到「不得改动标题行、加粗小节名与分段」的硬约束；万一模型仍然把卡片揉平，该轮润色会被自动作废回退（后续环节仍在完好结构上继续润色）。整篇润色、逐段重跑、批量生成三条路径都生效。
- **竞品卡覆盖度检查**：模板编辑器的竞品池面板新增按钮，写模板时就能看到哪些竞品够格上榜、谁缺哪一节、每个小节实际绑到了卡里的哪个 `##` 标题、文件名有没有撞车、型号写法是不是把同一款产品分裂成了两个竞品。补完素材点一次即可复查（每次都会先刷新一遍资料库索引）。
- **文章页显示采样告警**：竞品缺料清单、素材不足这类提示此前只存在后台数据里，现在直接显示在组装预览上方。

### Changed

- **榜单数量对不上时直接中止生成**：竞品卡池要求固定数量（写死或在生成表单里填死）而合格竞品不够时，不再静默少出几张卡，而是中止并给出逐个竞品的缺料清单（缺哪个小节、哪个文件）。用「随机区间」设置数量时仍按可用数量出稿并给出提示。
- **竞品身份识别更宽容**：同一竞品的多张卡片笔记型号写法不一致（`竞品-戴森V8` / `戴森V8` / `戴森 V8` / 全角字符）现在会被认成同一个竞品，不再拆成两个各缺一半小节的「幽灵竞品」。型号只差连字符（`X9` 与 `X-9`）时不自动合并，但会提示疑似同款重复上榜。

### Fixed

- **标题序号多出一个顿号**：模板里把标题块的序号填成「一、」时，生成的文章会渲染成「## 一、、{关键词}怎么选」——渲染时无条件又补了一个顿号。现在序号自带分隔符（顿号、句号、点、冒号、右括号等）或以空格结尾时不再重复添加；填「三」这种光秃秃的写法仍会自动补成「三、」，行为不变。出厂模板「导购·吸尘器·三品」的前两个标题就是这种写法，受此影响。
- **会变的图标不跟着变**：界面上那些「成功打勾 / 失败打叉」「开始 / 暂停」之类会随状态切换的小图标，此前只在组件第一次渲染时决定画哪个，之后状态变了图标也不变。受影响的有：评论编辑器的编辑/播放按钮、百度采集设置里的导入结果与连接测试结果徽标（结果已经变成失败，图标还停在打勾上）。同时补上缺失的「隐藏」眼睛图标。
- **改过的竞品素材没有立刻生效**：把卡片里写错的参数订正成同样长度（`550` 改成 `660`、`口啤` 改成 `口碑`）后，生成的文章仍会印出旧内容，直到重启程序；覆盖度检查同理会显示旧的小节。现已改为跟着资料库索引一起失效，改完立刻生效。
- **覆盖度检查现在会显示每个小节实际绑到了卡里的哪个 `##` 标题**：小节名与标题不完全一致时（比如卡里写「口碑」、模板里写「市场口碑数据」）会列出来，方便发现绑错。
- **多张卡的层级标签不一致时的提示改为如实说明**：此前写「按路径序取用某个」，实际每次生成会随机用其中一张卡、标签跟着那张卡走。
- 主推卡小节找不到素材时，报错会带上筛选条件（此前只说目录，筛选值敲错一个字无从查起）；没设置资料库目录时覆盖度检查给中文提示而不是 Python 报错原文。

## [0.7.5] - 2026-07-21

### Changed

- **同一条视频的多条评论任务共享一次评论区抓取**：任务身份键加入评论文本后，同一条视频下常有多条评论任务——此前每轮监测会把同一个评论区完整抓 N 次（本地模式同账号反复翻同一视频是显眼的机器人特征，API 模式每页计费直接 ×N）。现在同一轮内同视频只真实抓取一次，其余任务直接对共享快照匹配各自评论；抓取失败也整组统一报同一原因，不再对疑似风控的端点连环重试。API 模式的「命中即停」同步升级为组感知：扫到该视频**所有**在监测的评论都命中（或翻满检索深度）才停，快照因此对组内每个任务都完整。共享快照最长保留 15 分钟、只用来覆盖同一轮派发里排队靠后的同视频任务，且每个任务对同一份快照最多消费一次——重复运行同一个任务总会触发真实的重新抓取，下一轮定时监测也照常全新抓取。
- **评论列表给同视频多任务加辨识度**：同一条视频下的多条评论任务，在批次的评论列表里此前完全同名（行名都派生自视频链接尾段），只能点进详情才能分辨。现在每行第二行直接显示所监测评论的文本片段（悬停看全文，新导入还没跑过首轮的任务也能显示）；相关文案同步从「视频」口径改为「评论」口径——列头「视频名字」改「视频 / 评论」、面包屑「视频列表」改「评论列表」、条数徽标明确为「N 条评论」、详情页标题改「评论监测详情」。

### Fixed

- **评论留存批量导入丢行（导入 65 行只建出 39 个任务）**：任务身份此前按「平台 + 视频链接」唯一，同一条视频下的多条评论会在逐行提交时互相覆盖——每个链接只留最后一行的评论，其余静默丢失且提交全部显示成功。现在任务身份改为「平台 + 视频链接 + 评论文本」：同视频不同评论各建独立任务，同视频同评论重复导入仍去重更新；知乎 / 百度等非评论任务的「重复添加即更新」语义不变。**已被合并吞掉的评论无法自动找回：把原表格重新批量导入一次即可补齐缺失的任务，不会产生重复。注意两点：① 重导会按导入弹窗的当前设置（定时 / 启用 / 理想排名）更新已存在的同名任务，重导时请把这些选项选得与原来一致；② 导入完成后先手动跑一轮监测——新补的任务在首轮监测前会被计成「未监测」，暂时拉低批次留存率显示，跑完一轮即恢复正常。**
- **GitHub 发布说明被压成单行**：v0.7.1 起的每个 Release 页面里，本文件的版本段落被工作流拼接成了一整行（小标题与条目全挤在一起、无法阅读）。现在按行显式换行拼接，且发布说明提取失败会直接让流水线红灯而不是发出空说明。(#176)

## [0.7.4] - 2026-07-15

### Added

- **素材库多产品线通用化（净化器等新产品线全面支持）**：素材库此前假设单一吸尘器产品线——净化器参数录了却显示 0/32、参数分组写死吸尘器字段、型号混排没有产品线维度、录入树看不到净化器的空骨架文件夹。现在：品牌型号页新增产品线下拉筛选（与顶栏汇总联动，产品线消失后筛选自愈不死锁）；参数按笔记真实 H2 小节分组渲染（吸尘器 7 节 / 净化器 5 节 / 未来新产品线自动正确），删除写死的吸尘器分组；摘要卡按产品线精选指标（净化器 = 价格 / 颗粒物 CADR / 甲醛 CADR / 噪音 / 适用面积，吸尘器沿用原 5 项，未知产品线通用兜底），无参数型号显示空态而非一排空横线；录入树改为全目录枚举（中间层可见、两个「产品参数」不再同名歧义），空文件夹自动借兄弟产品线的表单模板并显示「模板借自」来源提示，AI 拆条菜单与写入白名单同步过滤、不随枚举放宽。(#174)

### Fixed

- **词表外品牌的型号参数恒空（净化器录了参数却显示 0/32）**：型号识别在「登记」与「参数解析」两条链路各写一套、判定不一致，DARZ / UORRIS / 亚都等内置词表外品牌的参数被解析侧整体丢弃。现在统一走同一条「frontmatter 优先、文件名兜底」的识别链，词表外品牌参数完整可见；连字符型号也不再被截断、误合并成不存在的「幻影型号」。(#174)
- **GEO 卡位判定与回答对不上（「没提到我，却显示首推 #1」）**：抽取层此前原样采信大模型自由输出的「是否提及 / 排名」字段，模型自相矛盾时（回答里根本没出现品牌，却判成首推第 1）脏数据会一路污染曝光 SOC、首推率、结论条与竞品表。现在一律以「品牌名或别名是否真的出现在回答正文里」这一可核验证据做校正：凭空判提及的撤销、只以别名出现而被漏判的补回；且判为「未提及」时排名与口碑一并归零，不再出现「未提及」却显示「口碑正面」的自相矛盾。(#173)
- **GEO 品牌别名不生效，自家产品被当成竞品**：抽取时只把中文主名告诉大模型、不给别名，导致回答里只写英文别名（如品牌「希喂」的别名「CEWEY」，回答写成「CEWEY DS18」）时被判未提及，还被列进竞品榜。现在别名会一并告知模型，且只要别名在正文中出现就正确归到你的品牌名下。(#173)
- **GEO 竞品榜同一品牌裂成多行**：大模型返回的是产品型号名、且各平台写法不一（「戴森」/「戴森V8 Cyclone」/「戴森 V12」，「希亦 V800」/「希亦V800」只差一个空格），竞品矩阵按原始字符串分组导致同一品牌重复出现。现在抽取只取品牌名并做确定性去重与位次重编号（模型不听话也不会裂行），前端按归一化名合并、且每个平台只取该品牌的最优位次（避免均值被同平台多个型号拉高）。(#173)
- **GEO 同一屏各视图口径不一**：热力矩阵此前独立读推荐列表里的目标标记来定位次，会与概览卡的「未提及」自相矛盾；竞争结论文案又按原始名精确匹配，出现「图里 3 个平台第 1、文案却说 2 个」。目标位次统一以 cell 的提及 + 排名为唯一真相源，竞品位次统一走同一套归一化匹配。(#173)

### Notes

- **升级后首轮可能出现一波「参数已更新」提示，属预期**：旧版对词表外品牌型号的参数指纹一直建立在空数据上，本版修复识别链后指纹回归真实——升级后第一轮检测会对这批型号（约数十个）各提示一次「参数已变更」，一次性自愈、之后不再重复，无需处理。(#174)
- **GEO 指标升级后会一次性跳变，别误读成真实排名变化**：竞品去重把位次从产品级压缩到品牌级（如 14 条产品 → 约 8 个品牌），目标卡位数字会变小、首推率 / top3 率会一次性抬升；反方向，凭空判提及的「幻觉首推」被撤销后曝光 SOC / 首推率也可能一次性下降——两者都只是口径修正，AI 的回答并没有变。另外修复只作用于新采集：已存库的旧数据不自愈，需对相关关键词重跑一轮采集才会纠正（纠正性重跑可能触发一次性的「掉出首推」类告警，属预期）。(#173)

## [0.7.3] - 2026-07-13

本版是「百度 SEO 排名监控」大修 + 「GEO 采集」四期升级两大主题的合并发布。

### Added

- **GEO 采集「失败原因看得懂」**：以前采集失败 / 够不到平台只有一句模糊提示，现在按 9 类具体原因归类（未登录 / 流式超时 / 选择器漂移 / 被限流 / 配额耗尽 / 内容被安全过滤 / 网络异常 / 中断 / 未知）并在结果卡直接显示；首个关键词未登录、或连续多次失败时短路跳过该平台余下关键词，不再让你干等。(#164)
- **GEO「本次采集完整度」+ 7 天滚动中位**：概览新增「本次采集覆盖 M / N 平台」，覆盖不全时标红「数据不完整」，一眼看清这批数据可不可信；趋势图叠加 7 天滚动中位虚线（≥2 天才画），忽略单日抖动看典型水平。(#167)
- **GEO 多采样投票 + 翻转复核**：同一（关键词 × 平台）可采多次投票产出更稳的结论（是否提及取多数、命中排名取中位、情感取多数）。采样次数默认每格 1 次（K=1，与旧行为等价）、可按需调高，主要面向豆包 / 通义等 API 快平台；**翻转复核默认开启**——即便每格只采 1 次，凡相对上一轮发生提及翻转的格子都会自动补采 1 次确认以抑制单次误翻转（含 Kimi / DeepSeek / 元宝等 RPA 平台，已在样本之间加入间隔节流以防软封）。(#169)
- **百度断点续抓 + 崩溃安全（不丢已抓数据）**：百度排名监控被反爬风控中断后不再丢弃本轮已抓关键词，新增「▶ 从断点续抓」按钮从中断处重抓（而非从头全量重扫）；更进一步，硬关闭 / 程序崩溃 / 断网 / 更新器杀进程等**任何**中断都会把已抓关键词增量落库，下次自动从断点继续，横幅区分「被百度风控拦截」与「上次监测意外中断」两种情形。(#162, #166)

### Changed

- **GEO 采集更快更稳**：API 平台（豆包 / 通义）与 RPA 平台（Kimi / DeepSeek / 元宝）双车道并发采集；RPA 平台跨关键词复用同一浏览器、每个关键词回首页重置会话（防止多个关键词灌进同一对话、污染提及与排名）；RPA 增加发送键多候选兜底（站点改版失效时回落回车键）、超时先抓取已生成答案再决定是否重试、答后随机「思考间隔」与关键词每日确定性洗牌以对抗节奏指纹 / 软封；机器睡眠 / 时钟跳变判为「中断」而非平台故障、不再误触发重试。(#164, #167, #169)
- **GEO 定时采集去除机器人指纹**：定时的 GEO 任务加入确定性启动抖动（同一天保持同序、跨天变序，最多约 20 分钟），避免固定整点全速补跑；可选「迟到守卫」（默认关）让错过太久的周期跳过而非堆积补跑。(#169)
- **百度抓取提速**：同一篇软文一轮只抓一次正文（URL 去重）、搜索结果页可见域名命中排除清单即短路省一次跳转、同一进程内频繁重跑走 6 小时正向命中缓存（日更任务跨天必过期、绝不读到陈旧排名）；「停止」在单个关键词内秒级生效（原先最多需等约 5 分钟）。(#161, #162, #163)
- **百度命中判定新增摘要兜底**：当软文正文抓取失败、且标题里没出现品牌词时，回退用搜索结果页摘要再判一层品牌命中（软文的品牌名常只出现在摘要里），减少「其实已命中却被判成未命中」的漏判。(#163)
- **历史报告日期按本地日归桶**：评论留存 / 知乎排名 / 百度 / 知乎搜索的每日趋势、「较上周净增减」徽章、删除事件列表统一按本地日归桶，修掉本地凌晨 / 深夜跑出的结果被算到相邻一天（相差 8 小时）的错位。(#163, #165, #168)

### Fixed

- **百度抓不到最新资讯 / 默认排名时有时无**：2026-07 百度把搜索结果页换成新版 cosc 组件系统，旧「最新资讯」选择器对真实页面恒解出 0 行，资讯现改以「{关键词}的最新相关信息」聚合卡呈现。按聚合卡表头可见文字重建资讯卡与卡内文章抽取（文字锚点比会变的内部模板名更稳）、并补齐 5 个新版杂卡（百科实体 / 百科多义 / AI 问答 / 爱采购批发 / 建站）的排除以免污染默认软文排名。已经用户实机验证通过。(#171)
- **百度排名监控一批抓取 / 调度 / 登录缺陷（P0×8 + P1×8）**：修掉长任务被调度器每 60 秒重复派发、跳转解析失败导致整行结果静默蒸发、定时任务按 UTC 判到点造成日期错 8 小时、登录副本链路误弹验证码 / 未校验 BDUSS、文章验证码窗口不可见（内嵌值得买等站点场景）、「重置 profile」删错副本目录、风控 / 登录文本误报（页面明明有自然结果却判「请登录 / 安全验证」）、前端一次失败就把全部关键词显示成「未跑」等问题；并让品牌命中匹配做 NFKC 归一化 + ASCII 词边界（「Nova」不再命中「innovation」）、抓取正文剥离 script / style（品牌名藏在页面 JS 里不再假命中）、整轮抓取全失败时如实报「失败」而非「完成空表」。(#161)

### Notes

- 本版另含一批稳定性 / 体积 / 清理类内部改进：百度端 content_preview 不再落库（省 30–40% 结果体积）、监控结果定期清理（保留最近 180 天、防数据库无限膨胀——本版首次接入清理逻辑，升级后首次运行会一次性、不可逆地清掉 180 天前的旧监控结果）、孤儿 Chrome 进程兜底清理、验证码等待超时真正生效并把老默认 90s 迁移到 300s、副本复制遇磁盘满时报明确「磁盘空间不足」、断点落库与草稿清理并入单一事务防止重复断点；另修两处与近期改动无关的陈旧单测。以上对日常使用无感知影响。(#162, #163, #168, #170)

## [0.7.2] - 2026-07-09

### Changed

- **知乎「单个问题」不再套多余的列表层**：知乎问题监控里，只含 1 个问题的任务不再强制走「批次 → 子任务列表（"1 个问题"）→ 详情」两层壳——点一下直接在右侧看该问题详情（当前卡位 / 7 天趋势 / 前 N 条答案）；含多个问题的批次维持原来的两层钻入，单问题行的 ⋯ 菜单也从批次级改为任务级（立刻监测 / 编辑任务 / 删除任务）。数据中心「跳到该知乎问题」按新模型解析批次，单问题直出详情、多问题钻入并高亮。

### Fixed

- **暗色模式多处仍是白底 / 白线（导航栏 · 创作区 · 图文编辑器）**：这些组件把浅色写死、不随 `body[data-theme="dark"]` 翻。修掉左侧导航栏发亮的白色右边框（"白线"）与磨砂白条、选中态白块（近白图标不再糊成一片）；创作区（组装 / 初稿 / 成稿）的白编辑卡与质检卡、图文编辑器（标题 / 正文输入 + 各素材面板）的白底统一换成会翻的卡面 token——暗色下"近白正文字压白底看不见"的问题一并解决；手机预览整块协调翻深。新增 `--card-warm` / `--nav-*` / `--edge-hi` 三组主题 token；彩色按钮上的白字与图片黑色蒙层保持不动。（另修创作区「取消重跑」按钮引用了未定义的 `--danger*` token、暗色下发亮粉）

## [0.7.1] - 2026-07-07

### Added

- **付费 API 抓取模式（TikHub）**：设置页新增「抓取数据源」开关（本地浏览器抓取 ↔ TikHub 付费 API）。开启后，知乎问题与抖音 / B站 / 快手评论改走 TikHub 付费 API（走 APP 接口，绕过本地反爬与限速）；API Key 经系统 keyring 加密存储，可配 Base URL（大陆 `api.tikhub.dev` / 海外 `api.tikhub.io`），设置页带按次计费成本提示。收到 402 余额耗尽即全平台短路，避免继续烧费与通知洪水。（旁路 API 适配器 + 模式感知分派，本地抓取路径零改动）
- **知乎问题 API 抓取**：给问题链接 + 目标品牌名 / 别名，抓「访客默认排序」下前 N 条回答，做正文品牌命中排名（复用本地同款清洗 / 匹配口径）。
- **评论留存监控（API 模式）**：给视频链接 + 你的评论原文，检索该视频评论区**前 100 名**判断留存与排名。命中即停省请求、找不到才翻满确认；结果分档显示「在显 / 跌出理想 / 超 100 名外 / 被删除 / 未监测 / 监测失败」——其中「被删除」靠上次快照对比（评论曾在前 100、这次消失才判）；检索深度做成单一真相源，改一处、前端文案自动跟随。

## [0.7.0] - 2026-07-06

### Added

- **创作台「品牌型号记忆库」（把真实产品参数喂进生成，杜绝编造）**：新建 `.md` 素材库解析层，从文件名派生品牌 / 型号 + 别名归一，把「产品参数表」解析成带单位 / 区间 / 占位的结构化事实（认证字段不抽数字）。生成时按当前主推 / 竞品型号自动注入真实规格（主推深、竞品浅，按卖点维度优先、命中标【主打】），并构建「注入源 ∪ specs ∪ 认证」的事实白名单；导出前做**事实核对门禁**——正文里超出白名单的带单位数字 / 认证被判为「疑似编造」列出，用户可逐条放行或退回重核（默认关，可在设置开）。含万值对称与「竞品删除」豁免。(#128–129, #132)
- **创作台「标题 + 角度」智能组装**：起飞条新增角度选择器 AnglePicker（预设 / 目标人群 / 卖点维度 / 语调 / 自定义标题，走受控词表：3 语调 / 10 卖点维度 / 人群矩阵 / 4 预设），角度会真正驱动组稿——按人群过滤素材块、按卖点采样并生成角度指令块、标题领衔并纳入白名单，reroll 跟随角度不跳出人群。(#134–136)
- **创作台「Skill 链」多-pass 生成**：可把「组装 → 人设 → 去 AI 味」等多个 skill 串成有序链（SkillChainPicker 三 role 槽），按位置定职责逐 pass 精修；ArticleView 可逐 pass 预览 / 重跑级联 / 看成本，重跑改为流式实时、可取消。(#138–140, #144–145)
- **创作台「交互式整篇润色」（成稿增强）**：整篇润色改接 finalize 端点，让品牌事实注入 + 角度 + skill 链在这一步真正生效，SSE 流式实时出稿并带润色进度。(#141–143)
- **生成成本透明**：链 / 润色 / 重跑完成后显示「调用 N 次 · ≈X tokens · ≈¥Y」估算，设置页新增按模型单价表（PricingCard）；无单价时回退只显 token。(#144)
- **激进契约模式 + 完整性反查 + 确定性评分 + 批量出稿选优**：新增「保守 / 激进」契约档（Hero chip + 设置卡 + per-article 覆盖），激进模式放宽字节约束；质检卡新增「主推事实完整性反查」（主推该讲的规格漏没漏）与「综合评分」两项（0–100 确定性评分：禁区 lint + AI 味启发式 + 事实核对，AI 味信号含连接词 / 三段式 / 排比 / 总结段 / 同质化）；批量出稿升级为「注入 + skill 链 + 核对计数 + 评分 + 每关键词多候选自动选优」并汇总总成本，落选稿一并留档可复查。(#152)
- **创作台「横评」模式（一次生成多型号对比稿）**：起飞条切换「常规 | 横评」，型号多选弹层（主推 / 竞品分组，2–4 个）→ 确定性组装出参数对照表 + 各型号亮点 + 实测对比 + 主推背书总结（空节省略），再复用 finalize 走 LLM 润色 / 事实核对 / 导出全链。(#153)
- **创作台「反馈学习闭环 + 事实更新传导」（monitor.db v9）**：导出即记录本次用了哪些素材 / 角度（全程 fail-open，绝不影响导出），设置可开「按反馈加权采样」让常被采用的素材更易被选中；素材库新增「使用反馈」tab（素材 / 角度两张统计表）。素材参数变更后自动对比型号指纹，在素材库型号行、历史记录页打「参数已变更」角标并弹「N 个型号参数已更新」通知，历史记录可一键用原参数「重新生成」。(#155)
- **素材库（全新一级入口）**：侧栏新增「素材库」入口（`/materials` 路由），四个 tab——**品牌型号**（只读浏览型号参数 + 注入预览）、**录入**（文件夹驱动的动态表单手动入库，带 `.md` 实时预览）、**AI 拆条**（粘贴整篇文章 → AI 拆条 + 归类 → 复用录入写入器落库，逐条 commit / 撤销、置信度提示、跨块去重、长文自动分块带进度 / 取消）、**使用反馈**。写入器不覆盖已有文件、幂等登记、可安全撤销。(#131, #146–147, #149)
- **「去 AI 味 / 人设」skill 解耦**：原「家电科普博主」skill 拆成可复用的「家电科普人设」（persona）与「去 AI 味」（humanize，24 类通用去痕模式，去品牌事实）两块，skill 支持 `role` 字段，编辑页可选角色。(#130, #132)

### Changed

- **素材库 V2 视觉重构**：四个 tab 按 Claude Design「暖米纸感」设计语言重做——品牌型号概要卡（参数进度 + 5 项 stat + 商品页链接）+ 分组锚点 scroll-spy + 6 组参数卡、录入页素材树 + 暗色 `.md` 预览、AI 拆条三态 + 置信度结果卡、使用反馈空态引导。全部走 CSS 变量，亮 / 暗色与强调色自适应；数据接线复用现有 store，无后端改动。(#157)
- **禁区 lint（确定性合规扫描 + 软拦导出）**：质检卡新增「禁区」项，导出前机械扫描违禁 / 高风险表述并可一键清理（幂等 autofix，含引号 / 破折号 / 对称逗号规整），未清理时软拦导出（可确认放行）；质检卡的「禁区」「完整性」「综合评分」等项统一迁入真实渲染的主检查区，不可下钻的卡不再假装可点。(#148, #150)
- **长文档 vault 增量索引提速**：素材库改为增量索引（按文件 mtime 巡走、只重解析变更文件，异常回退全量、RLock 串行化），生成 / 拆条 / reroll / 写入器 / 启动扫描统一走增量入口，大 vault 下明显更快。(#149)

### Fixed

- **百度排名监控「默认搜索」区块 0 命中（定位不到文章）**：2026-07 百度 SERP 改版把结果卡 class 里的 `result` token 整个去掉，旧 XPath 的 `contains(@class,'result')` 条件恒不满足——每个关键词都解析出 0 条默认结果，任务却仍报 `ok`，界面显示假的「无排名」。重写默认区块选择器：① class 改 token 级匹配（顺序无关、不依赖已消失的 token）；② 杂卡排除抽成 `_EXCLUDED_TPLS` tpl 黑名单并补齐两套模板桶的新杂卡（登录桶 `rel_base_realtime` 实时资讯 / `b2b_factory_wise_san` B2B 工厂，匿名桶 `b2b_prod` 爱采购 / `image_grid_san` / `recommend_list` / `uer_feedback` / `new_baikan_index` / `note_lead`）；③ 移除已失效的 `cosc-title-slot` 结构排除（该 span 现已泛化为普通结果卡的通用标题槽，保留会把整页 organic 几乎全数误杀）；④ 新增 content_left 兜底选择器 + `selector_fallback` 落库标记 + 0 命中 WARNING 诊断日志（带页面 tpl 清单，下次漂移直接从日志读出新模板名），并常开「兜底 vs 主选择器」对比哨兵——只有部分结果卡丢 token 的静默漏抓同样会告警；资讯区容器存在但解出 0 行也告警；⑤ 补偿守卫：百科 / 自搜索 / 图片 / 好看视频 / b2b 等百度自有垂类 host 永不计入排名（知识卡词条正文天然含品牌词，计入会假报「自家软文排第 N」；host 精确匹配，不误伤百家号）。(#151)
- **整篇润色丢失 per-article 契约档选择**：起飞（takeoff）是 draft-only 不跑 LLM，真正的润色在 finalize 步骤，但前端构造 finalize 请求时漏传 `contract_mode`，后端回退到全局设置——用户在 Hero 选的「激进 / 保守」被静默忽略。补齐一行透传，端到端生效（横评路径不受影响）。(#154)
- **批量出稿同分落选稿互相覆盖**：多候选选优时，同一关键词的多个落选稿若分数相同（内容相同必然同分），旧文件名只含整数分会静默互相覆盖只留最后一份。文件名加候选序 `c{k}` 消歧 + 分数保留一位小数，`candidates/` 目录建不出时降级为日志而非把已成优胜的整词拖成失败。(#152)

### Notes

- 本版另含一批开发 / 发版工具与测试链路的内部修复（release.py 同步 bump `Cargo.lock`、修 `interactive_login` 测试 collection 中断、Phase 2 测试卫生等），对使用无影响。(#125–126, #137)

## [0.6.6] - 2026-06-22

### Fixed
- **百度排名监控因品牌别名报错失败**：0.6.2 引入的「品牌别名」把 `aliases` 在 `fetch()` 里解析、却在内部抓取方法 `_fetch_once` 里使用，跨方法作用域导致 `NameError("name 'aliases' is not defined")`——凡真正抓到搜索结果页的百度任务都会被当成适配器异常而失败（native Chrome 模式下尤为明显，表现为「弹完成通知但界面没跑、一秒结束」）。修复：让别名与主品牌一样按参数贯穿整条抓取链路（`fetch → _fetch_with_promotion → _fetch_once`），含别名的文章重新能正确判定为「自家」；并补回归测试钉死该路径。
- **监控断点可能从旧位置恢复**：当一个任务的两条结果在同一时刻写入（`checked_at` 时间戳相同，进程繁忙时易发）时，「读取最近断点」的查询缺少确定性排序，可能读到较早的那条、导致 resume 从错误的关键词位置继续。为该查询补上按记录 `id` 倒序的兜底排序。

## [0.6.5] - 2026-06-22

### Fixed
- **百度排名「重新导入 Chrome profile」复制失败**：用户日常 Chrome 开着时（这功能本就是为「复制日常 profile」设计的），`Network\Cookies` 与各 leveldb `LOCK` 文件被 Chrome 独占锁住，原来的 `shutil.copytree` 是「全有或全无」——任一文件 `[Errno 13] Permission denied` 都会在最后一次性抛错，把整次导入判失败（哪怕 99% 文件已复制好）。改为逐文件容错复制：`LOCK` 等运行时锁哨兵按名跳过（0 字节、下次启动自动重建，复制过去反而会让副本 Chromium 误判被占），被锁的 `Cookies` 吞错并记录而非整体失败。登录态文件被锁时复制仍算成功，但回一条黄色提示让用户「关掉 Chrome 重导」或「登录百度（副本）」，不再报红「复制失败」。
- **百度排名监控失败却假报「监测任务完成」**：百度反爬熔断器打开后，`fetch()` 会瞬间正常返回一个 `status="risk_control"` 的空结果——它经由 monitor_loop 的正常完成路径发出 `finished` 事件，前端据此弹「监测任务完成」通知；但该结果无 metric，任务状态又回落成「未跑」并显示伪造的「断点 keyword #0」，把真实失败彻底藏起来（表现为「通知完成 + 界面未跑 + 一秒结束」）。两处修复：① monitor_loop 对 adapter **正常返回**的非 ok 结果改发 `failed` 事件（带原因），不再当成 `finished`；② 熔断早退由 `risk_control` 改为 `failed` + 中文可操作原因（「百度反爬熔断中…请重新导入并登录副本」），不再伪装成断点。

## [0.6.4] - 2026-06-18

### Fixed
- **图文编辑器 / 挖掘评论的图片不显示**：应用的内容安全策略（CSP）`img-src` 未放行 sidecar 来源 `http://127.0.0.1:*`，导致所有 `<img>` 加载本地图片被 WebView 拦截——上传走 axios（归 `connect-src` 管，已放行）故能传上去、缩略图数量也对，但图片像素一律渲染不出来（图文编辑器封面/预览空白、挖掘评论配图空白）。给 `img-src` 补齐 `http://127.0.0.1:* http://localhost:*`，与 `connect-src` 对齐；新增回归测试钉死「凡 connect-src 里的本地 sidecar 来源，img-src 必须也有」。

## [0.6.3] - 2026-06-17

### Added
- **小红书图文笔记编辑器（全新模块）**：左侧导航新增「小红书」入口（独立 `/xhs` 路由），三栏布局——左栏素材面板 / 中栏纯文本编辑器 / 右栏手机实时预览：
  - **编辑内核**：标题 + 正文纯文本编辑，实时字数统计与超限提示；草稿本地持久化（独立 `xhs.db`）+ 去抖自动保存 + 一键复制标题 / 正文 / 全文；草稿支持行内重命名与复制副本。
  - **文字素材库**：模板 / 标题 / 文案 / 话题 / 装饰五类起步素材（JSON 驱动），点击即插入；分类标签条自动换行（最多三行、超出滚动）。话题点击或输入即追加到正文末尾 `#标签`。模板 / 标题 / 文案 / 话题均可「存为我的」自定义素材。
  - **表情库**：「常用分组」13 类（情绪 / 高亮装饰 / 句首序号 / 重点点缀 / 对话 / 颜色 / 符号等排版用法）+「全部」24 类（动物 / 食物 / 服饰 / 交通 / 天气 / 运动 / 人物等）共 476 个 Unicode emoji；另有「小红书代码」模式（`[害羞R]` 等贴纸代码，正文与预览渲染为占位药丸，不打包官方贴纸图）。
  - **图片**：本地上传 / 缩略图 / 拖拽排序 / 设封面 / 删除（magic-byte 校验 + 5MB 上限 + 级联清理）；预览按封面展示真实图、多图轮播。
  - **手机预览**：真实 iPhone 外框，「笔记页」与「发现页」两种视图随编辑实时同步（发现页按正文品类词匹配竞品卡）。
  - **AI 助手**：一键生成 / 润色正文（复用现有 LLM 配置），生成与润色提示词可在设置页自定义。

### Changed
- 默认窗口尺寸由 1280×800 调整为 1360×900（最小尺寸保持 1280×800）。

## [0.6.2] - 2026-06-15

### Added
- **暗色主题**：设置页支持「明亮 / 暗色 / 跟随系统」三态切换，暗色为暖咖 Espresso 配色，切换即生效并持久化；冷启动前预写主题避免首屏闪白（FOUC）。配套把全站硬编码颜色、投影、状态色统一收编进设计 token（Card / Pill / StatCard 等改 CVA 变体），暗色下自动主题化、图表网格 / 刻度 / 折线随主题翻色。
- **全局任务托盘**：侧栏新增任务托盘入口（运行中任务 + 最近完成，带数字角标与呼吸动效，与通知铃铛互斥）；监测 / 引流 / 批量 / 单篇四类任务的完成与失败统一推进通知铃铛；任务进度带 ETA 估算；SSE 断线后自动对账补全终态，不再卡幽灵进度。
- **单篇文章生成支持取消**：生成过程可从托盘一键取消（协作式取消端点）。
- **启动时检查更新**：应用启动静默检查新版本并弹窗提醒，可「跳过此版本」；托盘右键菜单精简（移除无效项）。

### Changed
- **监测中心五页 UX 全面重设计**：知乎问题 / 知乎搜索 / 百度排名 / 平台评论 / AI 卡位（GEO）五页统一为「左栏任务列表 + 右栏详情」两栏布局；左栏统一瘦身为任务行 + ⋯ 操作菜单 + 二级下钻，右栏分任务汇总（KPI + 趋势 + 速览 + 导出 / 定时）与单项详情两级；五页左栏视觉对齐统一标准。
- **百度验证码体验优化**：百度监控触发图形验证码时，采集浏览器自动切到有头模式并弹到屏幕中央，配「系统桌面通知 + app 内醒目横幅 + 任务栏闪烁」三重提醒，人工解完自动继续采集。
- **百度品牌别名匹配**：百度排名任务支持同品牌多种叫法（如 CEWEY / 希喂），文章命中任一别名即判定为「自家」；任务表单与批量导入（弹窗输入 + Excel「品牌别名」列）均可填写。
- **移除 PyQt6 老栈**：清退旧 csm_gui 桌面栈，仓库统一为单一 Tauri + Vue + sidecar 架构；清理前端无引用的死组件与死代码。

### Fixed
- 平台评论监测页左栏顶部工具栏溢出（平台下拉框过宽，收窄贴合内容）。
- 知乎问题 / 知乎搜索任务详情重复的「自家命中数」KPI 卡去重。
- 引流采集 EventBus 拒绝并发的第二条数据流，杜绝孤儿队列卡死；引流 CSV 导出表头对齐。

## [0.6.1] - 2026-06-09

### Added
- **首页工作台按 bento 版式重做**：全比例自适应布局 + 卡片细节打磨。新增 StatCard 大数字卡（百度 SEO / 知乎问题 / 知乎搜索，均带「较上周」徽章）、GEO 半圆仪表盘卡（全局曝光率 SoC + 较上周）、高权重信源榜卡（跨任务全局 top-N 域名 + 排名周对比，新进标「新」）、评论留存率卡（专用 7 天端点 + 平台 tab + 跨平台加权聚合折线）。配套后端：3 个 ranking 端点补 `changed_prev`、GEO 汇总曝光率端点、全局高权重信源榜端点、summary 增加 zhihu_search / geo 摘要。
- **数据中心 GEO 分析页**：关键词 × AI 平台覆盖矩阵（「重点 / 覆盖榜」双视图）+ 高权重信源榜 + 曝光趋势 + 按品牌任务选择器；新增跨关键词数据层 `useGeoAnalytics`。
- **数据中心新增「知乎搜索」分析页**：镜像知乎问题页，配聚合端点 `/api/monitor/history/zhihu-search`；「知乎排名」改名「知乎问题」。
- **引流（mining）品牌词预筛**：引流任务可填「目标品牌词」，每条视频评论命中品牌词 ≥3 即标记排除（fail-open，不误杀）；`brand_keywords` 提交 → 落库 → runner 可读，V8 迁移新增 `brand_comment_hits` / `exclude_reason` / `brand_keywords`；品牌词预筛忽略空白匹配（「希 喂」→「希喂」、「CE WEY」→「CEWEY」）。
- **评论平台抓取进度条 + 提速可调档**：B 站 / 抖音 / 快手评论适配器翻页进度实时上报（L2/L3 进度条读 monitorStatus）+ `scrape_top_n` 抓取上限；评论平台 pacing / concurrency 可调档（默认保守）。
- **信源规整与权重**：`canonical_source` 规范化（百度系 / 微信拆分、知乎合并）+ authority 权威度权重表；信源榜 `weight = 被引次数 × 覆盖平台数 × 权威度`，按权重降序。

### Changed
- **监控中心与数据中心导航统一**：pivot 对齐、「AI 卡位」→「GEO」、「卡位任务」→「监测任务」。
- **RPA 采集浏览器移屏外**：百度 / GEO 真浏览器 RPA 采集时把有头窗口移到屏幕外（`window_util` 移屏 flags + 反遮挡 + CDP 上浮/隐藏）；百度验证码需人工解时窗口临时上浮、解完移回。引流 mining 不受影响。
- **数据中心 GEO 页与首页留存卡 UI 优化**：曝光趋势改近 7 天日历横轴 + 纵轴 + 柱顶数值（去图例 / 灰底 / 右上大值）；覆盖榜未提及格子与图例上色、AI 平台表头加宽显全（含 DeepSeek）、点击行/平台格跳转「关键词下钻页」（各平台原文 + 引用信源）；各平台覆盖率折线常显圆点 + 100% 数据点不被裁切 + 图例居中；高权重信源榜去掉「N 条」与网址类型标签、竞争·信源「信源权重」按引用 ≥10 次过滤上榜 + 散点/图例左右布局；首页评论留存率卡折线改用带纵轴 + 背景网格的图表控件。

## [0.6.0] - 2026-06-04

### Added
- **AI 卡位监控（GEO）· 阶段 1**：新增 `geo_query` 监测任务类型，批量关键词 × AI 平台（阶段 1 接入通义千问 / Kimi，走各自联网 API）自动采集回答与引用信源，LLM 抽取后产出四大卡位 KPI——**曝光度 Share of Chat**（<20% 判「隐身」）、**首推率**、**净情感得分**、**引用信源聚合榜**（按域名频次降序，自动归类知乎 / 小红书 / 权威媒体 / 电商 / 其他，指导「精准喂饭」铺内容）。一品牌一任务，任务内 `关键词 × 平台` fan-out，复用现有监测调度 / SSE / 凭证 / 批量·续抓·取消基建。
- **监测中心「AI 卡位」tab**：建任务（品牌 + 别名 + 批量关键词 + 平台多选 + 抽取模型）、一键运行 + SSE 实时进度、最近一次 4 KPI 快照 + 信源榜 Top。
- **监测中心任务详情 · 全套卡位分析**：进入任务即见四大 KPI + 卡位矩阵（平台 × {曝光度 / 首推率 / 情感}）+ 趋势 + 信源聚合榜（7/30/90 天筛选）+ 竞争对手 + 原文钻取；多关键词走二级页、单关键词直达。
- **V7 数据库迁移**：新增 `geo_cells` / `geo_citations` 两张规范化表（按 `task_id + checked_at` 关联，不与 `monitor_results` 双写），支撑信源榜 `GROUP BY` 聚合与原文钻取；新增只读端点 `GET /api/monitor/geo/{task_id}/citations`、`/cells`。
- 采集层每个 cell 一开始就记原始响应日志（http / len / first200）+ `raw_json` 落库，便于分辨「0 提及」是 cookie 失效 / 真无结果 / schema 变 / 风控；API provider 覆盖非 JSON 响应、应用层错误码、内容过滤（→ blocked）、取消与分段超时；全部 cell 失败 → 运行标 `failed`（避免误触发「掉出」告警）。
- **新增 Kimi(Moonshot) / 豆包(Ark) 两个 LLM provider**：设置页可单独配置二者的 API Key / 模型 / Base URL（均为 OpenAI 兼容，也可当抽取/生成模型用）。GEO 的 Kimi 采集由此获得 key 配置入口（原来设置页只有 6 个 provider，没处填 Kimi key）；豆包 key 可提前配好（采集 adapter 阶段 2 落地）。
- GEO 采集 provider 改为读设置里配置的模型（默认 Kimi=`kimi-k2.6`、通义=`qwen-plus`），不再写死旧模型；OpenAI 兼容 client 在模型拒绝 temperature 时（如 `kimi-k2.6` 只允许 `temperature=1`）自动去掉温度重试一次，修复「测试连接」对推理模型报错。
- **依赖**：新增 `tldextract>=5.0`（信源域名规整，离线快照模式，已加入 PyInstaller 打包清单）。
- 新增单测 39 条（`tests/core/monitor/geo/`：models / classify / metrics / storage / providers / extract / adapter / 注册 invariant）+ sidecar 路由测试。
- **AI 卡位监控（GEO）· 阶段 2**：**豆包（火山方舟 Ark 联网 bot）采集接入**（设置页配「联网 Bot ID」+ key）；**Kimi 因 Moonshot `$web_search` 只回 `search_id`、不给信源 URL，从 API 采集移至阶段 3 RPA** —— 当前 API 联网采集平台为**通义千问 + 豆包**（两家 API 都回信源）；**信源榜一键导出 Excel**（Tauri 原生「另存为」对话框，浏览器 dev 回退下载）；GEO 任务支持**每周调度**（`weekly-<周几>-<HH:MM>`）；新增**三类卡位告警**——隐身（曝光度 SoC<20%）/ 首推率显著下滑 / 某平台从「提及」变「未提及」，三者都区分「采集失败（没问到）」与「真没提及」，API 故障 / 软封不误报；信源榜每行**「去引流中心铺这个源」**一键跳转引流中心并预填关键词，打通「卡位洞察 → 内容铺设」闭环；数据中心冗余「AI 卡位」pivot 移除（全套分析统一在监测中心任务详情）。新增告警 / 豆包 provider / weekly 调度 / Excel 导出单测。
- GEO 阶段 3：AI 卡位新增「真浏览器 RPA」采集通道，覆盖 DeepSeek / Kimi / 腾讯元宝
  （这三家 API 拿不到联网信源）。DOM 交互：开真站→开联网→等流式→抓回答+来源链接，
  产出与 API provider 同形的 GeoAnswer，下游抽取/指标/告警/信源榜/引流闭环全复用。
  设置页新增「AI 卡位 · RPA 登录」分组（持久档登录，扫码/账号）。Kimi 由阶段 2 的
  API（无信源）改走 RPA 重新上线。geo_query 任务串行化 + 透传 cancel_token（长耗时
  RPA 可被「停止」及时中断；取消按控制流上抛，不记成采集失败）。
- **GEO 阶段 3 · 真站校准打通三平台信源 + 交互加固**：DeepSeek（内联 `<a>` 信源；开
  「深度思考」后推理与答案同 `ds-markdown`，抓取收窄到 `ds-assistant-message-main-content`
  排除推理）、Kimi（信源在「搜索网页」toolcall 里——点开后全页抓 `<a>` + 过滤 bing 跳转壳
  与自家域名）、腾讯元宝（全程无信源 URL，改抓「深度思考」检索资料标题作 name-only 信源；
  答案排除 `-cot` 推理块）。RPA 交互：登录态轮询到可判定再判（修重 SPA 未加载完误报
  「未登录」）；富文本编辑器（元宝 Quill / Kimi Lexical）提交加节流（聚焦→逐字→提交，修
  瞬时打字+回车不触发发送）；元宝每轮先点「新建对话」开干净会话；按站点开「深度思考 /
  联网搜索」开关。
- 监测中心新增「知乎搜索排名」监控：用知乎官方搜索 API 对关键词取前 10 结果，追踪目标品牌词命中位置。需在设置页填写知乎开放平台 Access Secret。

### Changed
- **百度「原生 Chrome 副本」缓存自动清理**（原挂名 0.5.11，从未单独发布，并入本版）：每轮百度监控结束、副本 Chrome 完全关闭后，自动删除副本里的 Chrome 缓存目录（`Service Worker` / `Cache` / `Code Cache` / `CacheStorage` / `Shared Dictionary` 等），使副本常态维持 ~0.5GB，不再随监控运行无限增长（实测旧副本曾涨到 14GB，其中 86% 是 `Service Worker\CacheStorage`）。仅清缓存，保留 `Network\Cookies` 登录态、`Local State`、IndexedDB / Local Storage / Extensions，无需重新登录、功能零改动。`copy_profile_to` 导入时同步纳入 `CacheStorage` / `Shared Dictionary` 跳过名单。
- **监测中心 UI 一致性大调**：① 知乎搜索排名改为与百度同款两级双卡布局（L1 任务表 + 任务详情预览卡，L2 关键词列表 + 单关键词详情）；② AI 卡位（GEO）任务列表 / L2 对齐百度（去「变化」列、标题 14px、列对齐；返回头改圆形按钮 + eyebrow + 关键词数徽章、选中改低调底色）；③ 知乎搜索 L2 详情卡镜像知乎问题右卡（KPI 卡位数量 / 最高排名 + 最近 7 天卡位趋势 + 前 10 结果固定高滚动卡片，含类型「专栏/回答」·作者·赞同·自家命中标记）；④ 知乎问题任务列头「批次名」→「任务名字」。

### Fixed
- **新建 GEO 任务覆盖同品牌的已有任务（数据丢失）**：`monitor_tasks` 的
  `UNIQUE(type, target_url)` + `create_task` 的 `ON CONFLICT DO UPDATE`，而 GEO `target_url`
  原来仅按品牌派生（`geo://品牌`）——同品牌第二个任务撞键把第一个 UPDATE 覆盖。改为每任务
  唯一（`geo://品牌/{uuid}`，编辑时沿用原键按 id 更新，新建必为新行）。
- **新建百度排名 / 知乎搜索任务覆盖同首词的已有任务（数据丢失）**：与上条同根因——这两类
  任务的 `target_url` 由「第一个关键词」派生，首词相同的两个任务撞 `UNIQUE(type, target_url)`
  被 `create_task` 的 `ON CONFLICT DO UPDATE` 覆盖。改为在真实搜索 URL 后追加无害唯一参数
  （`…&_csm={uuid}`）——既保留「点开真实搜索页」、又每任务唯一；编辑沿用原键（按 id 更新）。
  批量导入同首词多行亦不再互相覆盖。唯一化逻辑抽到 `utils/taskTargetUrl.ts` 并加单测。
- **AI 卡位任务列表与百度排名列表不一致**：改成百度同款两级下钻——Level 1 扁平任务表
  （任务名字/变化/状态/操作），点任务进 Level 2 关键词列表（带返回），点关键词右栏出三
  页签详情。信源榜改两列 + 固定高滚动（信源多时不撑长、不压扁散点图）；平台对比卡片原文
  截断 8 行、信源固定高滚动（卡片高度受控，masonry 更均匀）。

### Notes
- RPA 选择器随站点改版会失效，集中在 csm_core/monitor/geo/providers/rpa/sites.py，
  失效时改那里 + 重新校准（见 acceptance 清单）。夸克AI 不在本期。

## [0.5.10] - 2026-05-29

### Added
- **知乎问题监测「批量化」**：知乎任务列表从扁平改为「总任务（批次）→ 子任务」两层结构（沿用评论平台命名约定，一个批次共享目标品牌词 + 监测前 N 个回答）。批量导入每行填「问题名 + 问题 URL」，批次级一键启动全部 / 编辑 / 删除，点批次名钻入子任务列表。
- **知乎问题浏览量**：每次监测抓取问题「被浏览」数（知乎问题级 API 返 403，改从渲染后页面 DOM 抓 NumberBoard），存入结果 metric，子任务列表以万 / 亿单位展示。

### Fixed
- **百度「原生 Chrome 副本」登录失败「缺 Chrome 可执行文件路径」**：① `find_chrome_executable` 补 HKCU 注册表 + `%LOCALAPPDATA%` per-user 安装位置探测（无管理员权限安装的 Chrome 只写 HKCU / 装在 LOCALAPPDATA，原来探不到）；② 复制 profile 成功后顺手探测并持久化 `chrome_executable_path`（否则走完复制流程该字段一直为空，点「登录副本」/ 跑监控直接报缺路径）；③ 登录副本窗口的失败不再被误显示成「复制失败」。
- **百度登录态「登录成功却显示未登录」**：`get_login_status` 与「默认 headless」抓取的 headless 启动改用完整 Chromium 的 `executable_path`，绕开未随包的 `chrome-headless-shell` 二进制（缺失导致状态读取与 headless 抓取启动失败）。
- **「重置百度浏览器 profile」按钮在 release 下点击无反应**：原生 `confirm()` 在 Tauri 2 WebView 被拦截抛错，改用应用内 `confirmDialog`。
- **监测列表布局**：统一所有列表（知乎 / 评论 / 百度）表头与内容列对齐（名称列左对齐，其余居中，表头正对数值）；子任务列表与右侧详情卡滚动区收敛——表头 / 返回条 / KPI / 趋势固定，只有数据行 / 答案列表滚动。

### Changed
- 百度账号登录入口从 Cookie 管理器迁到「设置 → 百度关键词 · 默认 headless 开关上方」；Cookie 管理器平台下拉移除「百度」（百度不走 cookie 池）。
- 百度登录轮询 / 状态读取增加 INFO 级原始日志，便于排查 silent failure。

## [0.5.9] - 2026-05-28

### Added
- **百度排名监测「原生 Chrome 副本」模式（方案 B'，默认关闭）**：针对百度对自动化浏览器（Patchright 指纹）的强反爬，新增可选的原生 Chrome 模式。设置 → 百度抓取 一键把用户日常 Chrome profile **复制**到 CSM 独占目录（`<config_dir>/baidu_chrome_profile_copy/`，非 Chrome 默认目录——直接挂默认目录会被 Chrome 91+ 拒绝 "DevTools remote debugging requires a non-default data directory"），用真实 cookie/历史/书签伪装抓取。复制时跳过 Cache / Code Cache / Service Worker / GPUCache / Crashpad 等临时目录（实测 ~14GB → ~500MB）。因 DPAPI 限制副本 cookie 启动时被清空，提供「在副本里登录百度」一键按钮（spawn headed Chrome、监听退出、记录上次登录时间），登录一次后持久复用。共 7 个新 monitor 路由（`detect-chrome` / `list-profiles` / `copy-profile` / `launch-login-window` / `test-native` + `native-config` GET/POST）；SERP `page.goto` 超时放宽到 60s（副本 Chrome 首次冷启动 + extension 初始化需 ~30-45s）。
- **百度抓取设置页**：新建 `BaiduScrapeSettings.vue`（设置 → 工作流 → 百度抓取），原生模式开关、检测 Chrome、导入 profile（10 分钟超时容大 profile）、上次登录时间、测试抓取均在 UI 内完成，开关切换即自动保存。
- **系统通知（`@tauri-apps/plugin-notification`）**：新增 `useSystemNotify` composable（无权限时静默降级），原生模式「需人工解验证码 / 监控完成」等场景弹桌面通知；前端首次接入 vitest 测试运行器。
- **「同步到监控」功能**：采集任务完成后，点击任务行三点菜单 → **同步到监控**，可将该批次所有视频的 tier-1 草稿评论一键同步为 `monitor_tasks`（`enabled=False`，默认手动触发）。操作入口只在任务状态为 `done` / `partial_done` 时可用；所有视频都有草稿才能同步（防止漏评论）。弹窗支持设置任务名前缀、`top_n`（1–50）、可选 cron 表达式；同步后展示已创建/跳过重复/无草稿计数。
- **采集全局去重**：`on_card` 回调新增跨表去重检查（`is_video_tracked_anywhere`）——视频已在 `videos` 表 **或** 已存在对应 `monitor_tasks` 记录时直接跳过，不再写入重复数据。
- **搜索翻页保护（`max_attempts`）**：三个搜索 adapter（抖音/快手/B 站）新增 `max_attempts` 参数（默认抖音 3、快手 5、B 站 8），超出后停止翻页并 log，防止无限分页触发平台反爬。
- **V6 数据库迁移**：`monitor_tasks(type, target_url)` 联合索引（`idx_monitor_tasks_target_url`），加速去重反查。
- **`csm_core/mining/config.py`**：新增 `MAX_ATTEMPTS_PER_PLATFORM`、`PAGE_DELAY_RANGE_SEC`、`DEFAULT_MONITOR_TOP_N`、`DEFAULT_MONITOR_SCRAPE_TOP_N` 常量集中管理。
- **`csm_core/mining/sync_to_monitor.py`**：`SyncParams` / `SyncResult` dataclass + `run()` 服务函数（幂等，单条失败不中断整批，收集到 `errors[]`）。
- **HTTP 端点 `POST /api/mining/jobs/{job_id}/sync_to_monitor`**：带 404 / 409（状态未完成 / 未全部评论）/ 422（参数校验）防护。
- 新增单测 24 条：`test_collect_dedup.py`（11 条）、`test_sync_to_monitor.py`（7 条）、`test_sync_to_monitor_api.py`（6 条）。
- 百度原生模式新增大量后端单测：`test_chrome_detect.py`、`test_chrome_preflight.py`、`test_baidu_browser.py`、`test_monitor_routes.py`、`test_monitor_bus.py`、`test_config_routes.py` 及 `test_baidu_keyword.py` 扩充（合计数百行）。

### Changed
- **软着陆验证码风控模式复用 `risk_detector`**：`_try_human_solve` 不再 hardcode 风控 URL/DOM 子集，改引用 `risk_detector._URL_PATTERNS` / `_DOM_SELECTORS` 同源，杜绝与 `detect_risk` drift。
- **文章漏检诊断日志**：`_check_block` 每条 article fetch 记一行 INFO log（rank / host / content_len / matched / title / fetch_error），用户报漏检时跑一次即可定位根因（壳页 / 抓取失败 / 正文无字面品牌词）。

### Fixed
- **强反爬站文章漏检（什么值得买 / 知乎等品牌软文）**：`fetch_article_http` 是 curl_cffi 纯 HTTP GET，不渲染 JS，SPA 反爬站只拿到 < 500 字符的 JS challenge 壳页 → 品牌词匹配必然漏。新增多级兜底链：① readability 提取过短时 fallback 抽整个 `<body>` 文本（`http_raw_fallback`）；② 壳页标记 `is_js_challenge` 时 fallback 到 SERP title 匹配品牌；③ `fetch_article_browser_isolated` 用独立 tab 渲染 SPA 后提正文（不污染百度主 page，B' 副本模式独有）；④ 文章级软着陆验证码：smzdm 等弹验证码时保持 tab 打开 + 弹通知 + 轮询等用户手动解（最多 180s），解掉继续提正文，超时才退到 title 兜底。
- **验证码解完判定卡死到超时**：解完判定改用正文 body 长度（≥ 800 字）而非「验证码关键词消失」——smzdm 正文页 `<head>` 残留 captcha SDK 引用会让旧逻辑永远以为还在验证码页，用户已进正文却卡到 180s 超时。
- **监测失败路径时间戳用错时区，误报「百度账号未登录」**：`MonitorLoop._clock` 默认 `datetime.now`（本地时间）但 `checked_at` 带 'Z' 当 UTC 存，比成功路径（`utcnow`）晚 8 小时 → `ORDER BY checked_at DESC` 把过期的 `risk_control` 断点排到 `ok` 之前 → 副本登录成功跑出 rank 仍显示风控 banner。默认 clock 改 `datetime.utcnow`。
- **首页「视频抓取」卡片显示抓取时的旧数量**：hero 数字与状态原先用 `progress.got`（抓取时计数）+ 原始抓取状态，裁剪 + 评论完的任务仍显示「30 / 完成」。改为 hero = Σ live `video_count`（后端已排除软删），逐行状态镜像 `TaskListItem`（抓取中 / 进行中 / 已完成 / 失败 / 排队）。
- **软删视频仍被计入致同步到监控 409**：同步闸门 / 同步服务 / 任务列表计数 / 卡片徽章原先都数原始抓取总数，裁剪后评论完的任务显示「进行中 · 30 条」并 409（「13/30」）。所有 per-job 计数加 `WHERE v.excluded=0`（与 `list_videos` 对齐）；同步端点 404/409 文案中文化。
- **同步弹窗崩溃 + 未处理 rejection**：`TaskListItem` `@mouseenter` 内联用了 `if` 语句（Vue 模板只接受表达式）导致整个 MiningView 动态 import 崩溃，改三元；`SyncToMonitorModal` 重设计对齐 `BatchImportTaskModal` 布局，并吞掉已通过错误条展示过的 409，避免冒泡成原生 Tauri 错误弹窗。
- **模板文件夹扫描砍错目录**：设置页「默认模板目录」是文件夹选择器，旧 `resolve_dir()` 无条件 `.parent` 上提一级（只对 `.json` 文件路径成立），选了文件夹反而扫不到里面的模板。改用所选目录本身扫描。
- **透明无边框窗口需切页/右键才重绘**：关闭 `CalculateNativeWinOcclusion`（保留 Tauri 其余默认 browser args），修复所有状态变更不刷新 UI、以及 onboarding 点「下一步」无反应（step 已切但 WebView2 未重绘）。
- **重装后反复弹欢迎页**：`cfg.load` 轮询重试到成功再判首启、拿不到 config 时不弹欢迎页——修复重装后 WebView2 localStorage flag 被卸载器清掉 + sidecar handshake 早于 HTTP 就绪的冷启动竞态，导致用户名仍在却反复弹欢迎页。

## [0.5.8] - 2026-05-25

### Fixed
- **快手抓取 v0.5.7 仍然 0 视频 + "完成"**：v0.5.7 把 HTTP 客户端从 vanilla httpx 换成 curl_cffi `impersonate="chrome120"`，sidecar.log 显示 `httpx: HTTP Request` 那一行确实消失了（curl_cffi 接管了），但 server 仍返回 `[ks-graphql] page=1 new=0 emitted=0 pcursor='no_more'`——**快手 server 的指纹识别不只 JA3**，还查 cookie 状态 / 设备 hint / header 顺序综合，Python 客户端任何变种都会被识破。本版根治：GraphQL POST 整个从 Python 抬到 patchright 浏览器内，用 `page.evaluate("async ({url, body}) => { const resp = await fetch(url, {method: 'POST', credentials: 'include', ...}); return { status, body }; }")` 在 Chrome 的 JS 上下文里发请求 —— server 看到的就是一次真实 Chrome XHR，TLS handshake / cookie / header order 全是 Chrome 原生，没有指纹差异可识别。`credentials: 'include'` 让浏览器自动带上 `mining_browser.launched_page` 注入的 BrowserContext cookie，不再需要 `_http.cookies_from_context` 提取到 Python 再绕一圈。
- **GraphQL variables 补 `webPageArea`**：schema 接受这个变量但 v0.5.0–v0.5.7 都没传。某些 server 端严格校验路径会因此 silent 返空。MediaCrawler 较新分支也都加了。
- **加 raw response logging**：sidecar.log 每页 POST 现在 log `[ks-graphql] http=200 len=N first500=...`。之前每次卡住都要发新版本加日志才知道 server 实际返了啥，现在下次再撞类似 silent failure 直接 grep log 就能定位（cookie 失效 / API 改了 / 关键词被风控 / 真没结果）。

### Changed
- `kuaishou_search.py` 不再 import `csm_core.mining.platforms._http`（page.evaluate 路径不需要 cookie 提取也不需要 Python HTTP 客户端）。`_http.build_stealth_client` 函数本身留在 `_http.py`，将来 bilibili 等若需类似手段可复用。

## [0.5.7] - 2026-05-25

### Fixed
- **快手抓取在 v0.5.6 不再报 FileNotFoundError，但 GraphQL POST 返回 200 OK + 空 feeds + `pcursor='no_more'`，UI 显示「完成 0 条」**：v0.5.6 的 `.graphql` 模板已经进 bundle、HTTP 请求也能发出去，但**快手 server 端按 JA3 TLS 指纹做反爬识别**，vanilla `httpx.Client` 一握手就被识破，server 返回 200 但 feeds 列表是空（soft shadow-ban —— 看起来像"没结果"，实际是"我知道你是脚本"）。修法：`csm_core/mining/platforms/_http.py` 加 `build_stealth_client()` 用 `curl_cffi.requests.Session(impersonate="chrome120")`，把 TLS 握手 / ALPN / cipher 顺序 / HTTP/2 frame ordering 全模拟成真实 Chrome 120 —— 跟 zhihu_question / baidu_keyword / *_comment 已经在用的同款 stealth 套路。`kuaishou_search.py` 切到 stealth client（`client.post(content=...)` → `data=...`，curl_cffi 的 API 差异）。B 站搜索这次不动（用户没报问题），等后续单独验证再决定。
- 配 5 个 invariant 单测守住：return type 必须是 curl_cffi Session、impersonate 必须是 chrome120、cookie/referer/UA 必须透传、`kuaishou_search.py` 必须调 `build_stealth_client` (不能回退到 `build_httpx_client`)、POST 必须用 `data=` 参数（用 httpx 的 `content=` 会 TypeError）。

## [0.5.6] - 2026-05-24

### Fixed
- **引流抓取里快手任务一开始就失败、报 `FileNotFoundError: ...\_vendor\mc_kuaishou_search.graphql`**：`kuaishou_search.py:76` 运行时读 `_vendor/mc_kuaishou_search.graphql` GraphQL 模板，但 `sidecar/csm-sidecar.spec` 的 `datas` 列表**从来就没列 csm_core 的非-py 数据文件**——PyInstaller onefile 默认只把 .py 包进 bundle，这个 .graphql 模板从 v0.5.0 引入 mining 模块起到 v0.5.5 一直缺，每次跑快手任务在 `_MEI*` 临时目录里都找不到文件直接挂。**v0.5.0/v0.5.1/v0.5.2/v0.5.3/v0.5.4/v0.5.5 都是这个 broken bundle**，只是用户之前可能没真用快手所以没暴露。修法：spec `datas` 加 catch-all `collect_data_files("csm_core", include_py_files=False)` + `collect_data_files("csm_sidecar", include_py_files=False)`，**整棵树**所有非-py 文件（含将来新加的 .json/.yaml/.sql/.html 等）自动进 bundle。配 invariant 单测守住 `collect_data_files("csm_core"` 永远在 spec 里。
- **引流抓取里抖音撞验证码中间页就直接失败、用户没机会输入图形码**：`douyin_search.py:117-119` scroll 循环里 `_risk.detect(page)` 命中就 `break`，立刻返回 `risk_control` 状态 + 关 patchright 浏览器。commit 注释字面是「captcha bail」——by-design 但 UX 错的。修法：检测到 captcha 时**不立刻 bail**，调新加的 `_wait_for_captcha_cleared` poll 5 分钟（每 3s 检查一次 `_risk.detect`），让用户在 headed 浏览器里手解 captcha；解掉自动回 scrolling 继续抓，超时才真的返回 `risk_control`。配套 `csm_core/mining/models.py::PlatformPhase` 加 `"captcha_waiting"`，期间发 `progress` 事件让前端 `TaskListItem` chip 切到「需验证」紫色态 + native tooltip 显示「请在弹出的浏览器中手动完成验证」。

### Changed
- 验证 csm_core / sidecar 全树非-py 数据文件 audit（runtime 只在 `kuaishou_search.py:40` 一处 `Path(__file__).parent` 引用 package 数据），新 spec 的 catch-all 已盖全所有现存 + 将来增量。

## [0.5.5] - 2026-05-24

### Fixed
- **应用内热更新依然撞 WinError 32，v0.5.2 的 image-lock 修复没盖全根因**：v0.5.2 把 updater.exe stage 到 `%TEMP%` 跑解决了 updater 自己的 image 锁，但**install dir 的 cwd handle 锁**没修。实际链路：用户双击桌面/Start Menu 快捷方式启动 CSM 时，NSIS shortcut 把 csm-tauri.exe 的 cwd 设为 install dir → csm-tauri spawn 的所有子进程（csm-sidecar、msedgewebview2 × 6、updater）**全部继承 cwd = install dir** → 每个子进程都持一个 install dir 的目录 handle → updater rename `<install> → <install>.bak` 时拿不动（18s retry 全失败）。更糟的是 Tauri 2 没把 WebView2 子进程绑到 Win32 Job Object，csm-tauri 退出后 webview2 变成 **孤儿**（PPID 指向已死的 pid），`taskkill /T csm-tauri` 触及不到，它们继续锁着 install dir。三层修复：
  1. **Rust `install_and_restart`** spawn updater 时显式 `cmd.current_dir(std::env::temp_dir())`，updater 自己的 cwd 不再锁 install dir
  2. **Python `updater/main.py`** 启动后立刻 `os.chdir(tempfile.gettempdir())`，作为双保险（若将来 spawner 又忘记设 cwd 也能兜住）
  3. **`_taskkill_csm_processes()` + NSIS PREINSTALL hook** 加按 Tauri identifier `com.csm.app` cmdline 过滤的 `msedgewebview2.exe` 清理，靠 psutil 枚举所有孤儿（NSIS 那边走 PowerShell `Get-CimInstance`）—— **不会误伤其他 Tauri/Electron 应用**的 WebView2 子进程
- **⚠️ 所有 ≤ v0.5.4 的老用户必须走一次 setup.exe 重装到 v0.5.5**：你机器上跑的 spawn 流程是当前装的版本的代码 —— v0.5.4 的 Rust 没 `current_dir` fix、v0.5.4 的 updater 没杀 webview2，应用内热更新升 v0.5.5 还是会撞同样的 cwd lock。只能走 [setup.exe](https://github.com/zev96/CSM/releases) 跨过这道坎。装上 v0.5.5 之后，**后续热更新就稳了**（v0.5.5 → v0.5.6 → ... 都不会再撞）。

## [0.5.4] - 2026-05-24

### Added
- **监测中心运行中任务真正可取消**：之前点「取消」只是不再调度下一轮，但当前正在跑的 fetch 不会中断（Top-100 的页拉到第 7 页要继续拉完才停）。现在 zhihu_question / bilibili_comment / douyin_comment / kuaishou_comment 四个 adapter 都接受 `cancel_token`，在分页循环 / 关键 await 节点检查 → 一旦用户按下取消就立即抛 CancelledError、不再发后续请求。
- **首页监测卡片趋势化**：ZhihuCard 顶部从"命中数"改成 `↑N/↓N` matched_count delta + 7 天 sparkline；CommentRetentionCard sparkline yMin=0/yMax=100（保留率相对 100% 的位置看得见）；KeywordTrendCard 加 yMax/yMin props，Y 轴绑定该关键词的 Top-N（不再随单日数据 auto-scale）。
- **首页卡片 → 详情页深链**：监测卡片现在可点直接跳到对应任务详情（MonitorView 接受 `route.query.task`，跨 tab 切换也能续上）；mining 卡片同理（MiningView 接受 `route.query.job`，首次挂载选中该 job）。
- **引流抓取三栏布局**：mining 视图改为 `TaskListPanel`（左）+ `SubtaskListPanel`（中）+ `VideoDetailPanel`（右），视频详情可一次性看到子任务列表（评论图层、回复内容、图片返图）；老的整页 `VideoCard.vue` 退役。
- **CSV 导出真实保存对话框**：之前 mining CSV 直接静默写到 Downloads 文件夹找不到，现在走 Tauri `dialog.save → fetch → writeFile` 链路弹原生保存框；导出格式新增分列「序号 / 平台 / 视频链接 / 第 N 层评论内容 / 评论图片 / 评论返图」+ `PLATFORM_LABEL_CN` 中文平台名。
- **TaskListItem 状态推断**：mining `list_jobs` SQL 增加 `video_count` + `commented_count` 子查询聚合，前端 `TaskListItem` 据此推 failed / running / in_progress / fully_completed 状态，不再靠启发式。
- **设置页重组**：SECTIONS 改为 basics / workflow / system 三组 + 260 px 富侧边栏（图标 + 名称 + 副标题）；Cookie 池入口移到监测 section 顶部；「重置百度浏览器 profile」从 Cookie Modal 回搬到设置（登录在 Cookie Modal，重置在设置，职责分离）。
- **CVA toolchain**：引入 `class-variance-authority` + `clsx` + `tailwind-merge`，`Btn` 组件作为首个 cva refactor 试点；后续 UI primitive 会沿用这套写法。

### Changed
- **Modal 大迁移到 Dialog primitive（Phase 1 完成）**：CreateTemplate / EditBatch / StartJob / CookieManager / SkillEdit / AddTask / AlertDetail / BatchImportTask 全部迁到统一 `Dialog.vue`；Dialog 新增 `xl` size + `zClass` prop（允许 ConfirmModal 提到 z-60 不被嵌套 modal 盖住）。
- **UI 一致性 pass**：聚焦环 / 输入背景 / 下拉 / 间距全局对齐；删除 3 个零引用孤儿组件清理；首页 hero / monitor 卡片 / dropdown 视觉打磨。
- **首页工作区 3 行布局**：CreateArticleHero / 监测卡片行 / 最近文档行的纵向节奏改为 3-row layout，配套 `DESIGN.md` 落地视觉规范。
- **知乎趋势窗口 14d → 7d**：sparkBuckets / `loadResults limit` / 标签同步；LineChart Y 轴绑定 selectedTask Top-N（优先 metric → task config → 10 fallback），避免单点波动放大失真。
- **「最近文档」「打开位置」可点开**：Tauri shell `open` scope 从 `true` 改成 `"^.{1,}"`（之前 `true` 没绕过 scope 校验，所有外部打开都失败），辅助 `toFileURL` 处理 Windows 路径。

### Fixed
- **默认窗口 / 最小窗口尺寸 1280×800**：之前 default 比 min 大、min 又超过部分主流笔记本物理屏幕，窗口会撑出可视区或拉不回来。两个都钉死到 1280×800。
- **Tauri 2 下 `window.confirm()` 报 "Command not found"**：Tauri 2 砍掉了 dialog|confirm IPC，浏览器原生 `confirm` 也走不通；统一改用 in-app `confirmDialog`，cookie 删除 / baidu 登录确认等地方现在都能弹出。
- **百度账号登录弹 "Network Error"**：sidecar `/baidu/login` 最长轮询 600s，但 axios 默认 60s 超时早早把请求杀掉、用户还没点完登录就报错。给这条 endpoint 单独设 660s timeout。
- **百度登录确认弹窗被 CookieManagerModal 盖住**：原来 ConfirmModal 跟父 modal 都是 z-50，z-index 平级 → DOM 顺序决定层级。Dialog 新增 `zClass` prop，ConfirmModal 升到 z-60；CookieManagerModal 在登录出错时自动关闭，避免 toast 也被 trap。
- **「历史查重」重建按钮按了无效**：之前只是个空 handler 没接后端，现在真的 `POST /api/dedup/build-index`。
- **AddTaskModal Top-N 输入失焦不保存**：之前用 `:model-value + @commit` 配对，FormInput 内部 proxy computed 在 blur 时读到的是 stale props → 用户键入的值被丢。改回直接 `v-model="topN"`。
- **dev 模式下空 `binaries/ms-playwright/` 卡死 patchright**：Tauri dev 会把 src-tauri 下的 `binaries/ms-playwright/`（在 dev 机上是空目录，CI 才填 chromium）镜像到 `target/debug/`，`ensure_browsers_path` 之前看到目录就当 bundled 路径 → patchright 拿空目录起 chromium 直接挂。收紧检查：必须有 `chromium-*` 子目录才认是 bundled；否则继续 fallback 到 LOCALAPPDATA 缓存。
- **StartJobModal `@login` emit 没声明**：原来 `$emit('close')` 没在 emits 里，Vue 警告且 v-model 失效；改成 `$emit('update:open', false)` 走 v-model 标准合约。
- **ArticleView `passCount` vue-tsc unused-var 警告**：加 `_` 前缀 + `void` 让 strict mode 编过又不丢语义。

## [0.5.3] - 2026-05-20

### Fixed
- **其他用户装 release 包后浏览器相关功能全炸 —— 评论抓取、Cookie 内置浏览器登录、百度账号登录弹窗一起报错**：根因是 NSIS 安装包从来没带过 Chromium 二进制。Patchright 的 `collect_data_files("patchright")` 只 bundle 了 `driver/node.exe`（Node.js 驱动），真正的 Chromium 浏览器二进制位于 `%LOCALAPPDATA%\ms-playwright\chromium-XXXX\`，由 `patchright install chromium` 单独装。dev 机有这个目录（开发时跑过一次），fresh 用户机没有 —— 所以每次 `pw.chromium.launch_persistent_context(...)` 都炸 `Executable doesn't exist`，前端看到 503 / 弹窗失败 / 评论抓取无果。本次：① release.yml 加 `python -m patchright install chromium` 步骤；② 把 `chromium-XXXX/` 目录（~408MB，跳过 headless-shell）通过 Tauri `bundle.resources` 拷到 NSIS 安装包的 `<install>/binaries/ms-playwright/`；③ `csm_core/browser_infra/patchright_pool.ensure_browsers_path` 加优先级：env var → `<sidecar-exe-dir>/binaries/ms-playwright/`（release） → `%LOCALAPPDATA%\ms-playwright`（dev/legacy）。**体积变化**：NSIS 安装包从 ~50MB 涨到 ~450MB；热更新 zip 同步变大（updater `zf.extractall()` + atomic rename 包含整个 install dir，所以 chromium 会随 hot-update 一起替换 —— 从 0.5.2 → 0.5.3 的热更新下载量会突涨到 ~450MB，但后续 0.5.3 → 0.5.4 同样涨，**目前没做"chromium 不变就跳过"的分层 zip 优化**，后续若需可在 `build_manifest.py` 加 chromium hash 字段 + updater 走条件下载）。0.5.1 及以下用户仍按 v0.5.2 CHANGELOG 说明走一次 NSIS setup.exe（旧 updater image-lock bug）。

## [0.5.2] - 2026-05-20

### Fixed
- **应用内热更新依然失败 (WinError 32)，v0.4.9 那次"修"没修干净**：v0.4.9 给 updater 加了 `taskkill /F /IM csm-sidecar.exe`，但实测 v0.4.9 → v0.5.1 升级照样 rename `<install>` → `<install>.bak` 失败 18 秒后回滚到旧版（关于页一直停在 v0.4.9）。真正的根因是 **updater.exe 自己跑在 `<install>/binaries/updater.exe`** —— Windows 把 running `.exe` 映像 mmap 成 image section 持有 deny-write/deny-delete handle 直到进程退出，install dir 在 updater 退出前永远 rename 不动，这跟 sidecar 是否被 kill 完全无关。本次让 updater spawn 前先把 `<install>/binaries/updater.exe` copy 到 `%TEMP%\csm_update\updater-<pid>.exe`，从 install dir **外面**跑，install dir 里就没有正在运行的 image 占用。**老用户 0.4.x → 0.5.1 装的需要走一次 NSIS setup.exe 重装到最新版**——他们机器里的旧 updater.exe 在 install dir 里跑，下次热更新还会撞同样的 image lock。

## [0.5.1] - 2026-05-20

### Added
- **评论模板库（mining）**：评论编辑器上方新增模板 chips 行（Top 5 高频/精选 + 抽屉按钮），右侧抽屉支持全量浏览/搜索/标签筛选/inline 管理（Ctrl+/ 快捷键唤起）。设置 → 评论模板库 提供完整 CRUD + 批量导入 + JSON 导出 + 隐藏切换 + 标签过滤 + 分页。已发出的评论通过 DAO 钩子自动入库（文本归一化去重）。

## [0.5.0] - 2026-05-17

### Added
- **视频引流抓取（mining）**：新建独立「引流」view，输入关键词后从抖音/B站/快手三平台搜索抓视频列表，全局按 `(platform, platform_video_id)` 去重落 SQLite。每平台 ≈50 条，5-10 分钟出表。
- **已评论反查**：抓回的视频反查 `monitor_tasks` 中 `*_comment` 类型任务，命中则标 `already_commented=1`；前端默认筛选"未评论"看不到，切到"已评论"看到 + 绿色徽章 + 来源 tooltip。
- **平台登录 UI**：首次手动登录浏览器、cookie 持久化到 `<config_dir>/browser_profiles/<platform>/`，下次抓取自动复用。
- **任务进度 SSE**：mining 任务运行时通过 SSE 实时推 `job.progress` / `job.platform_done` / `job.finished` 事件到前端进度卡。

### Changed
- 共享浏览器基建（`cookie_store` / `ua_pool` / `rate_limit` / `patchright_pool` / `interactive_login`）从 `csm_core/monitor/` 上提到新的顶层 `csm_core/browser_infra/` 包；`monitor` 包内保留 re-export 薄层以兼容现有调用方。
- monitor SQLite schema 升级到 v3（新增 `mining_jobs` / `videos` / `video_source_keywords` 三张表）。

## [0.4.9] - 2026-05-16

### Fixed
- **应用内热更新从来没真正 work 过 —— rename 安装目录失败 (WinError 32)**：v0.4.1 起 hot-update 路径就埋了这个 bug，只是之前没人实际触发过（多数用户走 NSIS setup.exe 升级）。updater 等 csm-tauri.exe 退出后立即 rename 安装目录，但 **csm-sidecar.exe 是 Tauri sidecar 子进程，主进程退出后没被一起 kill**，仍锁着 `<install>/csm-sidecar.exe` → rename 失败 → updater 静默回滚到旧版（关于页一直停在升级前的版本号，并伴随 csm-sidecar 重启时 PyInstaller `_MEI*` 解压撞文件的 dll Error 弹窗）。本次给 `updater/main.py` 在 rename 之前加 `taskkill /F /IM csm-sidecar.exe /T`（同款 `csm-tauri.exe` 防御），跟 NSIS PREINSTALL 钩子对齐。**老用户 0.4.7 / 0.4.8 装的需要走一次 NSIS setup.exe 重装到 0.4.9**——他们机器里的旧 updater.exe 没修，下次热更新还会撞同样的锁。

## [0.4.8] - 2026-05-16

### Fixed
- **设置 → 关于 显示版本号比实际安装的低一位**：v0.4.7 安装包装好后关于页显示 v0.4.6（热更新升级也一样）。原因是发版时只 bump 了 `tauri.conf.json` / `Cargo.toml` / `package.json` 三处，漏了 sidecar `__version__`——而关于页的版本号是 sidecar `/api/system/version` 实时返回。v0.4.8 把 sidecar 自报版本号补齐为 0.4.8。**老用户 0.4.7 → 0.4.8 热更新后关于页就会正确显示**。下次发版应该用 `python scripts/release.py X.Y.Z` 一键脚本，它会同时 bump 全部 4 处源头。

## [0.4.7] - 2026-05-16

### Added
- **百度关键词排名工作台**：监测中心新增"百度排名"页签（监测中心 → 百度），按任务组聚合每日排名快照，并提供 14 天日历聚合图表（同一天多次跑取最后一次、缺失天用 0 占位），可直观看到品牌词在各关键词上的卡位 / 跌出趋势。配套独立任务类型 `baidu_keyword`，与知乎 / 评论任务在同一调度器下并行运行。
- **全局排除域名**：设置 → 监测 新增"全局排除域名"弹窗，统一管理百度 SERP 抓取里要忽略的站点（自家站 / 镜像站 / 噪声站）。前端列表 + 校验 + 持久化，后端在 SERP 解析阶段过滤，避免误把自家域名当成"竞品卡位"。
- **运行中任务可取消**：监测中心进入运行态后顶部出现「取消」按钮，调用 `/api/monitor/cancel` 立即停止当前任务循环（不影响已写盘的数据）。

### Changed
- **monitor 任务进度跨页同步**：抽出 `monitorStatus` Pinia store，订阅 sidecar `progress` SSE 事件 + `/api/monitor/running` 状态端点，"创作 / 历史 / 设置"任意切页再回到监测中心都能看到正确的运行 / 进度 / 取消状态，不再因为切走而显示成"空闲"。
- **任务表单 UI 重排**：新增任务弹窗 + 批量导入弹窗按"类型 → 标识 → 关键词 → 调度"重排字段顺序，跟列表卡片的信息层级对齐；批量导入模板同步更新。
- **百度 SERP 抓取性能优化**：内嵌 Chromium 改用 stealth 假隐藏窗口策略（无可见窗口但带完整 UA + 字体指纹），单关键词抓取耗时下降，被风控/验证码触发率显著降低。

### Fixed
- **百度二级页头部对齐 B 站简洁版**：之前百度 Level 2 比 B 站 Level 2 多一道分隔 + padding 不一致，现在视觉重量对齐。
- **关键词选中态去掉橙色左竖条**：列表选中态只用底色 + 字色变化（跟 B 站列表统一），fallback 关键词行同样可选。

## [0.4.6] - 2026-05-15

### Fixed
- **NSIS 安装包遇到运行中的 CSM 会弹「Error opening file for writing」**：之前装包覆盖时 csm-sidecar.exe / csm-tauri.exe 还活着，文件被锁，NSIS 弹「中止/重试/忽略」对话框困住用户。加 NSIS PREINSTALL 钩子（`frontend/src-tauri/installer-hooks.nsh`）在拷贝文件前自动 `taskkill /f /im csm-*.exe`，500ms 等 Windows 释放句柄。下次双击 setup.exe 不会再卡这步。

## [0.4.5] - 2026-05-15

### Fixed
- **热更新会破坏用户数据 + rename 失败（致命）**：pre-v0.4.5 的用户数据目录是 `%LocalAppData%\CSM\CSM\`，而 NSIS 把应用装到 `%LocalAppData%\CSM\` —— **数据目录是安装目录的子级**。updater 把 install dir 整个重命名时会把数据一起搬走，再删 backup 时会**静默删光用户的 settings / cookies / 历史 / monitor db**。v0.4.4 的 rename 失败（"另一个进程正在使用此文件"）反而保住了数据。v0.4.5 把数据目录搬到 `%LocalAppData%\CSM-Data\`，跟 install dir 完全分离；老用户首次启动 v0.4.5 时会自动 `shutil.copytree` 把 `CSM\CSM\` 内容复制到 `CSM-Data\`（老目录保留作为备份，不删）。
- **Updater 安装时弹出黑色命令行窗口**：`updater.spec` 改 `console=False`，安装过程现在静默执行。日志仍写到 `%TEMP%\csm_update\updater.log`。失败时 app 静默回到旧版本（如果将来需要错误弹窗反馈再考虑加 MessageBox）。

### Changed
- **托盘右键菜单**加 "Content SEO Maker" 品牌头 + 分隔符 + 显示主窗口/退出的快捷键提示（Ctrl+Shift+C / Ctrl+Q），让 2 行的裸菜单看起来更"成型"。Windows 原生菜单无法直接套主界面的暖米色 + 圆角 + 字体（OS 接管渲染），所以视觉上仍是 Windows 原生灰白色，但信息密度跟主品牌指示提升。完全自定义渲染需要起一个透明 webview 小窗口，留给后续迭代。

## [0.4.3] - 2026-05-15

### Fixed
- **应用内热更新「立即重启」失败**：下载完成后点「立即重启」会弹「启动安装失败：zip_path is empty」，更新装不上。原因是 modal 的 resolveFinal 同步清空了 reactive state（包括 targetPath），SettingsView 在 await 之后再读已经是空。改为在 SSE done 回调里本地捕获 zip 路径，invoke Tauri 时用本地变量。
- **首次启动欢迎页「下一步」按钮不明显**：之前是个 46×46 px 的小空心圆只放一个 → 箭头，没文字、按下后没 loading 反馈。sidecar 第一次冷启动慢的话 patch 要好几秒，用户以为卡死就 force-quit。改为带「下一步」文字 + spinner 的实心按钮 + 按 Enter 也能提交 + 提交期间 disable 防连点。

## [0.4.2] - 2026-05-15

### Fixed
- 设置 → 关于 显示的版本号、以及「检查更新」弹窗里的「当前 vX.Y.Z」终于跟实际安装的版本号一致 —— 以前 sidecar `__version__` 一直停在 `0.0.1`、前端 `APP_VERSION` 常量停在 `0.4.0`，发版时 release.py 没把这两处一起 bump。改后版本号统一从 sidecar `/api/version` 实时读，release.py 也同时 bump sidecar `__init__.py`。

## [0.4.1] - 2026-05-14

### Added
- **桌面壳从 PyQt6 迁移到 Tauri 2 + Vue 3 + FastAPI sidecar 架构**：新的前端在浏览器/Tauri shell 中都能跑，UI 改进大量，启动更快，安装包更小。
- **应用内热更新**：设置 → 关于 → 检查更新，发现新版本自动弹窗显示版本号 / changelog / 文件大小；用户确认后流式下载（带 SHA256 校验、可取消），完成后一键关闭主程序、由独立 updater 替换安装目录、自动重启。
- **文章生成两步式流程**：拆分为「填资料 + 生成提纲」和「逐段落填充」两步，每一步独立保存，中断后可恢复；右侧栏新增「质检报告」面板显示历史重复率 + 素材引用率 + Top 3 相似来源。
- **历史报告页**（导航 → 历史报告）：知乎排名 trend、评论留存 trend 两块 LineChart 视图，全量历史数据可看。
- **批量导入**：监测任务支持 Excel 模板批量导入，错误行单独反馈不影响整体；模板下载入口在批量导入弹窗内。
- **NSIS 安装器**：首装走标准 Windows 安装包，自动写注册表 + 卸载条目 + Start Menu 快捷方式。

### Changed
- 段落筛选属性下拉在配置 Vault 后零额外操作即可使用（sidecar 启动时自动扫描素材库；前端在 409 时自愈重试 scan + 重新拉取）；value 支持多选（属性 `sample_values` 不超过 20 时渲染下拉，否则保留手填）。
- 新增「历史索引目录」概念：导出文章会自动以 `.md` 镜像到该目录（带 frontmatter `title / keyword / template / words / exported_at / source_format`），首页「最近文档」/ 字数统计 / 日历改用此目录作为数据源。**旧用户首次启动后，已有 `out_dir` 下的旧导出不会出现在最近文档中——历史归零是预期行为。**
- Templates / Skills / History 三个目录在首次启动自动建好（位于 `%LOCALAPPDATA%\CSM\CSM\` 下，macOS / Linux 对应位置同），内置样例模板 / Skills 自动种子；用户仍可在「设置 → 存储路径」修改位置。
- 「设置 → 历史查重」section 中的「历史索引目录」降级为只读地址（统一编辑入口到「存储路径」），重建按钮保留。

### Fixed
- 最近文档点击改为用系统默认应用打开文件（VS Code / Typora / Notepad），代替之前跳转到空白创作区的占位行为。
- 快手评论 /f/ 短链解析 + GraphQL V2 字段切换，快手内置账号登录器 cookie 检测与诊断改进。
- release 安装包不再把开发期 sidecar URL 烙进 Vite bundle（之前导致 release app 启动时回连一个早就死掉的开发机地址）。
- NSIS 首装链路串通 + UI 启动闪屏抖动修复。

## [0.3.0] - 2026-05-09

### Added
- 监测中心：新增一级导航页，整合 Case-6 知乎问题排名监测与 Case-8 多平台评论留存检测，建立"生成 → 投放 → 监测 → 反馈 → 再生成"闭环。
- 知乎抓取：curl_cffi（chrome120 TLS 指纹）主路径 + DrissionPage 兜底的双层方案，无需官方 API。
- 评论平台：B 站 / 抖音 / 快手 评论留存检测，API 直连（含 x-bogus / GraphQL 签名），失败自动降级到浏览器兜底。
- 调度与限流：QTimer 60s tick 单例调度器，平台级令牌桶 + RequestPacer + CircuitBreaker，主线程零阻塞。
- AI 联动：排名跌出 Top N 自动告警 + 一键跳转 ArticlePage 预填关键词 / 竞品摘要；评论情感与相关度 LLM 分类；Top 回答摘要落盘到 Vault。
- Cookie 管理：4 平台 Cookie 池 CRUD，按"失败次数升序、最近最少使用优先"轮询，连续失败 5 次自动停用。
- Excel 批量导入：监测任务支持模板下载 + 批量录入，错误行单独反馈不影响整体导入。
- 设置页「监测」分组：并发 / 限速 / 告警阈值 / 浏览器兜底路径 / AI 联动开关 / Cookie 管理入口。

### Fixed
- 设置页模型选择问题。
- 洗稿流程未调用 AI 的问题。

## [0.2.0] - 2026-05-07

### Added
- 系统托盘后台运行：关闭按钮默认最小化到托盘，托盘菜单提供新建文章 / 模板 / Skill / 设置 / 退出快捷操作。
- 单实例锁：避免重复双击启动多份 CSM 进程。
- 内容查重：创作区右侧润色按钮下方显示「历史重复率」+「素材引用率」双指标，支持下钻查看 top 3 相似来源 + 命中段落（MinHash + LSH 候选检索 + 13-字 shingling 精算）。
- 应用热更新：启动时静默检查 GitHub 私有仓库的最新 Release，发现新版本即弹窗提示，一键升级（独立 updater.exe 接管文件替换 + 失败回滚）。
- 设置页「关于 CSM」区块：显示当前版本 + 「检查更新」按钮 + 更新仓库配置。
- 自动化发版流水线：`scripts/release.py` 一键发版 + GitHub Actions 自动构建 + 抽 CHANGELOG 段落填充 Release notes。

## [0.1.0] - 2026-04-15

### Added
- 项目初版。
