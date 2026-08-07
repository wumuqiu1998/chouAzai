import { useState } from "react";
import {
  AlertTriangle,
  Boxes,
  BrainCircuit,
  CheckCircle2,
  CircleDot,
  CloudCog,
  ExternalLink,
  Gauge,
  Layers3,
  Network,
  ServerCog,
  ShieldCheck,
  TrendingUp,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import { deepSeekStockLayers, type ParticipationDegree } from "@/data/deepseek-stocks";

const TABS = ["总览", "产业链地图", "A股图谱", "技术与部署", "价值传导", "跟踪与风险"] as const;
type Tab = typeof TABS[number];

const chain = [
  ["01", "算力与数据中心", "AI 加速器、服务器、存储、高速网络、供电与液冷", "有效算力供给、集群利用率与总体拥有成本"],
  ["02", "模型训练与对齐", "数据治理、预训练、后训练、强化学习、评测", "高质量数据、训练稳定性与能力迭代"],
  ["03", "推理服务与 API", "推理集群、上下文缓存、调度、网关与云服务", "首字延迟、吞吐、稳定性与单位 Token 成本"],
  ["04", "私有化部署", "开源权重、蒸馏、量化、推理框架与国产硬件适配", "软硬件兼容、交付效率和持续运维"],
  ["05", "AI 中间件", "RAG、知识库、工具调用、模型路由、评测与安全", "数据治理、可观测性和复杂工作流可靠性"],
  ["06", "Agent 与行业应用", "编程、办公、客服、金融、制造、政企与端侧应用", "留存、付费、任务闭环和推理成本占收入比"],
];

const technologies = [
  ["MoE 稀疏激活", "每个 Token 只激活部分参数，降低单次计算量；代价是专家路由和跨卡通信更复杂。"],
  ["MLA 注意力", "压缩推理时的 KV Cache 压力，有利于长上下文和并发；收益仍取决于框架与硬件实现。"],
  ["FP8 / 量化", "降低存储、带宽和计算压力，但需要算子、精度和硬件支持共同验证。"],
  ["MTP / 推测解码", "通过多 Token 预测提高解码吞吐；实际加速取决于接受率、批处理和系统调度。"],
  ["强化学习推理", "强化复杂推理和自我校验能力，同时可能增加思考 Token、延迟与调用成本。"],
  ["蒸馏与小模型", "把部分推理能力迁移到更小模型，降低部署门槛，但需接受能力边界和场景化评测。"],
];

const deploymentRows = [
  ["官方 API", "接入快、前期投入低、模型持续升级", "外部调用、变动成本、版本迁移与合规"],
  ["云平台托管", "弹性资源、专有网络和工程服务", "平台依赖、计费口径和运维边界"],
  ["私有化全量部署", "数据可控、可深度定制", "硬件投入大、集群调度与适配复杂"],
  ["蒸馏 / 端侧部署", "低延迟、低门槛、离线可用", "能力损失、微调成本和场景边界"],
];

const valueRows = [
  ["算力基础设施", "调用量和私有化集群需求持续增长", "Token 量、服务器利用率、推理集群扩容", "单位任务算力下降快于需求增长"],
  ["云与推理服务", "低价带来需求弹性，平台保持高利用率", "调用量、缓存命中率、并发和推理毛利", "价格战压缩利润且客户多模型分流"],
  ["部署与中间件", "企业从试用走向生产，复杂工作流需要治理", "付费项目、续费、适配周期、故障率", "基础能力被云厂商快速内置"],
  ["数据、安全与评测", "高价值场景要求可追溯、可控和可验证", "知识库覆盖率、评测通过率、合规预算", "项目停留在一次性交付"],
  ["Agent 与应用", "真正嵌入工作流并节省人时或创造收入", "留存、付费率、任务完成率、单任务毛利", "活跃来自补贴，无法形成业务闭环"],
];

const metrics = [
  ["模型与 API", "版本、上下文长度、工具调用、价格、并发与缓存政策", "官方文档 / 更新日志"],
  ["推理效率", "TTFT、TPOT、Tokens/s、显存占用、批处理与缓存命中", "部署压测 / 框架基准"],
  ["基础设施", "集群利用率、服务器交付、机柜功率、PUE 与扩容节奏", "运营披露 / 项目验收"],
  ["开源生态", "权重下载、框架适配、版本发布与开发者活跃", "官方仓库 / 社区项目"],
  ["企业落地", "试点转生产率、合同续费、交付周期和故障率", "客户案例 / 项目公告"],
  ["应用商业化", "留存、付费、任务完成率、单用户 Token 成本", "产品运营数据"],
];

const risks = [
  ["成本错觉", "单 Token 成本下降不自动等于算力总需求上升，必须验证需求弹性。"],
  ["版本迭代", "API 名称、接口能力与部署栈变化快，兼容成本可能被低估。"],
  ["同质化竞争", "模型能力和推理价格快速收敛，中间层可能被平台内置。"],
  ["交付落差", "演示效果不等于生产可靠性，权限、数据质量和评测常成为瓶颈。"],
  ["数据与合规", "敏感数据外发、知识产权、审计与幻觉风险限制高价值场景。"],
  ["资本开支", "私有化部署若利用率不足，折旧、能耗和运维会显著抬高成本。"],
];

function SectionTitle({ icon: Icon, children }: { icon: typeof Network; children: string }) {
  return <h2 className="mb-3 flex items-center gap-2 text-base font-bold"><Icon className="h-4 w-4 text-primary" />{children}</h2>;
}

export function DeepSeekResearch() {
  const [tab, setTab] = useState<Tab>("总览");

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2 border-b border-border/60 pb-4">
        {TABS.map((item) => (
          <button
            key={item}
            onClick={() => setTab(item)}
            className={cn(
              "rounded-full border px-3.5 py-1.5 text-sm transition-colors",
              tab === item
                ? "border-primary bg-primary/15 font-semibold text-primary"
                : "border-border bg-muted/30 text-muted-foreground hover:text-foreground",
            )}
          >
            {item}
          </button>
        ))}
      </div>

      {tab === "总览" && <Overview />}
      {tab === "产业链地图" && <IndustryChain />}
      {tab === "A股图谱" && <StockMap />}
      {tab === "技术与部署" && <TechnologyAndDeployment />}
      {tab === "价值传导" && <ValueTransmission />}
      {tab === "跟踪与风险" && <TrackingAndRisks />}

      <SourceNote />
    </div>
  );
}

const degreeMeta: Record<ParticipationDegree, { label: string; className: string }> = {
  4: { label: "客户 / 生产落地", className: "bg-success/10 text-success" },
  3: { label: "产品化 / 深度适配", className: "bg-primary/10 text-primary" },
  2: { label: "接入验证", className: "bg-warning/10 text-warning" },
  1: { label: "内部使用 / 弱映射", className: "bg-muted text-muted-foreground" },
};

function Participation({ degree }: { degree: ParticipationDegree }) {
  const meta = degreeMeta[degree];
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className={cn("rounded-full px-2.5 py-1 text-[11px] font-medium", meta.className)}>{meta.label}</span>
      <span className="flex items-center gap-1" title={`参与度 ${degree}/4`}>
        {[1, 2, 3, 4].map((item) => <span key={item} className={cn("h-1.5 w-5 rounded-full", item <= degree ? "bg-primary" : "bg-muted")} />)}
      </span>
    </div>
  );
}

function StockMap() {
  return (
    <div className="space-y-5">
      <GlassCard glow>
        <SectionTitle icon={ShieldCheck}>先划清关系边界</SectionTitle>
        <p className="text-sm leading-7 text-muted-foreground">
          <b className="text-foreground">DeepSeek 运营主体不是 A 股上市公司。</b>
          下列公司是模型使用方、适配方、算力或应用服务商，不等于持有 DeepSeek 股权，也不自动构成官方合作关系。DeepSeek 开放平台协议还明确禁止第三方用“官方合作、授权合作”等称谓造成误解。
        </p>
        <div className="mt-3 grid gap-2 text-xs md:grid-cols-4">
          {([4, 3, 2, 1] as ParticipationDegree[]).map((degree) => (
            <div key={degree} className="rounded-xl border border-border/60 bg-muted/20 p-3"><Participation degree={degree} /></div>
          ))}
        </div>
        <p className="mt-3 text-xs text-warning">参与度只衡量落地阶段，不代表收入占比、利润弹性、估值高低或推荐顺序。</p>
      </GlassCard>

      {deepSeekStockLayers.map((layer) => (
        <section key={layer.name} className="space-y-3">
          <GlassCard className="p-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h3 className="font-bold">{layer.name}</h3>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">{layer.role}</p>
              </div>
              <div className="flex max-w-2xl flex-wrap gap-1.5">
                {layer.factors.map((factor) => <span key={factor} className="rounded-full border border-border/60 bg-muted/30 px-2.5 py-1 text-[11px] text-muted-foreground">{factor}</span>)}
              </div>
            </div>
          </GlassCard>

          <div className="grid gap-3 lg:grid-cols-2">
            {layer.stocks.map((stock) => (
              <GlassCard key={stock.code} className="flex h-full flex-col p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-bold">{stock.name} <span className="font-mono text-xs font-normal text-muted-foreground">{stock.code}</span></p>
                    <p className="mt-1 text-xs text-primary">{stock.stage}</p>
                  </div>
                  <Participation degree={stock.degree} />
                </div>

                <div className="mt-3 space-y-2 text-xs leading-5">
                  <p><span className="font-semibold text-foreground">已验证：</span><span className="text-muted-foreground">{stock.verified}</span></p>
                  <p><span className="font-semibold text-foreground">关键驱动：</span><span className="text-muted-foreground">{stock.driver}</span></p>
                  <p><span className="font-semibold text-foreground">证伪点：</span><span className="text-warning">{stock.invalidation}</span></p>
                </div>

                <a href={stock.source} target="_blank" rel="noreferrer" className="mt-auto inline-flex items-center gap-1 pt-3 text-[11px] text-primary hover:underline">
                  {stock.sourceLabel} · {stock.sourceDate}<ExternalLink className="h-3 w-3" />
                </a>
              </GlassCard>
            ))}
          </div>
        </section>
      ))}

      <div className="rounded-xl border border-warning/30 bg-warning/5 px-4 py-3 text-xs leading-5 text-muted-foreground">
        代表性样本并非完整概念股名单。模型适配新闻只能证明技术或产品动作；判断业绩贡献仍需继续核对定期报告中的 AI 收入、订单、客户数量、合同负债、毛利率和经营现金流。
      </div>
    </div>
  );
}

function Overview() {
  return (
    <div className="space-y-5">
      <GlassCard glow>
        <p className="text-sm leading-7 text-muted-foreground">
          <b className="text-foreground">核心判断：</b>
          DeepSeek 产业链不是单一“模型概念”，而是高性价比模型驱动的完整技术栈：上游提供算力与数据中心，中游完成模型训练、推理服务和私有化部署，下游通过 Agent 与行业应用把 Token 转化为真实任务。研究重点不是“接入了没有”，而是调用量、生产可靠性和商业闭环是否持续形成。
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          {[
            ["需求逻辑", "单位推理成本下降可能释放更多调用，但总算力是否增长取决于需求弹性。"],
            ["价值重心", "从模型能力竞赛逐步延伸到推理效率、部署交付、数据治理和工作流闭环。"],
            ["研究边界", "区分官方 API、开源权重和第三方适配；接入、试点、生产与收入不是同一阶段。"],
          ].map(([title, detail]) => (
            <div key={title} className="rounded-xl bg-muted/40 p-3">
              <p className="text-sm font-semibold">{title}</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p>
            </div>
          ))}
        </div>
      </GlassCard>

      <div className="grid gap-3 md:grid-cols-2">
        <GlassCard className="p-4">
          <div className="flex items-center gap-2"><CloudCog className="h-4 w-4 text-primary" /><p className="font-semibold">当前云端产品层</p></div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">截至 2026-08-05，官方 API 已进入 V4-Flash / V4-Pro，支持思考与非思考模式、1M 上下文、工具调用，并提供 OpenAI / Anthropic 兼容接口。</p>
        </GlassCard>
        <GlassCard className="p-4">
          <div className="flex items-center gap-2"><Boxes className="h-4 w-4 text-primary" /><p className="font-semibold">开源部署基础层</p></div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">公开可复用的部署生态主要建立在 V3 / R1 权重及其蒸馏模型上，围绕 MoE、MLA、FP8、强化学习推理和多种推理框架展开。</p>
        </GlassCard>
      </div>

      <GlassCard>
        <SectionTitle icon={CheckCircle2}>先看清一条价值传导链</SectionTitle>
        <div className="grid gap-2 text-center text-xs md:grid-cols-5">
          {["模型能力提升", "单位成本下降", "调用量与场景扩张", "生产部署深化", "收入 / 效率兑现"].map((item, index) => (
            <div key={item} className="rounded-xl border border-border/60 bg-muted/30 px-3 py-3">
              <span className="font-black text-primary/70">0{index + 1}</span>
              <p className="mt-1 font-medium">{item}</p>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs leading-5 text-muted-foreground">任一环节不能被公开数据验证，都不应直接推导为产业景气或商业兑现。</p>
      </GlassCard>
    </div>
  );
}

function IndustryChain() {
  return (
    <div className="space-y-5">
      <GlassCard>
        <SectionTitle icon={Network}>产业链地图：从算力投入到应用兑现</SectionTitle>
        <p className="text-sm leading-7 text-muted-foreground">DeepSeek 降低模型使用门槛后，价值并不会平均分布。越靠近上游越看资本开支与利用率，越靠近下游越看用户留存、任务完成率和付费能力。</p>
      </GlassCard>
      <div className="space-y-2">
        {chain.map(([number, title, scope, focus]) => (
          <GlassCard key={number} className="flex flex-col gap-3 p-4 lg:flex-row lg:items-center">
            <span className="text-xl font-black text-primary/80">{number}</span>
            <div className="lg:w-44"><p className="font-semibold">{title}</p></div>
            <p className="flex-1 text-xs leading-5 text-muted-foreground">{scope}</p>
            <span className="rounded-full bg-warning/10 px-2.5 py-1 text-xs text-warning lg:max-w-64">关注：{focus}</span>
          </GlassCard>
        ))}
      </div>
    </div>
  );
}

function TechnologyAndDeployment() {
  return (
    <div className="space-y-5">
      <div>
        <SectionTitle icon={BrainCircuit}>效率来自算法、框架与硬件协同</SectionTitle>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {technologies.map(([name, detail]) => (
            <GlassCard key={name} className="p-4">
              <Gauge className="h-4 w-4 text-primary" />
              <p className="mt-2 font-semibold">{name}</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p>
            </GlassCard>
          ))}
        </div>
      </div>

      <div>
        <SectionTitle icon={ServerCog}>四种部署路径不能混用同一估值逻辑</SectionTitle>
        <div className="overflow-x-auto rounded-2xl border border-border/70">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="bg-muted/50 text-muted-foreground"><tr><th className="p-3">部署路径</th><th className="p-3">主要优势</th><th className="p-3">关键约束</th></tr></thead>
            <tbody>{deploymentRows.map(([route, value, constraint]) => <tr key={route} className="border-t border-border/60"><td className="p-3 font-medium">{route}</td><td className="p-3 text-muted-foreground">{value}</td><td className="p-3 text-muted-foreground">{constraint}</td></tr>)}</tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function ValueTransmission() {
  return (
    <div className="space-y-5">
      <GlassCard glow>
        <SectionTitle icon={TrendingUp}>判断“受益”要同时满足三个条件</SectionTitle>
        <p className="text-sm leading-7 text-muted-foreground">需求真实增长、价值能够被该环节捕获、收入增量高于新增成本。只满足“概念相关”或“完成适配”，不足以证明持续受益。</p>
      </GlassCard>
      <div className="overflow-x-auto rounded-2xl border border-border/70">
        <table className="w-full min-w-[920px] text-left text-sm">
          <thead className="bg-muted/50 text-muted-foreground"><tr><th className="p-3">环节</th><th className="p-3">成立条件</th><th className="p-3">验证指标</th><th className="p-3">证伪信号</th></tr></thead>
          <tbody>{valueRows.map(([segment, condition, metric, invalidation]) => <tr key={segment} className="border-t border-border/60"><td className="p-3 font-medium">{segment}</td><td className="p-3 text-muted-foreground">{condition}</td><td className="p-3 text-muted-foreground">{metric}</td><td className="p-3 text-warning">{invalidation}</td></tr>)}</tbody>
        </table>
      </div>
      <GlassCard>
        <p className="text-sm font-semibold">研究结论应落到单位经济</p>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">应用层至少要回答：完成一个真实任务需要多少 Token、推理和人工复核成本是多少、用户愿意支付多少、错误造成的损失如何控制。没有这些变量，调用量增长可能只有收入，没有利润。</p>
      </GlassCard>
    </div>
  );
}

function TrackingAndRisks() {
  return (
    <div className="space-y-5">
      <div>
        <SectionTitle icon={Layers3}>六组跟踪指标</SectionTitle>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {metrics.map(([name, detail, source]) => (
            <GlassCard key={name} className="p-4">
              <CircleDot className="h-4 w-4 text-primary" />
              <p className="mt-2 font-semibold">{name}</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p>
              <p className="mt-2 text-[11px] text-primary/80">来源：{source}</p>
            </GlassCard>
          ))}
        </div>
      </div>

      <GlassCard>
        <SectionTitle icon={ShieldCheck}>风险与证伪清单</SectionTitle>
        <div className="grid gap-3 md:grid-cols-2">
          {risks.map(([name, detail]) => (
            <div key={name} className="rounded-xl border border-warning/20 bg-warning/5 p-3">
              <p className="flex items-center gap-1.5 text-sm font-semibold"><AlertTriangle className="h-3.5 w-3.5 text-warning" />{name}</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p>
            </div>
          ))}
        </div>
      </GlassCard>
    </div>
  );
}

function SourceNote() {
  return (
    <div className="rounded-xl border border-border/60 bg-muted/20 px-4 py-3 text-xs leading-5 text-muted-foreground">
      <p><b className="text-foreground">资料口径：</b>核实于 2026-08-05。云端产品规格来自 DeepSeek 官方 API 文档；开源架构与部署口径来自官方 V3 / R1 仓库。</p>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
        <a className="text-primary hover:underline" href="https://api-docs.deepseek.com/updates/" target="_blank" rel="noreferrer">官方更新日志</a>
        <a className="text-primary hover:underline" href="https://api-docs.deepseek.com/quick_start/pricing/" target="_blank" rel="noreferrer">模型与 API 规格</a>
        <a className="text-primary hover:underline" href="https://github.com/deepseek-ai/DeepSeek-V3" target="_blank" rel="noreferrer">DeepSeek-V3</a>
        <a className="text-primary hover:underline" href="https://github.com/deepseek-ai/DeepSeek-R1" target="_blank" rel="noreferrer">DeepSeek-R1</a>
      </div>
      <p className="mt-2">这是产业研究框架，不推荐个股、不预测涨跌。模型版本、价格与接口能力变化快，使用时请再次核对官方资料。</p>
    </div>
  );
}
