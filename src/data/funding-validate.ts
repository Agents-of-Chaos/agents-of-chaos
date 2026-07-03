/* funding-validate.ts — build-time validator for funding.json.
 *
 * This is a side-effect module: import it from FundingGraph.astro's Astro
 * frontmatter so `npm run build` (and `astro dev`) fail fast on bad data
 * before a single byte is shipped to browsers.
 *
 * MUST NEVER be imported from client scripts: it pulls in companies.json
 * (~200KB) which would inflate /funding's JS bundle, and the throws happen
 * at build time — swallowing them silently in the browser defeats the purpose.
 * All data integrity failures must be caught at build time, not at runtime. */

import { fundingNodes, fundingEdges, fundingMeta } from "./funding";
import { FUNDER_KINDS, DOMAINS } from "./funding-types";
import rawCompanies from "./companies.json";

const kindIds = new Set(FUNDER_KINDS.map((k) => k.id));
const domainIds = new Set(DOMAINS.map((d) => d.id));
const applyModes = new Set(["rolling", "rounds", "invite-only", "closed"]);
const granteeKinds = new Set(["research-org", "university", "startup", "fieldbuilding"]);
const companyIds = new Set((rawCompanies as { companies: { id: string }[] }).companies.map((c) => c.id));

if (!fundingMeta?.generatedAt) throw new Error("funding.json: meta.generatedAt is required (drives open-now)");

const ids = new Set<string>();
for (const n of fundingNodes) {
  if (ids.has(n.id)) throw new Error(`funding.json: duplicate id "${n.id}"`);
  ids.add(n.id);
  if (!n.sources?.length) throw new Error(`funding.json: "${n.id}" has no sources`);
  if (typeof n.priorityRank !== "number") throw new Error(`funding.json: "${n.id}" missing numeric priorityRank`);
  if (typeof n.fieldDollarsUSD !== "number" || n.fieldDollarsUSD < 0)
    throw new Error(`funding.json: "${n.id}" fieldDollarsUSD must be a number >= 0`);
  for (const t of n.domainTags ?? [])
    if (!domainIds.has(t)) throw new Error(`funding.json: "${n.id}" unknown domain tag "${t}"`);
  if (n.networksId && !companyIds.has(n.networksId))
    throw new Error(`funding.json: "${n.id}" networksId "${n.networksId}" not in companies.json`);
  if (n.kind === "funder") {
    if (!kindIds.has(n.funderKind)) throw new Error(`funding.json: "${n.id}" unknown funderKind "${n.funderKind}"`);
    if (!n.apply || !applyModes.has(n.apply.mode))
      throw new Error(`funding.json: "${n.id}" apply.mode missing/unknown`);
    if (n.apply.mode === "rounds" && n.apply.deadline && n.apply.deadline < fundingMeta.generatedAt)
      throw new Error(`funding.json: "${n.id}" rounds deadline ${n.apply.deadline} is in the past — re-verify or set mode "closed"`);
    if (n.annualFieldGivingUSD != null) {
      if (n.annualFieldGivingUSD < 0) throw new Error(`funding.json: "${n.id}" negative annual giving`);
      if (!n.annualFieldGivingBasis?.sourceUrl?.startsWith("http"))
        throw new Error(`funding.json: "${n.id}" annualFieldGivingUSD has no basis.sourceUrl — every $ needs a source`);
    }
    if (n.fieldDollarsUSD !== (n.annualFieldGivingUSD ?? 0))
      throw new Error(`funding.json: "${n.id}" fieldDollarsUSD must equal annualFieldGivingUSD ?? 0`);
  }
  if (n.kind === "grantee" && !granteeKinds.has(n.granteeKind))
    throw new Error(`funding.json: "${n.id}" unknown granteeKind "${n.granteeKind}"`);
  if (n.kind === "person" && !n.title) throw new Error(`funding.json: person "${n.id}" missing public title`);
}

const kindOf = (id: string) => fundingNodes.find((n) => n.id === id)?.kind;
const personHasAffil = new Set<string>();
const granteeHasEdge = new Set<string>();
for (const e of fundingEdges) {
  if (!ids.has(e.source)) throw new Error(`funding.json: edge from unknown node "${e.source}"`);
  if (!ids.has(e.target)) throw new Error(`funding.json: edge to unknown node "${e.target}"`);
  if (e.source === e.target) throw new Error(`funding.json: self-loop on "${e.source}"`);
  if (e.type === "grant") {
    if (kindOf(e.source) !== "funder") throw new Error(`funding.json: grant edge source "${e.source}" is not a funder`);
    if (kindOf(e.target) !== "grantee") throw new Error(`funding.json: grant edge target "${e.target}" is not a grantee`);
    if (e.amountUSD != null && !e.sourceUrl?.startsWith("http"))
      throw new Error(`funding.json: ${e.source}→${e.target} has a $ amount but no sourceUrl — every $ needs a source`);
    if (e.regrantOf && !ids.has(e.regrantOf))
      throw new Error(`funding.json: ${e.source}→${e.target} regrantOf "${e.regrantOf}" unknown`);
    granteeHasEdge.add(e.target);
  } else if (e.type === "investment") {
    if (kindOf(e.source) !== "funder") throw new Error(`funding.json: investment edge source "${e.source}" is not a funder`);
    if (kindOf(e.target) !== "grantee") throw new Error(`funding.json: investment edge target "${e.target}" is not a grantee`);
    if (e.amountUSD != null && !e.sourceUrl?.startsWith("http"))
      throw new Error(`funding.json: ${e.source}→${e.target} has a $ amount but no sourceUrl — every $ needs a source`);
    granteeHasEdge.add(e.target);
  } else if (e.type === "affiliation") {
    if (kindOf(e.source) !== "person") throw new Error(`funding.json: affiliation source "${e.source}" is not a person`);
    if (kindOf(e.target) !== "funder") throw new Error(`funding.json: affiliation target "${e.target}" is not a funder`);
    personHasAffil.add(e.source);
  } else {
    throw new Error(`funding.json: ${(e as { source: string }).source}→${(e as { target: string }).target} has unknown edge type "${(e as { type: string }).type}"`);
  }
}
for (const n of fundingNodes)
  if (n.kind === "person" && !personHasAffil.has(n.id))
    throw new Error(`funding.json: person "${n.id}" has no affiliation edge`);
for (const n of fundingNodes)
  if (n.kind === "grantee" && !granteeHasEdge.has(n.id))
    throw new Error(`funding.json: grantee "${n.id}" has no funding edge — it would be invisible on the map`);
