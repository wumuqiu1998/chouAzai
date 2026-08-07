export type ParticipationDegree = 1 | 2 | 3 | 4;

export interface DeepSeekStock {
  code: string;
  name: string;
  degree: ParticipationDegree;
  stage: string;
  verified: string;
  driver: string;
  invalidation: string;
  source: string;
  sourceLabel: string;
  sourceDate: string;
}

export interface DeepSeekStockLayer {
  name: string;
  role: string;
  factors: string[];
  stocks: DeepSeekStock[];
}

// 仅收录有交易所披露、投资者关系记录或公司官网材料可核验的代表性 A 股。
// degree 衡量业务参与阶段，不衡量收入占比、利润弹性或投资价值。
export const deepSeekStockLayers: DeepSeekStockLayer[] = [
  {
    name: "芯片与算力底座",
    role: "决定国产化部署的可得算力、推理效率与软件迁移成本。",
    factors: ["模型适配速度", "Tokens/s 与显存效率", "算子和框架生态", "芯片供给", "客户导入"],
    stocks: [
      {
        code: "688041",
        name: "海光信息",
        degree: 3,
        stage: "DCU 深度适配",
        verified: "海光 DCU 已适配主流大模型；公司披露 DeepSeek-V3.2-Exp 发布当日完成无缝适配与深度调优。",
        driver: "DCU 出货、国产算力采购、适配后的真实性能和软件生态成熟度。",
        invalidation: "适配停留在兼容层，未转化为整机采购、集群利用率或客户扩容。",
        source: "https://sns.sseinfo.com/resources/images/upload/202510/2025101616470181524512619.pdf",
        sourceLabel: "上证路演材料",
        sourceDate: "2025-10-16",
      },
      {
        code: "688343",
        name: "云天励飞-U",
        degree: 4,
        stage: "一体机与政务落地",
        verified: "云天天书训推一体机已适配 DeepSeek，并披露支撑政务外网部署全尺寸 R1 及多项政务应用。",
        driver: "NPU 产品放量、一体机交付、政务项目复制和推理效率。",
        invalidation: "案例无法跨区域复制，项目收入一次性强或芯片供给约束交付。",
        source: "https://sns.sseinfo.com/resources/images/upload/202509/202509231516013507051373.pdf",
        sourceLabel: "上证路演材料",
        sourceDate: "2025-09-23",
      },
    ],
  },
  {
    name: "服务器与一体机",
    role: "把芯片、内存、网络、模型和开发平台集成为可交付的私有化系统。",
    factors: ["显存与互连带宽", "模型版本兼容", "整机交付量", "软硬件毛利", "售后运维"],
    stocks: [
      {
        code: "603019",
        name: "中科曙光",
        degree: 3,
        stage: "全栈方案产品化",
        verified: "公司官网披露曙光 AI 解决方案适配 DeepSeek 等模型，并形成国产算力与云侧部署方案。",
        driver: "服务器和智算集群订单、超融合一体机交付、海光生态协同。",
        invalidation: "方案适配广但 DeepSeek 专项订单、收入与毛利未形成可观贡献。",
        source: "https://www.sugon.com/cut?id=2510&nav_id=",
        sourceLabel: "公司官网",
        sourceDate: "2025",
      },
      {
        code: "000977",
        name: "浪潮信息",
        degree: 4,
        stage: "专用服务器与平台",
        verified: "已推出元脑 R1 推理服务器、EPAI 企业平台和 DeepSeek 一体机，并持续完成新版本软硬件优化。",
        driver: "AI 服务器出货、单位 Token 性能、企业私有化部署和平台附加价值。",
        invalidation: "行业价格竞争导致毛利承压，模型降本未带来服务器需求弹性。",
        source: "https://www.ieisystem.com/about/news/23147.html",
        sourceLabel: "公司官网",
        sourceDate: "2026-07-09",
      },
      {
        code: "000938",
        name: "紫光股份",
        degree: 4,
        stage: "一体机与客户场景",
        verified: "旗下新华三推出灵犀 Cube / UniCube DeepSeek 一体机，覆盖 14B 至 671B，并披露政务场景部署。",
        driver: "政企订单、全栈交付率、网络存储配套销售和订阅运维收入。",
        invalidation: "一体机以试点为主、客户复购弱，或收入主要来自低毛利硬件。",
        source: "https://www.h3c.com/cn/d_202503/2369403_473262_0.htm",
        sourceLabel: "新华三官网",
        sourceDate: "2025-03",
      },
      {
        code: "002261",
        name: "拓维信息",
        degree: 3,
        stage: "国产算力深度适配",
        verified: "兆瀚算力产品完成 DeepSeek 多版本适配，并推出基于昇腾、鲲鹏的数据标注一体机。",
        driver: "兆瀚服务器出货、昇腾供给、政企项目转化和数据工程需求。",
        invalidation: "产品发布多于实际交付，或核心部件供给限制整机收入确认。",
        source: "https://www.talkweb.com.cn/news-center/news/detail/1890296679334764546",
        sourceLabel: "公司官网",
        sourceDate: "2025-02",
      },
    ],
  },
  {
    name: "云、MaaS 与算力服务",
    role: "以 API、弹性算力或托管部署方式提供模型调用，并承担集群调度和安全运维。",
    factors: ["Token 调用量", "算力利用率", "API 价格", "缓存命中率", "推理毛利", "客户续费"],
    stocks: [
      {
        code: "601728",
        name: "中国电信",
        degree: 4,
        stage: "全栈国产云落地",
        verified: "天翼云已完成 DeepSeek 系列适配；2026 年披露助力中国石化完成 V4-Pro 全国产化部署。",
        driver: "央企私有化需求、Token 服务量、智算资源利用率和云网协同收入。",
        invalidation: "大模型业务体量相对集团收入仍小，重资产扩容快于付费需求。",
        source: "https://www.chinatelecom.com.cn/ct/news/gdxw/166633.html",
        sourceLabel: "中国电信官网",
        sourceDate: "2026-05-14",
      },
      {
        code: "688158",
        name: "优刻得-W",
        degree: 4,
        stage: "MaaS 服务与客户交付",
        verified: "UModelVerse 上架 DeepSeek API 和镜像，完成国产芯片适配，并披露帮助国企客户接入。",
        driver: "API 付费调用、GPU 利用率、海外调用和企业训推一体机需求。",
        invalidation: "低价竞争压缩推理毛利，免费体验未能转为持续付费。",
        source: "https://www.ucloud.cn/site/about/news/recent/20251128/6804.html",
        sourceLabel: "公司官网",
        sourceDate: "2025-02-14",
      },
      {
        code: "000034",
        name: "神州数码",
        degree: 3,
        stage: "Agent 平台与一体机",
        verified: "官网产品矩阵包含神州问学 DeepSeek 版及神州鲲泰问学一体机 DeepSeek 版。",
        driver: "一体机交付、企业 Agent 项目、知识治理服务和高端网络配套。",
        invalidation: "DeepSeek 版本只是多模型平台中的一项能力，专项收入未单独披露。",
        source: "https://www.digitalchina.com/",
        sourceLabel: "公司官网产品页",
        sourceDate: "2026-08-05 核验",
      },
    ],
  },
  {
    name: "数据、中间件与行业集成",
    role: "把模型连接到企业知识、权限、流程和行业系统，解决生产环境的最后一公里。",
    factors: ["项目转生产率", "知识库准确率", "交付周期", "标准化程度", "续费与运维", "数据合规"],
    stocks: [
      {
        code: "002657",
        name: "中科金财",
        degree: 3,
        stage: "金融软硬一体方案",
        verified: "与海光联合推出适配 DeepSeek 的多模型引擎与 DCU 软硬一体方案，覆盖金融典型场景。",
        driver: "银行项目落地、模型路由与调优能力、软硬一体方案复制率。",
        invalidation: "方案仍以技术验证为主，金融客户预算或合规周期拖慢收入确认。",
        source: "https://www.sinodata.net.cn/article/2165.html",
        sourceLabel: "公司官网",
        sourceDate: "2025-02-07",
      },
      {
        code: "600850",
        name: "电科数字",
        degree: 3,
        stage: "央国企场景落地",
        verified: "公司披露部分 DeepSeek 相关 AI 项目已落地、部分仍在测试，并有百余个 AI 业务机会。",
        driver: "在手机会转订单率、央国企交付、知识管理与多模态项目复用。",
        invalidation: "业务机会长期停留售前或测试，项目定制成本吞噬利润。",
        source: "https://sns.sseinfo.com/resources/images/upload/202505/202505091541000779374645.pdf",
        sourceLabel: "上证路演材料",
        sourceDate: "2025-05",
      },
    ],
  },
  {
    name: "Agent 与行业应用",
    role: "将模型能力嵌入企业管理、金融、教育与商户运营，最终由付费和效率兑现价值。",
    factors: ["活跃与留存", "付费席位", "任务完成率", "人工节省", "Token 成本占比", "收入贡献"],
    stocks: [
      {
        code: "600588",
        name: "用友网络",
        degree: 3,
        stage: "企业软件接入 V4",
        verified: "用友 BIP 已公开完成 DeepSeek-V4 接入，覆盖企业数据、流程、智能应用与服务链路。",
        driver: "BIP 客户迁移、AI 订阅增购、智能体使用频次和客单价提升。",
        invalidation: "接入未带来订阅增购，推理成本和交付投入高于新增收入。",
        source: "https://www.yonyou.com/news/4937",
        sourceLabel: "公司官网",
        sourceDate: "2026",
      },
      {
        code: "300674",
        name: "宇信科技",
        degree: 3,
        stage: "金融一体机与 Agent",
        verified: "公司披露金融 AI 全栈服务、一体机案例及 DeepSeek 发布后银行侧 Agent 需求机会。",
        driver: "银行业务侧预算、潜在线索转订单、标准产品占比和海外金融需求。",
        invalidation: "需求持续停留在验证，银行合规和采购周期导致商业化延后。",
        source: "https://static.cninfo.com.cn/finalpage/2025-04-06/1223014051.PDF",
        sourceLabel: "巨潮投资者关系记录",
        sourceDate: "2025-04-06",
      },
      {
        code: "300248",
        name: "新开普",
        degree: 2,
        stage: "教育产品接入验证",
        verified: "小美同学和星工场以 API 接入 DeepSeek-R1 并进行适配；公司明确相关收入占比较低。",
        driver: "高校项目预算、私有部署需求、智能体使用率和新增模块收费。",
        invalidation: "公司已提示收入占比低；若试点不转预算，业绩影响仍有限。",
        source: "https://static.cninfo.com.cn/finalpage/2025-02-20/1222593981.PDF",
        sourceLabel: "巨潮投资者关系记录",
        sourceDate: "2025-02-19",
      },
      {
        code: "000997",
        name: "新大陆",
        degree: 1,
        stage: "内部运营使用",
        verified: "公司披露已接入包括 DeepSeek 在内的多家模型，主要用于内部标签、分析和风控降本。",
        driver: "内部效率节省是否可量化，以及能力能否转化为对外商户产品。",
        invalidation: "仅内部工具使用、无对外收入，且 DeepSeek 只是多模型之一。",
        source: "https://static.cninfo.com.cn/finalpage/2025-04-02/1222990857.PDF",
        sourceLabel: "巨潮投资者关系记录",
        sourceDate: "2025-04-02",
      },
    ],
  },
];
