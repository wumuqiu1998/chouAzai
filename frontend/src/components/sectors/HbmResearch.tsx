import { useState } from "react";
import { AlertTriangle, BarChart3, CircleDot, Factory, Layers3, Microscope, Thermometer, Wrench } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";

const TABS = ["总览", "技术代际", "成本与卡口", "产业龙头", "周期温度计"] as const;
type Tab = typeof TABS[number];

const generations = [
  ["HBM1 / 2", "早期堆叠带宽方案", "验证产品化与生态"],
  ["HBM3 / 3E", "AI 加速器主流搭配", "带宽、容量与供给爬坡"],
  ["HBM4", "更高 I/O 与先进封装协同", "跟踪量产、良率与客户导入"],
  ["HBM4E", "更远期演进", "跟踪标准、规格与验证窗口"],
];

const costChain = [
  ["存储晶圆", "DRAM 制程、容量与晶圆良率", "制程稳定性与供给"],
  ["TSV 与堆叠键合", "硅通孔、减薄、堆叠互连", "高层数的一致性与良率放大"],
  ["Base Die", "逻辑底座、I/O 与控制功能", "定制化与先进逻辑协同"],
  ["测试分选", "已知良品筛选、堆叠后测试", "测试覆盖和节拍"],
  ["封装材料", "底填、基板与热管理材料", "可靠性与长周期验证"],
];

function Title({ icon: Icon, children }: { icon: typeof Layers3; children: string }) {
  return <h2 className="mb-3 flex items-center gap-2 text-base font-bold"><Icon className="h-4 w-4 text-primary" />{children}</h2>;
}

export function HbmResearch() {
  const [tab, setTab] = useState<Tab>("总览");
  return <div className="space-y-5">
    <div className="flex flex-wrap gap-2 border-b border-border/60 pb-4">{TABS.map((item) => <button key={item} onClick={() => setTab(item)} className={cn("rounded-full border px-3.5 py-1.5 text-sm transition-colors", tab === item ? "border-primary bg-primary/15 font-semibold text-primary" : "border-border bg-muted/30 text-muted-foreground hover:text-foreground")}>{item}</button>)}</div>
    {tab === "总览" && <Overview />}{tab === "技术代际" && <Technology />}{tab === "成本与卡口" && <Costs />}{tab === "产业龙头" && <Landscape />}{tab === "周期温度计" && <Cycle />}
    <div className="flex gap-2 rounded-xl border border-warning/30 bg-warning/5 px-4 py-3 text-xs leading-relaxed text-muted-foreground"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" /><p>这是产业研究框架，不构成投资建议。代际量产、供需、价格和公司梯队均应以最新公开财报、官方统计与公告交叉验证。</p></div>
  </div>;
}

function Overview() {
  return <div className="space-y-5"><GlassCard glow><p className="text-sm leading-7 text-muted-foreground"><b className="text-foreground">一句话定义：</b>HBM（高带宽存储）把多层 DRAM 芯片通过 TSV 硅通孔垂直堆叠，并贴近 AI 芯片部署，以更宽的数据通路缓解“算得快、喂不饱”的内存带宽瓶颈。</p><div className="mt-4 grid gap-3 md:grid-cols-3">{[["核心矛盾", "算力增长往往快于内存带宽，数据供给成为系统约束。"], ["研究重点", "代际切换、堆叠层数、良率、供给与客户认证。"], ["不要混淆", "规格发布、工程样品、量产爬坡和收入确认并非同一时点。"]].map(([name, detail]) => <div key={name} className="rounded-xl bg-muted/40 p-3"><p className="text-sm font-semibold">{name}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p></div>)}</div></GlassCard><GlassCard><Title icon={BarChart3}>市场量级：研究时应回答四个问题</Title><ul className="space-y-2 text-sm text-muted-foreground"><li>• HBM 在 AI 硬件成本中的位置，以及口径和年份。</li><li>• 需求是来自新平台放量、存量升级还是库存补库。</li><li>• 主流出货代际与下一代切换窗口。</li><li>• 供给弹性来自晶圆、堆叠、测试还是先进封装。</li></ul></GlassCard></div>;
}

function Technology() {
  return <div className="space-y-5"><div><Title icon={Layers3}>代际演进：一张表看清路线</Title><div className="grid gap-3 md:grid-cols-4">{generations.map(([name, focus, research]) => <GlassCard key={name} className="p-4"><p className="text-lg font-extrabold text-primary">{name}</p><p className="mt-2 text-sm font-medium">{focus}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">{research}</p></GlassCard>)}</div></div><GlassCard><Title icon={Microscope}>两个值得追踪的技术开关</Title><div className="grid gap-4 md:grid-cols-2"><div><p className="font-semibold">堆叠键合路线</p><p className="mt-1 text-sm leading-6 text-muted-foreground">比较不同键合工艺的精度、热预算与良率；层数提升后，任何单层缺陷都可能放大为整颗报废。</p></div><div><p className="font-semibold">Base Die 改制</p><p className="mt-1 text-sm leading-6 text-muted-foreground">关注逻辑底座向更强 I/O、控制与定制能力演进时，对逻辑工艺、封装协同与验证周期的影响。</p></div></div></GlassCard></div>;
}

function Costs() {
  return <div className="space-y-5"><GlassCard><Title icon={Wrench}>成本拆解与良率放大效应</Title><p className="text-sm leading-7 text-muted-foreground">HBM 的价值不只来自单颗 DRAM：高层数堆叠使晶圆、TSV、键合、测试和封装材料彼此耦合。研究成本时，应同时看单步成本和良率损失如何向整颗产品放大。</p></GlassCard><div className="space-y-2">{costChain.map(([name, scope, bottleneck], i) => <GlassCard key={name} className="flex flex-col gap-2 p-4 md:flex-row md:items-center"><span className="font-black text-primary/80">0{i + 1}</span><div className="min-w-44"><p className="font-semibold">{name}</p><p className="text-xs text-muted-foreground">{scope}</p></div><span className="md:ml-auto rounded-full bg-warning/10 px-2.5 py-1 text-xs text-warning">卡口：{bottleneck}</span></GlassCard>)}</div></div>;
}

function Landscape() {
  const rows = [["存储原厂", "海外主导", "DRAM 制程、堆叠良率与客户协同"], ["Base Die 代工", "中外混合", "逻辑工艺、I/O 设计与供应链协作"], ["键合与测试设备", "海外主导 / 中外并行", "精度、节拍和长期可靠性"], ["关键封装材料", "海外主导 / 中外并行", "验证周期与材料一致性"], ["电子特气与前驱体", "多区域供应", "纯度、稳定性与认证壁垒"]];
  return <div className="space-y-5"><GlassCard><Title icon={Factory}>全球格局：沿产业链横向展开</Title><p className="text-sm leading-7 text-muted-foreground">每一环节分开回答：谁主导、壁垒在哪里、中国处于哪一梯队。判断时先区分“全球供应链不可缺”和“国产替代语境成立”，避免将两者混为一谈。</p></GlassCard><div className="overflow-hidden rounded-2xl border border-border/70"><table className="w-full text-left text-sm"><thead className="bg-muted/50 text-muted-foreground"><tr><th className="p-3">环节</th><th className="p-3">格局</th><th className="p-3">壁垒</th></tr></thead><tbody>{rows.map(([part, position, moat]) => <tr key={part} className="border-t border-border/60"><td className="p-3 font-medium">{part}</td><td className="p-3"><span className="rounded-full bg-primary/10 px-2 py-1 text-xs text-primary">{position}</span></td><td className="p-3 text-muted-foreground">{moat}</td></tr>)}</tbody></table></div></div>;
}

function Cycle() {
  return <div className="space-y-5"><GlassCard glow><Title icon={Thermometer}>周期温度计：用领先数据跟踪供需</Title><p className="text-sm leading-7 text-muted-foreground">存储是强周期行业。温度计不预测涨跌，而是把可公开、更新更快的数据按同一口径记录，观察需求、价格和供给的边际变化。</p></GlassCard><div className="grid gap-3 md:grid-cols-3">{[["韩国半导体出口同比", "月度官方数据；观察存储相关出口的同比与环比变化。"], ["存储合约价", "记录发布时间、产品口径与价格方向，避免跨品类比较。"], ["原厂资本开支", "在财报或公告中跟踪扩产、技术投资与产能利用率表述。"]].map(([metric, detail]) => <GlassCard key={metric} className="p-4"><CircleDot className="h-4 w-4 text-primary" /><p className="mt-2 font-semibold">{metric}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p></GlassCard>)}</div><GlassCard><p className="text-sm font-semibold">阅读规则</p><p className="mt-2 text-sm leading-6 text-muted-foreground">持续加速不自动等于景气见顶；同比走弱也需区分高基数、价格、出货与库存。每次记录都应保留发布日期、数据来源与判断口径。</p></GlassCard></div>;
}
