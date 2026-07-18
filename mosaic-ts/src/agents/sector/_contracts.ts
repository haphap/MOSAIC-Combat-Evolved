import type { StandardSectorAgentId } from "../types.js";
import { sectorDirectionIds } from "./registry.js";

export const STANDARD_SECTOR_AGENT_IDS = [
  "semiconductor",
  "technology",
  "energy",
  "biotech",
  "consumer",
  "industrials",
  "real_estate_construction",
  "financials",
  "agriculture",
] as const satisfies ReadonlyArray<StandardSectorAgentId>;

export const SECTOR_AGENT_IDS = [...STANDARD_SECTOR_AGENT_IDS, "relationship_mapper"] as const;

export interface StandardSectorRoleContract {
  agentId: StandardSectorAgentId;
  responsibility: { zh: string; en: string };
  prohibited: { zh: ReadonlyArray<string>; en: ReadonlyArray<string> };
  directionIds: readonly [string, ...string[]];
  requiredTools:
    | readonly ["get_sector_research_snapshot"]
    | readonly ["get_sector_research_snapshot", "get_role_event_snapshot"];
}

const contract = (
  agentId: StandardSectorAgentId,
  responsibility: { zh: string; en: string },
  prohibited: { zh: string[]; en: string[] },
): StandardSectorRoleContract => ({
  agentId,
  responsibility,
  prohibited,
  directionIds: sectorDirectionIds(agentId),
  requiredTools:
    agentId === "biotech"
      ? ["get_sector_research_snapshot"]
      : ["get_sector_research_snapshot", "get_role_event_snapshot"],
});

export const STANDARD_SECTOR_ROLE_CONTRACTS: Readonly<
  Record<StandardSectorAgentId, StandardSectorRoleContract>
> = {
  semiconductor: contract(
    "semiconductor",
    {
      zh: "只比较申万电子中的半导体二级产业方向。",
      en: "Compare only semiconductor directions within the SW electronics sector.",
    },
    {
      zh: ["不得纳入其他电子、计算机或通信"],
      en: ["Do not include other electronics, computers, or communications"],
    },
  ),
  technology: contract(
    "technology",
    {
      zh: "比较剔除半导体后的电子、计算机、通信和传媒。",
      en: "Compare non-semiconductor electronics, computers, communications, and media.",
    },
    {
      zh: ["不得重新纳入半导体", "不得用海外科技股替代 A 股证据"],
      en: [
        "Do not reinclude semiconductors",
        "Do not substitute foreign tech stocks for A-share evidence",
      ],
    },
  ),
  energy: contract(
    "energy",
    {
      zh: "比较煤炭、石油石化、电力、光伏、风电和电池/储能。",
      en: "Compare coal, oil and gas, power, solar, wind, and batteries/storage.",
    },
    {
      zh: ["新能源汽车整车属于消费", "基础化工、钢铁和有色属于工业"],
      en: [
        "Finished NEVs belong to consumer",
        "Chemicals, steel, and nonferrous metals belong to industrials",
      ],
    },
  ),
  biotech: contract(
    "biotech",
    {
      zh: "比较医药生物内部可投资方向。",
      en: "Compare investable directions within healthcare and biotech.",
    },
    {
      zh: ["不得以单一临床事件代表全行业"],
      en: ["Do not generalize one clinical event to the whole sector"],
    },
  ),
  consumer: contract(
    "consumer",
    {
      zh: "比较家电、食品饮料、纺服轻工、商贸服务、美容护理和汽车。",
      en: "Compare appliances, food and beverage, textiles/light industry, retail/services, beauty, and autos.",
    },
    { zh: ["汽车不得进入工业"], en: ["Autos must not enter industrials"] },
  ),
  industrials: contract(
    "industrials",
    {
      zh: "比较基础化工、钢铁/黑色、有色、机械、军工、电网设备、交通运输和环保。",
      en: "Compare chemicals, steel/ferrous, nonferrous metals, machinery, defense, grid equipment, transportation, and environmental services.",
    },
    {
      zh: ["不得纳入汽车、光伏、风电或电池", "不得重复 commodities 宏观冲击票"],
      en: [
        "Do not include autos, solar, wind, or batteries",
        "Do not repeat the commodities macro shock",
      ],
    },
  ),
  real_estate_construction: contract(
    "real_estate_construction",
    {
      zh: "比较房地产、建筑材料和建筑装饰。",
      en: "Compare real estate, building materials, and construction decoration.",
    },
    {
      zh: ["不得判断 PBOC", "不得让地产成为 china 的必选维度"],
      en: ["Do not judge the PBOC", "Do not make property mandatory for the China macro role"],
    },
  ),
  financials: contract(
    "financials",
    {
      zh: "比较银行、证券、保险和多元金融。",
      en: "Compare banks, securities, insurance, and diversified finance.",
    },
    {
      zh: ["不得替代 central_bank 判断 PBOC"],
      en: ["Do not replace the central_bank PBOC judgment"],
    },
  ),
  agriculture: contract(
    "agriculture",
    {
      zh: "比较种植/种业、养殖/水产、饲料/动保和林业/加工/服务。",
      en: "Compare crops/seeds, livestock/aquaculture, feed/animal health, and forestry/processing/services.",
    },
    {
      zh: ["不得重复 commodities 农产品宏观票", "不得把单一农产品价格外推为整个行业"],
      en: [
        "Do not repeat the commodities agriculture macro signal",
        "Do not extrapolate one crop price to the whole sector",
      ],
    },
  ),
};

export const SECTOR_CONTRACT_VERSION = "sector_direction_selection_v2";
