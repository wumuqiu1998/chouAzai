import { useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, CircleDot, Factory, Network, Route, Telescope } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";

const TABS = ["总览", "技术路线及产业链", "产业龙头", "CPO 路线"] as const;
type Tab = typeof TABS[number];

const generations = [
  ["400G", "可插拔光模块", "主流互连形态"],
  ["800G", "高速调制与多通道集成", "AI 集群规模部署"],
  ["1.6T", "更高单波速率与功耗优化", "下一代升级窗口"],
  ["3.2T", "面向更远期的系统演进", "跟踪标准与验证进度"],
];

const chain = [
  ["01", "上游材料 / 衬底", "磷化铟（InP）、硅光晶圆、保偏光纤", "材料纯度、良率与供给"],
  ["02", "光芯片和器件", "激光芯片、硅光 PIC、DSP、探测器", "高速率设计与耦合损耗"],
  ["03", "光引擎 / 光模块封装", "光电共封、精密耦合、热管理", "自动化与一致性"],
  ["04", "系统集成", "交换机、网卡、光模块整机", "系统级兼容与可靠性"],
  ["05", "需求端", "AI 数据中心、超大规模训练集群", "带宽密度、功耗与 TCO"],
];

function SectionTitle({ icon: Icon, children }: { icon: typeof Telescope; children: string }) {
  return <h2 className="mb-3 flex items-center gap-2 text-base font-bold"><Icon className="h-4 w-4 text-primary" />{children}</h2>;
}

export function OpticalInterconnectResearch() {
  const [tab, setTab] = useState<Tab>("总览");

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2 border-b border-border/60 pb-4">
        {TABS.map((item) => (
          <button key={item} onClick={() => setTab(item)} className={cn(
            "rounded-full border px-3.5 py-1.5 text-sm transition-colors",
            tab === item ? "border-primary bg-primary/15 font-semibold text-primary" : "border-border bg-muted/30 text-muted-foreground hover:text-foreground",
          )}>{item}</button>
        ))}
      </div>

      {tab === "总览" && <Overview />}
      {tab === "技术路线及产业链" && <TechnologyAndChain />}
      {tab === "产业龙头" && <IndustryLandscape />}
      {tab === "CPO 路线" && <CpoRoute />}

      <div className="flex gap-2 rounded-xl border border-warning/30 bg-warning/5 px-4 py-3 text-xs leading-relaxed text-muted-foreground">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
        <p>这是产业研究框架，不构成投资建议。代际进度、产能与市场规模须以最新公开财报、标准组织资料和公司公告交叉核实后再写入研究结论。</p>
      </div>
    </div>
  );
}

function Overview() {
  return <div className="space-y-5">
    <GlassCard glow>
      <p className="text-sm leading-7 text-muted-foreground"><b className="text-foreground">一句话定义：</b>光互联是在芯片与芯片、机架与机架之间，用“光”而非“铜”传输数据的高速互连方案；它服务于 AI 集群对带宽密度、传输距离与能效的持续要求。</p>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        {[["为什么现在受关注", "铜互连在更高速率、更长距离下的损耗与功耗压力上升。"], ["观察什么", "单通道速率、端口带宽、功耗、良率与客户验证。"], ["研究边界", "区分技术路线、工程验证和规模量产，避免把概念等同收入。"]].map(([title, text]) => (
          <div key={title} className="rounded-xl bg-muted/40 p-3"><p className="mb-1 text-sm font-semibold">{title}</p><p className="text-xs leading-5 text-muted-foreground">{text}</p></div>
        ))}
      </div>
    </GlassCard>
    <div>
      <SectionTitle icon={Route}>代际演进地图</SectionTitle>
      <div className="grid gap-3 md:grid-cols-4">{generations.map(([speed, tech, status], index) => <GlassCard key={speed} className="relative p-4">
        <span className="text-lg font-extrabold text-primary">{speed}</span>
        <p className="mt-2 text-sm font-medium">{tech}</p><p className="mt-1 text-xs text-muted-foreground">{status}</p>
        {index < generations.length - 1 && <ArrowRight className="absolute -right-5 top-1/2 hidden h-4 w-4 text-primary md:block" />}
      </GlassCard>)}</div>
    </div>
  </div>;
}

function TechnologyAndChain() {
  return <div className="space-y-5">
    <GlassCard><SectionTitle icon={Route}>技术路线：速率翻倍时，关键变化在哪里</SectionTitle>
      <p className="text-sm leading-7 text-muted-foreground">研究时逐代核对调制方式、单波速率、通道数、DSP / 硅光方案、封装与散热要求；“速率升级”不等于每个环节同步受益，瓶颈通常会随路线迁移。</p>
    </GlassCard>
    <div><SectionTitle icon={Network}>产业链地图：从上游到需求端</SectionTitle>
      <div className="space-y-2">{chain.map(([number, title, scope, bottleneck]) => <GlassCard key={number} className="flex flex-col gap-3 p-4 md:flex-row md:items-center">
        <span className="text-xl font-black text-primary/80">{number}</span><div className="min-w-40"><p className="font-semibold">{title}</p><p className="text-xs text-muted-foreground">{scope}</p></div>
        <div className="md:ml-auto"><span className="rounded-full bg-warning/10 px-2.5 py-1 text-xs text-warning">关注：{bottleneck}</span></div>
      </GlassCard>)}</div>
    </div>
  </div>;
}

function IndustryLandscape() {
  const rows = [["架构定义 / 系统标准", "海外主导", "标准、交换芯片与系统生态"], ["封装制造 / 精密耦合", "中外混合", "良率、自动化与可靠性"], ["高端光芯片 / 核心材料", "海外主导", "InP、硅光、激光器与关键设备"], ["光模块 / 系统组装", "中国已建立壁垒", "制造规模、交付与工程能力"]];
  return <div className="space-y-5">
    <GlassCard><SectionTitle icon={Factory}>全球格局：按环节，而非按公司看</SectionTitle><p className="text-sm leading-7 text-muted-foreground">将每个环节拆成“国家 / 地区主导、关键壁垒、中国厂商所处梯队”三件事；具体公司排名应以最新客户认证、出货与财报披露验证。</p></GlassCard>
    <div className="overflow-hidden rounded-2xl border border-border/70"><table className="w-full text-left text-sm"><thead className="bg-muted/50 text-muted-foreground"><tr><th className="p-3">产业环节</th><th className="p-3">竞争格局</th><th className="p-3">核心壁垒</th></tr></thead><tbody>{rows.map(([segment, position, moat]) => <tr key={segment} className="border-t border-border/60"><td className="p-3 font-medium">{segment}</td><td className="p-3"><span className="rounded-full bg-primary/10 px-2 py-1 text-xs text-primary">{position}</span></td><td className="p-3 text-muted-foreground">{moat}</td></tr>)}</tbody></table></div>
  </div>;
}

function CpoRoute() {
  const additions = [["外置激光源", "将热敏感光源与交换芯片热区解耦"], ["光引擎", "缩短电互连路径并提高带宽密度"], ["FAU 光纤阵列", "完成高精度光耦合"], ["微透镜阵列", "改善耦合与光路控制"], ["硅光封装", "在高密度条件下解决封装、热与可靠性"]];
  return <div className="space-y-5"><GlassCard glow><SectionTitle icon={Telescope}>CPO：下一代互连方向</SectionTitle><p className="text-sm leading-7 text-muted-foreground"><b className="text-foreground">定义：</b>共封装光学（CPO）将光引擎更靠近交换芯片封装，减少高速电信号在板级互连中的损耗。它是对可插拔光模块的下一代演进路线，不是短期内的简单替代。</p></GlassCard>
    <div className="grid gap-3 md:grid-cols-5">{additions.map(([name, detail]) => <GlassCard key={name} className="p-4"><CircleDot className="h-4 w-4 text-primary" /><p className="mt-2 text-sm font-semibold">{name}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p></GlassCard>)}</div>
    <GlassCard><SectionTitle icon={CheckCircle2}>研究检查清单</SectionTitle><ul className="space-y-2 text-sm text-muted-foreground"><li>• 最硬材料与制造瓶颈：重点核对 InP 衬底、精密耦合和高良率封装的验证进度。</li><li>• 量产节奏：区分实验室演示、小批量导入与客户侧规模部署，不用单一时间点替代验证。</li><li>• 替代关系：跟踪 CPO 与可插拔模块在不同带宽、距离及运维场景中的共存与替代边界。</li></ul></GlassCard>
  </div>;
}
